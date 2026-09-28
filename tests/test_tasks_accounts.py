from pathlib import Path

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.utils.tasks import junk_folder, pending_archive_path

INFOMANIAK = ImapConfig(host="mail.infomaniak.com", user="u", password="p")
GMAIL = ImapConfig(
    host="imap.gmail.com",
    user="g",
    password="p",
    pending_archive_file="db/pending_archive_gmail.json",
    folder_cache_file="data/gmail_folders.json",
    junk_folder_name="[Gmail]/Spam",
)
FAST = FastParseConfig(junk_folder_name="Junk", metrics_enabled=False)


def test_each_account_has_its_own_pending_archive():
    assert pending_archive_path(INFOMANIAK, "db/pending_archive.json") == Path("db/pending_archive.json")
    assert pending_archive_path(GMAIL, "db/pending_archive.json") == Path("db/pending_archive_gmail.json")


def test_each_account_has_its_own_junk_folder():
    assert junk_folder(ImapService(INFOMANIAK, FAST)) == "Junk"
    assert junk_folder(ImapService(GMAIL, FAST)) == "[Gmail]/Spam"


def test_gmail_never_writes_the_infomaniak_folder_cache():
    assert ImapService(INFOMANIAK, FAST).folder_cache_path == Path("data/imap_folders.json")
    assert ImapService(GMAIL, FAST).folder_cache_path == Path("data/gmail_folders.json")
