import imaplib

import pytest

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.mailbox_scan import scan_mailbox

KEY = b"BODY[HEADER.FIELDS (FROM SUBJECT)]"


class FakeClient:
    def __init__(self, folders, broken=(), fail_after_fetch=None):
        self.folders = folders
        self.broken = set(broken)
        self.fail_after_fetch = fail_after_fetch or {}  # folder -> number of fetches allowed to succeed
        self.current = None
        self.readonly_calls = []
        self._fetch_counts = {}

    def select_folder(self, name, readonly=False):
        self.readonly_calls.append(readonly)
        if name in self.broken:
            raise imaplib.IMAP4.error(f"cannot select {name}")
        self.current = name

    def search(self, criteria):
        assert criteria == ["ALL"]
        return list(self.folders[self.current])

    def fetch(self, uids, fields):
        assert fields == [b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"]
        folder = self.current
        count = self._fetch_counts.get(folder, 0)
        limit = self.fail_after_fetch.get(folder)
        if limit is not None and count >= limit:
            raise imaplib.IMAP4.error(f"fetch failed in {folder}")
        self._fetch_counts[folder] = count + 1
        return {u: {KEY: self.folders[self.current][u].encode()} for u in uids}


@pytest.fixture
def provider():
    service = ImapService(
        ImapConfig(host="h", user="u", password="p"), FastParseConfig()
    )
    return service


def header(sender, subject):
    return f"From: {sender}\r\nSubject: {subject}\r\n"


def test_counts_per_category_with_decoded_subjects(provider):
    provider.client = FakeClient({
        "Voyages": {1: header("Sixt <res@Sixt.ch>", "=?utf-8?Q?R=C3=A9servation?="),
                    2: header("res@sixt.ch", "Facture")},
        "Voyages/Transport": {7: header("res@sixt.ch", "Parking")},
        "Promotions": {9: header("res@sixt.ch", "Promo")},
    })  # fmt: skip

    result = scan_mailbox(provider, ["Voyages", "Voyages/Transport", "Promotions"], batch_size=1)

    entry = result["senders"]["res@sixt.ch"]
    assert entry["name"] == "Sixt"
    assert entry["domain"] == "sixt.ch"
    assert entry["categories"] == {"Voyages & Loisirs": 2, "Transports & Mobilité": 1}
    assert entry["subjects"] == ["Réservation", "Facture", "Parking"]
    assert entry["refs"] == [["Voyages", 1], ["Voyages", 2], ["Voyages/Transport", 7]]
    assert result["skipped_folders"] == []
    assert result["folders"] == {
        "Voyages": {"category": "Voyages & Loisirs", "senders": {"res@sixt.ch": 2}},
        "Voyages/Transport": {"category": "Transports & Mobilité", "senders": {"res@sixt.ch": 1}},
    }
    assert all(provider.client.readonly_calls)


def test_folder_overrides_take_precedence(provider):
    provider.client = FakeClient({
        "Voyages": {1: header("a@x.ch", "S")},
        "Voyages/Transport": {2: header("a@x.ch", "T")},
        "Promotions": {3: header("a@x.ch", "P")},
    })  # fmt: skip
    overrides = {"Voyages": "Santé", "Voyages/Transport": None, "Promotions": "Achats"}

    result = scan_mailbox(provider, ["Voyages", "Voyages/Transport", "Promotions"], overrides=overrides)

    assert result["senders"]["a@x.ch"]["categories"] == {"Santé": 1, "Achats": 1}
    assert set(result["folders"]) == {"Voyages", "Promotions"}


def test_samples_are_capped_at_five(provider):
    provider.client = FakeClient({"Voyages": {i: header("a@x.ch", f"S{i}") for i in range(1, 9)}})

    entry = scan_mailbox(provider, ["Voyages"])["senders"]["a@x.ch"]

    assert entry["categories"] == {"Voyages & Loisirs": 8}
    assert len(entry["subjects"]) == 5 and len(entry["refs"]) == 5


def test_unreadable_folder_is_skipped(provider):
    provider.client = FakeClient(
        {"Voyages": {1: header("a@x.ch", "S")}, "Voyages/Transport": {}}, broken={"Voyages/Transport"}
    )

    result = scan_mailbox(provider, ["Voyages/Transport", "Voyages"])

    assert result["skipped_folders"] == ["Voyages/Transport"]
    assert "a@x.ch" in result["senders"]
    assert "Voyages/Transport" not in result["folders"]


def test_folder_failing_mid_scan_contributes_nothing(provider):
    provider.client = FakeClient(
        {
            "Voyages": {1: header("a@x.ch", "S1"), 2: header("a@x.ch", "S2")},
            "Voyages/Transport": {7: header("res@sixt.ch", "Parking")},
        },
        fail_after_fetch={"Voyages": 1},
    )

    result = scan_mailbox(provider, ["Voyages", "Voyages/Transport"], batch_size=1)

    assert result["skipped_folders"] == ["Voyages"]
    assert "a@x.ch" not in result["senders"]
    assert "Voyages" not in result["folders"]
    assert result["senders"]["res@sixt.ch"]["categories"] == {"Transports & Mobilité": 1}
    assert result["folders"]["Voyages/Transport"] == {
        "category": "Transports & Mobilité",
        "senders": {"res@sixt.ch": 1},
    }


def test_mail_without_sender_is_ignored(provider):
    provider.client = FakeClient({"Voyages": {1: "Subject: no from\r\n", 2: header("a@x.ch", "ok")}})

    assert list(scan_mailbox(provider, ["Voyages"])["senders"]) == ["a@x.ch"]


def test_owner_addresses_are_ignored(provider):
    provider.client = FakeClient({
        "Voyages": {1: header("Fred <Fred.Jacquet@gmail.com>", "Backup done"), 2: header("a@x.ch", "ok")},
    })  # fmt: skip

    result = scan_mailbox(provider, ["Voyages"], ignored={"fred.jacquet@gmail.com"})

    assert list(result["senders"]) == ["a@x.ch"]
    assert result["folders"]["Voyages"]["senders"] == {"a@x.ch": 1}
