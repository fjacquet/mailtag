import base64

import pytest
from pytest_mock import MockerFixture

from mailtag.config import GmailConfig
from mailtag.gmail_service import GmailService


@pytest.fixture
def gmail_config() -> GmailConfig:
    """Returns a default GmailConfig for testing."""
    return GmailConfig(credentials_file="creds.json", token_file="token.json")


@pytest.fixture
def mock_google_service(mocker: MockerFixture):
    """Mocks the Google API service object."""
    service = mocker.MagicMock()
    service.users().labels().list().execute.return_value = {
        "labels": [
            {"id": "IMPORTANT", "name": "MyLabel"},
            {"id": "INBOX", "name": "Inbox"},
        ]
    }
    return service


@pytest.fixture
def gmail_service_instance(
    gmail_config: GmailConfig, mock_google_service: MockerFixture, mocker: MockerFixture
) -> GmailService:
    """Returns a GmailService instance with a mocked Google service."""
    mocker.patch("mailtag.gmail_service.get_gmail_service", return_value=mock_google_service)
    return GmailService(config=gmail_config)


def test_connect_context_manager(gmail_service_instance: GmailService, mock_google_service: MockerFixture):
    """Tests that the connect context manager caches labels on entry."""
    with gmail_service_instance.connect() as service:
        assert service.service is not None
        assert "MyLabel" in service._label_cache.values()


def test_get_emails_integration(gmail_service_instance: GmailService, mock_google_service: MockerFixture):
    """
    Tests that get_emails correctly fetches and parses data within the connect context.
    """
    with gmail_service_instance.connect() as service:
        # Mock the messages.list response
        mock_google_service.users().messages().list().execute.return_value = {"messages": [{"id": "123"}]}

        # Mock the messages.get response
        body_content = "Test body"
        encoded_body = base64.urlsafe_b64encode(body_content.encode("utf-8")).decode("utf-8")
        full_message_payload = {
            "id": "123",
            "labelIds": ["INBOX", "IMPORTANT"],
            "payload": {
                "headers": [{"name": "Subject", "value": "Test"}],
                "parts": [{"mimeType": "text/plain", "body": {"data": encoded_body}}],
            },
        }
        mock_google_service.users().messages().get().execute.return_value = full_message_payload

        emails = service.get_emails()
        assert len(emails) == 1
        assert emails[0].body == body_content
        assert "MyLabel" in emails[0].labels
