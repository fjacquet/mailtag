"""Email classification endpoints."""

from fastapi import APIRouter, HTTPException
from loguru import logger

from mailtag.config import CONFIG
from mailtag.gmail_service import GmailService
from mailtag.imap_service import ImapService
from mailtag.models import Email

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

UNACTIONABLE_CATEGORIES = frozenset({"À Classer", "(Model Error)", "Unclassified"})


def _to_email(req: ClassifyRequest) -> Email:
    """Convert API request to internal Email model."""
    return Email(
        msg_id=req.msg_id,
        subject=req.subject,
        sender_address=req.sender_address,
        sender_name=req.sender_name,
        body=req.body,
        labels=req.labels,
    )


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
    """Classify a single email using the 6-signal AMSC strategy.

    Returns the assigned category. The email is not moved — use
    `/classify-and-move` for classification with provider-based email moving.

    **N8N usage**: Send a POST with the email fields from your trigger node.
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    email = _to_email(request)
    category = app_state.classifier.classify_email(email)
    if app_state.database:
        app_state.database.flush()

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
    """Classify multiple emails in a single request.

    More efficient than individual calls — uses batch embeddings for
    the semantic router signal. Limited to `max_batch_size` emails per request
    (default: 50, configured in config.toml).
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
    if app_state.database:
        app_state.database.flush()

    results = [
        ClassifyResponse(msg_id=email.msg_id, category=category)
        for email, category in zip(emails, categories, strict=True)
    ]

    return ClassifyBatchResponse(
        results=results,
        total=len(results),
        classified=sum(1 for r in results if r.category not in UNACTIONABLE_CATEGORIES),
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
    """Classify an email and move it to the assigned category folder/label.

    Opens a connection to the specified provider (IMAP or Gmail), classifies
    the email, and moves it. Each request uses its own provider connection
    (stateless design suitable for webhook usage).

    **Note**: The `msg_id` must correspond to an existing message on the
    provider's server.
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
        labels=request.labels,
    )

    category = app_state.classifier.classify_email(email)
    if app_state.database:
        app_state.database.flush()

    if category in UNACTIONABLE_CATEGORIES:
        return ClassifyAndMoveResponse(
            msg_id=request.msg_id,
            category=category,
            moved=False,
            error="Category not actionable for move",
        )

    try:
        if request.provider == "imap":
            provider = ImapService(CONFIG.imap, CONFIG.fast_parse)
            with provider.connect():
                provider.move_email(email, category)
        elif request.provider == "gmail":
            provider = GmailService(CONFIG.gmail)
            with provider.connect():
                provider.move_email(email, category)

        return ClassifyAndMoveResponse(
            msg_id=request.msg_id,
            category=category,
            moved=True,
        )
    except (ConnectionError, RuntimeError, OSError) as e:
        logger.error("Failed to move email {}: {}", request.msg_id, e)
        return ClassifyAndMoveResponse(
            msg_id=request.msg_id,
            category=category,
            moved=False,
            error=str(e),
        )
