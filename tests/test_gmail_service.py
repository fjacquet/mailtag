import pytest
from pytest_mock import MockerFixture

from mailtag.config import GmailConfig
from mailtag.gmail_service import GmailService
from tests.mock_gmail_service import MockGmailService


@pytest.fixture
def gmail_config() -> GmailConfig:
    """Returns a default GmailConfig for testing."""
    return GmailConfig(credentials_file="creds.json", token_file="token.json")


@pytest.fixture
def gmail_service_instance(
    gmail_config: GmailConfig, mock_gmail_service: MockGmailService, mocker: MockerFixture
) -> GmailService:
    """Returns a GmailService instance with a mocked Google service."""
    service = GmailService(config=gmail_config)
    service.service = mock_gmail_service
    return service


def test_connect_context_manager(gmail_service_instance: GmailService, mock_gmail_service: MockGmailService):
    """Tests that the connect context manager caches labels on entry."""
    with gmail_service_instance.connect() as service:
        assert service.service is not None
        assert "MyLabel" in service._label_cache.values()


def test_get_emails_integration(gmail_service_instance: GmailService, mock_gmail_service: MockGmailService):
    """
    Tests that get_emails correctly fetches and parses data within the connect context.
    """
    mock_gmail_service.add_message(
        msg_id="123",
        label_ids=["INBOX", "IMPORTANT"],
        subject="Test",
        body="Test body",
    )

    with gmail_service_instance.connect() as service:
        emails = service.get_emails()
        assert len(emails) == 1
        assert emails[0].body == "Test body"
        assert "MyLabel" in emails[0].labels


def test_move_email(
    gmail_service_instance: GmailService, mock_gmail_service: MockGmailService, mocker: MockerFixture
):
    """
    Tests that move_email correctly modifies the labels of an email.
    """
    mock_gmail_service.add_message(
        msg_id="123",
        label_ids=["INBOX", "IMPORTANT"],
        subject="Test",
        body="Test body",
    )
    with gmail_service_instance.connect() as service:
        mocker.spy(service.service.users().messages(), "modify")
        email_to_move = service.get_emails()[0]
        service.move_email(email_to_move, "Archive")
        service.service.users().messages().modify.assert_called_once()


def test_get_emails_with_filters(gmail_service_instance: GmailService, mock_gmail_service: MockGmailService):
    """
    Tests that get_emails correctly applies filters.
    """
    mock_gmail_service.add_message(
        msg_id="123",
        label_ids=["INBOX", "IMPORTANT"],
        subject="A very specific test email",
        body="Test body",
    )
    mock_gmail_service.add_message(
        msg_id="456",
        label_ids=["INBOX"],
        subject="Another thing entirely",
        body="Another Test body",
        sender="another@sender.com",
    )

    with gmail_service_instance.connect() as service:
        emails = service.get_emails(subject="specific test")
        assert len(emails) == 1
        assert emails[0].msg_id == "123"

        emails = service.get_emails(sender="another@sender.com")
        assert len(emails) == 1
        assert emails[0].msg_id == "456"
