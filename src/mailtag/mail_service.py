import re
import subprocess

from loguru import logger

from .models import Email


class MailService:
    """Handles interactions with Apple Mail via AppleScript."""

    def _run_applescript(self, script: str) -> str:
        """Executes an AppleScript and returns the output."""
        try:
            process = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True,
            )
            return process.stdout.strip()
        except subprocess.CalledProcessError as e:
            # This error often happens if the user denies permission.
            logger.error(
                f"AppleScript execution failed: {e.stderr}. "
                "Please ensure MailTag has permission to control Mail in "
                "System Settings > Privacy & Security > Automation."
            )
            raise
        except FileNotFoundError:
            logger.error("`osascript` command not found. Is this running on macOS?")
            raise

    def get_inbox_emails(self) -> list[Email]:
        """Fetches emails from the Inbox using AppleScript."""
        script = """
        set output to ""
        tell application "Mail"
            set theMessages to every message of inbox
            repeat with aMessage in theMessages
                set theId to id of aMessage
                set theSubject to subject of aMessage
                set theSender to sender of aMessage
                set output to output & theId & ":::" & theSubject & ":::" & theSender & "
"
            end repeat
        end tell
        return output
        """  # noqa: E501
        raw_output = self._run_applescript(script)
        emails = []
        for line in raw_output.splitlines():
            if not line:
                continue
            try:
                msg_id_str, subject, sender_raw = line.split(":::", 2)
                sender_name, sender_address = self._parse_sender(sender_raw)
                emails.append(
                    Email(
                        msg_id=int(msg_id_str),
                        subject=subject,
                        sender_address=sender_address,
                        sender_name=sender_name,
                    )
                )
            except (ValueError, IndexError) as e:
                logger.warning(f"Could not parse email line: {line} - {e}")
        return emails

    def get_email_body(self, email: Email) -> str:
        """Reads the body of a specific email using AppleScript."""
        script = f'tell application "Mail" to return content of message {email.msg_id} of inbox'
        return self._run_applescript(script)

    def _parse_sender(self, raw_sender: str) -> (str, str):
        """Parses a raw sender string like 'Sender Name <sender@example.com>'."""
        match = re.match(r"(.+?) <(.+?)>", raw_sender)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return "", raw_sender.strip()
