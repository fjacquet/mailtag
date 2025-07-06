import imaplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest
from pytest_mock import MockerFixture

from mailtag.config import ImapConfig
from mailtag.imap_service import ImapService
from mailtag.models import Email


@pytest.fixture
def imap_config() -> ImapConfig:
    """Returns a default ImapConfig for testing."""
    return ImapConfig(host="test.com", user="test", password="password")


@pytest.fixture
def imap_service(imap_config: ImapConfig) -> ImapService:
    """Returns an ImapService instance."""
    return ImapService(config=imap_config)


def test_connect_success(imap_service: ImapService, mocker: MockerFixture):
    """Tests a successful connection to the IMAP server."""
    mock_imap = mocker.patch("imaplib.IMAP4_SSL")
    instance = mock_imap.return_value
    imap_service.connect()
    mock_imap.assert_called_once_with("test.com")
    instance.login.assert_called_once_with("test", "password")


def test_connect_failure(imap_service: ImapService, mocker: MockerFixture):
    """Tests a failed connection to the IMAP server."""
    mock_imap = mocker.patch("imaplib.IMAP4_SSL")
    mock_imap.side_effect = imaplib.IMAP4.error("Connection failed")
    with pytest.raises(imaplib.IMAP4.error):
        imap_service.connect()


def test_disconnect(imap_service: ImapService, mocker: MockerFixture):
    """Tests disconnecting from the IMAP server."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    imap_service.disconnect()
    imap_service.mail.logout.assert_called_once()


def test_get_emails(imap_service: ImapService, mocker: MockerFixture):
    """Tests fetching emails from the IMAP server."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    imap_service.mail.select.return_value = ("OK", [b"1"])
    imap_service.mail.search.return_value = ("OK", [b"1 2"])
    imap_service.mail.fetch.side_effect = [
        ("OK", [(b"1 (RFC822)", b"From: sender1@test.com\nSubject: Test 1\n\nBody 1")]),
        ("OK", [(b"2 (RFC822)", b"From: sender2@test.com\nSubject: Test 2\n\nBody 2")]),
    ]
    emails = imap_service.get_emails()
    assert len(emails) == 2
    assert emails[0].subject == "Test 1"
    assert emails[1].sender_address == "sender2@test.com"


def test_get_emails_select_fails(imap_service: ImapService, mocker: MockerFixture):
    """Tests that an empty list is returned when inbox selection fails."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    imap_service.mail.select.return_value = ("NO", [b"Error"])
    emails = imap_service.get_emails()
    assert emails == []


def test_get_email_body_plaintext(imap_service: ImapService, mocker: MockerFixture):
    """Tests fetching the body of a plaintext email."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")
    imap_service.mail.fetch.return_value = (
        "OK",
        [(b"1 (RFC822)", b"From: test@test.com\nSubject: Test\n\nThis is the body.")],
    )
    body = imap_service.get_email_body(email_model)
    assert "This is the body" in body


def test_get_email_body_multipart(imap_service: ImapService, mocker: MockerFixture):
    """Tests fetching the body of a multipart email."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("This is the plaintext body.", "plain"))
    msg.attach(MIMEText("<html><body><p>This is the HTML body.</p></body></html>", "html"))

    imap_service.mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])
    body = imap_service.get_email_body(email_model)
    assert "This is the plaintext body." in body


def test_get_email_body_html_only(imap_service: ImapService, mocker: MockerFixture):
    """Tests fetching the body of an HTML-only email."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("<html><body><p>This is the HTML body.</p></body></html>", "html"))

    imap_service.mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])
    body = imap_service.get_email_body(email_model)
    assert "This is the HTML body." in body


def test_get_email_body_empty(imap_service: ImapService, mocker: MockerFixture):
    """Tests fetching an empty email body."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")

    msg = MIMEMultipart("alternative")

    imap_service.mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])
    body = imap_service.get_email_body(email_model)
    assert body == ""


def test_move_email(imap_service: ImapService, mocker: MockerFixture):
    """Tests moving an email to a new destination."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")
    imap_service.move_email(email_model, "Archive")
    imap_service.mail.copy.assert_called_once_with(b"1", "Archive")
    imap_service.mail.store.assert_called_once_with(b"1", "+FLAGS", "\\Deleted")
    imap_service.mail.expunge.assert_called_once()


def test_get_email_body_multipart_with_attachment(imap_service: ImapService, mocker: MockerFixture):
    """Tests that attachments are ignored when fetching the email body."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    email_model = Email(msg_id="1", subject="", sender_address="", sender_name="")

    msg = MIMEMultipart()
    msg.attach(MIMEText("This is the body.", "plain"))
    attachment = MIMEText("This is an attachment.", "plain")
    attachment.add_header("Content-Disposition", "attachment", filename="test.txt")
    msg.attach(attachment)

    imap_service.mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])
    body = imap_service.get_email_body(email_model)
    assert "This is the body." in body
    assert "This is an attachment." not in body


def test_get_emails_with_filters(imap_service: ImapService, mocker: MockerFixture):
    """Tests fetching emails with various filters."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    imap_service.mail.select.return_value = ("OK", [b"1"])
    imap_service.mail.search.return_value = ("OK", [b"1"])
    imap_service.mail.fetch.return_value = (
        "OK",
        [(b"1 (RFC822)", b"From: sender1@test.com\nSubject: Test 1\n\nBody 1")],
    )

    imap_service.get_emails(subject="Test", sender="sender1@test.com", status="UNSEEN")
    imap_service.mail.search.assert_called_once_with(
        None, "ALL", '(HEADER Subject "Test")', '(HEADER From "sender1@test.com")', "UNSEEN"
    )


def test_connect_invalid_credentials(imap_service: ImapService, mocker: MockerFixture):
    """Tests that a connection with invalid credentials fails gracefully."""
    mock_imap = mocker.patch("imaplib.IMAP4_SSL")
    instance = mock_imap.return_value
    instance.login.side_effect = imaplib.IMAP4.error("Invalid credentials")
    with pytest.raises(imaplib.IMAP4.error):
        imap_service.connect()


def test_select_mailbox_not_found(imap_service: ImapService, mocker: MockerFixture):
    """Tests that a failure to select a mailbox is handled gracefully."""
    mocker.patch("imaplib.IMAP4_SSL")
    imap_service.connect()
    imap_service.mail.select.side_effect = imaplib.IMAP4.error("Mailbox not found")
    emails = imap_service.get_emails()
    assert emails == []