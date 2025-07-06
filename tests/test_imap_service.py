import pytest
from pytest_mock import MockerFixture

from mailtag.config import ImapConfig
from mailtag.imap_service import ImapService
from tests.mock_imap_client import MockImapClient


@pytest.fixture
def imap_config() -> ImapConfig:
    """Returns a default ImapConfig for testing."""
    return ImapConfig(host="imap.test.com", user="user", password="pass")


@pytest.fixture
def imap_service(imap_config: ImapConfig) -> ImapService:
    """Returns an ImapService instance."""
    return ImapService(config=imap_config)


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


def test_get_emails_integration(imap_service: ImapService, mock_imap_client: MockImapClient):
    """
    Tests the get_emails method's integration with the readonly context manager.
    """
    imap_service.client = mock_imap_client
    emails = imap_service.get_emails()
    assert len(emails) == 1
    assert emails[0].subject == "Test"
    assert emails[0].sender_address == "test@example.com"


def test_move_email(imap_service: ImapService, mock_imap_client: MockImapClient, mocker: MockerFixture):
    """
    Tests that the move_email method correctly moves an email.
    """
    imap_service.client = mock_imap_client
    mocker.spy(mock_imap_client, "move")
    email_to_move = imap_service.get_emails()[0]
    imap_service.move_email(email_to_move, "Archive")
    mock_imap_client.move.assert_called_once_with(email_to_move.msg_id, "Archive")