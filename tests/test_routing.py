from datetime import date

import pytest

from mailtag.models import Email
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders

TODAY = date(2026, 9, 27)


def routed(uid, category, sender="noreply@x.ch", subject="Info", mid=None, unsub=False, bulk=True):
    return RoutedMail(uid, category, sender, subject, mid if mid is not None else f"<{uid}@x>", unsub, bulk)


@pytest.fixture
def pending(tmp_path):
    return PendingArchive(tmp_path / "pending.json")


def test_groups_moves_by_action_folder_and_records_category(mocker, pending):
    provider = mocker.MagicMock()
    mails = [
        routed("1", "Banque & Placements", subject="Votre facture"),
        routed("2", "Médias & Divertissement"),
        routed("3", "Médias & Divertissement"),
        routed("4", "9-A revoir"),
    ]

    moved = route_to_action_folders(provider, pending, mails, validate=False, today=TODAY)

    assert moved == 4
    calls = {c.args[1]: c.args[0] for c in provider.batch_move_emails.call_args_list}
    assert calls == {"2-A payer": ["1"], "3-A lire": ["2", "3"], "9-A revoir": ["4"]}
    assert pending.get("<1@x>") == {
        "category": "Banque & Placements",
        "sender": "noreply@x.ch",
        "added": "2026-09-27",
    }
    assert pending.get("<4@x>")["category"] is None
    assert (pending.path).exists()


def test_validate_moves_nothing_and_records_nothing(mocker, pending):
    provider = mocker.MagicMock()

    assert (
        route_to_action_folders(provider, pending, [routed("1", "Achats")], validate=True, today=TODAY) == 0
    )
    provider.batch_move_emails.assert_not_called()
    assert pending.items() == []


def test_pending_is_saved_after_each_successful_group(mocker, pending):
    """Each group's entries must hit disk right away, so an interruption before the next
    group (e.g. process killed between groups) never loses an already-moved group."""
    provider = mocker.MagicMock()
    save_spy = mocker.spy(pending, "save")
    save_calls_seen_at_move = []

    def move(uids, folder):
        save_calls_seen_at_move.append((folder, save_spy.call_count))

    provider.batch_move_emails.side_effect = move
    mails = [
        routed("1", "Banque & Placements", subject="Votre facture"),  # -> 2-A payer
        routed("2", "Médias & Divertissement"),  # -> 3-A lire
    ]

    route_to_action_folders(provider, pending, mails, validate=False, today=TODAY)

    # save() must already have run for the first group before the second group's move starts.
    assert save_calls_seen_at_move == [("2-A payer", 0), ("3-A lire", 1)]
    assert save_spy.call_count == 2


def test_failed_move_is_not_recorded(mocker, pending):
    provider = mocker.MagicMock()
    provider.batch_move_emails.side_effect = ConnectionError("down")

    assert (
        route_to_action_folders(provider, pending, [routed("1", "Achats")], validate=False, today=TODAY) == 0
    )
    assert pending.items() == []


def test_mail_without_message_id_is_moved_but_not_tracked(mocker, pending):
    provider = mocker.MagicMock()

    moved = route_to_action_folders(
        provider, pending, [routed("1", "Achats", mid="")], validate=False, today=TODAY
    )

    assert moved == 1
    assert pending.items() == []


def test_from_headers_and_from_email():
    header = {
        "sender_address": "a@x",
        "subject": "S",
        "message_id": "<m>",
        "has_unsubscribe": True,
        "is_bulk": True,
    }
    assert RoutedMail.from_headers("7", "Achats", header) == RoutedMail(
        "7", "Achats", "a@x", "S", "<m>", True, True
    )

    email = Email(
        msg_id="8", subject="S", sender_address="a@x", sender_name="", message_id="<n>", is_bulk=True
    )
    assert RoutedMail.from_email(email, "Santé") == RoutedMail("8", "Santé", "a@x", "S", "<n>", False, True)


def test_pass1_routes_known_sender_in_taxonomy_mode(mocker, pending):
    from mailtag.utils import tasks

    provider = mocker.MagicMock()
    provider.client.search.return_value = [1, 2]
    provider.fast_parse_config.batch_size = 100
    provider.get_email_headers.return_value = {
        "1": {"sender_address": "a@sixt.ch", "subject": "Réservation", "message_id": "<1>",
              "has_unsubscribe": False, "is_bulk": True},
        "2": {"sender_address": "new@x.ch", "subject": "Hi", "message_id": "<2>",
              "has_unsubscribe": False, "is_bulk": False},
    }  # fmt: skip
    database = mocker.MagicMock()
    rules = mocker.MagicMock()
    rules.category_for.side_effect = lambda s: "Voyages & Loisirs" if s == "a@sixt.ch" else None

    uids, headers = tasks._run_fast_parse_on_folder(
        provider, database, "INBOX", False, pending=pending, rules=rules
    )

    assert uids == ["2"]
    provider.batch_move_emails.assert_called_once_with(["1"], "4-Pour info")
    assert pending.get("<1>")["category"] == "Voyages & Loisirs"
    database.get_dominant_classification.assert_not_called()
