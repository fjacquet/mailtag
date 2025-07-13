from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from tests.mock_imap_client import MockImapClient


@pytest.fixture
def imap_config() -> ImapConfig:
    """Returns a default ImapConfig for testing."""
    return ImapConfig(host="imap.test.com", user="user", password="pass")


@pytest.fixture
def fast_parse_config() -> FastParseConfig:
    """Returns a default FastParseConfig for testing."""
    return FastParseConfig(
        batch_size=10,
        folder_cache_ttl_hours=24,
        unclassified_folder_name="Unclassified",
        junk_folder_name="Junk",
    )


@pytest.fixture
def imap_service(imap_config: ImapConfig, fast_parse_config: FastParseConfig) -> ImapService:
    """Returns an ImapService instance."""
    return ImapService(config=imap_config, fast_parse_config=fast_parse_config)


@pytest.fixture
def mock_imap_client(mocker: MockerFixture) -> MockImapClient:
    """Fixture to mock the IMAP client."""
    mock_client = MockImapClient(host="imap.test.com")
    mocker.patch("mailtag.imap_service.IMAPClient", return_value=mock_client)
    return mock_client


def test_connect_context_manager(
    imap_service: ImapService, mock_imap_client: MockImapClient, mocker: MockerFixture
):
    """Tests that the connect context manager logs in and out."""
    mocker.spy(mock_imap_client, "login")
    mocker.spy(mock_imap_client, "logout")
    with imap_service.connect():
        mock_imap_client.login.assert_called_once()
        assert imap_service.client is not None
    mock_imap_client.logout.assert_called_once()


def test_connect_failure_raises_connection_error(
    imap_service: ImapService, mock_imap_client: MockImapClient, mocker: MockerFixture
):
    """Tests that a ConnectionError is raised on login failure."""
    mocker.patch.object(mock_imap_client, "login", side_effect=Exception("Login failed"))
    with pytest.raises(ConnectionError, match="IMAP connection failed"):
        with imap_service.connect():
            pass


def test_get_folder_hierarchy(
    imap_service: ImapService, mock_imap_client: MockImapClient, mocker: MockerFixture
):
    """Tests that the folder hierarchy is fetched and cached."""
    imap_service.client = mock_imap_client
    mocker.patch.object(Path, "exists", return_value=False)
    mock_open = mocker.patch("pathlib.Path.open", mocker.mock_open())
    folders = imap_service.get_folder_hierarchy()
    assert "INBOX" in folders
    mock_open.assert_called_once_with("w", encoding="utf-8")


def test_get_email_senders(imap_service: ImapService, mock_imap_client: MockImapClient):
    """Tests that email senders are fetched correctly."""
    imap_service.client = mock_imap_client
    imap_service.client.select_folder("INBOX")
    senders = imap_service.get_email_senders([1])
    assert senders["1"] == "test@example.com"


def test_get_full_emails(imap_service: ImapService, mock_imap_client: MockImapClient):
    """Tests that full emails are fetched correctly."""
    imap_service.client = mock_imap_client
    imap_service.client.select_folder("INBOX")
    emails = imap_service.get_full_emails([1])
    assert len(emails) == 1
    assert emails[0].subject == "Test"
    assert emails[0].sender_address == "test@example.com"


def test_batch_move_emails(
    imap_service: ImapService, mock_imap_client: MockImapClient, mocker: MockerFixture
):
    """Tests that emails are moved in a batch."""
    imap_service.client = mock_imap_client
    mocker.spy(mock_imap_client, "move")
    imap_service.batch_move_emails([1, 2], "Archive")
    mock_imap_client.move.assert_called_once_with([1, 2], "Archive")
