import imaplib
from datetime import date

import pytest

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.migration import (
    destination_for,
    empty_legacy_folders,
    folders_to_migrate,
    migrate_folder,
    migrate_mailbox,
)
from mailtag.pending_archive import PendingArchive
from mailtag.taxonomy import REVIEW


def test_categories_and_action_folders_and_inbox_are_excluded():
    legacy = ["Voyages", "1-A traiter", "9-A revoir", "INBOX", "Santé"]

    assert folders_to_migrate(legacy) == ["Voyages"]


def test_system_folders_are_excluded():
    legacy = ["Promotions", "Spam", "Sent", "Trash", "Voyages"]

    assert folders_to_migrate(legacy) == ["Voyages"]


def test_contacts_itself_excluded_but_contacts_children_kept():
    legacy = ["Contacts", "Contacts/Alice", "Contacts/Bob"]

    assert folders_to_migrate(legacy) == ["Contacts/Alice", "Contacts/Bob"]


def test_ordinary_legacy_folders_are_kept():
    legacy = ["Finance/Local/EDF", "Services/Development/GitHub"]

    assert folders_to_migrate(legacy) == legacy


class FakeRules:
    def __init__(self, categories=None):
        self.categories = categories or {}

    def category_for(self, sender):
        return self.categories.get(sender)


def test_validated_sender_rule_wins_over_folder_category():
    rules = FakeRules({"a@x.ch": "Santé"})

    assert destination_for("a@x.ch", "Achats", rules, own=set()) == "Santé"


def test_folder_category_used_when_no_sender_rule():
    rules = FakeRules({})

    assert destination_for("a@x.ch", "Achats", rules, own=set()) == "Achats"


def test_review_when_no_sender_rule_and_no_folder_category():
    rules = FakeRules({})

    assert destination_for("a@x.ch", None, rules, own=set()) == REVIEW


def test_own_address_uses_folder_category_ignoring_sender_rules():
    rules = FakeRules({"me@x.ch": "Achats"})

    assert destination_for("me@x.ch", "Santé", rules, own={"me@x.ch"}) == "Santé"


def test_own_address_with_no_folder_category_goes_to_review():
    rules = FakeRules({"me@x.ch": "Achats"})

    assert destination_for("me@x.ch", None, rules, own={"me@x.ch"}) == REVIEW


TODAY = date(2026, 9, 27)
KEY = b"BODY[HEADER.FIELDS (FROM MESSAGE-ID)]"


class FakeClient:
    """Folders of {uid: {"from": str, "mid": str | None}}."""

    def __init__(self, folders, broken_folders=frozenset()):
        self.folders = folders
        self.current = None
        self.broken_folders = broken_folders
        self.readonly_calls = []

    def select_folder(self, name, readonly=False):
        self.readonly_calls.append((name, readonly))
        if name in self.broken_folders:
            raise imaplib.IMAP4.error(f"select failed for {name}")
        self.current = name

    def search(self, criteria):
        assert criteria == ["ALL"]
        return list(self.folders[self.current])

    def fetch(self, uids, fields):
        assert fields == [b"BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)]"]
        result = {}
        for u in uids:
            m = self.folders[self.current][u]
            text = f"From: {m['from']}\r\n"
            if m.get("mid"):
                text += f"Message-ID: {m['mid']}\r\n"
            result[u] = {KEY: text.encode()}
        return result


def mail(sender, mid=None):
    return {"from": sender, "mid": mid}


@pytest.fixture
def provider():
    return ImapService(ImapConfig(host="h", user="u", password="p"), FastParseConfig(metrics_enabled=False))


@pytest.fixture
def pending(tmp_path):
    return PendingArchive(tmp_path / "pending.json")


def moving(provider, client):
    """provider.batch_move_emails actually moves uids between the fake client's folders."""
    provider.client = client

    def batch_move_emails(uids, destination):
        source = client.folders[client.current]
        moved = {uid: source.pop(uid) for uid in uids}
        client.folders.setdefault(destination, {}).update(moved)

    provider.batch_move_emails = batch_move_emails
    return provider


def test_migrate_folder_dry_run_moves_nothing_and_touches_no_pending(mocker, provider, pending):
    client = FakeClient({"Voyages": {1: mail("a@x.ch", "<1>")}})
    provider.client = client
    provider.batch_move_emails = mocker.MagicMock()

    counts = migrate_folder(provider, "Voyages", "Achats", FakeRules(), set(), pending, TODAY, apply=False)

    assert counts == {"Achats": 1}
    provider.batch_move_emails.assert_not_called()
    assert pending.items() == []
    assert client.folders["Voyages"] == {1: mail("a@x.ch", "<1>")}
    assert all(readonly for _, readonly in client.readonly_calls)


def test_migrate_folder_apply_groups_by_destination(mocker, provider, pending):
    client = FakeClient({"Voyages": {1: mail("a@x.ch", "<1>"), 2: mail("b@x.ch", "<2>")}})
    moving(provider, client)
    spy = mocker.spy(provider, "batch_move_emails")
    rules = FakeRules({"a@x.ch": "Santé"})

    counts = migrate_folder(provider, "Voyages", "Achats", rules, set(), pending, TODAY, apply=True)

    assert counts == {"Santé": 1, "Achats": 1}
    assert spy.call_count == 2
    assert client.folders["Voyages"] == {}
    assert client.folders["Santé"] == {1: mail("a@x.ch", "<1>")}
    assert client.folders["Achats"] == {2: mail("b@x.ch", "<2>")}


