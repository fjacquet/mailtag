import email
import imaplib

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

    def connect(self):
        """Connects to the IMAP server."""
        try:
            self.mail = imaplib.IMAP4_SSL(self.config.host)
            self.mail.login(self.config.user, self.config.password)
            logger.info(f"Successfully connected to IMAP server: {self.config.host}")
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            raise

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
        """Fetches emails from the Inbox."""
        if not self.mail:
            raise ConnectionError("Not connected to IMAP server.")

        try:
            select_status, _ = self.mail.select("inbox")
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

        status, messages = self.mail.search(None, *search_criteria)
        if status != "OK":
            logger.error("Failed to search for emails.")
            return []

        emails = []
        for num in messages[0].split():
            try:
                status, data = self.mail.fetch(num, "(RFC822)")
                if status != "OK":
                    logger.warning(f"Failed to fetch email with UID: {num}")
                    continue

                msg = email.message_from_bytes(data[0][1])
                sender = msg["From"]
                subject = msg["Subject"]
                sender_name, sender_address = self._parse_sender(sender)

                emails.append(
                    Email(
                        msg_id=num.decode(),
                        subject=subject,
                        sender_address=sender_address,
                        sender_name=sender_name,
                    )
                )
            except imaplib.IMAP4.error as e:
                logger.warning(f"Failed to fetch email with UID: {num} - {e}")
                continue
        return emails

    def get_email_body(self, email_model: Email) -> str:
        """
        Reads the body of a specific email, prioritizing plain text over HTML.
        """
        if not self.mail:
            raise ConnectionError("Not connected to IMAP server.")

        try:
            status, data = self.mail.fetch(email_model.msg_id.encode(), "(RFC822)")
            if status != "OK":
                logger.error(f"Failed to fetch email body for UID: {email_model.msg_id}")
                return ""
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to fetch email body for UID: {email_model.msg_id} - {e}")
            return ""

        msg = email.message_from_bytes(data[0][1])
        plain_text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain" and not plain_text_body:
                    try:
                        plain_text_body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8"
                        )
                    except (UnicodeDecodeError, AttributeError):
                        pass
                elif content_type == "text/html" and not html_body:
                    try:
                        html_body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8"
                        )
                    except (UnicodeDecodeError, AttributeError):
                        pass
        else:
            # Not a multipart email, just get the payload
            try:
                plain_text_body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8")
            except (UnicodeDecodeError, AttributeError):
                pass

        if plain_text_body:
            return plain_text_body

        if html_body:
            # Fallback to HTML, stripping tags
            soup = BeautifulSoup(html_body, "html.parser")
            return soup.get_text()

        return ""

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination."""
        if not self.mail:
            raise ConnectionError("Not connected to IMAP server.")

        try:
            self.mail.copy(email_model.msg_id.encode(), destination)
            self.mail.store(email_model.msg_id.encode(), "+FLAGS", "\\Deleted")
            self.mail.expunge()
            logger.info(f"Moved email {email_model.msg_id} to {destination}")
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to move email {email_model.msg_id} to {destination}: {e}")

    def _parse_sender(self, raw_sender: str) -> (str, str):
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        addr = email.utils.parseaddr(raw_sender)
        return addr
