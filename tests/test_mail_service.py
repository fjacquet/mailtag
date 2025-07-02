import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mailtag.mail_service import MailService
from mailtag.models import Email


@pytest.fixture
def mock_mail_dir(tmp_path: Path) -> Path:
    """Creates a mock mail directory structure."""
    v10_dir = tmp_path / "V10"
    mail_data_dir = v10_dir / "MailData"
    mail_data_dir.mkdir(parents=True)
    db_path = mail_data_dir / "Envelope Index"
    db_path.touch()
    return tmp_path


def test_find_latest_mail_v_folder(mock_mail_dir: Path):
    """Tests that the latest V* folder is found correctly."""
    service = MailService(mock_mail_dir)
    assert service.latest_v_folder.name == "V10"


def test_find_latest_mail_v_folder_no_v_folder(tmp_path: Path):
    """Tests that a FileNotFoundError is raised when no V* folder is found."""
    with pytest.raises(FileNotFoundError):
        MailService(tmp_path)


def test_find_latest_mail_v_folder_mail_dir_not_found(tmp_path: Path):
    """Tests that a FileNotFoundError is raised when the mail directory doesn't exist."""
    with pytest.raises(FileNotFoundError):
        MailService(tmp_path / "non_existent_dir")


def test_db_connection_permission_error(mock_mail_dir: Path):
    """Tests that a PermissionError is raised when the db is not accessible."""
    service = MailService(mock_mail_dir)
    with patch("shutil.copyfile", side_effect=PermissionError):
        with pytest.raises(PermissionError):
            with service._db_connection():
                pass


def test_db_connection_sqlite_error(mock_mail_dir: Path):
    """Tests that an sqlite3.Error is raised when the db is corrupted."""
    service = MailService(mock_mail_dir)
    with patch("sqlite3.connect", side_effect=sqlite3.Error):
        with pytest.raises(sqlite3.Error):
            with service._db_connection():
                pass


def test_get_inbox_emails(mock_mail_dir: Path):
    """Tests fetching emails from the inbox."""
    service = MailService(mock_mail_dir)
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        (1, "Test Subject", "sender@example.com", "Sender Name"),
    ]

    with patch.object(service, "_db_connection") as mock_db_connection:
        mock_db_connection.return_value.__enter__.return_value = mock_conn
        emails = service.get_inbox_emails()
        assert len(emails) == 1
        assert isinstance(emails[0], Email)
        assert emails[0].subject == "Test Subject"


def test_get_inbox_emails_sqlite_error(mock_mail_dir: Path):
    """Tests that an empty list is returned when an sqlite3.Error occurs."""
    service = MailService(mock_mail_dir)
    with patch.object(service, "_db_connection", side_effect=sqlite3.Error):
        emails = service.get_inbox_emails()
        assert emails == []


def test_get_email_body_emlx_not_found(mock_mail_dir: Path):
    """Tests that an empty string is returned when the .emlx file is not found."""
    service = MailService(mock_mail_dir)
    email = Email(
        msg_id=999,
        subject="Test",
        sender_address="test@test.com",
        sender_name="Test",
    )
    body = service.get_email_body(email)
    assert body == ""


def test_get_email_body_io_error(mock_mail_dir: Path):
    """Tests that an empty string is returned when an IOError occurs."""
    service = MailService(mock_mail_dir)
    email = Email(
        msg_id=1,
        subject="Test",
        sender_address="test@test.com",
        sender_name="Test",
    )
    emlx_path = mock_mail_dir / "V10/Messages/1.emlx"
    emlx_path.parent.mkdir()
    emlx_path.touch()
    service.emlx_index = {"1": emlx_path}
    with patch("pathlib.Path.open", side_effect=IOError):
        body = service.get_email_body(email)
        assert body == ""


def test_extract_body_from_mime_html_and_text():
    """Tests that the body is extracted from a multipart email with html and text."""
    html_part = "<html><body><p>Hello World</p></body></html>"
    text_part = "Hello World"
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text_part, "plain"))
    msg.attach(MIMEText(html_part, "html"))

    body = MailService._extract_body_from_mime(msg.as_bytes())
    assert "Hello World" in body


def test_extract_body_from_mime_with_attachment():
    """Tests that attachments are ignored when extracting the body."""
    text_part = "Hello World"
    attachment_part = "attachment"
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    msg = MIMEMultipart()
    msg.attach(MIMEText(text_part, "plain"))
    attachment = MIMEApplication(attachment_part.encode())
    attachment.add_header(
        "Content-Disposition", "attachment", filename="attachment.txt"
    )
    msg.attach(attachment)

    body = MailService._extract_body_from_mime(msg.as_bytes())
    assert body.strip() == "Hello World"


def test_get_email_body(mock_mail_dir: Path):
    """Tests reading and parsing an .emlx file."""
    service = MailService(mock_mail_dir)
    email = Email(
        msg_id=1,
        subject="Test",
        sender_address="test@test.com",
        sender_name="Test",
    )
    emlx_content = b"123\nFrom: test@test.com\nSubject: Test\n\nThis is the body."
    emlx_path = mock_mail_dir / "V10/Messages/1.emlx"
    emlx_path.parent.mkdir()
    emlx_path.write_bytes(emlx_content)
    service.emlx_index = {"1": emlx_path}

    body = service.get_email_body(email)
    assert "This is the body" in body
