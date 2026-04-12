"""Health check and status endpoints."""

from fastapi import APIRouter

from mailtag.config import CONFIG

from ..dependencies import app_state
from ..schemas import HealthResponse, StatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint (no authentication required).

    Returns basic server status for load balancers and uptime monitors.
    """
    return HealthResponse(
        status="ok" if app_state.classifier else "initializing",
        version="1.0.0",
        uptime_seconds=round(app_state.uptime_seconds, 1),
        classifier_ready=app_state.classifier is not None,
        database_loaded=app_state.database is not None,
    )


@router.get(
    "/api/v1/status",
    response_model=StatusResponse,
    responses={401: {"description": "Missing or invalid API key"}},
)
def detailed_status():
    """Detailed system status with category and provider information.

    Requires authentication. Returns classifier state, available categories,
    and which email providers are configured.
    """
    categories_count = 0
    if app_state.classifier and app_state.classifier.categories:
        categories_count = len(app_state.classifier.categories)

    return StatusResponse(
        status="ok" if app_state.classifier else "initializing",
        version="1.0.0",
        uptime_seconds=round(app_state.uptime_seconds, 1),
        classifier_ready=app_state.classifier is not None,
        database_loaded=app_state.database is not None,
        categories_count=categories_count,
        providers={
            "imap": bool(CONFIG.imap and CONFIG.imap.host),
            "gmail": bool(CONFIG.gmail and CONFIG.gmail.credentials_file),
        },
    )
