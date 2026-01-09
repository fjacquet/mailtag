import base64
import base64
from contextlib import contextmanager

from loguru import logger

from .config import GmailConfig
from .gmail_auth import get_gmail_service
from .models import Email
from .providers import EmailProvider
from .utils.email_parsing import parse_sender


class GmailService(EmailProvider):
    """Handles interactions with the Gmail API."""

    def __init__(self, config: GmailConfig):
        self.config = config
        self.service = None
        self._label_cache = {}

    @contextmanager
    def connect(self):
        """
        Connects to the Gmail API and yields the service as a context manager.
        """
        try:
            self.service = get_gmail_service(self.config.credentials_file, self.config.token_file)
            if self.service:
                logger.info("Successfully connected to Gmail API.")
                self._cache_labels()
                yield self
            else:
                raise ConnectionError("Failed to get Gmail service.")
        except ImportError as e:
            # Propagate import errors with a clear message
            logger.error(e)
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Gmail API: {e}")
            raise ConnectionError(f"Gmail connection failed: {e}") from e
        finally:
            # The Gmail API client doesn't have an explicit disconnect/logout method
            # as it's based on HTTP requests with tokens.
            logger.info("Gmail service context exited.")

    def _cache_labels(self) -> None:
        """Caches all available user labels for quick lookup."""
        if not self.service:
            return
        results = self.service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        self._label_cache = {label["id"]: label["name"] for label in labels}
        logger.info(f"Cached {len(self._label_cache)} Gmail labels.")

    def get_emails(
        self,
        subject: str | None = None,
        sender: str | None = None,
        status: str | None = None,
    ) -> list[Email]:
        """Fetches emails from the Inbox, including their body and labels."""
        if not self.service:
            raise ConnectionError("Not connected to Gmail API.")

        query_parts = ["in:inbox"]
        if subject:
            query_parts.append(f"subject:{subject}")
        if sender:
            query_parts.append(f"from:{sender}")
        if status:
            if status == "UNSEEN":
                query_parts.append("is:unread")
            elif status == "SEEN":
                query_parts.append("is:read")

        query = " ".join(query_parts)
        logger.debug(f"Using Gmail query: {query}")

        emails = []
        page_token = None
        while True:
            results = (
                self.service.users().messages().list(userId="me", q=query, pageToken=page_token).execute()
            )
            messages = results.get("messages", [])

            for message in messages:
                # Use format='full' to get all necessary details in one API call
                msg = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=message["id"], format="full")
                    .execute()
                )
                headers = msg["payload"]["headers"]
                subject_header = next((i["value"] for i in headers if i["name"] == "Subject"), "")
                sender_header = next((i["value"] for i in headers if i["name"] == "From"), "")
                sender_name, sender_address = self._parse_sender(sender_header)

                body = self._get_body_from_payload(msg["payload"])
                labels = [self._label_cache.get(lid, lid) for lid in msg.get("labelIds", [])]

                emails.append(
                    Email(
                        msg_id=message["id"],
                        subject=subject_header,
                        sender_address=sender_address,
                        sender_name=sender_name,
                        body=body,
                        labels=labels,
                    )
                )

            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return emails

    def _get_body_from_payload(self, payload: dict) -> str:
        """Extracts the text/plain body from the message payload."""
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain" and "data" in part["body"]:
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    break  # Found plain text, no need to look further
        elif "data" in payload["body"]:
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        return body

    def _get_label_id_by_name(self, label_name: str) -> str | None:
        """Gets the ID of a label by its name from the cache."""
        for label_id, name in self._label_cache.items():
            if name.lower() == label_name.lower():
                return label_id
        logger.warning(f"Label '{label_name}' not found in cache.")
        return None

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination by changing its labels."""
        if not self.service:
            raise ConnectionError("Not connected to Gmail API.")

        label_id_to_add = self._get_label_id_by_name(destination)
        if not label_id_to_add:
            # As a fallback, try to create the label
            logger.info(f"Label '{destination}' not found, attempting to create it.")
            try:
                label = (
                    self.service.users()
                    .labels()
                    .create(userId="me", body={"name": destination, "labelListVisibility": "labelShow"})
                    .execute()
                )
                label_id_to_add = label["id"]
                self._label_cache[label_id_to_add] = destination  # Update cache
            except Exception as e:
                logger.error(f"Could not create label '{destination}': {e}")
                return

        body = {"removeLabelIds": ["INBOX"], "addLabelIds": [label_id_to_add]}
        try:
            self.service.users().messages().modify(userId="me", id=email_model.msg_id, body=body).execute()
            logger.info(f"Moved email {email_model.msg_id} to {destination}")
        except Exception as e:
            logger.error(f"Failed to move email {email_model.msg_id}: {e}")

    def _parse_sender(self, raw_sender: str) -> tuple[str, str]:
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        return parse_sender(raw_sender)
