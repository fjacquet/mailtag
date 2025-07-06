import email
import re
from contextlib import contextmanager

from bs4 import BeautifulSoup
from imapclient import IMAPClient
from loguru import logger

from .config import ImapConfig
from .models import Email
from .providers import EmailProvider


class ImapService(EmailProvider):
    """Handles interactions with an IMAP email server using IMAPClient."""

    def __init__(self, config: ImapConfig):
        self.config = config
        self.client: IMAPClient | None = None

    def is_connected(self) -> bool:
        """Checks if the mail client is connected."""
        return self.client is not None and self.client.is_login()

    @contextmanager
    def connect(self):
        """
        Connects to the IMAP server and yields the client as a context manager.
        Ensures disconnection on exit.
        """
        try:
            self.client = IMAPClient(self.config.host)
            self.client.login(self.config.user, self.config.password)
            logger.info(f"Successfully connected to IMAP server: {self.config.host}")
            yield self
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            self.client = None
            raise ConnectionError(f"IMAP connection failed: {e}") from e
        finally:
            if self.client:
                self.client.logout()
                logger.info("Disconnected from IMAP server.")

    def get_emails(
        self,
        subject: str | None = None,
        sender: str | None = None,
        status: str | None = None,
    ) -> list[Email]:
        """
        Fetches emails from the Inbox, including their body and labels,
        without marking them as read.
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        self.client.select_folder("INBOX", readonly=True)
        search_criteria = ["ALL"]
        if subject:
            search_criteria.append(f'SUBJECT "{subject}"')
        if sender:
            search_criteria.append(f'FROM "{sender}"')
        if status:
            search_criteria.append(status)

        messages = self.client.search(search_criteria)
        if not messages:
            return []

        fetch_command = [b"BODY.PEEK[]"]
        if self.config.use_gmail_extensions:
            fetch_command.append(b"X-GM-LABELS")

        response = self.client.fetch(messages, fetch_command)
        emails = []
        for msg_id, data in response.items():
            msg = email.message_from_bytes(data[b"BODY[]"])
            sender_header = msg["From"]
            subject_header = msg["Subject"]
            sender_name, sender_address = self._parse_sender(sender_header)
            body = self._get_body_from_msg(msg)
            labels = [label.decode() for label in data.get(b"X-GM-LABELS", [])]

            emails.append(
                Email(
                    msg_id=str(msg_id),
                    subject=str(subject_header),
                    sender_address=sender_address,
                    sender_name=sender_name,
                    body=body,
                    labels=labels,
                )
            )
        return emails

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination."""
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        if not self.client.folder_exists(destination):
            self.client.create_folder(destination)

        self.client.move(email_model.msg_id, destination)
        logger.info(f"Moved email {email_model.msg_id} to {destination}")

    def _parse_sender(self, raw_sender: str) -> tuple[str, str]:
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        if not raw_sender:
            return "", ""
        match = re.match(r"(.+?)\s*<(.+?)>", raw_sender)
        if match:
            return match.groups()
        return "", raw_sender

    def _get_body_from_msg(self, msg) -> str:
        """
        Reads the body of a specific email message, prioritizing plain text over HTML.
        """
        plain_text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    plain_text_body = part.get_payload(decode=True).decode()
                elif content_type == "text/html":
                    html_body = part.get_payload(decode=True).decode()
        else:
            plain_text_body = msg.get_payload(decode=True).decode()

        if plain_text_body:
            return plain_text_body
        elif html_body:
            soup = BeautifulSoup(html_body, "html.parser")
            return soup.get_text()
        return ""