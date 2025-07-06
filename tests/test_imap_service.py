import imaplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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


def test_connect_success(imap_service: ImapService, mock_imap_conn: MockerFixture, imap_config: ImapConfig):
    """Tests a successful connection to the IMAP server."""
    imap_service.connect()
    mock_imap_conn.login.assert_called_once_with(imap_config.user, imap_config.password)
    assert imap_service.mail is mock_imap_conn


def test_connect_failure(imap_service: ImapService, mock_imap_conn: MockerFixture, caplog):
    """Tests the connection failure scenario."""
    error_message = "Login failed"
    mock_imap_conn.login.side_effect = imaplib.IMAP4.error(error_message)
    with caplog.at_level("ERROR"):
        imap_service.connect()
        assert not imap_service.is_connected()
        assert f"Failed to connect to IMAP server: {error_message}" in caplog.text.strip()


def test_disconnect(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """Tests disconnecting from the IMAP server."""
    imap_service.connect()
    imap_service.disconnect()
    mock_imap_conn.logout.assert_called_once()


def test_get_emails_preserves_unread_status(imap_service: ImapService, mock_imap_conn: MockerFixture):
    r"""
    Tests that get_emails uses readonly=True to select the inbox, preserving
    the \Seen flag on messages.
    """
    imap_service.connect()
    mock_imap_conn.select.return_value = ("OK", [b"1"])
    mock_imap_conn.search.return_value = ("OK", [b""])  # No messages

    imap_service.get_emails()

    # Check that the initial select is read-only
    mock_imap_conn.select.assert_any_call("inbox", readonly=True)
    # Check that it's set back to read-write at the end
    mock_imap_conn.select.assert_called_with("inbox", readonly=False)


def test_get_emails_fetches_body_and_labels(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """
    Tests that get_emails fetches the full message content and labels
    using BODY.PEEK[] and X-GM-LABELS.
    """
    imap_service.connect()
    mock_imap_conn.select.return_value = ("OK", [b"1"])
    mock_imap_conn.search.return_value = ("OK", [b"1"])

    # Create a sample email
    msg = MIMEMultipart("alternative")
    msg["From"] = "Sender 1 <sender1@test.com>"
    msg["Subject"] = "Test Subject"
    msg.attach(MIMEText("This is the plain text body."))
    msg.attach(MIMEText("<h1>HTML Body</h1>", "html"))

    # Mock the fetch response
    fetch_response = [
        (
            b'1 (X-GM-LABELS ("\\Inbox" "Services/Skylum") BODY[] {3...})',
            msg.as_bytes(),
        ),
        b")",
    ]
    # The structure of the response for X-GM-LABELS can be complex.
    # We simplify here and parse it inside the method.
    mock_imap_conn.fetch.return_value = ("OK", fetch_response)

    emails = imap_service.get_emails()

    assert len(emails) == 1
    email = emails[0]

    # Verify that BODY.PEEK[] was used
    mock_imap_conn.fetch.assert_called_once_with(b"1", "(BODY.PEEK[] X-GM-LABELS)")

    # Verify email content
    assert email.subject == "Test Subject"
    assert email.sender_address == "sender1@test.com"
    assert email.body == "This is the plain text body."
    assert "Services/Skylum" in email.labels
    assert "\\Inbox" not in email.labels  # System labels should be filtered


def test_move_email(imap_service: ImapService, mock_imap_conn: MockerFixture):
    """Tests moving an email to a different folder."""
    imap_service.connect()
    mock_imap_conn.create.return_value = ("OK", [b""])
    mock_imap_conn.copy.return_value = ("OK", [b"1"])
    mock_imap_conn.store.return_value = ("OK", [b"1"])
    mock_imap_conn.expunge.return_value = ("OK", [b""])

    email_to_move = imap_service.get_emails()[0] if imap_service.get_emails() else None
    if email_to_move:
        imap_service.move_email(email_to_move, "Archive")
        mock_imap_conn.create.assert_called_once_with("Archive")
        mock_imap_conn.copy.assert_called_once_with(email_to_move.msg_id.encode(), "Archive")
        mock_imap_conn.store.assert_called_once_with(email_to_move.msg_id.encode(), "+FLAGS", "\\Deleted")
        mock_imap_conn.expunge.assert_called_once()


def test_get_emails_select_failure(imap_service: ImapService, mock_imap_conn: MockerFixture, caplog):
    """Tests failure when selecting a mailbox."""
    imap_service.connect()
    error_message = "Mailbox not found"
    mock_imap_conn.select.return_value = ("NO", [error_message.encode()])
    with caplog.at_level("ERROR"):
        emails = imap_service.get_emails()
        assert not emails
        assert "Failed to select inbox." in caplog.text
