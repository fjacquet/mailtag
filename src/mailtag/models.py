from pydantic import BaseModel, Field


class Email(BaseModel):
    """Represents an email message with validation."""

    msg_id: str
    subject: str
    sender_address: str
    sender_name: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
