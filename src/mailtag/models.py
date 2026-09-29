from pydantic import BaseModel


class Email(BaseModel):
    """Represents an email message with validation."""

    msg_id: str
    subject: str
    sender_address: str
    sender_name: str
    body: str = ""
    message_id: str = ""
    has_unsubscribe: bool = False
    is_bulk: bool = False
