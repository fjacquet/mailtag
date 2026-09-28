import imaplib
from datetime import date

import pytest

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.migration import (
    delete_empty_folders,
    destination_for,
    empty_legacy_folders,
    folders_to_migrate,
    migrate_folder,
    migrate_mailbox,
)
from mailtag.pending_archive import PendingArchive
from mailtag.taxonomy import REVIEW


def test_categories_and_action_folders_and_inbox_are_excluded():
    legacy = ["Voyages", "1-A traiter", "5-A revoir", "INBOX", "Santé"]

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


def test_own_address_sent_to_review_gets_no_pending_entry(provider, pending):
    """Filing it later must not turn the owner's address into a validated rule."""
    client = FakeClient({"Finance/Locale/BCV": {1: mail("me@x.ch", "<1>")}})
    moving(provider, client)

    migrate_folder(provider, "Finance/Locale/BCV", None, FakeRules(), {"me@x.ch"}, pending, TODAY, apply=True)

    assert pending.items() == []
    assert client.folders[REVIEW] == {1: mail("me@x.ch", "<1>")}


def test_moves_are_sent_in_batches(mocker, provider, pending):
    client = FakeClient({"Voyages": {1: mail("a@x.ch", "<1>"), 2: mail("b@x.ch", "<2>")}})
    moving(provider, client)
    spy = mocker.spy(provider, "batch_move_emails")

    migrate_folder(
        provider, "Voyages", "Achats", FakeRules(), set(), pending, TODAY, apply=True, batch_size=1
    )

    assert spy.call_count == 2
    assert client.folders["Achats"] == {1: mail("a@x.ch", "<1>"), 2: mail("b@x.ch", "<2>")}


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
            "5-A revoir": {},
        }
    )
    legacy = ["Voyages/Sixt", "Voyages/Hotels", "5-A revoir"]
    live_folders = ["Voyages/Sixt", "Voyages/Hotels", "5-A revoir"]

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
    client = FakeClient({"Achats": {}, "5-A revoir": {}, "INBOX": {}})
    legacy = ["Achats", "5-A revoir", "INBOX"]
    live_folders = ["Achats", "5-A revoir", "INBOX"]

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


class DeletingClient(FakeClient):
    def __init__(self, folders, refuse=frozenset()):
        super().__init__(folders)
        self.refuse = refuse
        self.deleted = []

    def delete_folder(self, name):
        if name in self.refuse:
            raise imaplib.IMAP4.error(f"cannot delete {name}")
        self.deleted.append(name)
        del self.folders[name]


def test_delete_empty_folders_keeps_parent_of_a_child_that_got_mail():
    client = DeletingClient({"Voyages": {}, "Voyages/Sixt": {1: mail("a@x.ch")}, "INBOX": {}})

    deleted = delete_empty_folders(client, ["Voyages/Sixt", "Voyages"], ["Voyages", "Voyages/Sixt", "INBOX"])

    assert deleted == [] and client.deleted == []


def test_delete_empty_folders_keeps_parent_when_child_delete_fails():
    client = DeletingClient({"Voyages": {}, "Voyages/Sixt": {}, "INBOX": {}}, refuse={"Voyages/Sixt"})

    deleted = delete_empty_folders(client, ["Voyages/Sixt", "Voyages"], ["Voyages", "Voyages/Sixt", "INBOX"])

    assert deleted == [] and "Voyages" in client.folders


def test_delete_empty_folders_deletes_deepest_first_and_deselects():
    client = DeletingClient({"Voyages": {}, "Voyages/Sixt": {}, "INBOX": {}})

    deleted = delete_empty_folders(client, ["Voyages/Sixt", "Voyages"], ["Voyages", "Voyages/Sixt", "INBOX"])

    assert deleted == ["Voyages/Sixt", "Voyages"]
    assert client.current == "INBOX"


def test_existing_pending_entry_is_not_overwritten(provider, pending):
    pending.add("<1>", "Achats", "a@x.ch", "2026-09-01")
    client = FakeClient({"Finance/Locale/BCV": {1: mail("a@x.ch", "<1>")}})
    moving(provider, client)

    migrate_folder(provider, "Finance/Locale/BCV", None, FakeRules(), set(), pending, TODAY, apply=True)

    assert pending.get("<1>")["category"] == "Achats"


def test_unknown_destination_is_left_in_place(provider, pending):
    client = FakeClient({"Voyages": {1: mail("a@x.ch", "<1>")}})
    moving(provider, client)

    counts = migrate_folder(
        provider, "Voyages", "Not a category", FakeRules(), set(), pending, TODAY, apply=True
    )

    assert counts == {}
    assert client.folders["Voyages"] == {1: mail("a@x.ch", "<1>")}


