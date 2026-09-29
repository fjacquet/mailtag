import pytest

from mailtag.pending_archive import PendingArchive
from mailtag.review_refile import (
    coverage,
    group_key,
    read_review_mails,
    refile_review,
    review_groups,
    review_queue,
    suggest_categories,
)
from mailtag.taxonomy import category_folder, llm_sender_part
from mailtag.taxonomy_store import TaxonomyStore


@pytest.fixture(autouse=True)
def personal_domains(monkeypatch):
    monkeypatch.setattr("mailtag.review_refile.is_non_commercial_domain_cached", lambda d: d in {"gmail.com"})


def mail(address, name="", subject="", mid=""):
    return {"sender_address": address, "sender_name": name, "subject": subject, "message_id": mid}


class FakeClient:
    def __init__(self, exists=True, uids=None):
        self.exists = exists
        self.uids = uids or []
        self.selected = None
        self.readonly = None

    def folder_exists(self, name):
        return self.exists

    def select_folder(self, name, readonly=False):
        self.selected = name
        self.readonly = readonly

    def search(self, criteria):
        assert criteria == ["ALL"]
        return self.uids


class FakeProvider:
    def __init__(self, client, headers=None):
        self.client = client
        self.headers = headers or {}
        self.moves = []

    def get_email_headers(self, uids):
        return {uid: self.headers[uid] for uid in uids}

    def batch_move_emails(self, uids, destination):
        self.moves.append((uids, destination))


class FakeLLM:
    def __init__(self, answer="1"):
        self.answer = answer
        self.calls = []

    def classify_batch(self, static_prompt, parts, batch_size=8):
        self.calls.append((static_prompt, parts, batch_size))
        return [self.answer] * len(parts)


# --- group_key ---


def test_group_key_domain_for_commercial_domain():
    assert group_key("a@Shop.ch") == ("domain", "shop.ch")


def test_group_key_sender_for_non_commercial_domain():
    assert group_key("x@gmail.com") == ("sender", "x@gmail.com")


# --- read_review_mails ---


def test_read_review_mails_empty_when_folder_absent():
    provider = FakeProvider(FakeClient(exists=False))

    assert read_review_mails(provider) == []


def test_read_review_mails_merges_uid_with_headers():
    headers = {"1": mail("a@shop.ch", "A", "Hi", "<1>")}
    provider = FakeProvider(FakeClient(exists=True, uids=["1"]), headers=headers)

    assert read_review_mails(provider) == [{"uid": "1", **headers["1"]}]


# --- review_groups ---


class FakeRules:
    def __init__(self, categories=None, own=()):
        self.categories, self.own = categories or {}, set(own)

    def category_for(self, address):
        return self.categories.get(address)

    def is_own(self, address):
        return address in self.own


def test_review_groups_groups_domain_mails_together():
    mails = [mail("a@shop.ch", "A", "S1"), mail("a@shop.ch", "A", "S1"), mail("b@shop.ch", "B", "S2")]

    groups = review_groups(mails, FakeRules())

    assert groups == {
        "shop.ch": {
            "kind": "domain",
            "mails": 3,
            "senders": {
                "a@shop.ch": {"name": "A", "mails": 2},
                "b@shop.ch": {"name": "B", "mails": 1},
            },
            "subjects": ["S1", "S2"],
        }
    }


def test_review_groups_sender_group_for_non_commercial_domain():
    mails = [mail("x@gmail.com", "X", "Hi")]

    groups = review_groups(mails, FakeRules())

    assert groups == {
        "x@gmail.com": {
            "kind": "sender",
            "mails": 1,
            "senders": {"x@gmail.com": {"name": "X", "mails": 1}},
            "subjects": ["Hi"],
        }
    }


def test_review_groups_excludes_covered_senders_and_own_addresses():
    mails = [mail("a@shop.ch"), mail("b@shop.ch"), mail("me@shop.ch")]
    covered = {"a@shop.ch": "Achats"}

    groups = review_groups(mails, FakeRules(covered, own={"me@shop.ch"}))

    assert list(groups["shop.ch"]["senders"]) == ["b@shop.ch"]


def test_review_groups_caps_subjects_at_max_subjects():
    mails = [mail("a@shop.ch", subject=f"S{i}") for i in range(8)]

    groups = review_groups(mails, FakeRules(), max_subjects=3)

    assert len(groups["shop.ch"]["subjects"]) == 3


