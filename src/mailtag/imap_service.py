import email
import imaplib
import re
from contextlib import contextmanager, suppress

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

    @contextmanager
    def connect(self):
        """
        Connects to the IMAP server and yields the connection as a context manager.
        Ensures disconnection on exit.
        """
        try:
            self.mail = imaplib.IMAP4_SSL(self.config.host)
            self.mail.login(self.config.user, self.config.password)
            logger.info(f"Successfully connected to IMAP server: {self.config.host}")
            yield self
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            self.mail = None
            # Re-raise the exception to be handled by the caller
            raise ConnectionError(f"IMAP connection failed: {e}") from e
        finally:
            if self.mail:
                self.mail.logout()
                logger.info("Disconnected from IMAP server.")

    @contextmanager
    def _readonly_inbox(self):
        """A context manager to safely select and operate on the inbox in read-only mode."""
        if not self.mail:
            raise ConnectionError("Not connected to IMAP server.")
        try:
            select_status, _ = self.mail.select("inbox", readonly=True)
            if select_status != "OK":
                raise imaplib.IMAP4.error("Failed to select inbox.")
            yield
        finally:
            # Ensure the inbox is always returned to a read-write state
            if self.mail:
                self.mail.select("inbox", readonly=False)

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
        if not self.mail:
            raise ConnectionError("Not connected to IMAP server.")

        emails = []
        with self._readonly_inbox():
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
                return []

            fetch_command = "(BODY.PEEK[])"
            if self.config.use_gmail_extensions:
                fetch_command += " X-GM-LABELS"

            for num in messages[0].split():
                try:
                    typ, data = self.mail.fetch(num, fetch_command)
                    if typ != "OK":
                        logger.warning(f"Failed to fetch email with UID: {num}")
                        continue

                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    labels = []
                    if len(data) > 1 and isinstance(data[1], bytes):
                        labels_raw = data[1].decode("utf-8", "ignore")
                        if "X-GM-LABELS" in labels_raw:
                            match = re.search(r"\((.*?)\)", labels_raw)
                            if match:
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
        if not self.mail:
            raise ConnectionError("Not connected to IMAP server.")

        # Use suppress to ignore the "mailbox already exists" error.
        with suppress(imaplib.IMAP4.error):
            self.mail.create(destination)

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