def test_migrate_mailbox_stops_on_lost_connection(provider, pending):
    class Dropping(FakeClient):
        def select_folder(self, name, readonly=False):
            if name == "B":
                raise imaplib.IMAP4.abort("socket closed")
            super().select_folder(name, readonly)

    client = Dropping({"A": {1: mail("a@x.ch", "<1>")}, "B": {}, "C": {2: mail("c@x.ch", "<2>")}})
    moving(provider, client)

    report = migrate_mailbox(provider, ["A", "B", "C"], {"A": "Achats", "C": "Achats"}, FakeRules(), set(),
                             pending, TODAY, apply=False)  # fmt: skip

    assert report["aborted_at"] == "B"
    assert "C" not in report["folders"]


class RenamingClient(FakeClient):
    def __init__(self, folders, refuse=frozenset()):
        super().__init__(folders)
        self.refuse = refuse

    def rename_folder(self, old, new):
        if old in self.refuse:
            raise imaplib.IMAP4.error(f"cannot rename {old}")
        self.folders[new] = self.folders.pop(old)

    def delete_folder(self, name):
        del self.folders[name]


def test_reorganize_plan_renames_flat_categories_and_merges_duplicates():
    from mailtag.migration import reorganize_plan

    live = ["INBOX", "Santé", "Achats", "Archive", "9-A revoir", "5-Promos", "Promotions",
            "Domaines/Contacts", "Contacts"]  # fmt: skip
    plan = reorganize_plan(live)

    assert ("Santé", "Domaines/Santé") in plan["renames"]
    assert ("Achats", "Archive/Achats") in plan["renames"]
    assert ("9-A revoir", "5-A revoir") in plan["renames"]
    assert ("5-Promos", "Promotions") in plan["merges"]
    assert ("Contacts", "Domaines/Contacts") in plan["merges"]  # both exist: merge, never overwrite


def test_reorganize_plan_is_empty_once_done():
    from mailtag.migration import reorganize_plan

    done = ["INBOX", "Domaines/Santé", "5-A revoir", "Promotions"]
    assert reorganize_plan(done) == {"renames": [], "merges": []}


RENAME_AND_MERGE = {"renames": [("Santé", "Domaines/Santé")], "merges": [("5-Promos", "Promotions")]}


def test_reorganize_dry_run_changes_nothing(provider):
    from mailtag.migration import reorganize

    client = RenamingClient({"Santé": {1: mail("a@x.ch")}, "5-Promos": {2: mail("b@x.ch")}, "Promotions": {}})
    moving(provider, client)

    reorganize(provider, RENAME_AND_MERGE, apply=False)

    assert set(client.folders) == {"Santé", "5-Promos", "Promotions"}


def test_reorganize_apply_renames_and_merges(provider):
    from mailtag.migration import reorganize

    client = RenamingClient(
        {"INBOX": {}, "Santé": {1: mail("a@x.ch")}, "5-Promos": {2: mail("b@x.ch")},
         "Promotions": {3: mail("c@x.ch")}}
    )  # fmt: skip
    moving(provider, client)

    report = reorganize(provider, RENAME_AND_MERGE, apply=True)

    assert client.folders["Domaines/Santé"] == {1: mail("a@x.ch")}
    assert set(client.folders["Promotions"]) == {2, 3}
    assert "5-Promos" not in client.folders and "Santé" not in client.folders
    assert report["failed"] == []


def test_reorganize_failed_rename_is_reported_and_others_continue(provider):
    from mailtag.migration import reorganize

    client = RenamingClient({"INBOX": {}, "Santé": {}, "Achats": {}}, refuse={"Santé"})
    moving(provider, client)

    plan = {"renames": [("Santé", "Domaines/Santé"), ("Achats", "Archive/Achats")], "merges": []}
    report = reorganize(provider, plan, apply=True)

    assert report["failed"] == ["Santé"]
    assert "Archive/Achats" in client.folders


def test_para_folders_are_protected_from_migration_and_prune():
    legacy = ["Domaines/Santé", "Archive/Achats", "Domaines", "Ressources", "Voyages"]
    assert folders_to_migrate(legacy) == ["Voyages"]


def test_reorganize_merges_duplicate_system_folders_into_the_providers_ones():
    from mailtag.migration import reorganize_plan

    live = ["INBOX", "Archive", "Archives", "Spam", "Junk", "Trash", "Deleted Messages", "Sent",
            "Sent Messages"]  # fmt: skip
    assert reorganize_plan(live)["merges"] == [
        ("Archives", "Archive"), ("Junk", "Spam"), ("Deleted Messages", "Trash"), ("Sent Messages", "Sent")
    ]  # fmt: skip
