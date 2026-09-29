"""Email classification endpoints."""

import imaplib
from datetime import date

from fastapi import APIRouter, HTTPException
from loguru import logger

from mailtag.config import CONFIG
from mailtag.gmail_api import GmailApiService
from mailtag.imap_service import ImapService
from mailtag.models import Email
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders
from mailtag.taxonomy import REVIEW
from mailtag.utils.tasks import pending_archive_path

from ..dependencies import app_state
from ..schemas import (
    ClassifyAndMoveRequest,
    ClassifyAndMoveResponse,
    ClassifyBatchRequest,
    ClassifyBatchResponse,
    ClassifyRequest,
    ClassifyResponse,
    ErrorResponse,
)

router = APIRouter()


def _to_email(req: ClassifyRequest) -> Email:
    """Convert API request to internal Email model."""
    return Email(
        msg_id=req.msg_id,
        subject=req.subject,
        sender_address=req.sender_address,
        sender_name=req.sender_name,
        body=req.body,
    )


def _provider(name: str) -> ImapService:
    if name == "gmail":
        return GmailApiService(CONFIG.gmail, CONFIG.fast_parse)
    return ImapService(CONFIG.imap, CONFIG.fast_parse)


@router.post(
    "/classify",
    response_model=ClassifyResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        503: {"model": ErrorResponse, "description": "Classifier not yet initialized"},
    },
    summary="Classify a single email",
)
def classify_email(request: ClassifyRequest):
    """Classify a single email into one of the 19 taxonomy categories (or `5-A revoir`).

    The email is not moved — use `/classify-and-move` to file it.

    **N8N usage**: Send a POST with the email fields from your trigger node.
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    category = app_state.classifier.classify_email(_to_email(request))
    return ClassifyResponse(msg_id=request.msg_id, category=category)


@router.post(
    "/classify-batch",
    response_model=ClassifyBatchResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Batch size exceeds maximum"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        503: {"model": ErrorResponse, "description": "Classifier not yet initialized"},
    },
    summary="Classify a batch of emails",
)
def classify_batch(request: ClassifyBatchRequest):
    """Classify multiple emails in a single request (batched embeddings and LLM prompts).

    Limited to `max_batch_size` emails per request (default: 50, configured in config.toml).
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    max_batch = CONFIG.webhook.max_batch_size
    if len(request.emails) > max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(request.emails)} exceeds maximum of {max_batch}",
        )

    emails = [_to_email(req) for req in request.emails]
    categories = app_state.classifier.classify_emails_batch(emails)
    results = [
        ClassifyResponse(msg_id=email.msg_id, category=category)
        for email, category in zip(emails, categories, strict=True)
    ]
    return ClassifyBatchResponse(
        results=results,
        total=len(results),
        classified=sum(1 for r in results if r.category != REVIEW),
    )


@router.post(
    "/classify-and-move",
    response_model=ClassifyAndMoveResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid provider"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        403: {"model": ErrorResponse, "description": "Move operations disabled"},
        503: {"model": ErrorResponse, "description": "Classifier not yet initialized"},
    },
    summary="Classify and move an email",
)
def classify_and_move(request: ClassifyAndMoveRequest):
    """Classify an INBOX email and move it to its action folder, like `run` does.

    Its category is recorded in the account's pending archive (by `message_id`), so the
    archive sweep later files it into its category, or learns from it if it went to review.
    `msg_id` must be the email's UID in the account's INBOX.
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    if not CONFIG.webhook.allow_move:
        raise HTTPException(status_code=403, detail="Move operations are disabled")

    email = Email(
        msg_id=request.msg_id,
        subject=request.subject,
        sender_address=request.sender_address,
        sender_name=request.sender_name,
        body=request.body,
        message_id=request.message_id,
        has_unsubscribe=request.has_unsubscribe,
        is_bulk=request.is_bulk,
    )
    results = app_state.classifier.classify_detailed([email])
    category, agreed = results[0]

    provider = _provider(request.provider)
    pending_path = pending_archive_path(provider.config, CONFIG.taxonomy.pending_archive_file)
    try:
        with provider.connect():
            pending = PendingArchive(pending_path)
            provider.client.select_folder("INBOX")
            moved = route_to_action_folders(
                provider, pending, [RoutedMail.from_email(email, category)], False, date.today()
            )
    except (imaplib.IMAP4.error, ConnectionError, RuntimeError, OSError) as e:
        logger.error("Failed to move email {}: {}", request.msg_id, e)
        return ClassifyAndMoveResponse(msg_id=request.msg_id, category=category, moved=False, error=str(e))

    if moved == 1 and agreed:  # a mail that failed to move is retried: it must not count twice
        app_state.classifier.learn([email], results)

    return ClassifyAndMoveResponse(
        msg_id=request.msg_id,
        category=category,
        moved=moved == 1,
        error=None if moved else "Move failed",
    )
