import email
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
from imapclient import IMAPClient
from loguru import logger

from .config import FastParseConfig, ImapConfig
from .models import Email
from .providers import EmailProvider


class ImapService(EmailProvider):
    """Handles interactions with an IMAP email server using IMAPClient."""

    def __init__(self, config: ImapConfig, fast_parse_config: FastParseConfig):
        self.config = config
        self.fast_parse_config = fast_parse_config
        self.client: IMAPClient | None = None
        self.folder_cache_path = Path("data/imap_folders.json")

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

    def get_folder_hierarchy(self) -> list[str]:
        """
        Fetches the folder hierarchy from the IMAP server and caches it.
        """
        if self.folder_cache_path.exists():
            cache_mod_time = datetime.fromtimestamp(self.folder_cache_path.stat().st_mtime)
            if datetime.now() - cache_mod_time < timedelta(
                hours=self.fast_parse_config.folder_cache_ttl_hours
            ):
                with self.folder_cache_path.open("r", encoding="utf-8") as f:
                    return json.load(f)

        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        folders = [folder[2] for folder in self.client.list_folders()]
        with self.folder_cache_path.open("w", encoding="utf-8") as f:
            json.dump(folders, f, indent=2)
        return folders

    def get_email_senders(self, uids: list[str | int]) -> dict[str, str]:
        """
        Fetches only the 'From' header for a given batch of email UIDs.
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        response = self.client.fetch(uids, ["BODY[HEADER.FIELDS (FROM)]"])
        senders = {}
        for msg_id, data in response.items():
            msg = email.message_from_bytes(data[b"BODY[HEADER.FIELDS (FROM)]"])
            sender_header = msg["From"]
            _, sender_address = self._parse_sender(sender_header)
            senders[str(msg_id)] = sender_address
        return senders

    def get_full_emails(self, uids: list[str | int]) -> list[Email]:
        """
        Fetches the full content for the remaining emails for Pass 2.
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        fetch_command = [b"BODY.PEEK[]"]
        if self.config.use_gmail_extensions:
            fetch_command.append(b"X-GM-LABELS")

        response = self.client.fetch(uids, fetch_command)
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

    def get_emails(
        self,
        subject: str | None = None,
        sender: str | None = None,
        status: str | None = None,
    ) -> list[Email]:
        """This method is deprecated for IMAP and will not be implemented."""
        raise NotImplementedError("get_emails is not supported for IMAP with Fast Parse.")

    def batch_move_emails(self, uids: list[str], destination: str):
        """Moves a batch of emails to a new destination."""
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        if not self.client.folder_exists(destination):
            self.client.create_folder(destination)

        self.client.move(uids, destination)
        logger.info(f"Moved {len(uids)} emails to {destination}")

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination."""
        self.batch_move_emails([email_model.msg_id], destination)

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
        if html_body:
            soup = BeautifulSoup(html_body, "html.parser")
            return soup.get_text()
        return ""
