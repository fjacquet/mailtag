import email
import email.header
import json
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from bs4 import BeautifulSoup
from imapclient import IMAPClient
from loguru import logger

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.metrics import configure_metrics, log_metrics, timed
from mailtag.models import Email
from mailtag.providers import EmailProvider

from .retry import retry

# Type variable for generic return type
T = TypeVar("T")

# Maximum number of UIDs to fetch in a single batch to avoid "Too long argument" errors
# This is now configurable via FastParseConfig.batch_size


class ImapService(EmailProvider):
    """Handles interactions with an IMAP email server using IMAPClient."""

    def __init__(self, config: ImapConfig, fast_parse_config: FastParseConfig):
        self.config = config
        self.fast_parse_config = fast_parse_config
        self.client: IMAPClient | None = None
        self.folder_cache_path = Path("data/imap_folders.json")

        # Initialize metrics system
        configure_metrics(
            enabled=self.fast_parse_config.metrics_enabled, log_level=self.fast_parse_config.metrics_log_level
        )

        # Start metrics logging thread if enabled
        if self.fast_parse_config.metrics_enabled and self.fast_parse_config.metrics_log_interval_minutes > 0:
            self._start_metrics_logging_thread()

    def _start_metrics_logging_thread(self):
        """Start a background thread to periodically log metrics."""

        def log_metrics_periodically():
            while True:
                # Sleep for the configured interval
                time.sleep(self.fast_parse_config.metrics_log_interval_minutes * 60)
                # Log metrics

                log_metrics()

        # Create and start the thread as daemon so it doesn't block program exit
        metrics_thread = threading.Thread(target=log_metrics_periodically, daemon=True, name="metrics-logger")
        metrics_thread.start()
        interval = self.fast_parse_config.metrics_log_interval_minutes
        logger.debug(f"Started metrics logging thread with {interval} minute interval")

    def is_connected(self) -> bool:
        """Checks if the mail client is connected."""
        return self.client is not None and self.client.is_login()

    @timed(operation_name="imap_connect")
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
        except Exception as e:
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

    def get_folder_hierarchy(self) -> list[str]:
        """
        Fetches the folder hierarchy from the IMAP server and caches it.
        """
        # Try to load from cache if it exists and is not expired
        if self.folder_cache_path.exists():
            try:
                cache_mod_time = datetime.fromtimestamp(self.folder_cache_path.stat().st_mtime)
                if datetime.now() - cache_mod_time < timedelta(
                    hours=self.fast_parse_config.folder_cache_ttl_hours
                ):
                    with self.folder_cache_path.open("r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:  # Check if file is not empty
                            try:
                                return json.loads(content)
                            except json.JSONDecodeError as e:
                                logger.warning(f"Invalid JSON in cache file: {e}. Refreshing from server.")
            except Exception as e:
                logger.warning(f"Error reading cache file: {e}. Refreshing from server.")

        # If we get here, we need to fetch from the server
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        folders = self._list_folders_with_retry()

        # Ensure data directory exists
        self.folder_cache_path.parent.mkdir(exist_ok=True)

        # Save to cache
        with self.folder_cache_path.open("w", encoding="utf-8") as f:
            json.dump(folders, f, indent=2)

        return folders

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _list_folders_with_retry(self) -> list[str]:
        """
        Lists folders with retry support for transient failures.
        """
        return [folder[2] for folder in self.client.list_folders()]

    @timed(operation_name="imap_batch_fetch")
    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _batch_fetch(
        self, uids: list[str | int], fetch_command: list[bytes], processor: callable
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
            except Exception as e:
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
            except Exception as e:
                logger.warning(f"Error decoding header: {e}")
                return str(header_value)

        # Handle bytes
        if isinstance(header_value, bytes):
            try:
                return header_value.decode("utf-8", errors="replace")
            except Exception:
                return str(header_value)

        # Handle other types
        return str(header_value)

    def _process_email_headers(self, response: dict[int, dict[bytes, bytes]]) -> dict[str, dict[str, str]]:
        """Process email headers from IMAP response."""
        headers = {}
        for msg_id, data in response.items():
            try:
                # The response key might vary, so we need to find the header data
                header_key = next(
                    (k for k in data if k.startswith(b"BODY[HEADER.FIELDS (FROM SUBJECT)")), None
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
                _, sender_address = self._parse_sender(sender_header)

                headers[str(msg_id)] = {
                    "sender_address": sender_address or "",
                    "subject": subject_header or "",
                }

            except Exception as e:
                logger.error(f"Could not parse headers for email {msg_id}: {e}")
                # Log the actual data we received for debugging
                if "data" in locals():
                    logger.debug(f"Raw data for {msg_id}: {data}")
        return headers

    @timed(operation_name="imap_get_email_headers")
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
        return self._batch_fetch(
            int_uids, [b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"], self._process_email_headers
        )

    def get_email_senders(self, uids: list[str | int]) -> dict[str, str]:
        """
        Fetches only the 'From' header for a given batch of email UIDs.
        DEPRECATED: Use get_email_headers instead.
        """
        email_headers = self.get_email_headers(uids)
        return {uid: headers["sender_address"] for uid, headers in email_headers.items()}

    def _process_full_emails(self, response: dict[int, dict[bytes, bytes]]) -> dict[int, Email]:
        """Process full email content from IMAP response."""
        emails = {}
        for msg_id, data in response.items():
            try:
                msg = email.message_from_bytes(data[b"BODY[]"])
                sender_header = msg["From"]
                subject_header = msg["Subject"]

                # Safely convert header objects to strings
                if sender_header is not None:
                    if hasattr(sender_header, "decode"):
                        sender_header = sender_header.decode()
                    elif hasattr(email.header, "Header") and isinstance(sender_header, email.header.Header):
                        sender_header = str(sender_header)

                if subject_header is not None:
                    if hasattr(subject_header, "decode"):
                        subject_header = subject_header.decode()
                    elif hasattr(email.header, "Header") and isinstance(subject_header, email.header.Header):
                        subject_header = str(subject_header)

                sender_name, sender_address = self._parse_sender(sender_header or "")
                body = self._get_body_from_msg(msg)
                labels = [
                    label.decode() if isinstance(label, bytes) else str(label)
                    for label in data.get(b"X-GM-LABELS", [])
                ]

                emails[msg_id] = Email(
                    msg_id=str(msg_id),
                    subject=subject_header or "",
                    sender_address=sender_address or "",
                    sender_name=sender_name or "",
                    body=body,
                    labels=labels,
                )
            except Exception as e:
                logger.error(f"Could not process email {msg_id}: {e}")
        return emails

    @timed(operation_name="imap_get_full_emails")
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
        if self.config.use_gmail_extensions:
            fetch_command.append(b"X-GM-LABELS")

        # Use the batch fetch helper
        results = self._batch_fetch(int_uids, fetch_command, self._process_full_emails)

        # Return emails in the same order as requested UIDs
        return [results[uid] for uid in int_uids if uid in results]

    def get_emails(
        self,
        subject: str | None = None,
        sender: str | None = None,
        status: str | None = None,
    ) -> list[Email]:
        """This method is deprecated for IMAP and will not be implemented."""
        raise NotImplementedError("get_emails is not supported for IMAP with Fast Parse.")

    @timed(operation_name="imap_batch_move_emails")
    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def batch_move_emails(self, uids: list[str], destination: str):
        """Moves a batch of emails to a new destination with retry support."""
        if not self.client:
            raise ConnectionError("Not connected to IMAP server.")

        if not self.client.folder_exists(destination):
            self._create_folder_with_retry(destination)

        self._move_emails_with_retry(uids, destination)
        logger.info(f"Moved {len(uids)} emails to {destination}")

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    @timed(operation_name="imap_select_folder")
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
        except Exception as e:
            logger.error(f"Failed to create folder {folder}: {e}")
            raise

    @retry(exceptions=(ConnectionError, TimeoutError, IOError))
    def _move_emails_with_retry(self, uids: list[str], destination: str):
        """Moves emails with retry support."""
        self.client.move(uids, destination)

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination."""
        self.batch_move_emails([email_model.msg_id], destination)

    def _move_email_to_folder(self, uid: int, folder: str) -> bool:
        """Move an email to a specific folder.

        Args:
            uid: The email UID to move
            folder: The destination folder

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if folder exists, create it if it doesn't
            if not self.client.folder_exists(folder):
                logger.info(f"Folder {folder} does not exist, creating it")
                self._create_folder_with_retry(folder)

            self.client.move([uid], folder)
            return True
        except Exception as e:
            logger.error(f"Failed to move email {uid} to folder {folder}: {e}")
            return False

    def _parse_sender(self, raw_sender) -> tuple[str, str]:
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        # Handle None case
        if raw_sender is None:
            return "", ""

        # Handle email.header.Header objects
        if hasattr(email.header, "Header") and isinstance(raw_sender, email.header.Header):
            raw_sender = str(raw_sender)
        # Handle bytes objects
        elif isinstance(raw_sender, bytes):
            try:
                raw_sender = raw_sender.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    raw_sender = raw_sender.decode("latin-1")
                except Exception:
                    return "", ""
        # Ensure we have a string
        elif not isinstance(raw_sender, str):
            try:
                raw_sender = str(raw_sender)
            except Exception:
                return "", ""

        # Empty string check
        if not raw_sender:
            return "", ""

        # Parse the sender string
        match = re.match(r"(.+?)\s*<(.+?)>", raw_sender)
        if match:
            name, address = match.groups()
            return name, address.lower()
        return "", raw_sender.lower() if raw_sender else ""

    def _decode_payload(self, part) -> str:
        """
        Decode email part payload with proper character encoding handling.
        """
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                return ""

            # Try to get charset from the part
            charset = part.get_content_charset() or "utf-8"

            # Common charsets to try if the specified one fails
            charsets = [charset, "utf-8", "latin-1", "iso-8859-1", "windows-1252"]

            for cs in charsets:
                try:
                    return payload.decode(cs, errors="strict")
                except (UnicodeDecodeError, LookupError):
                    continue

            # If all else fails, use replace to handle errors
            return payload.decode("utf-8", errors="replace")

        except Exception as e:
            logger.warning(f"Error decoding email part: {e}")
            return "[Error decoding content]"

    def _get_body_from_msg(self, msg) -> str:
        """
        Reads the body of a specific email message, prioritizing plain text over HTML.
        Handles various character encodings and malformed content.
        """
        plain_text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                try:
                    content_type = part.get_content_type()
                    payload = self._decode_payload(part)

                    if content_type == "text/plain" and not plain_text_body:
                        plain_text_body = payload
                    elif content_type == "text/html" and not html_body:
                        html_body = payload
                except Exception as e:
                    logger.warning(f"Error processing email part: {e}")
                    continue
        else:
            try:
                plain_text_body = self._decode_payload(msg)
            except Exception as e:
                logger.warning(f"Error processing email: {e}")

        # Return plain text if available, otherwise try HTML
        if plain_text_body.strip():
            return plain_text_body.strip()

        if html_body:
            try:
                soup = BeautifulSoup(html_body, "html.parser")
                return soup.get_text(separator="\n", strip=True)
            except Exception as e:
                logger.warning(f"Error parsing HTML content: {e}")
                # If we can't parse the HTML, return it as is
                return html_body.strip()

        return ""
