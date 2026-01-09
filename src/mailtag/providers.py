from abc import ABC, abstractmethod

from .models import Email


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    def connect(self) -> "EmailProvider":
        """Connects to the email server."""

    @abstractmethod
    def get_emails(
        self,
        subject: str | None = None,
        sender: str | None = None,
        status: str | None = None,
    ) -> list[Email]:
        """Fetches emails from the server."""

    @abstractmethod
    def move_email(self, email: Email, destination: str) -> None:
        """Moves an email to a new destination."""
