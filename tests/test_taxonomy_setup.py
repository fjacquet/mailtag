import contextlib
import json
import os
from pathlib import Path

import pytest


def test_missing_inputs(tmp_path):
    from scripts.taxonomy_setup import missing_inputs

    present = tmp_path / "scan.json"
    present.write_text("{}")
    absent = tmp_path / "crosscheck.json"

    assert missing_inputs([present, absent]) == [absent]
    assert missing_inputs([present]) == []


def test_needs_rescan_overrides_missing(tmp_path):
    from scripts.taxonomy_setup import needs_rescan

    scan = tmp_path / "scan.json"
    scan.write_text("{}")
    overrides = tmp_path / "folder_overrides.json"

    assert needs_rescan(scan, overrides) is False


def test_needs_rescan_scan_older(tmp_path):
    from scripts.taxonomy_setup import needs_rescan

    scan = tmp_path / "scan.json"
    overrides = tmp_path / "folder_overrides.json"
    scan.write_text("{}")
    overrides.write_text("{}")
    os.utime(scan, (1000, 1000))
    os.utime(overrides, (2000, 2000))

    assert needs_rescan(scan, overrides) is True


def test_needs_rescan_scan_newer(tmp_path):
    from scripts.taxonomy_setup import needs_rescan

    scan = tmp_path / "scan.json"
    overrides = tmp_path / "folder_overrides.json"
    scan.write_text("{}")
    overrides.write_text("{}")
    os.utime(overrides, (1000, 1000))
    os.utime(scan, (2000, 2000))

    assert needs_rescan(scan, overrides) is False


def test_migration_blocked_when_rules_missing(tmp_path):
    from mailtag.config import TaxonomyConfig
    from scripts.taxonomy_setup import migration_blocked

    cfg = TaxonomyConfig(taxonomy_db_dir=str(tmp_path))

    assert migration_blocked(cfg) is not None


def test_migration_not_blocked_when_enabled_and_rules_present(tmp_path):
    from mailtag.config import TaxonomyConfig
    from scripts.taxonomy_setup import migration_blocked

    (tmp_path / "senders.json").write_text("{}")
    (tmp_path / "domains.json").write_text("{}")
    cfg = TaxonomyConfig(taxonomy_db_dir=str(tmp_path))

    assert migration_blocked(cfg) is None


class FakeProvider:
    """A provider whose `connect()` is a no-op context manager, like the real ones."""

    @contextlib.contextmanager
    def connect(self):
        yield self


def test_review_scan_path():
    from scripts.taxonomy_setup import review_scan_path

    assert review_scan_path("gmail") == Path("data/review_scan_gmail.json")
    assert review_scan_path("imap") == Path("data/review_scan_imap.json")


def test_account_imap_uses_infomaniak_config(mocker):
    import scripts.taxonomy_setup as ts

    fake_service = mocker.MagicMock()
    mocker.patch("mailtag.imap_service.ImapService", return_value=fake_service)

    service, cfg = ts._account("imap")

    assert service is fake_service
    assert cfg is ts.CONFIG.imap


def test_account_gmail_uses_gmail_config(mocker):
    import scripts.taxonomy_setup as ts

    fake_service = mocker.MagicMock()
    mocker.patch("mailtag.gmail_api.GmailApiService", return_value=fake_service)

    service, cfg = ts._account("gmail")

    assert service is fake_service
    assert cfg is ts.CONFIG.gmail


def test_account_gmail_missing_config_exits(mocker):
    import scripts.taxonomy_setup as ts

    mocker.patch.object(ts.CONFIG, "gmail", None)

    with pytest.raises(SystemExit):
        ts._account("gmail")


class FakeStore:
    """`TaxonomyStore` stand-in: every sender is uncovered, whatever the constructor args."""

    def __init__(self, *args, **kwargs):
        pass

    def category_for(self, address):
        return None

    def is_own(self, address):
        return False


def test_every_store_gets_the_owners_addresses(mocker):
    import dataclasses

    import scripts.taxonomy_setup as ts

    taxonomy = dataclasses.replace(ts.CONFIG.taxonomy, own_addresses=["me@x.ch"])
    mocker.patch.object(ts, "CONFIG", dataclasses.replace(ts.CONFIG, taxonomy=taxonomy))
    store_cls = mocker.patch("scripts.taxonomy_setup.TaxonomyStore")

    ts._store()

    assert store_cls.call_args.kwargs["own_addresses"] == ["me@x.ch"]


def test_review_scan_writes_groups_and_reuses_existing_suggestions(tmp_path, mocker):
    import scripts.taxonomy_setup as ts

    scan_path = tmp_path / "review_scan_gmail.json"
    scan_path.write_text(json.dumps({"groups": {}, "suggestions": {"shop.ch": "Achats"}}))
    mocker.patch("scripts.taxonomy_setup.review_scan_path", return_value=scan_path)
    mocker.patch("scripts.taxonomy_setup.TaxonomyStore", FakeStore)
    mocker.patch("scripts.taxonomy_setup._account", return_value=(FakeProvider(), object()))
    mails = [
        {"sender_address": "a@shop.ch", "sender_name": "A", "subject": "S1", "message_id": "<1>", "uid": "1"}
    ]
    mocker.patch("mailtag.review_refile.read_review_mails", return_value=mails)
    llm_class = mocker.patch("mailtag.mlx_provider.MLXLLM")

    ts.review_scan("gmail")

    written = json.loads(scan_path.read_text())
    assert written["groups"]["shop.ch"]["mails"] == 1
    assert written["suggestions"] == {"shop.ch": "Achats"}
    llm_class.assert_not_called()