# --- review_queue ---


def one(mails, senders=None):
    return {"kind": "domain", "mails": mails, "senders": senders or {}, "subjects": []}


def test_review_queue_sorted_desc_and_skips_dropped():
    groups = {
        "a.ch": one(2, {"x@a.ch": {"name": "", "mails": 2}}),
        "b.ch": one(5, {"y@b.ch": {"name": "", "mails": 5}}),
        "c.ch": one(1, {"z@c.ch": {"name": "", "mails": 1}}),
    }

    rows = review_queue(groups, category_for=lambda a: None, split=set(), skipped={"c.ch"})

    assert [key for key, _ in rows] == ["b.ch", "a.ch"]


def test_review_queue_fully_covered_group_disappears():
    groups = {"a.ch": one(2, {"x@a.ch": {"name": "", "mails": 2}})}

    rows = review_queue(groups, category_for=lambda a: "Achats", split=set(), skipped=set())

    assert rows == []


def test_review_queue_partly_covered_domain_shows_uncovered_mails_only():
    groups = {
        "a.ch": {
            "kind": "domain",
            "mails": 5,
            "senders": {"x@a.ch": {"name": "", "mails": 3}, "y@a.ch": {"name": "", "mails": 2}},
            "subjects": [],
        }
    }

    rows = review_queue(
        groups, category_for=lambda a: "Achats" if a == "x@a.ch" else None, split=set(), skipped=set()
    )

    assert rows == [
        (
            "a.ch",
            {
                "kind": "domain",
                "mails": 2,
                "senders": {"y@a.ch": {"name": "", "mails": 2}},
                "subjects": [],
            },
        )
    ]


def test_review_queue_split_replaces_domain_row_with_one_row_per_sender():
    groups = {
        "a.ch": {
            "kind": "domain",
            "mails": 5,
            "senders": {"x@a.ch": {"name": "X", "mails": 3}, "y@a.ch": {"name": "Y", "mails": 2}},
            "subjects": ["S"],
        }
    }

    rows = review_queue(groups, category_for=lambda a: None, split={"a.ch"}, skipped=set())

    assert dict(rows) == {
        "x@a.ch": {
            "kind": "sender", "mails": 3, "senders": {"x@a.ch": {"name": "X", "mails": 3}},
            "subjects": ["S"], "domain": "a.ch",
        },
        "y@a.ch": {
            "kind": "sender", "mails": 2, "senders": {"y@a.ch": {"name": "Y", "mails": 2}},
            "subjects": ["S"], "domain": "a.ch",
        },
    }  # fmt: skip


# --- coverage ---


def test_coverage_counts_covered_and_total_mails():
    groups = {
        "a.ch": {
            "kind": "domain",
            "mails": 5,
            "senders": {"x@a.ch": {"name": "", "mails": 3}, "y@a.ch": {"name": "", "mails": 2}},
            "subjects": [],
        }
    }

    covered, total = coverage(groups, category_for=lambda a: "Achats" if a == "x@a.ch" else None)

    assert (covered, total) == (3, 5)


# --- suggest_categories ---


def test_suggest_categories_skips_done_and_queries_llm_for_the_rest():
    groups = {
        "a.ch": {
            "kind": "domain", "mails": 3,
            "senders": {"x@a.ch": {"name": "X", "mails": 3}}, "subjects": ["S1"],
        },
        "b.ch": {
            "kind": "domain", "mails": 1,
            "senders": {"y@b.ch": {"name": "Y", "mails": 1}}, "subjects": [],
        },
    }  # fmt: skip
    llm = FakeLLM(answer="1")

    results = suggest_categories(groups, llm, done={"b.ch": "Achats"})

    assert results == {"b.ch": "Achats", "a.ch": "Banque & Placements"}
    assert len(llm.calls) == 1
    assert llm.calls[0][1] == [llm_sender_part("a.ch", "x@a.ch", ["S1"])]


def test_suggest_categories_does_not_call_llm_when_nothing_new():
    groups = {"a.ch": {"kind": "domain", "mails": 1, "senders": {}, "subjects": []}}
    llm = FakeLLM()

    results = suggest_categories(groups, llm, done={"a.ch": "Achats"})

    assert results == {"a.ch": "Achats"}
    assert llm.calls == []


