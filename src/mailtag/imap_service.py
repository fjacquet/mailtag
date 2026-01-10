import email
import email.header
import imaplib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from imapclient import IMAPClient
from loguru import logger

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.metrics import configure_metrics, log_metrics, timed
from mailtag.models import Email
from mailtag.providers import EmailProvider
from mailtag.utils.email_parsing import extract_body_from_message, parse_sender

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
        
        # Thread management for metrics logging
        self._metrics_stop_event = threading.Event()
        self._metrics_thread: threading.Thread | None = None

        # Initialize metrics system
        configure_metrics(
            enabled=self.fast_parse_config.metrics_enabled, log_level=self.fast_parse_config.metrics_log_level
        )

        # Start metrics logging thread if enabled
        if self.fast_parse_config.metrics_enabled and self.fast_parse_config.metrics_log_interval_minutes > 0:
            self._start_metrics_logging_thread()

    def _start_metrics_logging_thread(self):
        """Start a background thread to periodically log metrics with proper lifecycle management."""
        if self._metrics_thread and self._metrics_thread.is_alive():
            return  # Already running

        def log_metrics_periodically():
            """Log metrics at configured intervals until stopped."""
            interval_seconds = self.fast_parse_config.metrics_log_interval_minutes * 60
            while not self._metrics_stop_event.wait(timeout=interval_seconds):
                try:
                    log_metrics()
                except Exception as e:
                    logger.error(f"Metrics logging failed: {e}")
                    # Continue running despite errors

        self._metrics_thread = threading.Thread(
            target=log_metrics_periodically,
            daemon=True,
            name="metrics-logger"
        )
        self._metrics_thread.start()
        interval_minutes = self.fast_parse_config.metrics_log_interval_minutes
        logger.debug(f"Started metrics logging thread with {interval_minutes} minute interval")

    def _stop_metrics_thread(self):
        """Stop the metrics logging thread gracefully."""
        if self._metrics_stop_event:
            self._metrics_stop_event.set()
        if self._metrics_thread and self._metrics_thread.is_alive():
            self._metrics_thread.join(timeout=5.0)  # Wait up to 5s
            logger.debug("Metrics logging thread stopped")

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
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            self.client = None
            raise ConnectionError(f"IMAP connection failed: {e}") from e
        finally:
            # Stop metrics thread before disconnecting
            self._stop_metrics_thread()
            
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
            except (OSError, PermissionError) as e:
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

            except (KeyError, ValueError, UnicodeDecodeError, AttributeError) as e:
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
            except (KeyError, ValueError, UnicodeDecodeError, AttributeError, TypeError) as e:
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
        except (imaplib.IMAP4.error, OSError) as e:
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
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"Failed to move email {uid} to folder {folder}: {e}")
            return False

    def _parse_sender(self, raw_sender) -> tuple[str, str]:
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        return parse_sender(raw_sender)

    def _get_body_from_msg(self, msg) -> str:
        """
        Reads the body of a specific email message, prioritizing plain text over HTML.
        Handles various character encodings and malformed content.
        """
        return extract_body_from_message(msg)
