from abc import ABC, abstractmethod

from .models import Email


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    def connect(self):
        """Connects to the email server."""

    @abstractmethod
    def get_emails(self) -> list[Email]:
        """Fetches emails from the server."""

    @abstractmethod
    def get_email_body(self, email: Email) -> str:
        """Reads the body of a specific email."""

    @abstractmethod
    def move_email(self, email: Email, destination: str):
        """Moves an email to a new destination."""
