"""End-to-end run of `run_classification` in taxonomy mode, IMAP provider mocked."""

import json

import pytest

from mailtag.classifier import Classifier
from mailtag.config import (
    AppConfig,
    ClassifierConfig,
    FastParseConfig,
    GeneralConfig,
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
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3
        ),
        imap=ImapConfig(host="h", user="u@x.ch", password="p"),
        gmail=GmailConfig(credentials_file="c", token_file="t"),
        fast_parse=FastParseConfig(batch_size=100, metrics_enabled=False),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(
            enabled=True,
            taxonomy_db_dir=str(tmp_path / "taxonomy"),
            pending_archive_file=str(tmp_path / "pending.json"),
        ),
    )


def _provider(mocker, tmp_path):
    provider = mocker.MagicMock(spec=ImapService)
    provider.config = ImapConfig(host="h", user="u@x.ch", password="p", junk_folder_name="Junk")
    provider.fast_parse_config = FastParseConfig(batch_size=100, metrics_enabled=False)
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
    return _provider(mocker, tmp_path), archive


def test_run_routes_rules_and_models_into_action_folders(env, tmp_path, mocker):
    provider, archive = env

    tasks.run_classification(provider, mocker.MagicMock(), False)

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


def test_validate_run_moves_and_writes_nothing(env, tmp_path, mocker):
    provider, archive = env

    tasks.run_classification(provider, mocker.MagicMock(), True)

    provider.batch_move_emails.assert_not_called()
    assert not (tmp_path / "pending.json").exists()
    assert sorted(p.name for p in (tmp_path / "taxonomy").iterdir()) == ["validated.json"]
    assert archive.call_args.args[5] is True
