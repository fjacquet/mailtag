"""End-to-end run of `run_classification` in taxonomy mode, IMAP provider mocked."""

import json

import pytest

from mailtag.classifier import Classifier
from mailtag.config import (
    AppConfig,
    FastParseConfig,
    GmailConfig,
    ImapConfig,
    LoggingConfig,
    MLXConfig,
    TaxonomyConfig,
)
from mailtag.imap_service import ImapService
from mailtag.models import Email
from mailtag.taxonomy import REVIEW
from mailtag.utils import tasks

HEADERS = {
    "1": {"sender_address": "a@sixt.ch", "subject": "Réservation", "message_id": "<1@x>",
          "has_unsubscribe": False, "is_bulk": True},
    "2": {"sender_address": "doc@clinic.ch", "subject": "Rendez-vous", "message_id": "<2@x>",
          "has_unsubscribe": False, "is_bulk": True},
    "3": {"sender_address": "who@unknown.ch", "subject": "Hello", "message_id": "<3@x>",
          "has_unsubscribe": False, "is_bulk": True},
}  # fmt: skip
FULL = [
    Email(msg_id="2", subject="Rendez-vous", sender_address="doc@clinic.ch", sender_name="", body="b",
          message_id="<2@x>", is_bulk=True),
    Email(msg_id="3", subject="Hello", sender_address="who@unknown.ch", sender_name="", body="b",
          message_id="<3@x>", is_bulk=True),
]  # fmt: skip


def _config(tmp_path):
    return AppConfig(
        logging=LoggingConfig(level="DEBUG", file=""),
        imap=ImapConfig(host="h", user="u@x.ch", password="p"),
        gmail=GmailConfig(credentials_file="c", token_file="t"),
        fast_parse=FastParseConfig(batch_size=100),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(
            taxonomy_db_dir=str(tmp_path / "taxonomy"),
            pending_archive_file=str(tmp_path / "pending.json"),
        ),
    )


def _run(provider, validate):
    tasks.run_classification(provider, validate, Classifier(tasks.CONFIG, read_only=validate))


def _provider(mocker):
    provider = mocker.MagicMock(spec=ImapService)
    provider.config = ImapConfig(host="h", user="u@x.ch", password="p", junk_folder_name="Junk")
    provider.fast_parse_config = FastParseConfig(batch_size=100)
    provider.connect.return_value.__enter__.return_value = provider
    provider.client = mocker.MagicMock()  # an instance attribute: spec=ImapService does not provide it
    selected = {}
    provider.client.select_folder.side_effect = lambda name, readonly=False: selected.update(name=name)
    provider.client.search.side_effect = lambda *a: [1, 2, 3] if selected["name"] == "INBOX" else []
    provider.get_email_headers.return_value = HEADERS
    provider.get_full_emails.return_value = FULL
    return provider


