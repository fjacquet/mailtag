"""Request/response Pydantic models for the MailTag webhook API.

All models include json_schema_extra with realistic examples for Swagger UI.
"""

from pydantic import BaseModel, ConfigDict, Field


class ClassifyRequest(BaseModel):
    """Single email classification request."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "msg_id": "12345",
                    "subject": "Your invoice #INV-2024-001",
                    "sender_address": "billing@example.com",
                    "sender_name": "Billing Department",
                    "body": "Please find attached your invoice for January 2024.",
                    "labels": ["INBOX"],
                }
            ]
        }
    )

    msg_id: str = Field(..., description="Unique message identifier (IMAP UID or Gmail message ID)")
    subject: str = Field(..., description="Email subject line")
    sender_address: str = Field(..., description="Sender email address")
    sender_name: str = Field(default="", description="Sender display name")
    body: str = Field(default="", description="Email body text (plain text preferred)")
    labels: list[str] = Field(default_factory=list, description="Existing server-side labels/folders")


class ClassifyResponse(BaseModel):
    """Classification result for a single email."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "msg_id": "12345",
                    "category": "Finance/Invoices",
                }
            ]
        }
    )

    msg_id: str = Field(..., description="Message identifier from the request")
    category: str = Field(..., description="Assigned category (folder path)")


class ClassifyBatchRequest(BaseModel):
    """Batch classification request."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "emails": [
                        {
                            "msg_id": "12345",
                            "subject": "Your invoice #INV-2024-001",
                            "sender_address": "billing@example.com",
                            "sender_name": "Billing Dept",
                        },
                        {
                            "msg_id": "12346",
                            "subject": "Welcome to our newsletter",
                            "sender_address": "news@company.com",
                            "sender_name": "Company News",
                        },
                    ]
                }
            ]
        }
    )

    emails: list[ClassifyRequest] = Field(..., min_length=1, description="List of emails to classify")


class ClassifyBatchResponse(BaseModel):
    """Batch classification results."""

    results: list[ClassifyResponse] = Field(..., description="Classification results in input order")
    total: int = Field(..., description="Total number of emails processed")
    classified: int = Field(..., description="Number successfully classified (excluding unclassified/errors)")


class ClassifyAndMoveRequest(BaseModel):
    """Request to classify and move an email via a provider."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "msg_id": "12345",
                    "subject": "Your invoice #INV-2024-001",
                    "sender_address": "billing@example.com",
                    "sender_name": "Billing Department",
                    "body": "Please find attached your invoice.",
                    "labels": ["INBOX"],
                    "provider": "imap",
                }
            ]
        }
    )

    msg_id: str = Field(..., description="Unique message identifier")
    subject: str = Field(..., description="Email subject line")
    sender_address: str = Field(..., description="Sender email address")
    sender_name: str = Field(default="", description="Sender display name")
    body: str = Field(default="", description="Email body text")
    labels: list[str] = Field(default_factory=list, description="Existing labels/folders")
    provider: str = Field(
        ..., pattern="^(imap|gmail)$", description="Provider to use for moving (imap or gmail)"
    )


class ClassifyAndMoveResponse(BaseModel):
    """Response after classifying and moving an email."""

    msg_id: str = Field(..., description="Message identifier from the request")
    category: str = Field(..., description="Assigned category")
    moved: bool = Field(..., description="Whether the email was successfully moved")
    error: str | None = Field(default=None, description="Error message if move failed")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Server status: ok or initializing")
    version: str = Field(..., description="API version")
    uptime_seconds: float = Field(..., description="Server uptime in seconds")
    classifier_ready: bool = Field(..., description="Whether the classifier is initialized")
    database_loaded: bool = Field(..., description="Whether the classification database is loaded")


class StatusResponse(BaseModel):
    """Detailed status response with system information."""

    status: str = Field(..., description="Server status")
    version: str = Field(..., description="API version")
    uptime_seconds: float = Field(..., description="Server uptime in seconds")
    classifier_ready: bool = Field(..., description="Whether the classifier is initialized")
    database_loaded: bool = Field(..., description="Whether the classification database is loaded")
    categories_count: int = Field(..., description="Number of known classification categories")
    providers: dict[str, bool] = Field(..., description="Available providers and their configuration status")


class ErrorResponse(BaseModel):
    """Structured error response."""

    detail: str = Field(..., description="Human-readable error description")
    error_code: str = Field(..., description="Machine-readable error code")
