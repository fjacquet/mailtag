import email
import email.errors
import email.header
import imaplib
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from imapclient import IMAPClient
from loguru import logger

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.models import Email
from mailtag.utils.email_parsing import extract_body_from_message, parse_sender

from .retry import retry

# Type variable for generic return type
T = TypeVar("T")

# Maximum number of UIDs to fetch in a single batch to avoid "Too long argument" errors
# This is now configurable via FastParseConfig.batch_size

HEADER_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"


def list_header_flags(msg: email.message.Message) -> tuple[str, bool, bool]:
    """Return (message_id, has_unsubscribe, is_bulk) from a parsed message's headers."""
    message_id = str(msg.get("Message-ID") or "").strip()
    has_unsubscribe = msg.get("List-Unsubscribe") is not None
    precedence = str(msg.get("Precedence") or "").strip().lower()
    is_bulk = has_unsubscribe or msg.get("List-Id") is not None or precedence in ("bulk", "list", "junk")
    return message_id, has_unsubscribe, is_bulk


class ImapService:
    """Handles interactions with an IMAP email server using IMAPClient."""

    def __init__(self, config: ImapConfig, fast_parse_config: FastParseConfig):
        self.config = config
        self.fast_parse_config = fast_parse_config
        self.client: IMAPClient | None = None

        # Cache for verified folder existence (avoids repeated IMAP LIST calls)
        self._verified_folders: set[str] = set()

    @contextmanager
    def connect(self):
        """
        Connects to the IMAP server and yields the client as a context manager.
        Ensures disconnection on exit.
        """
        try:
            self._connect_with_retry()
            logger.info(f"Successfully connected to IMAP server: {self.config.host}")
            yield self
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            self.client = None
            raise ConnectionError(f"IMAP connection failed: {e}") from e
        finally:
            if self.client:
                self.client.logout()
                logger.info("Disconnected from IMAP server.")

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _connect_with_retry(self):
        """
        Establishes connection to the IMAP server with retry support.
        """
        self.client = IMAPClient(self.config.host)
        self.client.login(self.config.user, self.config.password)

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _batch_fetch(
        self, uids: list[str | int], fetch_command: list[bytes], processor: Callable[[dict], dict]
    ) -> dict[Any, Any]:
        """
        Helper method to fetch UIDs in batches and process the results.
        Uses retry decorator to handle transient failures.

        Args:
            uids: List of UIDs to fetch
            fetch_command: IMAP fetch command to use
            processor: Function to process the fetched data

        Returns:
            Dictionary of processed results keyed by UID
        """
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        results = {}

        # Process UIDs in batches using the configured batch size
        batch_size = self.fast_parse_config.batch_size
        for i in range(0, len(uids), batch_size):
            batch = uids[i : i + batch_size]
            try:
                response = self.client.fetch(batch, fetch_command)
                # Process the batch results
                batch_results = processor(response)
                results.update(batch_results)
            except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                logger.error(f"Error fetching batch {i // batch_size + 1}: {e}")
                # Optionally, re-raise or continue with next batch
                raise

        return results

    def _parse_header_value(self, header_value: Any) -> str:
        """Safely parse a header value, handling different types including email.header.Header."""
        if header_value is None:
            return ""

        # Handle email.header.Header objects
        if hasattr(header_value, "__class__") and header_value.__class__.__name__ == "Header":
            try:
                # Get the decoded string representation
                from email.header import decode_header

                decoded_parts = []
                for part, encoding in decode_header(header_value):
                    if isinstance(part, bytes):
                        try:
                            part = part.decode(encoding or "utf-8", errors="replace")
                        except (UnicodeDecodeError, LookupError):
                            part = part.decode("utf-8", errors="replace")
                    decoded_parts.append(str(part) if part else "")
                return "".join(decoded_parts).strip()
            except (UnicodeDecodeError, LookupError, ValueError) as e:
                logger.warning(f"Error decoding header: {e}")
                return str(header_value)

        # Handle bytes
        if isinstance(header_value, bytes):
            try:
                return header_value.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                return str(header_value)

        # Handle str, decoding RFC 2047 encoded words (=?utf-8?Q?...?=)
        text = str(header_value)
        try:
            return str(email.header.make_header(email.header.decode_header(text)))
        except (UnicodeDecodeError, LookupError, ValueError, email.errors.HeaderParseError):
            return text

    def _process_email_headers(self, response: dict[int, dict[bytes, bytes]]) -> dict[str, dict[str, str]]:
        """Process email headers from IMAP response."""
        headers = {}
        for msg_id, data in response.items():
            try:
                # The response key might vary, so we need to find the header data
                header_key = next(
                    (k for k in data if k.startswith(b"BODY[HEADER.FIELDS (FROM SUBJECT")), None
                )

                if not header_key or header_key not in data:
                    logger.warning(f"No header data found for email {msg_id}")
                    continue

                # Parse the email message from bytes
                msg = email.message_from_bytes(data[header_key])

                # Safely extract and parse headers
                sender_header = self._parse_header_value(msg.get("From"))
                subject_header = self._parse_header_value(msg.get("Subject"))

                # Parse sender information
                name, sender_address = self._parse_sender(sender_header)

                message_id, has_unsubscribe, is_bulk = list_header_flags(msg)
                headers[str(msg_id)] = {
                    "sender_address": sender_address or "",
                    "sender_name": name or "",
                    "subject": subject_header or "",
                    "message_id": message_id,
                    "has_unsubscribe": has_unsubscribe,
                    "is_bulk": is_bulk,
                }

            except (KeyError, ValueError, UnicodeDecodeError, AttributeError) as e:
                logger.error(f"Could not parse headers for email {msg_id}: {e}")
                # Log the actual data we received for debugging
                if "data" in locals():
                    logger.debug(f"Raw data for {msg_id}: {data}")
        return headers

    def get_email_headers(self, uids: list[str | int]) -> dict[str, dict[str, str]]:
        """
        Fetches 'From' and 'Subject' headers for a given batch of email UIDs.

        Args:
            uids: List of UIDs to fetch headers for

        Returns:
            Dictionary mapping UIDs to their header information
        """
        if not uids:
            return {}

        # Convert all UIDs to integers for consistent processing
        int_uids = [int(uid) if isinstance(uid, str) and uid.isdigit() else uid for uid in uids]

        # Use the batch fetch helper
        return self._batch_fetch(int_uids, [HEADER_FETCH], self._process_email_headers)

    def _process_full_emails(self, response: dict[int, dict[bytes, bytes]]) -> dict[int, Email]:
        """Process full email content from IMAP response."""
        emails = {}
        for msg_id, data in response.items():
            try:
                msg = email.message_from_bytes(data[b"BODY[]"])
                sender_header = self._parse_header_value(msg["From"])
                subject_header = self._parse_header_value(msg["Subject"])

                sender_name, sender_address = self._parse_sender(sender_header or "")
                body = self._get_body_from_msg(msg)
                message_id, has_unsubscribe, is_bulk = list_header_flags(msg)

                emails[msg_id] = Email(
                    msg_id=str(msg_id),
                    subject=subject_header or "",
                    sender_address=sender_address or "",
                    sender_name=sender_name or "",
                    body=body,
                    message_id=message_id,
                    has_unsubscribe=has_unsubscribe,
                    is_bulk=is_bulk,
                )
            except (KeyError, ValueError, UnicodeDecodeError, AttributeError, TypeError) as e:
                logger.error(f"Could not process email {msg_id}: {e}")
        return emails

    def get_full_emails(self, uids: list[str | int]) -> list[Email]:
        """
        Fetches the full content for the specified email UIDs in batches.

        Args:
            uids: List of UIDs to fetch full emails for

        Returns:
            List of Email objects
        """
        if not uids:
            return []

        # Convert all UIDs to integers for consistent processing
        int_uids = [int(uid) if isinstance(uid, str) and uid.isdigit() else uid for uid in uids]

        # Prepare fetch command
        fetch_command = [b"BODY.PEEK[]"]

        # Use the batch fetch helper
        results = self._batch_fetch(int_uids, fetch_command, self._process_full_emails)

        # Return emails in the same order as requested UIDs
        return [results[uid] for uid in int_uids if uid in results]

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def batch_move_emails(self, uids: list[str], destination: str):
        """Moves a batch of emails to a new destination with retry support."""
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        if destination not in self._verified_folders:
            if not self.client.folder_exists(destination):
                self._create_folder_with_retry(destination)
            self._verified_folders.add(destination)

        self._move_emails_with_retry(uids, destination)
        logger.info(f"Moved {len(uids)} emails to {destination}")

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def select_folder(self, folder_name: str) -> None:
        """Selects a folder with retry support."""
        self.client.select_folder(folder_name)

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _create_folder_with_retry(self, folder: str) -> bool:
        """Create an IMAP folder with retry logic.

        Args:
            folder: The folder path to create

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Creating folder: {folder}")
            self.client.create_folder(folder)
            return True
        except (imaplib.IMAP4.error, OSError) as e:
            logger.error(f"Failed to create folder {folder}: {e}")
            raise

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _move_emails_with_retry(self, uids: list[str], destination: str):
        """Moves emails with retry support."""
        self.client.move(uids, destination)

    def _parse_sender(self, raw_sender) -> tuple[str, str]:
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        return parse_sender(raw_sender)

    def _get_body_from_msg(self, msg) -> str:
        """
        Reads the body of a specific email message, prioritizing plain text over HTML.
        Handles various character encodings and malformed content.
        """
        return extract_body_from_message(msg)
