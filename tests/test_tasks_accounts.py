from pathlib import Path

from mailtag.config import FastParseConfig, GmailConfig, ImapConfig
from mailtag.gmail_api import GmailApiService
from mailtag.imap_service import ImapService
from mailtag.utils.tasks import junk_folder, pending_archive_path

INFOMANIAK = ImapConfig(host="mail.infomaniak.com", user="u", password="p")
GMAIL_API = GmailConfig(credentials_file="c", token_file="t")
FAST = FastParseConfig(junk_folder_name="Junk")


def test_each_account_has_its_own_pending_archive():
    assert pending_archive_path(INFOMANIAK, "db/pending_archive.json") == Path("db/pending_archive.json")
    assert pending_archive_path(GMAIL_API, "db/pending_archive.json") == Path("db/pending_archive_gmail.json")


def test_each_account_has_its_own_junk_folder():
    assert junk_folder(ImapService(INFOMANIAK, FAST)) == "Junk"
    assert junk_folder(GmailApiService(GMAIL_API, FAST)) == "SPAM"
