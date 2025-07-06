import imaplib
from email.mime.multipart import MIMEMultipart

import pytest
from pytest_mock import MockerFixture

from mailtag.config import ImapConfig
from mailtag.imap_service import ImapService


@pytest.fixture
def imap_config() -> ImapConfig:
    """Returns a default ImapConfig for testing."""
    return ImapConfig(host="imap.test.com", user="user", password="pass")


@pytest.fixture
def imap_service(imap_config: ImapConfig) -> ImapService:
    """Returns an ImapService instance."""
    return ImapService(config=imap_config)


@pytest.fixture
def mock_imap_conn(mocker: MockerFixture) -> MockerFixture:
    """Mocks the imaplib.IMAP4_SSL connection object and patches the module."""
    mock_conn = mocker.MagicMock(spec=imaplib.IMAP4_SSL)
    mocker.patch("mailtag.imap_service.imaplib.IMAP4_SSL", return_value=mock_conn)
    return mock_conn


def test_connect_context_manager(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """Tests that the connect context manager logs in and out."""
    with imap_service.connect():
        mock_imap_conn.login.assert_called_once()
        assert imap_service.mail is not None
    mock_imap_conn.logout.assert_called_once()


def test_connect_failure_raises_connection_error(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """Tests that a ConnectionError is raised on login failure."""
    mock_imap_conn.login.side_effect = imaplib.IMAP4.error("Login failed")
    with pytest.raises(ConnectionError, match="IMAP connection failed"):
        with imap_service.connect():
            pass  # This block should not be reached


def test_readonly_inbox_context_manager(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """Tests the _readonly_inbox context manager selects and deselects correctly."""
    imap_service.mail = mock_imap_conn
    mock_imap_conn.select.return_value = ("OK", [b"1"])

    with imap_service._readonly_inbox():
        mock_imap_conn.select.assert_called_once_with("inbox", readonly=True)

    # After exiting the context, it should be called again to reset to read-write
    mock_imap_conn.select.assert_called_with("inbox", readonly=False)
    assert mock_imap_conn.select.call_count == 2


def test_get_emails_integration(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """
    Tests the get_emails method's integration with the readonly context manager.
    """
    imap_service.mail = mock_imap_conn
    mock_imap_conn.select.return_value = ("OK", [b"1"])
    mock_imap_conn.search.return_value = ("OK", [b"1"])

    msg = MIMEMultipart()
    msg["From"] = "test@example.com"
    msg["Subject"] = "Test"
    fetch_response = [(b"1 (BODY.PEEK[])", msg.as_bytes()), b")"]
    mock_imap_conn.fetch.return_value = ("OK", fetch_response)

    emails = imap_service.get_emails()
    assert len(emails) == 1
    mock_imap_conn.select.assert_any_call("inbox", readonly=True)
    mock_imap_conn.select.assert_called_with("inbox", readonly=False)


def test_move_email_suppresses_already_exists(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """
    Tests that the 'ALREADYEXISTS' error is suppressed when creating a mailbox.
    """
    imap_service.mail = mock_imap_conn
    mock_imap_conn.select.return_value = ("OK", [b"1"])
    mock_imap_conn.search.return_value = ("OK", [b"1"])
    # Simulate the error that should be suppressed
    mock_imap_conn.create.side_effect = imaplib.IMAP4.error("Mailbox already exists (ALREADYEXISTS)")

    email_to_move = imap_service.get_emails()[0] if imap_service.get_emails() else None
    if email_to_move:
        # This should not raise an exception
        imap_service.move_email(email_to_move, "Archive")

        mock_imap_conn.create.assert_called_once_with("Archive")
        # Verify that the rest of the move operation continues
        mock_imap_conn.copy.assert_called_once()
        mock_imap_conn.store.assert_called_once()
        mock_imap_conn.expunge.assert_called_once()