def test_review_scan_calls_llm_for_groups_without_a_suggestion(tmp_path, mocker):
    import scripts.taxonomy_setup as ts

    scan_path = tmp_path / "review_scan_imap.json"
    mocker.patch("scripts.taxonomy_setup.review_scan_path", return_value=scan_path)
    mocker.patch("scripts.taxonomy_setup.TaxonomyStore", FakeStore)
    mocker.patch("scripts.taxonomy_setup._account", return_value=(FakeProvider(), object()))
    mails = [
        {"sender_address": "a@shop.ch", "sender_name": "A", "subject": "S1", "message_id": "<1>", "uid": "1"}
    ]
    mocker.patch("mailtag.review_refile.read_review_mails", return_value=mails)
    fake_llm = mocker.MagicMock()
    fake_llm.classify_batch.return_value = ["1"]
    llm_class = mocker.patch("mailtag.mlx_provider.MLXLLM", return_value=fake_llm)

    ts.review_scan("imap")

    llm_class.assert_called_once()
    written = json.loads(scan_path.read_text())
    assert written["suggestions"] == {"shop.ch": "Banque & Placements"}


def test_refile_blocked_when_rules_missing(tmp_path, mocker):
    import scripts.taxonomy_setup as ts

    mocker.patch.object(ts.CONFIG.taxonomy, "taxonomy_db_dir", str(tmp_path))

    with pytest.raises(SystemExit):
        ts.refile("imap", apply=False)


def test_refile_calls_refile_review_dry_run_and_leaves_pending_save_to_it(tmp_path, mocker):
    import scripts.taxonomy_setup as ts
    from mailtag.config import ImapConfig

    (tmp_path / "senders.json").write_text("{}")
    (tmp_path / "domains.json").write_text("{}")
    mocker.patch.object(ts.CONFIG.taxonomy, "taxonomy_db_dir", str(tmp_path))
    fake_cfg = ImapConfig(host="h", user="u", password="p", pending_archive_file=str(tmp_path / "p.json"))
    mocker.patch("scripts.taxonomy_setup._account", return_value=(FakeProvider(), fake_cfg))
    mocker.patch("scripts.taxonomy_setup.TaxonomyStore", FakeStore)
    save_spy = mocker.patch("mailtag.pending_archive.PendingArchive.save")
    refile_review_mock = mocker.patch(
        "mailtag.review_refile.refile_review", return_value={"moves": {}, "left": 0}
    )

    ts.refile("gmail", apply=False)

    refile_review_mock.assert_called_once()
    assert refile_review_mock.call_args.args[-1] is False
    save_spy.assert_not_called()


def test_review_scan_retries_unreadable_suggestions(tmp_path, mocker):
    import scripts.taxonomy_setup as ts

    scan_path = tmp_path / "review_scan_gmail.json"
    scan_path.write_text(json.dumps({"groups": {}, "suggestions": {"shop.ch": None}}))
    mocker.patch("scripts.taxonomy_setup.review_scan_path", return_value=scan_path)
    mocker.patch("scripts.taxonomy_setup.TaxonomyStore", FakeStore)
    mocker.patch("scripts.taxonomy_setup._account", return_value=(FakeProvider(), object()))
    mails = [
        {"sender_address": "a@shop.ch", "sender_name": "A", "subject": "S1", "message_id": "<1>", "uid": "1"}
    ]
    mocker.patch("mailtag.review_refile.read_review_mails", return_value=mails)
    llm = mocker.patch("mailtag.mlx_provider.MLXLLM").return_value
    llm.classify_batch.return_value = ["1"]

    ts.review_scan("gmail")

    assert json.loads(scan_path.read_text())["suggestions"]["shop.ch"] == "Banque & Placements"


TRAIN_MAILS = [
    {
        "sender": f"s{i}@x.ch",
        "sender_name": "",
        "subject": word,
        "body": "",
        "category": cat,
        "verified": False,
    }
    for i, (word, cat) in enumerate(
        [("pizza", "Achats"), ("impot", "Impôts & Administration"), ("train", "Transports & Mobilité")] * 4
    )
]


def _train_setup(tmp_path, monkeypatch, mocker, mails):
    import scripts.taxonomy_setup as setup
    from mailtag.config import CONFIG, LogRegConfig
    from tests.fake_embedder import FakeEmbedder

    corpus = tmp_path / "corpus.json"
    if mails is not None:
        corpus.write_text(json.dumps(mails), encoding="utf-8")
    monkeypatch.setattr(setup, "CORPUS", corpus)
    monkeypatch.setattr(CONFIG, "logreg", LogRegConfig(model_file=str(tmp_path / "logreg.npz")))
    mocker.patch("mailtag.mlx_provider.MLXEmbedder", FakeEmbedder)
    return setup, mocker.patch.object(setup, "_imap")


def test_train_writes_the_model_without_imap(tmp_path, monkeypatch, mocker):
    from mailtag.config import CONFIG
    from mailtag.logreg_provider import load_model

    setup, imap = _train_setup(tmp_path, monkeypatch, mocker, TRAIN_MAILS)

    setup.train()

    model = load_model(tmp_path / "logreg.npz", CONFIG.mlx.embedding_model)
    assert sorted(model["classes"].tolist()) == sorted({m["category"] for m in TRAIN_MAILS})
    imap.assert_not_called()


def test_train_without_corpus_exits_with_a_message(tmp_path, monkeypatch, mocker):
    setup, _ = _train_setup(tmp_path, monkeypatch, mocker, None)

    with pytest.raises(SystemExit, match="build"):
        setup.train()


def test_train_with_too_few_categories_exits_with_a_message(tmp_path, monkeypatch, mocker):
    setup, _ = _train_setup(tmp_path, monkeypatch, mocker, TRAIN_MAILS[:2])

    with pytest.raises(SystemExit, match="3 categories"):
        setup.train()
    assert not (tmp_path / "logreg.npz").exists()
