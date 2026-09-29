import email as email_lib
from email.header import Header

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
    mocker.patch.object(mock_imap_client, "login", side_effect=ConnectionError("Login failed"))
    with pytest.raises(ConnectionError, match="IMAP connection failed"):
        with imap_service.connect():
            pass


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


def test_parse_sender_header(imap_service: ImapService):
    """Ensure _parse_sender accepts email.header.Header objects."""
    header = Header("Sender Name <sender@example.com>", "utf-8")
    name, address = imap_service._parse_sender(header)
    assert name == "Sender Name"
    assert address == "sender@example.com"


def test_list_header_flags_newsletter():
    from mailtag.imap_service import list_header_flags

    msg = email_lib.message_from_string(
        "Message-ID: <abc@x>\nList-Unsubscribe: <mailto:u@x>\nList-Id: <news.x>\n\nbody"
    )
    assert list_header_flags(msg) == ("<abc@x>", True, True)


def test_list_header_flags_precedence_bulk_without_unsubscribe():
    from mailtag.imap_service import list_header_flags

    msg = email_lib.message_from_string("Message-ID: <m@x>\nPrecedence: Bulk\n\nbody")
    assert list_header_flags(msg) == ("<m@x>", False, True)


def test_list_header_flags_person_without_message_id():
    from mailtag.imap_service import list_header_flags

    assert list_header_flags(email_lib.message_from_string("Subject: hi\n\nbody")) == ("", False, False)


def test_get_email_headers_includes_list_flags(mock_imap_client, mocker):
    from mailtag.config import FastParseConfig, ImapConfig
    from mailtag.imap_service import ImapService

    mock_imap_client.mailboxes["INBOX"][1][
        b"BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"
    ] = b"From: Shop <shop@x.ch>\r\nSubject: Promo\r\nMessage-ID: <p@x>\r\nList-Unsubscribe: <u>\r\n"
    service = ImapService(
        ImapConfig(host="h", user="u", password="p"), FastParseConfig(metrics_enabled=False)
    )
    service.client = mock_imap_client
    mock_imap_client.select_folder("INBOX")

    headers = service.get_email_headers([1])

    assert headers["1"] == {
        "sender_address": "shop@x.ch",
        "sender_name": "Shop",
        "subject": "Promo",
        "message_id": "<p@x>",
        "has_unsubscribe": True,
        "is_bulk": True,
    }


ENCODED_SUBJECT = "=?utf-8?Q?FACTURE_AOF6A10318_de_la_r=C3=A9servation?="
ENCODED_FROM = "=?utf-8?Q?Andr=C3=A9_M=C3=BCller?= <andre@example.ch>"


def test_full_emails_decode_encoded_subject_and_sender(imap_service, mock_imap_client):
    mock_imap_client.mailboxes["INBOX"][1][b"BODY[]"] = (
        f"From: {ENCODED_FROM}\r\nSubject: {ENCODED_SUBJECT}\r\n\r\nbody".encode()
    )
    imap_service.client = mock_imap_client
    mock_imap_client.select_folder("INBOX")

    mail = imap_service.get_full_emails([1])[0]

    assert mail.subject == "FACTURE AOF6A10318 de la réservation"
    assert mail.sender_name == "André Müller"
    assert mail.sender_address == "andre@example.ch"


def test_headers_decode_encoded_subject(imap_service, mock_imap_client):
    mock_imap_client.mailboxes["INBOX"][1][
        b"BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"
    ] = f"From: {ENCODED_FROM}\r\nSubject: {ENCODED_SUBJECT}\r\n".encode()
    imap_service.client = mock_imap_client
    mock_imap_client.select_folder("INBOX")

    headers = imap_service.get_email_headers([1])

    assert headers["1"]["subject"] == "FACTURE AOF6A10318 de la réservation"
    assert headers["1"]["sender_address"] == "andre@example.ch"
