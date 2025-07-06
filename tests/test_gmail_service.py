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
    # Mock the initial label list call during connection
    service.users().labels().list().execute.return_value = {
        "labels": [
            {"id": "IMPORTANT", "name": "MyLabel"},
            {"id": "INBOX", "name": "Inbox"},
        ]
    }
    return service


@pytest.fixture
def gmail_service(
    gmail_config: GmailConfig, mock_google_service: MockerFixture, mocker: MockerFixture
) -> GmailService:
    """Returns a GmailService instance with a mocked Google service."""
    mocker.patch("mailtag.gmail_service.get_gmail_service", return_value=mock_google_service)
    service = GmailService(config=gmail_config)
    service.connect()  # Connect to cache labels
    return service


def test_connect_and_cache_labels(gmail_service: GmailService, mock_google_service: MockerFixture):
    """Tests that connecting successfully caches the labels."""
    assert gmail_service.service is not None
    mock_google_service.users().labels().list.assert_called_once_with(userId="me")
    assert "MyLabel" in gmail_service._label_cache.values()
    assert "IMPORTANT" in gmail_service._label_cache


def test_get_emails_single_call_and_parsing(gmail_service: GmailService, mock_google_service: MockerFixture):
    """
    Tests that get_emails uses format='full' to fetch all data in one call
    and correctly parses the response.
    """
    # Mock the messages.list response
    mock_google_service.users().messages().list().execute.return_value = {"messages": [{"id": "123"}]}

    # Mock the messages.get response with a full payload
    body_content = "This is the email body."
    encoded_body = base64.urlsafe_b64encode(body_content.encode("utf-8")).decode("utf-8")
    full_message_payload = {
        "id": "123",
        "labelIds": ["INBOX", "IMPORTANT"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Full Test"},
                {"name": "From", "value": "Sender Name <sender@example.com>"},
            ],
            "parts": [{"mimeType": "text/plain", "body": {"data": encoded_body}}],
        },
    }
    mock_google_service.users().messages().get().execute.return_value = full_message_payload

    emails = gmail_service.get_emails()

    # Verify that get was called with format='full'
    mock_google_service.users().messages().get.assert_called_once_with(userId="me", id="123", format="full")

    assert len(emails) == 1
    email = emails[0]
    assert email.subject == "Full Test"
    assert email.sender_name == "Sender Name"
    assert email.sender_address == "sender@example.com"
    assert email.body == body_content
    assert "Inbox" in email.labels
    assert "MyLabel" in email.labels


def test_move_email_label_exists(gmail_service: GmailService, mock_google_service: MockerFixture):
    """Tests moving an email when the destination label already exists in the cache."""
    email_to_move = gmail_service.get_emails()[0] if gmail_service.get_emails() else None
    if email_to_move:
        gmail_service.move_email(email_to_move, "MyLabel")

        expected_body = {"removeLabelIds": ["INBOX"], "addLabelIds": ["IMPORTANT"]}
        mock_google_service.users().messages().modify.assert_called_once_with(
            userId="me", id=email_to_move.msg_id, body=expected_body
        )
        # Ensure create is not called when label exists
        mock_google_service.users().labels().create.assert_not_called()


def test_move_email_creates_label_if_not_found(
    gmail_service: GmailService, mock_google_service: MockerFixture
):
    """
    Tests that a new label is created during a move operation if the destination
    label does not exist.
    """
    new_label_name = "NewLabel"
    new_label_id = "NEW_ID"

    # Mock the create response
    mock_google_service.users().labels().create().execute.return_value = {
        "id": new_label_id,
        "name": new_label_name,
    }

    email_to_move = gmail_service.get_emails()[0] if gmail_service.get_emails() else None
    if email_to_move:
        gmail_service.move_email(email_to_move, new_label_name)

        # Verify that create was called
        expected_label_body = {"name": new_label_name, "labelListVisibility": "labelShow"}
        mock_google_service.users().labels().create.assert_called_once_with(
            userId="me", body=expected_label_body
        )

        # Verify that the email was moved to the newly created label
        expected_move_body = {"removeLabelIds": ["INBOX"], "addLabelIds": [new_label_id]}
        mock_google_service.users().messages().modify.assert_called_once_with(
            userId="me", id=email_to_move.msg_id, body=expected_move_body
        )

        # Verify the cache was updated
        assert gmail_service._label_cache[new_label_id] == new_label_name