def test_migrate_folder_review_destination_adds_pending_entry_before_move(provider, pending):
    client = FakeClient({"Finance/Locale/BCV": {1: mail("a@x.ch", "<1>")}})
    moving(provider, client)

    counts = migrate_folder(
        provider, "Finance/Locale/BCV", None, FakeRules(), set(), pending, TODAY, apply=True
    )

    assert counts == {REVIEW: 1}
    assert pending.get("<1>") == {"category": None, "sender": "a@x.ch", "added": TODAY.isoformat()}
    assert client.folders[REVIEW] == {1: mail("a@x.ch", "<1>")}


def test_mail_without_message_id_goes_to_review_without_pending_entry(provider, pending):
    client = FakeClient({"Finance/Locale/BCV": {1: mail("a@x.ch", None)}})
    moving(provider, client)

    counts = migrate_folder(
        provider, "Finance/Locale/BCV", None, FakeRules(), set(), pending, TODAY, apply=True
    )

    assert counts == {REVIEW: 1}
    assert pending.items() == []
    assert client.folders[REVIEW] == {1: mail("a@x.ch", None)}


def test_mail_whose_destination_is_its_own_folder_is_not_moved(provider, pending):
    client = FakeClient({"Achats": {1: mail("a@x.ch", "<1>")}})
    moving(provider, client)

    counts = migrate_folder(provider, "Achats", "Achats", FakeRules(), set(), pending, TODAY, apply=True)

    assert counts == {}
    assert client.folders["Achats"] == {1: mail("a@x.ch", "<1>")}


def test_second_pass_finds_nothing_left_to_migrate(provider, pending):
    client = FakeClient({"Voyages": {1: mail("a@x.ch", "<1>")}})
    moving(provider, client)
    rules = FakeRules()

    migrate_folder(provider, "Voyages", "Voyages & Loisirs", rules, set(), pending, TODAY, apply=True)
    counts = migrate_folder(
        provider, "Voyages", "Voyages & Loisirs", rules, set(), pending, TODAY, apply=False
    )

    assert counts == {}


def test_migrate_mailbox_skips_broken_folder_others_continue(provider, pending):
    client = FakeClient(
        {"Broken": {1: mail("a@x.ch", "<1>")}, "Voyages": {2: mail("b@x.ch", "<2>")}},
        broken_folders={"Broken"},
    )
    moving(provider, client)

    report = migrate_mailbox(
        provider,
        ["Broken", "Voyages"],
        overrides={},
        rules=FakeRules(),
        own=set(),
        pending=pending,
        today=TODAY,
        apply=True,
    )

    assert report["skipped_folders"] == ["Broken"]
    assert report["folders"] == {"Voyages": {"Voyages & Loisirs": 1}}
    assert report["totals"] == {"Voyages & Loisirs": 1}
    assert report["review_total"] == 0


def test_migrate_mailbox_uses_folder_override_and_counts_review_total(provider, pending):
    client = FakeClient({"Finance/Locale/BCV": {1: mail("a@x.ch", "<1>")}})
    moving(provider, client)

    report = migrate_mailbox(
        provider,
        ["Finance/Locale/BCV"],
        overrides={"Finance/Locale/BCV": None},
        rules=FakeRules(),
        own=set(),
        pending=pending,
        today=TODAY,
        apply=True,
    )

    assert report["folders"] == {"Finance/Locale/BCV": {REVIEW: 1}}
    assert report["review_total"] == 1
    assert pending.get("<1>") is not None


def test_empty_legacy_folders_only_empty_and_old():
    client = FakeClient(
        {
            "Voyages/Sixt": {},
            "Voyages/Hotels": {1: mail("a@x.ch")},
            "9-A revoir": {},
        }
    )
    legacy = ["Voyages/Sixt", "Voyages/Hotels", "9-A revoir"]
    live_folders = ["Voyages/Sixt", "Voyages/Hotels", "9-A revoir"]

    assert empty_legacy_folders(client, legacy, live_folders) == ["Voyages/Sixt"]


def test_parent_kept_when_child_has_mail():
    client = FakeClient({"Voyages": {}, "Voyages/Sixt": {1: mail("a@x.ch")}})
    legacy = ["Voyages", "Voyages/Sixt"]
    live_folders = ["Voyages", "Voyages/Sixt"]

    assert empty_legacy_folders(client, legacy, live_folders) == []


def test_parent_kept_when_child_is_not_a_legacy_folder():
    client = FakeClient({"Voyages": {}, "Voyages/NewStuff": {}})
    legacy = ["Voyages"]
    live_folders = ["Voyages", "Voyages/NewStuff"]

    assert empty_legacy_folders(client, legacy, live_folders) == []


def test_empty_parent_and_child_both_removable_deepest_first():
    client = FakeClient({"Voyages": {}, "Voyages/Sixt": {}})
    legacy = ["Voyages", "Voyages/Sixt"]
    live_folders = ["Voyages", "Voyages/Sixt"]

    assert empty_legacy_folders(client, legacy, live_folders) == ["Voyages/Sixt", "Voyages"]


def test_protected_folders_never_included_even_if_empty():
    client = FakeClient({"Achats": {}, "9-A revoir": {}, "INBOX": {}})
    legacy = ["Achats", "9-A revoir", "INBOX"]
    live_folders = ["Achats", "9-A revoir", "INBOX"]

    assert empty_legacy_folders(client, legacy, live_folders) == []


def test_folder_no_longer_live_is_skipped():
    client = FakeClient({})
    legacy = ["Voyages/Gone"]
    live_folders = []

    assert empty_legacy_folders(client, legacy, live_folders) == []


def test_broken_folder_is_treated_as_not_removable():
    client = FakeClient({"Voyages/Sixt": {}}, broken_folders={"Voyages/Sixt"})
    legacy = ["Voyages/Sixt"]
    live_folders = ["Voyages/Sixt"]

    assert empty_legacy_folders(client, legacy, live_folders) == []
