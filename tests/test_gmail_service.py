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
    return GmailService(config=gmail_config)


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
