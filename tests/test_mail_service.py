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
