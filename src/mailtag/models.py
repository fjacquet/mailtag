from pydantic import BaseModel


class Email(BaseModel):
    """Represents an email message with validation."""

    msg_id: int
    subject: str
    sender_address: str
    sender_name: str
