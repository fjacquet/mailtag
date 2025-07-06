from unittest.mock import patch, MagicMock
import pytest
from mailtag.gmail_service import GmailService
from mailtag.config import GmailConfig
from mailtag.models import Email

@pytest.fixture
def gmail_config() -> GmailConfig:
    """Returns a default GmailConfig for testing."""
    return GmailConfig(credentials_file="creds.json", token_file="token.json")

@pytest.fixture
def gmail_service(gmail_config: GmailConfig) -> GmailService:
    """Returns a GmailService instance."""
    return GmailService(config=gmail_config)

@patch("mailtag.gmail_service.get_gmail_service")
def test_connect_success(mock_get_service, gmail_service: GmailService):
    """Tests a successful connection to the Gmail API."""
    gmail_service.connect()
    mock_get_service.assert_called_once_with("creds.json", "token.json")

@patch("mailtag.gmail_service.get_gmail_service")
def test_get_emails(mock_get_service, gmail_service: GmailService):
    """Tests fetching emails from the Gmail API."""
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service
    gmail_service.connect()

    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "1"}, {"id": "2"}]
    }
    mock_service.users().messages().get.return_value.execute.side_effect = [
        {"id": "1", "payload": {"headers": [{"name": "Subject", "value": "Test 1"}, {"name": "From", "value": "sender1@test.com"}]}},
        {"id": "2", "payload": {"headers": [{"name": "Subject", "value": "Test 2"}, {"name": "From", "value": "sender2@test.com"}]}},
    ]

    emails = gmail_service.get_emails()
    assert len(emails) == 2
    assert emails[0].subject == "Test 1"
    assert emails[1].sender_address == "sender2@test.com"

@patch("mailtag.gmail_service.get_gmail_service")
def test_get_emails_pagination(mock_get_service, gmail_service: GmailService):
    """Tests fetching emails with pagination."""
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service
    gmail_service.connect()

    mock_service.users().messages().list.side_effect = [
        MagicMock(execute=MagicMock(return_value={
            "messages": [{"id": "1"}],
            "nextPageToken": "token2",
        })),
        MagicMock(execute=MagicMock(return_value={
            "messages": [{"id": "2"}],
        })),
    ]
    mock_service.users().messages().get.return_value.execute.side_effect = [
        {"id": "1", "payload": {"headers": [{"name": "Subject", "value": "Test 1"}, {"name": "From", "value": "sender1@test.com"}]}},
        {"id": "2", "payload": {"headers": [{"name": "Subject", "value": "Test 2"}, {"name": "From", "value": "sender2@test.com"}]}},
    ]

    emails = gmail_service.get_emails()
    assert len(emails) == 2
    assert emails[0].subject == "Test 1"
    assert emails[1].sender_address == "sender2@test.com"

@patch("mailtag.gmail_service.get_gmail_service")
def test_get_email_body(mock_get_service, gmail_service: GmailService):
    """Tests fetching the body of an email."""
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service
    gmail_service.connect()

    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")
    mock_service.users().messages().get.return_value.execute.return_value = {
        "payload": {"body": {"data": "VGhpcyBpcyB0aGUgYm9keS4="}} # "This is the body."
    }
    body = gmail_service.get_email_body(email_model)
    assert "This is the body." in body

@patch("mailtag.gmail_service.get_gmail_service")
def test_move_email(mock_get_service, gmail_service: GmailService):
    """Tests moving an email to a new destination."""
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service
    gmail_service.connect()

    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")
    gmail_service.move_email(email_model, "Label_1")
    mock_service.users().messages().modify.assert_called_once()