@pytest.fixture
def env(mocker, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # anything written under data/ stays in tmp_path
    (tmp_path / "taxonomy").mkdir()
    (tmp_path / "taxonomy" / "validated.json").write_text(
        json.dumps({"a@sixt.ch": "Voyages & Loisirs"}), encoding="utf-8"
    )
    mocker.patch.object(tasks, "CONFIG", _config(tmp_path))
    # Without this, the domain cache would load (empty) from tmp_path and stay cached for other tests
    mocker.patch("mailtag.taxonomy_store.is_non_commercial_domain_cached", return_value=False)
    mocker.patch.object(
        Classifier,
        "_nomic_top",
        side_effect=lambda emails: [
            ("Santé", 0.60) if e.sender_address == "doc@clinic.ch" else ("Achats", 0.50) for e in emails
        ],
    )
    mocker.patch.object(Classifier, "_llm_categories", side_effect=lambda emails: ["Santé"] * len(emails))
    archive = mocker.patch.object(tasks, "run_archive")
    return _provider(mocker), archive


def test_run_routes_rules_and_models_into_action_folders(env, tmp_path, mocker):
    provider, archive = env

    _run(provider, False)

    moves = [(c.args[0], c.args[1]) for c in provider.batch_move_emails.call_args_list]
    assert moves == [(["1"], "4-Pour info"), (["2"], "4-Pour info"), (["3"], REVIEW)]
    pending = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert {mid: e["category"] for mid, e in pending.items()} == {
        "<1@x>": "Voyages & Loisirs",
        "<2@x>": "Santé",
        "<3@x>": None,
    }
    archive.assert_called_once()
    assert archive.call_args.args[5] is False


def _senders(tmp_path):
    path = tmp_path / "taxonomy" / "senders.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_agreement_is_learned_once_the_mail_moved(env, tmp_path):
    provider, _ = env

    _run(provider, False)

    assert _senders(tmp_path) == {"doc@clinic.ch": {"category": "Santé", "agreements": 1}}


def test_agreement_is_not_learned_when_the_move_fails(env, tmp_path):
    provider, _ = env

    def move(uids, folder):
        if uids == ["2"]:
            raise ConnectionError("down")

    provider.batch_move_emails.side_effect = move

    _run(provider, False)

    assert _senders(tmp_path) == {}


def test_validate_run_moves_and_writes_nothing(env, tmp_path, mocker):
    provider, archive = env

    _run(provider, True)

    provider.batch_move_emails.assert_not_called()
    assert not (tmp_path / "pending.json").exists()
    assert sorted(p.name for p in (tmp_path / "taxonomy").iterdir()) == ["validated.json"]
    assert archive.call_args.args[5] is True


def test_run_writes_no_manual_matching_dump(env, tmp_path):
    provider, _ = env

    _run(provider, False)

    assert not (tmp_path / "data").exists()


def test_junk_folder_mail_covered_by_a_rule_is_routed(env, tmp_path, mocker):
    _, _ = env
    provider = _provider(mocker)
    selected = {}
    provider.client.select_folder.side_effect = lambda name, readonly=False: selected.update(name=name)
    provider.client.search.side_effect = lambda *a: {"INBOX": [1, 2, 3], "Junk": [9]}.get(
        selected["name"], []
    )
    junk = {**HEADERS["1"], "message_id": "<9@x>"}
    provider.get_email_headers.side_effect = lambda uids: {
        str(u): junk if str(u) == "9" else HEADERS[str(u)] for u in uids
    }

    _run(provider, False)

    moves = [(c.args[0], c.args[1]) for c in provider.batch_move_emails.call_args_list]
    assert (["9"], "4-Pour info") in moves
    pending = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert pending["<9@x>"]["category"] == "Voyages & Loisirs"


def test_pass_1_skips_own_addresses(env, tmp_path):
    provider, _ = env
    import dataclasses

    cfg = tasks.CONFIG
    tasks.CONFIG = dataclasses.replace(
        cfg, taxonomy=dataclasses.replace(cfg.taxonomy, own_addresses=["A@sixt.ch"])
    )
    try:
        _run(provider, False)
    finally:
        tasks.CONFIG = cfg

    pending = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert "<1@x>" not in pending  # left for Pass 3 instead of routed by a rule


def test_all_providers_share_one_classifier(mocker, tmp_path):
    from main import start_classification_run

    mocker.patch("mailtag.utils.db_backup.backup_all_databases")
    mocker.patch("mailtag.utils.db_backup.cleanup_old_backups")
    mocker.patch("main.CONFIG")
    mocker.patch("main.ImapService")
    mocker.patch("main.GmailApiService")
    build = mocker.patch("main.Classifier")
    run = mocker.patch("main.run_classification")

    start_classification_run("all", True)

    build.assert_called_once()
    assert build.call_args.kwargs["read_only"] is True
    assert [c.args[2] for c in run.call_args_list] == [build.return_value] * 2
