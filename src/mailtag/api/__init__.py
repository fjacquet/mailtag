"""MailTag Webhook API — FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from loguru import logger

from mailtag.config import CONFIG

from .dependencies import app_state
from .middleware import APIKeyMiddleware
from .routes import classify, health

API_VERSION = "1.0.0"

# Security scheme for Swagger "Authorize" button
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Health checks and system status. The `/health` endpoint is public (no auth).",
    },
    {
        "name": "classification",
        "description": (
            "Email classification endpoints. Uses the 6-signal AMSC strategy: "
            "Validated DB → Server Labels → History → Domain → Semantic Router → LLM fallback."
        ),
    },
]

DESCRIPTION = """\
**MailTag Webhook API** — Classify and organize emails using AI.

External services like [N8N](https://n8n.io) can trigger email classification
via HTTP POST requests instead of running batch CLI commands.

## Classification Strategy (AMSC)

Emails are classified using 6 signals evaluated in priority order:

| Signal | Method | Confidence |
|--------|--------|-----------|
| 1 | Validated Database | 100% |
| 2 | Server-Side Labels | 95% |
| 3 | Historical Patterns | 90%+ |
| 4 | Domain Classification | 90% |
| 5 | Semantic Router (embeddings) | Variable |
| 6 | LLM Fallback | Variable |

## Authentication

All `/api/v1/*` endpoints require an `X-API-Key` header.
Use the **Authorize** button above to set your API key for testing.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting MailTag webhook server...")
    app_state.initialize()
    yield
    logger.info("Shutting down MailTag webhook server...")
    app_state.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="MailTag API",
        description=DESCRIPTION,
        version=API_VERSION,
        contact={"name": "Frederic Jacquet", "email": "fred.jacquet@gmail.com"},
        license_info={"name": "MIT", "identifier": "MIT"},
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    # Add API key authentication if configured
    if CONFIG.webhook.api_key:
        app.add_middleware(APIKeyMiddleware, api_key=CONFIG.webhook.api_key)
        logger.info("API key authentication enabled")
    else:
        logger.warning("No WEBHOOK_API_KEY configured — API is unprotected")

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error("Unhandled error on {}: {}", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
        )

    # Register routes
    app.include_router(health.router)
    app.include_router(classify.router, prefix="/api/v1", tags=["classification"])

    return app
