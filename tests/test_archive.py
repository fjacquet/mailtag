import imaplib
from datetime import date

import pytest

from mailtag.archive import run_archive
from mailtag.pending_archive import PendingArchive

TODAY = date(2026, 9, 27)


class FakeClient:
    """Folders of {uid: {"mid": str, "seen": bool, "flagged": bool, "old": bool}}."""

    def __init__(self, folders, broken_folders=frozenset()):
        self.folders = folders
        self.current = None
        self.broken_folders = broken_folders

    def folder_exists(self, name):
        return name in self.folders

    def select_folder(self, name, readonly=False):
        if name in self.broken_folders:
            raise imaplib.IMAP4.error(f"select failed for {name}")
        self.current = name

    def search(self, criteria):
        mails = self.folders[self.current]
        if criteria == ["ALL"]:
            return list(mails)
        if criteria[:2] == ["HEADER", "Message-ID"]:
            return [u for u, m in mails.items() if m["mid"] == criteria[2]]
        assert criteria[:3] == ["SEEN", "UNFLAGGED", "BEFORE"]
        assert criteria[3] == date(2026, 9, 20)
        return [u for u, m in mails.items() if m["seen"] and not m["flagged"] and m["old"]]

    def fetch(self, uids, fields):
        key = b"BODY[HEADER.FIELDS (MESSAGE-ID)]"
        return {u: {key: f"Message-ID: {self.folders[self.current][u]['mid']}\r\n".encode()} for u in uids}


def mail(mid, seen=True, flagged=False, old=True):
    return {"mid": mid, "seen": seen, "flagged": flagged, "old": old}


@pytest.fixture
def pending(tmp_path):
    return PendingArchive(tmp_path / "pending.json")


def setup(mocker, folders, broken_folders=frozenset()):
    provider = mocker.MagicMock()
    provider.client = FakeClient(folders, broken_folders=broken_folders)
    return provider, mocker.MagicMock()


def test_archives_only_seen_unflagged_old_known_mails(mocker, pending):
    provider, db = setup(mocker, {
        "4-Pour info": {1: mail("<a>"), 2: mail("<b>", seen=False), 3: mail("<c>", flagged=True),
                        4: mail("<d>", old=False), 5: mail("<unknown>")},
    })  # fmt: skip
    for mid in ("<a>", "<b>", "<c>", "<d>"):
        pending.add(mid, "Achats", "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    provider.batch_move_emails.assert_called_once_with([1], "Achats")
    assert result == {"archived": 1, "learned": 0, "orphans": 0}
    assert pending.get("<a>") is None
    assert pending.get("<b>") is not None


def test_review_folder_is_never_archived(mocker, pending):
    provider, db = setup(mocker, {"9-A revoir": {1: mail("<r>")}})
    pending.add("<r>", None, "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    provider.batch_move_emails.assert_not_called()
    assert result["archived"] == 0
    assert pending.get("<r>") is not None


def test_mail_moved_from_review_to_category_becomes_rule(mocker, pending):
    provider, db = setup(mocker, {"9-A revoir": {}, "Santé": {9: mail("<r>")}})
    pending.add("<r>", None, "doc@clinic.ch", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    db.set_validated.assert_called_once_with("doc@clinic.ch", "Santé")
    db.save.assert_called_once()
    assert result["learned"] == 1
    assert pending.items() == []


def test_orphan_entries_are_removed(mocker, pending):
    provider, db = setup(mocker, {"4-Pour info": {}})
    pending.add("<gone>", "Achats", "s@x", "2026-09-01")
    pending.add("<gone-review>", None, "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    assert result["orphans"] == 2
    assert pending.items() == []
    db.promote_to_validated.assert_not_called()


def test_missing_action_folder_is_skipped(mocker, pending):
    provider, db = setup(mocker, {})

    assert run_archive(provider, pending, db, days=7, today=TODAY) == {
        "archived": 0,
        "learned": 0,
        "orphans": 0,
    }


def test_one_broken_folder_does_not_abort_the_others(mocker, pending):
    """A transient IMAP error reading one action folder must not stop the sweep from
    archiving the other, healthy folders."""
    provider, db = setup(
        mocker,
        {
            "3-A lire": {1: mail("<broken>")},
            "4-Pour info": {2: mail("<healthy>")},
        },
        broken_folders={"3-A lire"},
    )
    pending.add("<broken>", "Médias & Divertissement", "s@x", "2026-09-01")
    pending.add("<healthy>", "Achats", "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    provider.batch_move_emails.assert_called_once_with([2], "Achats")
    assert result["archived"] == 1


def test_broken_folder_entries_are_not_removed_as_orphans(mocker, pending):
    """An entry whose folder could not be read must not be treated as an orphan: we
    simply don't know whether it is still there."""
    provider, db = setup(
        mocker,
        {"3-A lire": {1: mail("<in-broken-folder>")}, "4-Pour info": {}},
        broken_folders={"3-A lire"},
    )
    pending.add("<in-broken-folder>", "Médias & Divertissement", "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    assert result["orphans"] == 0
    assert pending.get("<in-broken-folder>") is not None


def test_broken_review_folder_does_not_abort_learning_from_other_categories(mocker, pending):
    """A transient error reading one taxonomy category during the review-learning pass
    must not stop learning from the remaining categories."""
    provider, db = setup(
        mocker,
        {"9-A revoir": {}, "Assurances & Retraite": {}, "Santé": {9: mail("<r>")}},
        broken_folders={"Assurances & Retraite"},
    )
    pending.add("<r>", None, "doc@clinic.ch", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    db.set_validated.assert_called_once_with("doc@clinic.ch", "Santé")
    assert result["learned"] == 1


def test_validate_changes_nothing(mocker, pending):
    provider, db = setup(mocker, {"4-Pour info": {1: mail("<a>")}, "Santé": {2: mail("<r>")}})
    pending.add("<a>", "Achats", "s@x", "2026-09-01")
    pending.add("<r>", None, "s@x", "2026-09-01")

    run_archive(provider, pending, db, days=7, today=TODAY, validate=True)

    provider.batch_move_emails.assert_not_called()
    db.promote_to_validated.assert_not_called()
    assert len(pending.items()) == 2
    db.set_validated.assert_not_called()
    db.save.assert_not_called()
