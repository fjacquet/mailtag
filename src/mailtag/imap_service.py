import email
import imaplib
import re
from contextlib import suppress

from bs4 import BeautifulSoup
from loguru import logger

from .config import ImapConfig
from .models import Email
from .providers import EmailProvider


class ImapService(EmailProvider):
    """Handles interactions with an IMAP email server."""

    def __init__(self, config: ImapConfig):
        self.config = config
        self.mail = None

    def is_connected(self) -> bool:
        """Checks if the mail client is connected."""
        return self.mail is not None

    def connect(self):
        """Connects to the IMAP server."""
        try:
            self.mail = imaplib.IMAP4_SSL(self.config.host)
            self.mail.login(self.config.user, self.config.password)
            logger.info(f"Successfully connected to IMAP server: {self.config.host}")
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            self.mail = None

    def disconnect(self):
        """Closes the connection to the IMAP server."""
        if self.mail:
            self.mail.logout()
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
        if not self.is_connected():
            raise ConnectionError("Not connected to IMAP server.")

        try:
            # Select in read-only mode to prevent marking emails as read
            select_status, _ = self.mail.select("inbox", readonly=True)
            if select_status != "OK":
                logger.error("Failed to select inbox.")
                return []
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to select inbox: {e}")
            return []

        search_criteria = ["ALL"]
        if subject:
            search_criteria.append(f'(HEADER Subject "{subject}")')
        if sender:
            search_criteria.append(f'(HEADER From "{sender}")')
        if status:
            search_criteria.append(status)

        typ, messages = self.mail.search(None, *search_criteria)
        if typ != "OK":
            logger.error("Failed to search for emails.")
            # Ensure we leave the mailbox in a read-write state
            self.mail.select("inbox", readonly=False)
            return []

        emails = []
        for num in messages[0].split():
            try:
                # Use BODY.PEEK to fetch content without setting the \Seen flag.
                # Also fetch X-GM-LABELS for Gmail-specific labels via IMAP.
                typ, data = self.mail.fetch(num, "(BODY.PEEK[] X-GM-LABELS)")
                if typ != "OK":
                    logger.warning(f"Failed to fetch email with UID: {num}")
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Extract labels from the second part of the fetch data
                labels = []
                if len(data) > 1 and isinstance(data[1], bytes):
                    labels_raw = data[1].decode("utf-8", "ignore")
                    if "X-GM-LABELS" in labels_raw:
                        match = re.search(r"\((.*?)\)", labels_raw)
                        if match:
                            # This regex handles both quoted and unquoted labels
                            label_parts = re.findall(r'"([^"]*)"|(\S+)', match.group(1))
                            labels = [p[0] or p[1] for p in label_parts if not p[1].startswith("\\")]

                sender_header = msg["From"]
                subject_header = msg["Subject"]
                sender_name, sender_address = self._parse_sender(sender_header)
                body = self._get_body_from_msg(msg)

                emails.append(
                    Email(
                        msg_id=num.decode(),
                        subject=str(subject_header),
                        sender_address=sender_address,
                        sender_name=sender_name,
                        body=body,
                        labels=labels,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to process email with UID: {num} - {e}")
                continue

        # Crucially, re-select the inbox in read-write mode to allow subsequent operations
        self.mail.select("inbox", readonly=False)
        return emails

    def _get_body_from_msg(self, msg: email.message.Message) -> str:
        """
        Reads the body of a specific email message, prioritizing plain text over HTML.
        """
        plain_text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain" and not plain_text_body:
                    with suppress(UnicodeDecodeError, AttributeError):
                        plain_text_body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8"
                        )
                elif content_type == "text/html" and not html_body:
                    with suppress(UnicodeDecodeError, AttributeError):
                        html_body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8"
                        )
        else:
            with suppress(UnicodeDecodeError, AttributeError):
                plain_text_body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8")

        if plain_text_body:
            return plain_text_body

        if html_body:
            soup = BeautifulSoup(html_body, "html.parser")
            return soup.get_text()

        return ""

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IMAP server.")

        try:
            # Ensure the destination mailbox exists
            self.mail.create(destination)
        except imaplib.IMAP4.error as e:
            # If the mailbox already exists, the server will return an error.
            # We can safely ignore it and proceed.
            if "ALREADYEXISTS" not in str(e):
                # However, if it's a different error, we should raise it.
                raise

        try:
            self.mail.copy(email_model.msg_id.encode(), destination)
            self.mail.store(email_model.msg_id.encode(), "+FLAGS", "\\Deleted")
            self.mail.expunge()
            logger.info(f"Moved email {email_model.msg_id} to {destination}")
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to move email {email_model.msg_id} to {destination}: {e}")

    def _parse_sender(self, raw_sender: str) -> tuple[str, str]:
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        if not raw_sender:
            return "", ""
        addr = email.utils.parseaddr(raw_sender)
        return addr[0], addr[1]