# --- refile_review ---


def test_refile_review_dry_run_reports_without_moving_or_writing(tmp_path):
    mails = {
        "1": mail("a@shop.ch", mid="<1>"),
        "2": mail("a@shop.ch", mid="<2>"),
        "3": mail("b@other.ch", mid="<3>"),
    }
    provider = FakeProvider(FakeClient(exists=True, uids=list(mails)), headers=mails)
    pending = PendingArchive(tmp_path / "pending.json")
    pending.add("<1>", None, "a@shop.ch", "2026-01-01")
    pending.save()

    report = refile_review(provider, lambda a: "Achats" if a == "a@shop.ch" else None, pending, apply=False)

    assert report == {"moves": {"Achats": 2}, "left": 1}
    assert provider.moves == []
    assert pending.get("<1>") is not None


def test_refile_review_apply_moves_removes_pending_and_leaves_own_and_uncovered(tmp_path, mocker):
    mails = {
        "1": mail("a@shop.ch", mid="<1>"),
        "2": mail("a@shop.ch", mid="<2>"),  # no pending entry: moved anyway
        "3": mail("me@shop.ch", mid="<3>"),  # own address: never moved
        "4": mail("b@other.ch", mid="<4>"),  # no rule: left in place
    }
    provider = FakeProvider(FakeClient(exists=True, uids=list(mails)), headers=mails)
    pending = PendingArchive(tmp_path / "pending.json")
    pending.add("<1>", None, "a@shop.ch", "2026-01-01")
    pending.save()
    save = mocker.spy(pending, "save")

    (tmp_path / "domains.json").write_text('{"shop.ch": "Achats"}', encoding="utf-8")
    store = TaxonomyStore(tmp_path, own_addresses=["me@shop.ch"])

    report = refile_review(provider, store.category_for, pending, apply=True)

    assert report == {"moves": {"Achats": 2}, "left": 2}
    assert provider.moves == [(["1", "2"], category_folder("Achats"))]
    assert pending.get("<1>") is None
    save.assert_called_once()


def test_refile_review_apply_handles_move_failure_without_raising(tmp_path):
    mails = {"1": mail("a@shop.ch", mid="<1>")}
    provider = FakeProvider(FakeClient(exists=True, uids=["1"]), headers=mails)

    def failing_move(uids, destination):
        raise ConnectionError("boom")

    provider.batch_move_emails = failing_move
    pending = PendingArchive(tmp_path / "pending.json")

    report = refile_review(provider, lambda a: "Achats", pending, apply=True)

    assert report == {"moves": {"Achats": 0}, "left": 0}


def test_refile_review_missing_review_folder_reports_nothing(tmp_path):
    provider = FakeProvider(FakeClient(exists=False))
    pending = PendingArchive(tmp_path / "pending.json")

    report = refile_review(provider, lambda a: "Achats", pending, apply=False)

    assert report == {"moves": {}, "left": 0}


def test_refile_review_opens_review_read_write_only_when_applying(tmp_path):
    for apply in (False, True):
        client = FakeClient(exists=True, uids=[])
        refile_review(FakeProvider(client), lambda a: None, PendingArchive(tmp_path / "p.json"), apply)
        assert client.readonly is (not apply)


def test_refile_review_moves_in_chunks_and_keeps_entries_of_a_failed_chunk(tmp_path, mocker):
    mocker.patch("mailtag.review_refile._MOVE_CHUNK", 2)
    mails = {str(i): mail("a@shop.ch", mid=f"<{i}>") for i in range(1, 6)}
    provider = FakeProvider(FakeClient(exists=True, uids=list(mails)), headers=mails)
    calls = []

    def move(uids, destination):
        calls.append(list(uids))
        if len(calls) == 2:
            raise ConnectionError("boom")

    provider.batch_move_emails = move
    pending = PendingArchive(tmp_path / "pending.json")
    for i in range(1, 6):
        pending.add(f"<{i}>", None, "a@shop.ch", "2026-01-01")

    report = refile_review(provider, lambda a: "Achats", pending, apply=True)

    assert calls == [["1", "2"], ["3", "4"], ["5"]]
    assert report["moves"] == {"Achats": 3}
    assert [mid for mid, _ in pending.items()] == ["<3>", "<4>"]
