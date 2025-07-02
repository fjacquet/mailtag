import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Dict, Iterator, List

from bs4 import BeautifulSoup

from .config import TEMP_DB_PREFIX
from .models import Email


class MailService:
    """Handles interactions with the Apple Mail database and file system."""

    def __init__(self, mail_dir: Path):
        self.mail_dir = mail_dir
        self.latest_v_folder = self._find_latest_mail_v_folder()
        self.db_path = self.latest_v_folder / "MailData/Envelope Index"
        self.emlx_index = self._build_emlx_index()

    def _find_latest_mail_v_folder(self) -> Path:
        """Finds the latest V* folder in the Mail directory."""
        if not self.mail_dir.is_dir():
            raise FileNotFoundError(
                f"Mail directory not found at {self.mail_dir}. "
                "Is Apple Mail configured on this macOS?"
            )
        v_folders = sorted(
            [d for d in self.mail_dir.iterdir() if d.name.startswith("V") and d.is_dir()],
            key=lambda v: int(v.name[1:]) if v.name[1:].isdigit() else -1,
        )
        if not v_folders:
            raise FileNotFoundError(f"No V* folder found in {self.mail_dir}.")
        return v_folders[-1]

    @contextmanager
    def _db_connection(self) -> Iterator[sqlite3.Connection]:
        """Provides a read-only connection to a temporary copy of the Mail database."""
        temp_db_path = Path(f"/tmp/{TEMP_DB_PREFIX}_{os.getpid()}.db")
        try:
            shutil.copyfile(self.db_path, temp_db_path)
            logging.info(f"Database copied to {temp_db_path}")
            conn = sqlite3.connect(f"file:{temp_db_path}?mode=ro", uri=True)
            yield conn
        except PermissionError as e:
            raise PermissionError(
                "Permission denied. Grant Full Disk Access to the terminal."
            ) from e
        except sqlite3.Error as e:
            logging.error(f"Database error: {e}")
            raise
        finally:
            if "conn" in locals() and conn:
                conn.close()
            if temp_db_path.exists():
                os.remove(temp_db_path)
                logging.info(f"Temporary database {temp_db_path} removed.")

    def get_inbox_emails(self) -> List[Email]:
        """Fetches emails from the Inbox."""
        query = """
        SELECT m.ROWID, s.subject, r.address, r.comment
        FROM messages m
        JOIN subjects s ON m.subject = s.ROWID
        JOIN addresses r ON m.sender = r.ROWID
        JOIN mailboxes mb ON m.mailbox = mb.ROWID
        WHERE mb.url LIKE '%/Inbox' ESCAPE '\\'
        """
        try:
            with self._db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query)
                rows = cur.fetchall()
                return [
                    Email(
                        msg_id=row[0],
                        subject=row[1] or "",
                        sender_address=row[2] or "",
                        sender_name=row[3] or "",
                    )
                    for row in rows
                ]
        except (sqlite3.Error, PermissionError) as e:
            logging.critical(f"Could not fetch emails: {e}")
            return []

    def _build_emlx_index(self) -> Dict[str, Path]:
        """Builds an index of all .emlx files."""
        logging.info("Indexing .emlx files, please wait...")
        return {p.stem: p for p in self.latest_v_folder.rglob("*.emlx")}

    def get_email_body(self, email: Email) -> str:
        """Reads an .emlx file and extracts its body."""
        emlx_path = self.emlx_index.get(str(email.msg_id))
        if not emlx_path or not emlx_path.exists():
            return ""
        try:
            with emlx_path.open("rb") as f:
                first_line = f.readline()
                byte_count_str = first_line.decode("ascii", errors="ignore").strip()
                byte_count = int(byte_count_str) if byte_count_str.isdigit() else 0
                mime_bytes = f.read(byte_count) if byte_count > 0 else f.read()
                return self._extract_body_from_mime(mime_bytes)
        except (IOError, ValueError) as e:
            logging.warning(f"Could not read {emlx_path}: {e}")
            return ""

    @staticmethod
    def _extract_body_from_mime(mime_bytes: bytes) -> str:
        """Extracts the text body from MIME content."""
        try:
            msg = BytesParser(policy=policy.default).parsebytes(mime_bytes)
        except Exception:
            return ""

        text_parts = []
        for part in msg.walk():
            if part.is_attachment() or part.get_content_type() not in (
                "text/plain",
                "text/html",
            ):
                continue
            try:
                content = part.get_content()
                if part.get_content_type() == "text/html":
                    soup = BeautifulSoup(content, "html.parser")
                    text_parts.append(soup.get_text(separator=" ", strip=True))
                else:
                    text_parts.append(content)
            except Exception:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                text_parts.append(payload.decode(charset, errors="ignore"))
        return "\n".join(filter(None, (t.strip() for t in text_parts)))
