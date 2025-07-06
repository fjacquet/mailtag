import base64

from loguru import logger

from .config import GmailConfig
from .gmail_auth import get_gmail_service
from .models import Email
from .providers import EmailProvider


class GmailService(EmailProvider):
    """Handles interactions with the Gmail API."""

    def __init__(self, config: GmailConfig):
        self.config = config
        self.service = None

    def connect(self):
        """Connects to the Gmail API."""
        self.service = get_gmail_service(self.config.credentials_file, self.config.token_file)
        logger.info("Successfully connected to Gmail API.")

    def get_emails(self) -> list[Email]:
        """Fetches emails from the Inbox."""
        if not self.service:
            raise ConnectionError("Not connected to Gmail API.")

        emails = []
        page_token = None
        while True:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", labelIds=["INBOX"], pageToken=page_token)
                .execute()
            )
            messages = results.get("messages", [])

            for message in messages:
                msg = self.service.users().messages().get(userId="me", id=message["id"]).execute()
                headers = msg["payload"]["headers"]
                subject = next((i["value"] for i in headers if i["name"] == "Subject"), None)
                sender = next((i["value"] for i in headers if i["name"] == "From"), None)
                sender_name, sender_address = self._parse_sender(sender)

                emails.append(
                    Email(
                        msg_id=message["id"],
                        subject=subject,
                        sender_address=sender_address,
                        sender_name=sender_name,
                    )
                )

            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return emails

    def get_email_body(self, email_model: Email) -> str:
        """Reads the body of a specific email."""
        if not self.service:
            raise ConnectionError("Not connected to Gmail API.")

        msg = self.service.users().messages().get(userId="me", id=email_model.msg_id).execute()
        payload = msg["payload"]
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"]["data"]
                    return base64.urlsafe_b64decode(data).decode("utf-8")
        else:
            data = payload["body"]["data"]
            return base64.urlsafe_b64decode(data).decode("utf-8")
        return ""

    def move_email(self, email_model: Email, destination: str):
        """Moves an email to a new destination by changing its labels."""
        if not self.service:
            raise ConnectionError("Not connected to Gmail API.")

        body = {"removeLabelIds": ["INBOX"], "addLabelIds": [destination]}
        self.service.users().messages().modify(userId="me", id=email_model.msg_id, body=body).execute()
        logger.info(f"Moved email {email_model.msg_id} to {destination}")

    def _parse_sender(self, raw_sender: str) -> (str, str):
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        if "<" in raw_sender and ">" in raw_sender:
            name, address = raw_sender.split("<")
            return name.strip(), address.replace(">", "").strip()
        return "", raw_sender