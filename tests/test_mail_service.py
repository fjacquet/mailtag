import subprocess
from unittest.mock import MagicMock, patch

import pytest

from mailtag.mail_service import MailService
from mailtag.models import Email


@pytest.fixture
def mail_service() -> MailService:
    """Returns a MailService instance."""
    return MailService()


def test_get_inbox_emails(mail_service: MailService):
    """Tests fetching emails from the inbox via AppleScript."""
    script_output = """
123:::Test Subject 1:::Sender One <sender1@example.com>
456:::Test Subject 2:::sender2@example.com
"""
    with patch("subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.stdout = script_output
        mock_run.return_value = mock_process

        emails = mail_service.get_inbox_emails()
        assert len(emails) == 2
        assert emails[0].subject == "Test Subject 1"
        assert emails[0].sender_name == "Sender One"
        assert emails[0].sender_address == "sender1@example.com"
        assert emails[1].subject == "Test Subject 2"
        assert emails[1].sender_name == ""
        assert emails[1].sender_address == "sender2@example.com"


def test_get_email_body(mail_service: MailService):
    """Tests fetching an email body via AppleScript."""
    email = Email(msg_id=123, subject="", sender_address="", sender_name="")
    script_output = "This is the email body."
    with patch("subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.stdout = script_output
        mock_run.return_value = mock_process

        body = mail_service.get_email_body(email)
        assert body == script_output


def test_applescript_error(mail_service: MailService):
    """Tests the handling of an AppleScript error."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "osascript", stderr="An error occurred.")
        with pytest.raises(subprocess.CalledProcessError):
            mail_service.get_inbox_emails()

def test_osascript_not_found(mail_service: MailService):
    """Tests the handling of `osascript` not being found."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError
        with pytest.raises(FileNotFoundError):
            mail_service.get_inbox_emails()

def test_email_parsing_error(mail_service: MailService):
    """Tests that malformed email lines are handled gracefully."""
    script_output = "this is not a valid email line"
    with patch("subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.stdout = script_output
        mock_run.return_value = mock_process

        emails = mail_service.get_inbox_emails()
        assert len(emails) == 0
