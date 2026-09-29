# Taxonomy-only cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make taxonomy mode the only mode and remove legacy and dead code (~8k lines), keeping `run`, `serve`, `taxonomy_setup.py` and `taxonomy_review.py` behaviour intact.

**Architecture:** Five stacked PRs on branch `refactor/taxonomy-only`. PR A adds a safety net (end-to-end test, `read_only` argument, backups of the files that matter). PR B removes the legacy core; the API rewire is done inside PR B because the files it deletes (`database.py`, `gmail_service.py`) are imported by the API. PR C makes Docker rules-only. PR D removes dead code and dependencies. PR E rewrites the docs.

**Tech Stack:** Python 3.13, uv, pytest + pytest-mock, ruff, FastAPI, IMAPClient, MLX (mlx-lm, sentence-transformers).

**Spec:** `docs/superpowers/specs/2026-09-29-taxonomie-seule-nettoyage-design.md`

**Deviation from the spec:** the spec lists the API rewire as stage C, after the legacy-core removal. The API imports `ClassificationDatabase` and `GmailService`, so it must be rewired before those files are deleted: the API rewire is Task 6, inside PR B. PR C keeps the Docker part.

## Global Constraints

- Taxonomy mode is the only mode; `[taxonomy] enabled` disappears.
- The webhook API (`serve`) and Docker stay, rewired on the taxonomy.
- Docker without MLX classifies by rules only (signals 1, 3, 4); the rest goes to `5-A revoir`. litellm disappears.
- `metrics.py` disappears entirely (periodic log thread, `@timed`, psutil).
- Backups cover `db/taxonomy/*.json` and `db/pending_archive*.json`, 10 copies per file, in `db/backups/`.
- `src/app.py` stays.
- The folder cache (`get_folder_hierarchy`, `folder_cache_file`, `folder_cache_ttl_hours`) disappears.
- `Email.labels` disappears from the model and the API schemas.
- `--validate` must stay read-only at every step: no move, no write in `db/taxonomy/` or `db/pending_archive*.json`.
- `load_config` change and `config.toml`/`.env.example` change land in the same commit.
- Never delete runtime data (`data/`, `db/`) from code or by hand; Task 16 lists stale files for the owner.
- Do not run anything against the live mailbox while `migrate --apply` runs; ask the owner before any live smoke test.
- Every task ends with `uv run pytest -q` and `uv run ruff check .` green. Line length 110.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Use `rtk git ...` for git commands.

## Review Focus

1. A `--validate` run (IMAP or Gmail) must not move mail nor write `db/taxonomy/*`, `db/pending_archive*.json`, nor learn a sender. Pinned by Task 2 (`test_validate_run_moves_and_writes_nothing`) and Task 1.
2. An N8N client that still sends `labels` in `/classify` or `/classify-and-move` must keep getting 200 (the field is ignored, not rejected). Pinned by Task 6 (`test_legacy_labels_field_is_ignored`).
3. A `/classify-and-move` mail sent to `5-A revoir` must get a pending entry with `category: None`, so filing it teaches the rule. Pinned by Task 6 (`test_review_mail_gets_pending_entry`).
4. An existing `config.toml` that still has `[general]`, `[classifier]`, `enabled = true` under `[taxonomy]` or `folder_cache_file` must still load (unknown keys ignored), so the owner's file and CI's do not break before they are edited. Pinned by Task 8 (`test_old_sections_are_ignored`).
5. Without MLX (Docker), a mail no rule covers must go to `5-A revoir`, never raise nor call a network model. Pinned by Task 10 (`test_without_mlx_uncovered_mail_goes_to_review`).

Known limitation, not fixed here: `PendingArchive` has no file lock. If `serve` records an entry while a `run` holds the same pending file in memory, the `run`'s final save drops that entry; the mail then stays in its action folder until filed by hand. Documented in Task 16.

---

## PR A — Safety net

### Task 1: `read_only` argument on `Classifier`

**Files:**
- Modify: `src/mailtag/classifier.py:38-72`
- Modify: `src/mailtag/utils/tasks.py:212-221`
- Test: `tests/test_classifier_taxonomy.py`

**Interfaces:**
- Produces: `Classifier(config: AppConfig, database, read_only: bool = False)`. `database` is removed in Task 7.

- [ ] **Step 1: Write the failing test**

In `tests/test_classifier_taxonomy.py`, replace `test_read_only_database_means_no_learning_written` with:

```python
def test_read_only_classifier_writes_nothing(db, tmp_path, mocker):
    classifier = Classifier(config=_config(tmp_path), database=db, read_only=True)
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classifier.classify_emails_batch([mail(sender="doc@clinic.ch")])

    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_classifier_taxonomy.py::test_read_only_classifier_writes_nothing -q`
Expected: FAIL with `TypeError: Classifier.__init__() got an unexpected keyword argument 'read_only'`

- [ ] **Step 3: Implement**

In `src/mailtag/classifier.py`, change the signature and the store creation:

```python
    def __init__(self, config: AppConfig, database: ClassificationDatabase, read_only: bool = False):
```

```python
            self.taxonomy_store = TaxonomyStore(
                Path(config.taxonomy.taxonomy_db_dir),
                min_agreements=config.taxonomy.learn_min_agreements,
                read_only=read_only,
            )
```

In `src/mailtag/utils/tasks.py` `run_classification`, pass the flag on both `Classifier(...)` calls:

```python
        if isinstance(provider_instance, ImapService):
            classifier = Classifier(CONFIG, database, read_only=validate)
        else:
            gmail_config = dataclasses.replace(
                CONFIG, taxonomy=dataclasses.replace(CONFIG.taxonomy, enabled=False)
            )
            classifier = Classifier(gmail_config, database, read_only=validate)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass. If a webhook test relied on `getattr(database, "read_only")`, the API never ran read-only, so no API test should change.

- [ ] **Step 5: Commit**

```bash
rtk git add src/mailtag/classifier.py src/mailtag/utils/tasks.py tests/test_classifier_taxonomy.py
rtk git commit -m "feat(taxonomy): read_only argument on Classifier

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: End-to-end test of `run_classification`

**Files:**
- Create: `tests/test_run_classification.py`

**Interfaces:**
- Consumes: `Classifier(..., read_only=...)` from Task 1; `tasks.run_classification(provider, database, validate)` (current signature; Task 4 drops `database`).
- Produces: `_config(tmp_path)`, `_provider(mocker, tmp_path)` helpers reused by Tasks 4 and 8.

This is a characterization test: it must pass against the current code. Steps check that it can fail.

- [ ] **Step 1: Write the test**

```python
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
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_run_classification.py -q`
Expected: 2 passed.

- [ ] **Step 3: Check it can fail**

Temporarily change `read_only=validate` to `read_only=False` in `tasks.run_classification` (ImapService branch). Run the file again.
Expected: `test_validate_run_moves_and_writes_nothing` FAILS on the `taxonomy` dir listing (a `senders.json` appears). Revert the change and re-run: 2 passed.

- [ ] **Step 4: Commit**

```bash
rtk git add tests/test_run_classification.py
rtk git commit -m "test: end-to-end run_classification in taxonomy mode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Back up the taxonomy files, not the legacy ones

**Files:**
- Modify: `src/mailtag/utils/db_backup.py`
- Test: `tests/test_db_backup.py`

**Interfaces:**
- Produces: `backup_all_databases(db_dir: Path, backup_dir: Path | None = None) -> list[Path]` backs up `db_dir/taxonomy/*.json` and `db_dir/pending_archive*.json`. `backup_database`, `cleanup_old_backups`, `get_backup_stats` unchanged. `restore_database` and `list_backups` removed (never called).

- [ ] **Step 1: Write the failing test**

In `tests/test_db_backup.py`, delete `test_backup_all`, `test_restore_from_backup`, `test_restore_nonexistent_backup`, `test_list_backups`, `test_list_empty_directory` and any import of `restore_database`/`list_backups`. Add:

```python
def test_backup_all_covers_taxonomy_rules_and_pending_archives(tmp_path):
    db = tmp_path / "db"
    (db / "taxonomy").mkdir(parents=True)
    for name in ("taxonomy/validated.json", "taxonomy/senders.json", "pending_archive.json",
                 "pending_archive_gmail.json", "sender_classification_db.json"):  # fmt: skip
        (db / name).write_text("{}", encoding="utf-8")

    backups = backup_all_databases(db)

    assert sorted(p.name.rsplit("_", 2)[0] for p in backups) == [
        "pending_archive",
        "pending_archive_gmail",
        "senders",
        "validated",
    ]
    assert all(p.parent == db / "backups" for p in backups)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_db_backup.py::test_backup_all_covers_taxonomy_rules_and_pending_archives -q`
Expected: FAIL (the list holds `sender_classification_db` only).

- [ ] **Step 3: Implement**

Replace `backup_all_databases` with:

```python
def backup_all_databases(db_dir: Path, backup_dir: Path | None = None) -> list[Path]:
    """Back up the taxonomy rules (`db/taxonomy/*.json`) and each account's pending archive."""
    if backup_dir is None:
        backup_dir = db_dir / "backups"

    db_files = sorted((db_dir / "taxonomy").glob("*.json")) + sorted(db_dir.glob("pending_archive*.json"))
    backups = [path for path in (backup_database(f, backup_dir) for f in db_files) if path]

    logger.info(f"Backed up {len(backups)} database files to {backup_dir}")
    return backups
```

Delete `restore_database` and `list_backups`. Update the module docstring to `"""Timestamped backups of the taxonomy rules and pending archives."""`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_db_backup.py tests/test_main.py -q && uv run ruff check src/mailtag/utils/db_backup.py`
Expected: pass.

- [ ] **Step 5: Commit and open PR A**

```bash
rtk git add src/mailtag/utils/db_backup.py tests/test_db_backup.py
rtk git commit -m "feat(backup): back up taxonomy rules and pending archives

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
rtk git push -u origin refactor/taxonomy-only
```

Open PR A with `gh pr create --title "Taxonomy-only cleanup A: safety net" --body "..."` (body: the three tasks, then `🤖 Generated with [Claude Code](https://claude.com/claude-code)`). Continue on the same branch; later PRs stack on it (or merge A first, then branch again from `main` — ask the owner which they prefer before opening PR A).

---

## PR B — Remove the legacy core

### Task 4: `run_classification` taxonomy-only

**Files:**
- Modify: `src/mailtag/utils/tasks.py` (full rewrite below)
- Modify: `src/main.py:59-92` (`start_classification_run`)
- Test: `tests/test_run_classification.py`, `tests/test_routing.py:132-156`, `tests/test_main.py`

**Interfaces:**
- Consumes: `Classifier(config, database, read_only=...)` (Task 1).
- Produces: `run_classification(provider_instance: ImapService, validate: bool) -> None`; `_run_fast_parse_on_folder(provider, folder_name, validate, pending, rules) -> list[str]`; `pending_archive_path`, `junk_folder` unchanged.

- [ ] **Step 1: Update the tests to the new signatures (they fail)**

In `tests/test_run_classification.py`, replace both calls:

```python
    tasks.run_classification(provider, False)
```
```python
    tasks.run_classification(provider, True)
```

and add:

```python
def test_run_writes_no_manual_matching_dump(env, tmp_path):
    provider, _ = env

    tasks.run_classification(provider, False)

    assert not (tmp_path / "data").exists()
```

In `tests/test_routing.py`, `test_pass1_routes_known_sender_in_taxonomy_mode`: remove `database = mocker.MagicMock()` and the last assert, and replace the call with:

```python
    uids = tasks._run_fast_parse_on_folder(provider, "INBOX", False, pending, rules)
```

In `tests/test_main.py`: in the test at lines ~140-146 change `assert args[2] is True` to `assert args[1] is True`; replace `test_validate_opens_database_read_only` with:

```python
@pytest.mark.parametrize("validate", [True, False])
def test_run_passes_validate_to_each_provider(mocker: MockerFixture, validate):
    from main import start_classification_run

    mocker.patch("mailtag.utils.db_backup.backup_all_databases")
    mocker.patch("mailtag.utils.db_backup.cleanup_old_backups")
    config = mocker.patch("main.CONFIG")
    config.gmail = None
    mocker.patch("main.ImapService")
    run = mocker.patch("main.run_classification")

    start_classification_run("imap", validate)

    assert run.call_args.args[1] is validate
```

Remove any `mocker.patch("main.refresh_imap_folders"...)` / `main.ClassificationDatabase` patch in the other tests of `tests/test_main.py` that now target missing names (they fail with `AttributeError` once Step 3 lands).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_run_classification.py tests/test_routing.py tests/test_main.py -q`
Expected: FAIL (`TypeError` on the signatures; the dump test finds `data/`).

- [ ] **Step 3: Rewrite `src/mailtag/utils/tasks.py`**

```python
import imaplib
from datetime import date
from pathlib import Path

from loguru import logger

from mailtag.archive import run_archive
from mailtag.classifier import Classifier
from mailtag.config import CONFIG, GmailConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders
from mailtag.taxonomy_store import TaxonomyStore


def _run_fast_parse_on_folder(
    provider: ImapService,
    folder_name: str,
    validate: bool,
    pending: PendingArchive,
    rules: TaxonomyStore,
) -> list[str]:
    """Pass 1: route each email a taxonomy rule covers; return the UIDs left for Pass 3."""
    logger.info(f"Starting Pass 1 on folder: {folder_name}")
    try:
        provider.client.select_folder(folder_name)
    except (imaplib.IMAP4.error, KeyError, ValueError) as e:
        logger.warning(f"Could not select folder '{folder_name}'. It might not exist. Skipping. Error: {e}")
        return []

    all_uids = provider.client.search()
    if not all_uids:
        logger.info(f"No emails to process in {folder_name}.")
        return []

    logger.info(f"Found {len(all_uids)} emails in {folder_name}.")
    remaining: list[str] = []
    for i in range(0, len(all_uids), provider.fast_parse_config.batch_size):
        batch_uids = all_uids[i : i + provider.fast_parse_config.batch_size]
        routed: list[RoutedMail] = []
        for uid, header_data in provider.get_email_headers(batch_uids).items():
            category = rules.category_for(header_data["sender_address"])
            if category:
                logger.info(
                    f'Email "{header_data["subject"]}" from {header_data["sender_address"]}'
                    f" -> Category: {category} (Pass 1)"
                )
                routed.append(RoutedMail.from_headers(uid, category, header_data))
            else:
                remaining.append(uid)
        if routed:
            route_to_action_folders(provider, pending, routed, validate, date.today())

    logger.info(f"Pass 1 on {folder_name} complete. {len(all_uids) - len(remaining)} emails routed.")
    return remaining


def pending_archive_path(config: ImapConfig | GmailConfig, default: str) -> Path:
    """Each IMAP account keeps its own pending archive: one account's sweep cannot see the
    other's mails and would remove their entries as orphans."""
    return Path(config.pending_archive_file or default)


def junk_folder(provider: ImapService) -> str | None:
    return provider.config.junk_folder_name or provider.fast_parse_config.junk_folder_name


def run_classification(provider_instance: ImapService, validate: bool) -> None:
    """Pass 1 (rules) on the junk folder and INBOX, Pass 3 (nomic/Gemma) on the rest, then the archive sweep."""
    try:
        classifier = Classifier(CONFIG, None, read_only=validate)
        rules = classifier.taxonomy_store
        pending = PendingArchive(
            pending_archive_path(provider_instance.config, CONFIG.taxonomy.pending_archive_file)
        )

        with provider_instance.connect() as provider:
            junk = junk_folder(provider)
            if junk:
                _run_fast_parse_on_folder(provider, junk, validate, pending, rules)
            remaining = _run_fast_parse_on_folder(provider, "INBOX", validate, pending, rules)

            logger.info(f"Starting Pass 3: AI classification for {len(remaining)} remaining emails...")
            if remaining:
                emails = provider.get_full_emails(remaining)
                categories = classifier.classify_emails_batch(emails)
                route_to_action_folders(
                    provider,
                    pending,
                    [RoutedMail.from_email(e, c) for e, c in zip(emails, categories, strict=True)],
                    validate,
                    date.today(),
                )
            logger.info("Pass 3 complete.")

            run_archive(provider, pending, rules, CONFIG.taxonomy.archive_after_days, date.today(), validate)
            logger.info("Analysis complete.")

    except (FileNotFoundError, ConnectionError) as e:
        logger.critical(e)
```

- [ ] **Step 4: Rewrite `start_classification_run` in `src/main.py`**

```python
def start_classification_run(provider, validate):
    """Sets up and starts the classification run."""
    from mailtag.utils.db_backup import backup_all_databases, cleanup_old_backups

    db_dir = Path("db")
    logger.info("Creating database backups...")
    backup_all_databases(db_dir)
    cleanup_old_backups(db_dir / "backups", keep_count=10)

    providers_to_run = []
    if provider in ("imap", "all") and CONFIG.imap:
        providers_to_run.append(ImapService(CONFIG.imap, CONFIG.fast_parse))
    if provider in ("gmail", "all") and CONFIG.gmail:
        providers_to_run.append(GmailApiService(CONFIG.gmail, CONFIG.fast_parse))

    if not providers_to_run:
        logger.warning("No providers configured or selected. Check your config.toml.")
        return

    for p in providers_to_run:
        logger.info(f"Running classification for provider: {type(p).__name__}")
        run_classification(p, validate)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_run_classification.py tests/test_routing.py tests/test_main.py tests/test_tasks_accounts.py -q`
Expected: pass. Then `uv run pytest -q`: tests that exercise the deleted `_run_domain_classification_pass` / Gmail `else` branch (in `tests/integration/test_full_classification_workflow.py`, `tests/test_error_recovery.py`) fail; delete those whole files now (they are legacy-only, listed in the spec).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . --fix && uv run ruff format src/mailtag/utils/tasks.py src/main.py
rtk git add -A src/mailtag/utils/tasks.py src/main.py tests/
rtk git commit -m "refactor(taxonomy): run_classification is taxonomy-only

Drops Pass 2, the pass-3 manual matching dump, the Gmail legacy branch
and the folder refresh at startup.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Remove the legacy CLI commands

**Files:**
- Modify: `src/main.py` (full content below)
- Modify: `src/mailtag/utils/db_backup.py` (remove `get_backup_stats`)
- Test: `tests/test_main.py`, `tests/test_db_backup.py`

**Interfaces:**
- Produces: CLI commands `run` and `serve` only.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_only_run_and_serve_remain():
    from main import cli

    assert sorted(cli.commands) == ["run", "serve"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_main.py::test_only_run_and_serve_remain -q`
Expected: FAIL (lists `analyze-domains`, `cleanup`, `db-stats`, `filters`, `prune-db` too).

- [ ] **Step 3: Rewrite `src/main.py`**

```python
#!/usr/bin/env python3

"""
Main CLI entry point for the mailtag email classification script.
"""

import sys
from pathlib import Path

import click
from loguru import logger

try:
    from mailtag.config import CONFIG
except RuntimeError as e:
    print(f"❌ Configuration file error: {e}")
    print("Please ensure config.toml exists and is valid TOML format")
    sys.exit(1)
except ValueError as e:
    print(f"❌ Configuration validation error: {e}")
    print("Please check your config.toml and .env file settings")
    sys.exit(1)
from mailtag.gmail_api import GmailApiService
from mailtag.imap_service import ImapService
from mailtag.logging_config import setup_logging
from mailtag.utils.tasks import run_classification


def start_classification_run(provider, validate):
    """Sets up and starts the classification run."""
    from mailtag.utils.db_backup import backup_all_databases, cleanup_old_backups

    db_dir = Path("db")
    logger.info("Creating database backups...")
    backup_all_databases(db_dir)
    cleanup_old_backups(db_dir / "backups", keep_count=10)

    providers_to_run = []
    if provider in ("imap", "all") and CONFIG.imap:
        providers_to_run.append(ImapService(CONFIG.imap, CONFIG.fast_parse))
    if provider in ("gmail", "all") and CONFIG.gmail:
        providers_to_run.append(GmailApiService(CONFIG.gmail, CONFIG.fast_parse))

    if not providers_to_run:
        logger.warning("No providers configured or selected. Check your config.toml.")
        return

    for p in providers_to_run:
        logger.info(f"Running classification for provider: {type(p).__name__}")
        run_classification(p, validate)


@click.group()
def cli():
    """MailTag: Email Classification Tool"""
    setup_logging(CONFIG.logging.level, CONFIG.logging.file)


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["imap", "gmail", "all"]),
    default="all",
    help="The email provider to use.",
)
@click.option(
    "--validate",
    is_flag=True,
    help="Run in validation mode (read-only): classify and log, move and learn nothing.",
)
def run(provider, validate):
    """Run the email classification process."""
    start_classification_run(provider, validate)
```

Then append the existing `serve` command and the `if __name__ == "__main__": cli()` block unchanged (copy them from the current file, lines `@cli.command()` above `def serve` through the end).

- [ ] **Step 4: Remove `get_backup_stats`**

Delete `get_backup_stats` from `src/mailtag/utils/db_backup.py` and `test_stats_with_backups`, `test_stats_empty_directory` from `tests/test_db_backup.py`. Delete from `tests/test_main.py` every test for `filters`, `analyze-domains`, `cleanup`, `db-stats`, `prune-db` (`grep -n "filters\|analyze\|cleanup\|db-stats\|db_stats\|prune" tests/test_main.py`).

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q && uv run ruff check .`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
rtk git add -A src/main.py src/mailtag/utils/db_backup.py tests/test_main.py tests/test_db_backup.py
rtk git commit -m "refactor(cli): keep only run and serve

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Webhook API taxonomy-only

**Files:**
- Modify: `src/mailtag/api/dependencies.py` (full content below)
- Modify: `src/mailtag/api/__init__.py` (description, tags, lifespan)
- Modify: `src/mailtag/api/routes/classify.py` (full content below)
- Modify: `src/mailtag/api/routes/health.py`
- Modify: `src/mailtag/api/schemas.py`
- Test: `tests/test_webhook_api.py`

**Interfaces:**
- Consumes: `pending_archive_path` (Task 4), `route_to_action_folders`, `RoutedMail.from_email`, `GmailApiService`.
- Produces: `AppState` with `start_time`, `classifier`, `initialize()`, `uptime_seconds` (no `database`, `legacy_classifier`, `shutdown`). `ClassifyAndMoveRequest` gains `message_id: str = ""`, `has_unsubscribe: bool = False`, `is_bulk: bool = False`; `labels` gone from both request models; `database_loaded` gone from `HealthResponse`/`StatusResponse`.

- [ ] **Step 1: Rewrite the move tests (they fail)**

In `tests/test_webhook_api.py`:
- remove `mock_database` fixture and its parameter everywhere; in `_make_client` remove `app_state.database = mock_database` and the `app_state.database = None` / `app_state.legacy_classifier = None` resets; add `mock_config.taxonomy = MagicMock(pending_archive_file="db/pending_archive.json")`.
- remove `"labels": ["INBOX"]` from `_sample_email()`.
- remove `database_loaded` assertions in the health tests.
- delete `_real_config`, the whole Gmail-legacy test class (the three tests from `test_gmail_uses_legacy_classifier_when_taxonomy_enabled` to `test_taxonomy_disabled_never_builds_second_classifier`) and `test_classify_and_move_unactionable`, `test_classify_and_move_success`, `test_classify_and_move_files_a_category_into_its_para_folder`.
- add at module level:

```python
@pytest.fixture
def move_env(tmp_path):
    provider = MagicMock()
    provider.connect.return_value.__enter__ = MagicMock(return_value=provider)
    provider.connect.return_value.__exit__ = MagicMock(return_value=False)
    pending_file = tmp_path / "pending.json"
    with (
        patch("mailtag.api.routes.classify.ImapService", return_value=provider) as imap_cls,
        patch("mailtag.api.routes.classify.GmailApiService", return_value=provider) as gmail_cls,
        patch("mailtag.api.routes.classify.pending_archive_path", return_value=pending_file),
    ):
        yield provider, imap_cls, gmail_cls, pending_file


def _move_payload(provider="imap", **extra):
    payload = _sample_email() | {"provider": provider, "message_id": "<m@x>", "is_bulk": True}
    return payload | extra
```

- add in `TestClassifyAndMove`:

```python
    def test_routes_into_action_folder_and_records_category(self, api_client, mock_classifier, move_env):
        provider, imap_cls, _, pending_file = move_env
        mock_classifier.classify_email.return_value = "Santé"

        response = api_client.post("/api/v1/classify-and-move", json=_move_payload(), headers=_auth_headers())

        assert response.status_code == 200
        assert response.json() == {"msg_id": "12345", "category": "Santé", "moved": True, "error": None}
        imap_cls.assert_called_once()
        provider.client.select_folder.assert_called_once_with("INBOX")
        provider.batch_move_emails.assert_called_once_with(["12345"], "4-Pour info")
        assert json.loads(pending_file.read_text(encoding="utf-8"))["<m@x>"]["category"] == "Santé"

    def test_review_mail_gets_pending_entry(self, api_client, mock_classifier, move_env):
        provider, _, _, pending_file = move_env
        mock_classifier.classify_email.return_value = "5-A revoir"

        response = api_client.post("/api/v1/classify-and-move", json=_move_payload(), headers=_auth_headers())

        assert response.json()["moved"] is True
        provider.batch_move_emails.assert_called_once_with(["12345"], "5-A revoir")
        assert json.loads(pending_file.read_text(encoding="utf-8"))["<m@x>"]["category"] is None

    def test_gmail_goes_through_the_gmail_api(self, api_client, mock_classifier, move_env):
        _, imap_cls, gmail_cls, _ = move_env
        mock_classifier.classify_email.return_value = "Santé"

        response = api_client.post(
            "/api/v1/classify-and-move", json=_move_payload("gmail"), headers=_auth_headers()
        )

        assert response.status_code == 200
        gmail_cls.assert_called_once()
        imap_cls.assert_not_called()

    def test_failed_move_is_reported(self, api_client, mock_classifier, move_env):
        provider, _, _, pending_file = move_env
        mock_classifier.classify_email.return_value = "Santé"
        provider.batch_move_emails.side_effect = ConnectionError("down")

        response = api_client.post("/api/v1/classify-and-move", json=_move_payload(), headers=_auth_headers())

        assert response.json()["moved"] is False
        assert response.json()["error"] == "Move failed"
        assert not pending_file.exists()

    def test_legacy_labels_field_is_ignored(self, api_client, mock_classifier, move_env):
        mock_classifier.classify_email.return_value = "Santé"

        classify = api_client.post(
            "/api/v1/classify", json=_sample_email() | {"labels": ["INBOX"]}, headers=_auth_headers()
        )
        move = api_client.post(
            "/api/v1/classify-and-move", json=_move_payload(labels=["INBOX"]), headers=_auth_headers()
        )

        assert classify.status_code == 200
        assert move.status_code == 200
```

Add `import json` at the top of the test file. Keep `test_classify_and_move_disabled` and `test_classify_and_move_invalid_provider`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_webhook_api.py -q`
Expected: the new tests FAIL (`AttributeError: ... has no attribute 'GmailApiService'` / `pending_archive_path`).

- [ ] **Step 3: Rewrite `src/mailtag/api/dependencies.py`**

```python
"""Shared application state for the MailTag webhook server."""

import time

from loguru import logger

from mailtag.classifier import Classifier
from mailtag.config import CONFIG


class AppState:
    """Shared application state initialized during FastAPI lifespan."""

    def __init__(self):
        self.start_time = time.time()
        self.classifier: Classifier | None = None

    def initialize(self) -> None:
        """Build the classifier (called during FastAPI lifespan startup).

        Nothing needs flushing at shutdown: the taxonomy store saves itself after each batch.
        """
        logger.info("Initializing classifier...")
        self.classifier = Classifier(CONFIG, None)
        logger.info("Classifier ready with {} categories", len(self.classifier.categories))

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time


app_state = AppState()
```

- [ ] **Step 4: Rewrite `src/mailtag/api/routes/classify.py`**

```python
"""Email classification endpoints."""

import imaplib
from datetime import date

from fastapi import APIRouter, HTTPException
from loguru import logger

from mailtag.config import CONFIG
from mailtag.gmail_api import GmailApiService
from mailtag.imap_service import ImapService
from mailtag.models import Email
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders
from mailtag.taxonomy import REVIEW
from mailtag.utils.tasks import pending_archive_path

from ..dependencies import app_state
from ..schemas import (
    ClassifyAndMoveRequest,
    ClassifyAndMoveResponse,
    ClassifyBatchRequest,
    ClassifyBatchResponse,
    ClassifyRequest,
    ClassifyResponse,
    ErrorResponse,
)

router = APIRouter()


def _to_email(req: ClassifyRequest) -> Email:
    """Convert API request to internal Email model."""
    return Email(
        msg_id=req.msg_id,
        subject=req.subject,
        sender_address=req.sender_address,
        sender_name=req.sender_name,
        body=req.body,
    )


def _provider(name: str) -> ImapService:
    if name == "gmail":
        return GmailApiService(CONFIG.gmail, CONFIG.fast_parse)
    return ImapService(CONFIG.imap, CONFIG.fast_parse)


@router.post(
    "/classify",
    response_model=ClassifyResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        503: {"model": ErrorResponse, "description": "Classifier not yet initialized"},
    },
    summary="Classify a single email",
)
def classify_email(request: ClassifyRequest):
    """Classify a single email into one of the 19 taxonomy categories (or `5-A revoir`).

    The email is not moved — use `/classify-and-move` to file it.

    **N8N usage**: Send a POST with the email fields from your trigger node.
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    category = app_state.classifier.classify_email(_to_email(request))
    return ClassifyResponse(msg_id=request.msg_id, category=category)


@router.post(
    "/classify-batch",
    response_model=ClassifyBatchResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Batch size exceeds maximum"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        503: {"model": ErrorResponse, "description": "Classifier not yet initialized"},
    },
    summary="Classify a batch of emails",
)
def classify_batch(request: ClassifyBatchRequest):
    """Classify multiple emails in a single request (batched embeddings and LLM prompts).

    Limited to `max_batch_size` emails per request (default: 50, configured in config.toml).
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    max_batch = CONFIG.webhook.max_batch_size
    if len(request.emails) > max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(request.emails)} exceeds maximum of {max_batch}",
        )

    emails = [_to_email(req) for req in request.emails]
    categories = app_state.classifier.classify_emails_batch(emails)
    results = [
        ClassifyResponse(msg_id=email.msg_id, category=category)
        for email, category in zip(emails, categories, strict=True)
    ]
    return ClassifyBatchResponse(
        results=results,
        total=len(results),
        classified=sum(1 for r in results if r.category != REVIEW),
    )


@router.post(
    "/classify-and-move",
    response_model=ClassifyAndMoveResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid provider"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        403: {"model": ErrorResponse, "description": "Move operations disabled"},
        503: {"model": ErrorResponse, "description": "Classifier not yet initialized"},
    },
    summary="Classify and move an email",
)
def classify_and_move(request: ClassifyAndMoveRequest):
    """Classify an INBOX email and move it to its action folder, like `run` does.

    Its category is recorded in the account's pending archive (by `message_id`), so the
    archive sweep later files it into its category, or learns from it if it went to review.
    `msg_id` must be the email's UID in the account's INBOX.
    """
    if not app_state.classifier:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    if not CONFIG.webhook.allow_move:
        raise HTTPException(status_code=403, detail="Move operations are disabled")

    email = Email(
        msg_id=request.msg_id,
        subject=request.subject,
        sender_address=request.sender_address,
        sender_name=request.sender_name,
        body=request.body,
        message_id=request.message_id,
        has_unsubscribe=request.has_unsubscribe,
        is_bulk=request.is_bulk,
    )
    category = app_state.classifier.classify_email(email)

    provider = _provider(request.provider)
    pending = PendingArchive(pending_archive_path(provider.config, CONFIG.taxonomy.pending_archive_file))
    try:
        with provider.connect():
            provider.client.select_folder("INBOX")
            moved = route_to_action_folders(
                provider, pending, [RoutedMail.from_email(email, category)], False, date.today()
            )
    except (imaplib.IMAP4.error, ConnectionError, RuntimeError, OSError) as e:
        logger.error("Failed to move email {}: {}", request.msg_id, e)
        return ClassifyAndMoveResponse(msg_id=request.msg_id, category=category, moved=False, error=str(e))

    return ClassifyAndMoveResponse(
        msg_id=request.msg_id,
        category=category,
        moved=moved == 1,
        error=None if moved else "Move failed",
    )
```

- [ ] **Step 5: Schemas, health, app factory**

`src/mailtag/api/schemas.py`:
- delete the `labels` field and `"labels": ["INBOX"]` example lines from `ClassifyRequest` and `ClassifyAndMoveRequest`;
- replace example categories `"Finance/Invoices"` with `"Banque & Placements"`;
- add to `ClassifyAndMoveRequest` (after `body`):

```python
    message_id: str = Field(default="", description="Message-ID header; needed to archive the email later")
    has_unsubscribe: bool = Field(default=False, description="The email has a List-Unsubscribe header")
    is_bulk: bool = Field(default=False, description="The email has Precedence: bulk/list")
```

- delete `database_loaded` from `HealthResponse` and `StatusResponse`.

`src/mailtag/api/routes/health.py`: delete both `database_loaded=...` lines.

`src/mailtag/api/__init__.py`:
- in `lifespan`, delete `app_state.shutdown()` (keep the log line);
- replace the `classification` tag description with `"Email classification into the 19-category taxonomy: rules (validated sender, learned sender, domain), then nomic embeddings and the Gemma LLM."`;
- replace the `## Classification Strategy (AMSC)` section of `DESCRIPTION` (heading, sentence and table) with:

```markdown
## Classification

Rules first (validated sender, learned sender, validated domain, computed domain), then
nomic embeddings above the threshold, else nomic and the Gemma LLM must agree. Anything else
goes to `5-A revoir`. Without MLX (Docker), only the rules run.
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_webhook_api.py -q && uv run pytest -q && uv run ruff check .`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
rtk git add -A src/mailtag/api tests/test_webhook_api.py
rtk git commit -m "refactor(api): taxonomy-only webhook, classify-and-move through action folders

Gmail requests use GmailApiService; /classify-and-move records the pending
archive entry like run does.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: `Classifier` taxonomy-only, `Email.labels` removed

**Files:**
- Modify: `src/mailtag/classifier.py` (full content below)
- Modify: `src/mailtag/models.py`, `src/mailtag/imap_service.py` (`_process_full_emails`, `get_full_emails`)
- Modify: `src/mailtag/utils/tasks.py`, `src/mailtag/api/dependencies.py` (constructor call), `scripts/eval_embeddings.py:663-666`
- Test: `tests/test_classifier_taxonomy.py`, `tests/test_imap_service.py`

**Interfaces:**
- Produces: `Classifier(config: AppConfig, read_only: bool = False)` with `categories`, `taxonomy_store`, `classify_email`, `classify_emails_batch`, `_classify_uncertain_detailed`, `_nomic_top`, `_llm_categories`, `_rule_category`, `_embeddings_path`. `Email` has no `labels`.

- [ ] **Step 1: Write the failing test**

In `tests/test_classifier_taxonomy.py`: delete the `db` fixture, `test_labels_are_ignored_in_taxonomy_mode`, `test_no_suggestion_db_writes_in_taxonomy_mode`, and the `from mailtag.database import ...` / `from collections import defaultdict` imports; drop the `labels` parameter from `mail()`; replace every `Classifier(config=_config(tmp_path), database=db...)` by `Classifier(config=_config(tmp_path)...)` (keeping `read_only=True` where present); remove `db` from test parameters and `db.get_dominant_classification.assert_not_called()`. Add:

```python
def test_classifier_needs_no_database(tmp_path):
    classifier = Classifier(_config(tmp_path))

    assert classifier.categories == list(TAXONOMY)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_classifier_taxonomy.py -q`
Expected: FAIL with `TypeError: Classifier.__init__() missing 1 required positional argument: 'database'`.

- [ ] **Step 3: Rewrite `src/mailtag/classifier.py`**

```python
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from .config import AppConfig
from .models import Email
from .taxonomy import (
    REVIEW,
    TAXONOMY,
    llm_email_part,
    llm_static_prompt,
    nomic_text,
    parse_category_number,
    to_category,
)
from .taxonomy_store import TaxonomyStore, normalize_address
from .utils.text_utils import smart_truncate

if TYPE_CHECKING:
    from .mlx_provider import MLXLLM, MLXEmbedder
    from .semantic_router import SemanticRouter


class Classifier:
    """Classifies emails into the 19-category taxonomy.

    Rules first (validated sender, learned sender, domain), then nomic embeddings above the
    threshold, else nomic and the LLM must agree; anything else goes to review.
    """

    def __init__(self, config: AppConfig, read_only: bool = False):
        self.config = config
        self._mlx_lock = threading.RLock()  # Reentrant lock for MLX initialization

        # MLX components (lazy loaded)
        self._embedder: MLXEmbedder | None = None
        self._semantic_router: SemanticRouter | None = None
        self._mlx_llm: MLXLLM | None = None
        self._mlx_initialized = False

        self.categories = list(TAXONOMY)
        self._own_addresses = {normalize_address(a) for a in config.taxonomy.own_addresses}
        self.taxonomy_store = TaxonomyStore(
            Path(config.taxonomy.taxonomy_db_dir),
            min_agreements=config.taxonomy.learn_min_agreements,
            read_only=read_only,
        )
        logger.info(f"Using the {len(self.categories)}-category taxonomy")

    def _embeddings_path(self) -> Path:
        """The 19 real-mail centroids."""
        return Path(self.config.taxonomy.centroids_file)
```

Then copy unchanged from the current file, in this order: `_init_mlx_components` (current lines 89-149; in it, replace the "Run 'python scripts/build_category_embeddings.py' to generate." message by "Run 'python scripts/taxonomy_setup.py build' to generate."), `_truncate_body` (281-293), `_rule_category`, `_nomic_top`, `_llm_categories`, `_classify_uncertain_detailed`, `_classify_batch_taxonomy` (the block after `# --- Taxonomy mode ...`, current lines ~842-927, **without** `_classify_uncertain`). Rename `_classify_batch_taxonomy`'s docstring to `"""Rules first, then the nomic/LLM chain; agreements teach the sender rules."""`. Then add:

```python
    def classify_email(self, email: Email) -> str:
        return self._classify_batch_taxonomy([email])[0]

    def classify_emails_batch(self, emails: list[Email]) -> list[str]:
        """One category per email, batching embeddings and LLM prompts."""
        return self._classify_batch_taxonomy(emails)
```

Everything else in the old file goes (legacy signals, AI cache, proposals, litellm, `export_metrics`, `log_metrics_summary`, `_classify_uncertain`).

- [ ] **Step 4: Update the callers**

- `src/mailtag/utils/tasks.py`: `classifier = Classifier(CONFIG, read_only=validate)`.
- `src/mailtag/api/dependencies.py`: `self.classifier = Classifier(CONFIG)`.
- `scripts/eval_embeddings.py` (`chain_eval`, ~line 663): replace the `config = dataclasses.replace(...)` line and the `Classifier(config, ClassificationDatabase(...))` statement by `classifier = Classifier(CONFIG, read_only=True)`; replace `classifier._classify_uncertain(emails)` (if present in the file) by `[c for c, _ in classifier._classify_uncertain_detailed(emails)]`. Leave the rest of the script to Task 11.
- `src/mailtag/models.py`: delete the `labels` line and the now-unused `Field` import.
- `src/mailtag/imap_service.py`: in `_process_full_emails` delete the `labels = [...]` statement and the `labels=labels,` argument; in `get_full_emails` replace the fetch command block with `fetch_command = [b"BODY.PEEK[]"]`.
- `tests/test_imap_service.py`: delete assertions or tests about `X-GM-LABELS` / `labels` (`grep -n "labels\|X-GM" tests/test_imap_service.py tests/test_gmail_api.py`).

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q && uv run ruff check .`
Expected: `tests/test_classifier.py`, `tests/test_ai_confidence.py`, `tests/test_classification_metrics.py` fail (legacy-only): delete these three files. Re-run: pass.

- [ ] **Step 6: Commit**

```bash
rtk git add -A src/mailtag/classifier.py src/mailtag/models.py src/mailtag/imap_service.py src/mailtag/utils/tasks.py src/mailtag/api/dependencies.py scripts/eval_embeddings.py tests/
rtk git commit -m "refactor(classifier): taxonomy-only classifier, no database, no labels

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Configuration without legacy sections and folder cache

**Files:**
- Modify: `src/mailtag/config.py`
- Modify: `config.toml`, `.env.example`
- Modify: `src/mailtag/imap_service.py` (folder cache), `src/mailtag/gmail_api.py:233` (docstring)
- Modify: `scripts/taxonomy_setup.py:48-55` (`migration_blocked`)
- Test: `tests/test_config.py`, `tests/test_taxonomy_setup.py`, `tests/test_tasks_accounts.py`, `tests/test_run_classification.py`, `tests/test_classifier_taxonomy.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `AppConfig(logging, imap, gmail, fast_parse, mlx, webhook=None, taxonomy=None)`. `ImapConfig(host, user, password, pending_archive_file=None, junk_folder_name=None)`. `GmailConfig(credentials_file, token_file, pending_archive_file="db/pending_archive_gmail.json", junk_folder_name="SPAM")`. `FastParseConfig(batch_size=500, junk_folder_name="Junk", metrics_enabled=True, metrics_log_level="DEBUG", metrics_log_interval_minutes=10)` (metrics fields go in Task 13). `TaxonomyConfig` without `enabled`. `migration_blocked(cfg)` checks only the rule files.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_old_sections_are_ignored(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("IMAP_USER", "me@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
ollama_model = "x"
[classifier]
min_count = 5
[logging]
level = "INFO"
file = "logs/mailtag.log"
[imap]
host = "mail.example.com"
use_gmail_extensions = false
[gmail]
credentials_file = "c.json"
token_file = "t.json"
folder_cache_file = "data/gmail_labels.json"
[fast_parse]
folder_cache_ttl_hours = 24
unclassified_folder_name = "Unclassified"
[taxonomy]
enabled = true
nomic_threshold = 0.7
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.imap.user == "me@example.com"
    assert cfg.gmail.junk_folder_name == "SPAM"
    assert cfg.taxonomy.nomic_threshold == 0.7
    assert not hasattr(cfg, "general")
```

In `tests/test_taxonomy_setup.py`, delete the "disabled" test at lines ~56-66 and change `TaxonomyConfig(enabled=True, taxonomy_db_dir=...)` to `TaxonomyConfig(taxonomy_db_dir=...)`. In `tests/test_tasks_accounts.py`, delete `test_gmail_never_writes_the_infomaniak_folder_cache`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py::test_old_sections_are_ignored tests/test_taxonomy_setup.py -q`
Expected: FAIL (`MODEL not found` / `KeyError: 'classifier'`; `TaxonomyConfig` rejects nothing yet but `hasattr(cfg, "general")` is true).

- [ ] **Step 3: Rewrite the dataclasses in `src/mailtag/config.py`**

Delete `GeneralConfig` and `ClassifierConfig`. Replace `ImapConfig`, `GmailConfig`, `FastParseConfig`, `AppConfig` with:

```python
@dataclass
class ImapConfig:
    host: str
    user: str
    password: str
    # Per-account overrides (the Gmail account sets them; None = the global setting)
    pending_archive_file: str | None = None
    junk_folder_name: str | None = None


@dataclass
class GmailConfig:
    credentials_file: str
    token_file: str
    # Gmail through the API (docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md)
    pending_archive_file: str | None = "db/pending_archive_gmail.json"
    junk_folder_name: str | None = "SPAM"


@dataclass
class FastParseConfig:
    batch_size: int = 500
    junk_folder_name: str = "Junk"
    metrics_enabled: bool = True
    metrics_log_level: str = "DEBUG"
    metrics_log_interval_minutes: int = 10
```

```python
@dataclass
class AppConfig:
    logging: LoggingConfig
    imap: ImapConfig
    gmail: GmailConfig
    fast_parse: FastParseConfig
    mlx: MLXConfig
    webhook: WebhookConfig = None  # type: ignore[assignment]
    taxonomy: TaxonomyConfig = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.webhook is None:
            self.webhook = WebhookConfig()
        if self.taxonomy is None:
            self.taxonomy = TaxonomyConfig()
```

In `TaxonomyConfig`, delete `enabled: bool = False` and change the docstring to `"""19-category taxonomy with action folders (see docs/superpowers/specs/2026-09-27-*)."""` (unchanged text, `enabled` line gone).

- [ ] **Step 4: Rewrite `load_config` and `_validate_config`**

Add `import dataclasses` at the top. Replace `load_config` and `_validate_config` with:

```python
def load_config(path: Path) -> AppConfig:
    """Loads the application configuration from a TOML file (unknown keys are ignored)."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)

        imap_user = os.getenv("IMAP_USER", data["imap"].get("user"))
        if not imap_user:
            raise ValueError("IMAP_USER not found in environment or config file.")
        imap_password = os.getenv("IMAP_PASSWORD", data["imap"].get("password"))
        if not imap_password:
            raise ValueError("IMAP_PASSWORD not found in environment or config file.")

        mlx_config = _dataclass_from_dict(MLXConfig, data.get("mlx", {}))
        # Allow MLX_ENABLED env var to override config (for Docker/non-Apple-Silicon)
        mlx_enabled_env = os.getenv("MLX_ENABLED")
        if mlx_enabled_env is not None:
            mlx_config = dataclasses.replace(
                mlx_config, enabled=mlx_enabled_env.lower() in ("true", "1", "yes")
            )

        webhook_config = _dataclass_from_dict(WebhookConfig, data.get("webhook", {}))
        webhook_api_key = os.getenv("WEBHOOK_API_KEY", webhook_config.api_key)
        if webhook_api_key.startswith("${"):
            webhook_api_key = ""
        webhook_config = dataclasses.replace(webhook_config, api_key=webhook_api_key)

        return AppConfig(
            logging=LoggingConfig(level=data["logging"]["level"], file=data["logging"]["file"]),
            imap=ImapConfig(host=data["imap"]["host"], user=imap_user, password=imap_password),
            gmail=_dataclass_from_dict(GmailConfig, data["gmail"]),
            fast_parse=_dataclass_from_dict(FastParseConfig, data.get("fast_parse", {})),
            mlx=mlx_config,
            webhook=webhook_config,
            taxonomy=_dataclass_from_dict(TaxonomyConfig, data.get("taxonomy", {})),
        )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError, ValueError) as e:
        raise RuntimeError(f"Failed to load or parse config file: {e}") from e


def _validate_config(config: AppConfig) -> None:
    """Validate configuration values.

    Raises:
        ValueError: If any configuration value is invalid
    """
    import re

    # Check email format. Skip unsubstituted template placeholders like
    # ${IMAP_USER} (e.g. in CI where the env var is unset).
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not config.imap.user.startswith("${") and not re.match(email_regex, config.imap.user):
        raise ValueError(f"Invalid email format: {config.imap.user}")

    if not config.imap.password:
        raise ValueError("IMAP password cannot be empty. Set IMAP_PASSWORD environment variable.")
```

- [ ] **Step 5: Folder cache, `migration_blocked`, config files**

- `src/mailtag/imap_service.py`: delete `self.folder_cache_path = ...` and the whole `get_folder_hierarchy` method; remove imports it alone used (`json`, `datetime`, `timedelta`, `Path` if unused — let `ruff check --fix` report).
- `src/mailtag/gmail_api.py`: in the `GmailApiService` docstring remove `` `get_folder_hierarchy` `` from the inherited-methods list.
- `scripts/taxonomy_setup.py` `migration_blocked`: delete the two `if not cfg.enabled:` lines.
- `config.toml`: delete the `[general]` and `[classifier]` sections (with their comments), the `enabled = true` line under `[taxonomy]` (and its comment line if any), `folder_cache_file` and `use_gmail_extensions` under `[gmail]` (and the comment words "and folder cache (never overwrite Infomaniak's data/imap_folders.json; …)" — rewrite that comment to `# This account's own pending-archive file and junk label (the Gmail sweep never treats Infomaniak's mail as orphans).`), and under `[fast_parse]` delete `folder_cache_ttl_hours`, `unclassified_folder_name`, `max_retries`, `retry_delay`, `retry_backoff`, `retry_jitter` with their comments.
- `.env.example`: delete the whole "REQUIRED: AI Model Configuration" section (Ollama, Gemini, OpenRouter options) and the `LITELLM_TIMEOUT` and CrewAI lines; in NOTES delete item 4 (Ollama) and renumber.

- [ ] **Step 6: Update test configs**

In `tests/test_run_classification.py`, `tests/test_classifier_taxonomy.py`, `tests/test_main.py` (if it builds an `AppConfig`), `tests/test_webhook_api.py`: remove `general=...` and `classifier=...` arguments, `GeneralConfig`/`ClassifierConfig` imports, and `enabled=True` from `TaxonomyConfig(...)`. In `tests/test_config.py`, delete every test that asserts on `general`, `classifier`, `MODEL`, `MODEL_NAME`, `OLLAMA_API_URL`, `API_BASE`, `api_base`, thresholds, `use_gmail_extensions`, `folder_cache_file`, or `taxonomy.enabled` (`grep -n "general\|classifier\|MODEL\|api_base\|API_BASE\|threshold\|folder_cache\|gmail_extensions\|enabled is True" tests/test_config.py`); keep the IMAP user/password, MLX_ENABLED, webhook and taxonomy-values tests, adjusting their TOML fixtures to drop the removed sections.

- [ ] **Step 7: Run tests**

Run: `uv run pytest -q && uv run ruff check . && uv run python -c "import sys; sys.path.insert(0, 'src'); from mailtag.config import CONFIG; print(CONFIG.taxonomy.nomic_threshold)"`
Expected: pass; the last command prints the configured threshold (loads the real `config.toml` and `.env`).

- [ ] **Step 8: Commit**

```bash
rtk git add -A src/mailtag/config.py src/mailtag/imap_service.py src/mailtag/gmail_api.py scripts/taxonomy_setup.py config.toml .env.example tests/
rtk git commit -m "refactor(config): drop legacy sections, taxonomy flag and folder cache

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: Delete legacy files and check the real runs

**Files:**
- Delete: `src/mailtag/database.py`, `src/mailtag/folder_analyzer.py`, `src/mailtag/filter_generator.py`, `src/mailtag/gmail_service.py`, `src/mailtag/providers.py`, `src/streamlit_app.py`, `src/mailtag/utils/domain_analyzer.py`, `src/mailtag/utils/data_cleanup.py`, `src/mailtag/utils/data_validation.py`, `scripts/build_category_embeddings.py`, `scripts/build_domain_database.py`, `scripts/update_domain_db.py`, `scripts/check_duplicates.py`, `scripts/inject_filters.py`
- Delete tests: `tests/test_database.py`, `tests/test_filter_generator.py`, `tests/test_domain_analyzer.py`, `tests/test_data_cleanup.py`, `tests/test_data_validation.py`, `tests/test_gmail_service.py`, `tests/mock_gmail_service.py`
- Modify: `src/mailtag/imap_service.py` (drop `EmailProvider` base and `get_emails`), `tests/conftest.py` (drop `mock_gmail_service` fixture and import, and the commented litellm fixture), `tests/test_missing_google_deps.py` (drop the `GmailService` test, keep the `gmail_auth` one)

- [ ] **Step 1: Check nothing imports them**

Run:
```bash
grep -rnE "mailtag\.(database|folder_analyzer|filter_generator|gmail_service|providers)|utils\.(domain_analyzer|data_cleanup|data_validation)|ClassificationDatabase|GmailService\b|EmailProvider|streamlit_app" src scripts tests --include='*.py' | grep -vE "^(src/mailtag/(database|folder_analyzer|filter_generator|gmail_service|providers)\.py|src/mailtag/utils/(domain_analyzer|data_cleanup|data_validation)\.py|src/streamlit_app\.py|scripts/(build_category_embeddings|build_domain_database|update_domain_db|check_duplicates|inject_filters)\.py|tests/test_(database|filter_generator|domain_analyzer|data_cleanup|data_validation|gmail_service)\.py|tests/mock_gmail_service\.py)"
```
Expected: only `src/mailtag/imap_service.py` (`EmailProvider`), `tests/conftest.py`, `tests/test_missing_google_deps.py`. Anything else: fix that caller first.

- [ ] **Step 2: Delete and edit**

```bash
git rm src/mailtag/database.py src/mailtag/folder_analyzer.py src/mailtag/filter_generator.py \
  src/mailtag/gmail_service.py src/mailtag/providers.py src/streamlit_app.py \
  src/mailtag/utils/domain_analyzer.py src/mailtag/utils/data_cleanup.py src/mailtag/utils/data_validation.py \
  scripts/build_category_embeddings.py scripts/build_domain_database.py scripts/update_domain_db.py \
  scripts/check_duplicates.py scripts/inject_filters.py \
  tests/test_database.py tests/test_filter_generator.py tests/test_domain_analyzer.py \
  tests/test_data_cleanup.py tests/test_data_validation.py tests/test_gmail_service.py tests/mock_gmail_service.py
```

In `src/mailtag/imap_service.py`: `class ImapService:` (no base), delete the `from mailtag.providers import EmailProvider` import and the `get_emails` method. Edit `tests/conftest.py` and `tests/test_missing_google_deps.py` as listed above.

- [ ] **Step 3: Run tests**

Run: `uv run pytest -q && uv run ruff check .`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor: delete legacy modules, scripts and tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Live read-only check (ask the owner first)**

Ask the owner: "OK to run `run --validate` on both accounts now (read-only; no `migrate --apply` running)?" Only on yes:

```bash
stat -f "%m %N" db/taxonomy/*.json db/pending_archive*.json > /tmp/claude-before.txt
uv run python src/main.py run --provider imap --validate
uv run python src/main.py run --provider gmail --validate
stat -f "%m %N" db/taxonomy/*.json db/pending_archive*.json | diff /tmp/claude-before.txt -
```
Expected: both runs end with `Analysis complete.`; the `diff` prints nothing. (Use the session scratchpad directory instead of `/tmp` for the stat file.)

- [ ] **Step 6: Open PR B**

Push and open "Taxonomy-only cleanup B: remove the legacy core" with a body listing Tasks 4-9, the live check result, and `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

## PR C — Docker rules-only

### Task 10: Docker without litellm

**Files:**
- Modify: `config.docker.toml`, `pyproject.toml` (drop `litellm`), `docker-compose.yml` (comments only, if they mention a cloud model)
- Test: `tests/test_classifier_taxonomy.py`

- [ ] **Step 1: Write the test**

```python
def test_without_mlx_uncovered_mail_goes_to_review(tmp_path, mocker):
    network = mocker.patch("socket.socket.connect", side_effect=AssertionError("no network"))
    classifier = Classifier(_config(tmp_path))  # MLXConfig(enabled=False)

    assert classifier.classify_emails_batch([mail(sender="new@unknown.ch")]) == [REVIEW]
    network.assert_not_called()
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_classifier_taxonomy.py::test_without_mlx_uncovered_mail_goes_to_review -q`
Expected: PASS (characterization; Task 7 already removed litellm from the classifier).

- [ ] **Step 3: Rewrite `config.docker.toml`**

```toml
# Docker container configuration for MailTag API.
# Copy to config.toml or mount as a volume.
#
# MLX needs Apple Silicon, so the container classifies by rules only
# (validated sender, learned sender, domain); everything else goes to "5-A revoir".
# The rules live in db/taxonomy/ (mount db/). Do not run `serve` in Docker while a
# `run` works on the Mac: the file lock does not cross the Docker Desktop VM.
#
# All ${VAR} placeholders are resolved from environment variables.

[logging]
level = "INFO"
file = "logs/mailtag.log"

[imap]
host = "${IMAP_HOST}"
user = "${IMAP_USER}"
password = "${IMAP_PASSWORD}"

[gmail]
credentials_file = "secrets/credentials.json"
token_file = "secrets/token.json"
pending_archive_file = "db/pending_archive_gmail.json"
junk_folder_name = "SPAM"

[fast_parse]
batch_size = 500
junk_folder_name = "Junk"

[mlx]
enabled = false

[taxonomy]
archive_after_days = 7
pending_archive_file = "db/pending_archive.json"
taxonomy_db_dir = "db/taxonomy"

[webhook]
# Bind to all interfaces inside the container
host = "0.0.0.0"
port = 8000
api_key = "${WEBHOOK_API_KEY}"
allow_move = true
max_batch_size = 50
```

Copy `own_addresses` from the `[taxonomy]` section of `config.toml` as a commented example line: `# own_addresses = ["me@example.com"]`.

- [ ] **Step 4: Drop litellm**

In `pyproject.toml` delete the two lines `# Cloud/Ollama AI fallback (...)` and `"litellm>=1.93.0",`. Run `uv lock` then `grep -rn litellm src scripts tests Dockerfile docker-compose.yml`.
Expected: no match (the `tests/conftest.py` comment block was removed in Task 9).

- [ ] **Step 5: Build check**

Run: `uv run pytest -q && docker compose build` (skip the build if Docker is not running; say so in the PR).
Expected: pass; image builds.

- [ ] **Step 6: Commit and open PR C**

```bash
rtk git add config.docker.toml pyproject.toml uv.lock tests/test_classifier_taxonomy.py docker-compose.yml
rtk git commit -m "refactor(docker): rules-only container, drop litellm

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## PR D — Dead code and dependencies

### Task 11: `eval_embeddings.py` keeps only `chain`

**Files:**
- Modify: `scripts/eval_embeddings.py`
- Test: `tests/test_eval_embeddings.py`

**Interfaces:**
- Produces: script with `chain_eval` and its helpers `leave_sender_out_top`, `threshold_sweep`, `best_threshold`, `chain_metrics`, and a CLI with the `chain` mode only.

- [ ] **Step 1: Trim the tests**

In `tests/test_eval_embeddings.py`, delete the tests of `score`, `coverage_at_precision`, `knn_*`, `centroid_sims_leave_sender_out` (lines ~7-90 and their imports). Keep the tests of the four kept helpers.

- [ ] **Step 2: Trim the script**

Delete the `collect`, `evaluate`, `tune`, `gemma` and `taxonomy` modes and every function only they call: `score`, `coverage_at_precision`, `centroid_sims_leave_sender_out`, `knn_*`, `category_examples`, `encode_cached`, `query_text`, and anything using `MLXLLM.classify`, `_build_llm_prompt_prefix`, `data/imap_folders.json` or `ClassificationDatabase`. Keep the argument parser with the `chain` subcommand only. Remove imports ruff reports unused.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/test_eval_embeddings.py -q && uv run ruff check scripts/eval_embeddings.py && uv run python scripts/eval_embeddings.py --help`
Expected: pass; help lists only `chain`. `grep -nE "classify\(|imap_folders|ClassificationDatabase|_build_llm_prompt_prefix" scripts/eval_embeddings.py` prints nothing.

- [ ] **Step 4: Commit**

```bash
rtk git add scripts/eval_embeddings.py tests/test_eval_embeddings.py
rtk git commit -m "refactor(eval): keep only the chain measurement

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: Trim `semantic_router.py` and `mlx_provider.py`

**Files:**
- Modify: `src/mailtag/semantic_router.py`, `src/mailtag/mlx_provider.py`, `src/mailtag/classifier.py` (`_init_mlx_components`), `src/mailtag/taxonomy_build.py:175`, `scripts/taxonomy_setup.py:109,229`, `src/mailtag/config.py` (`MLXConfig`), `config.toml` (`[mlx]`)
- Test: `tests/test_semantic_router.py`, `tests/test_mlx_provider.py`

**Interfaces:**
- Produces: `SemanticRouter(embedder)` with `load_embeddings`, `save_embeddings`, `_build_embedding_matrix`, `build_from_examples`, `top_batch`, `num_categories`. `MLXEmbedder(model_name)` with `model`, `encode`, `encode_documents`. `MLXLLM(model_name)` with `model`, `tokenizer`, `classify_batch`. `MLXConfig(enabled=True, embedding_model=..., llm_model=...)`.

- [ ] **Step 1: Trim the tests**

In `tests/test_semantic_router.py` delete tests of `route`, `route_batch`, `route_with_alternatives`, `add_category`, `remove_category`, `get_category_info`, `build_from_validated_db`, `score_threshold`. In `tests/test_mlx_provider.py` delete tests of `encode_query`, `similarity`, `generate`, `classify` (not `classify_batch`), `get_embedder`, `get_llm`, `max_tokens`/`temperature`. Replace `SemanticRouter(embedder, score_threshold=...)` and `MLXLLM(name, max_tokens=..., temperature=...)` in the remaining tests by `SemanticRouter(embedder)` / `MLXLLM(name)`.

- [ ] **Step 2: Run the trimmed tests**

Run: `uv run pytest tests/test_semantic_router.py tests/test_mlx_provider.py -q`
Expected: pass (the constructors have defaults today). They are the guard for Step 3: they must still pass after the trim.

- [ ] **Step 3: Trim the modules**

- `semantic_router.py`: delete `build_from_validated_db`, `route`, `route_batch`, `route_with_alternatives`, `add_category`, `remove_category`, `get_category_info`; constructor becomes `def __init__(self, embedder: MLXEmbedder):` without `self.score_threshold`; its log line becomes `logger.info("SemanticRouter initialized")`.
- `mlx_provider.py`: delete `MLXEmbedder.encode_query`, `MLXEmbedder.similarity`, `MLXLLM.generate`, `MLXLLM.classify`, `get_embedder`, `get_llm`; `MLXLLM.__init__(self, model_name: str = "mlx-community/gemma-4-e4b-it-OptiQ-4bit")` without `max_tokens`, `temperature`, `_generate_fn`, `_sampler`; `_load_model` keeps only `from mlx_lm import load` and `self._model, self._tokenizer = load(self.model_name)`. Update the module docstring: `MLXLLM: answers short prompts in batches (Signal 6)`.
- `classifier.py` `_init_mlx_components`: `SemanticRouter(self._embedder)` and `MLXLLM(model_name=self.config.mlx.llm_model)`.
- `taxonomy_build.py:175`: `SemanticRouter(embedder)`.
- `scripts/taxonomy_setup.py:109,229`: `MLXLLM(CONFIG.mlx.llm_model)`.
- `config.py` `MLXConfig`: keep only `enabled`, `embedding_model`, `llm_model` (with their comments).
- `config.toml` `[mlx]`: delete `score_threshold`, `embeddings_file`, `llm_confidence`, `llm_max_tokens`, `llm_temperature` if present.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q && uv run ruff check .`
Expected: pass. `grep -rnE "score_threshold|llm_max_tokens|llm_temperature|encode_query|\.generate\(" src scripts tests` prints nothing.

- [ ] **Step 5: Commit**

```bash
rtk git add -A src scripts tests config.toml
rtk git commit -m "refactor(mlx): keep only what the taxonomy chain uses

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Remove metrics and dead IMAP methods

**Files:**
- Delete: `src/mailtag/metrics.py`
- Modify: `src/mailtag/imap_service.py`, `src/mailtag/gmail_api.py` (`connect`), `src/mailtag/config.py` (`FastParseConfig`), `config.toml` (`[fast_parse]`)
- Test: `tests/test_imap_service.py`, `tests/test_mailbox_scan.py`, `tests/test_migration.py`, `tests/test_tasks_accounts.py`, `tests/test_gmail_api.py`, `tests/test_run_classification.py`

**Interfaces:**
- Produces: `FastParseConfig(batch_size=500, junk_folder_name="Junk")`. `ImapService` without `is_connected`, `get_email_senders`, `_move_email_to_folder`, metrics thread.

- [ ] **Step 1: Update tests (they fail)**

Replace every `FastParseConfig(metrics_enabled=False)` by `FastParseConfig()` and `FastParseConfig(junk_folder_name="Junk", metrics_enabled=False)` by `FastParseConfig(junk_folder_name="Junk")`, and `FastParseConfig(batch_size=100, metrics_enabled=False)` by `FastParseConfig(batch_size=100)` (`grep -rn "metrics_enabled" tests`). Delete tests of `get_email_senders`, `is_connected`, `_move_email_to_folder` and metrics (`grep -rn "get_email_senders\|is_connected\|_move_email_to_folder\|metrics" tests`).

- [ ] **Step 2: Run the updated tests**

Run: `uv run pytest -q`
Expected: pass (`metrics_enabled` defaults to True today, so dropping the argument changes nothing yet). They guard Step 3.

- [ ] **Step 3: Implement**

- `git rm src/mailtag/metrics.py`.
- `imap_service.py`: delete the `from mailtag.metrics import ...` line, every `@timed(...)` decorator line, `_metrics_stop_event`, `_metrics_thread`, the `configure_metrics(...)` call and the thread start in `__init__`, `_start_metrics_logging_thread`, `_stop_metrics_thread` and its call in `connect`'s `finally`, `is_connected`, `get_email_senders`, `_move_email_to_folder`; remove `threading` and other imports ruff reports unused.
- `gmail_api.py` `GmailApiService.connect`: delete `self._stop_metrics_thread()`.
- `config.py` `FastParseConfig`: delete `metrics_enabled`, `metrics_log_level`, `metrics_log_interval_minutes`.
- `config.toml` `[fast_parse]`: delete the `# Performance metrics configuration` block and its three settings.
- `pyproject.toml`: delete `"psutil>=7.0.0",`.

- [ ] **Step 4: Run tests**

Run: `uv lock && uv run pytest -q && uv run ruff check .`
Expected: pass. `grep -rn "metrics\|psutil" src scripts --include='*.py'` prints nothing.

- [ ] **Step 5: Commit**

```bash
rtk git add -A src tests config.toml pyproject.toml uv.lock
rtk git commit -m "refactor: remove metrics module and dead IMAP methods

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 14: Trim `text_utils.py` and `domain_utils.py`

**Files:**
- Modify: `src/mailtag/utils/text_utils.py`, `src/mailtag/utils/domain_utils.py`
- Test: `tests/test_text_utils.py`, `tests/test_non_commercial_domains.py`

**Interfaces:**
- Produces: `text_utils`: `smart_truncate`, `_remove_signatures` (and private helpers `smart_truncate` calls). `domain_utils`: `extract_domain`, `normalize_domain`, `load_non_commercial_domains`, `is_non_commercial_domain_cached`.

- [ ] **Step 1: Trim the tests**

In `tests/test_text_utils.py` delete tests of `extract_urls`, `count_links`, `has_unsubscribe_link`, `extract_first_n_words`, `clean_whitespace`, `extract_subject_keywords`, `is_likely_automated`. Delete tests of `is_valid_domain`, `is_non_commercial_domain` (uncached), `get_domain_similarity` wherever they are (`grep -rn "is_valid_domain\|get_domain_similarity\|is_non_commercial_domain(" tests`).

- [ ] **Step 2: Trim the modules**

Delete those functions from `text_utils.py` and `domain_utils.py`, after checking each has no caller left: `grep -rnE "extract_urls|count_links|has_unsubscribe_link|extract_first_n_words|clean_whitespace|extract_subject_keywords|is_likely_automated|is_valid_domain|get_domain_similarity|is_non_commercial_domain\(" src scripts` must print only the definitions. Keep any helper `smart_truncate` uses.

- [ ] **Step 3: Run tests**

Run: `uv run pytest -q && uv run ruff check .`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
rtk git add -A src/mailtag/utils tests
rtk git commit -m "refactor(utils): drop unused text and domain helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: Clean `pyproject.toml` dependencies

**Files:**
- Modify: `pyproject.toml`, `uv.lock`

- [ ] **Step 1: Edit dependencies**

In `[project] dependencies`: delete `"pytest-mock>=3.14.1"` (already in `dev`), `"watchdog>=6.0.0"`, `"google>=3.0.0"`, the second `"pydantic>=2.11.7"` (keep `"pydantic==2.11.7"`), `"dotenv>=0.9.9"` (keep `python-dotenv`), `"defusedxml>=0.7.1"`. In `[project.optional-dependencies] gmail`: delete `"google>=3.0.0"`.

- [ ] **Step 2: Check each removed name is not imported**

Run: `grep -rnE "^\s*(import|from) (watchdog|defusedxml|google\b[^.])" src scripts tests` and `grep -rnE "^\s*(import|from) dotenv" src scripts`.
Expected: only `from dotenv import load_dotenv` (provided by `python-dotenv`).

- [ ] **Step 3: Lock and test**

Run: `uv lock && uv sync --all-extras && uv run pytest -q && uv run ruff check .`
Expected: pass.

- [ ] **Step 4: Commit and open PR D**

```bash
rtk git add pyproject.toml uv.lock
rtk git commit -m "build: drop unused and duplicate dependencies

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## PR E — Documentation

### Task 16: Rewrite the docs for one mode

**Files:**
- Modify: `CLAUDE.md`, `src/mailtag/CLAUDE.md`, `src/mailtag/utils/CLAUDE.md`, `scripts/CLAUDE.md`, `tests/CLAUDE.md`, `README.md` (if it describes legacy commands), docs site pages (`ls docs/` and `mkdocs.yml` to find them)

- [ ] **Step 1: Find stale references**

Run: `grep -rnlE "AMSC|6-signal|6 signals|Pass 2|three-pass|Three-Pass|pass3_manual|ClassificationDatabase|sender_classification_db|validated_classification_db|domain_classifications|filter_generator|mailfilter|analyze-domains|db-stats|prune-db|cleanup --consolidate|FolderAnalyzer|imap_folders.json|gmail_labels.json|category_embeddings|build_category_embeddings|litellm|GmailService\b|Server-Side Labels|use_imap_folders|Dynamic vs Static|MODEL=|taxonomy\] enabled|enabled = true" --include='*.md' --include='*.yml' . | grep -v "docs/superpowers/"`
(Specs and plans under `docs/superpowers/` are history: leave them.)

- [ ] **Step 2: Rewrite root `CLAUDE.md`**

- Project Overview: "classifies emails into a 19-category taxonomy" (no 6-signal wording).
- AI Model Configuration: only `[mlx]` (nomic + Gemma); no `.env` MODEL path.
- Running the Application: `run`, `run --validate`, `serve`, `serve --host 0.0.0.0 --reload`, plus the `scripts/taxonomy_setup.py` subcommands already documented.
- Architecture: replace "Multi-Signal Classification Strategy (AMSC)", "Three-Pass Processing System", "Database Layer", "Dynamic vs Static Classification", "Metrics" by one "Classification flow" section: Pass 1 rules (validated sender → learned sender → validated domain → computed domain) on the junk folder and INBOX, Pass 3 nomic ≥ `nomic_threshold` else nomic/Gemma agreement else `5-A revoir`, routing to action folders with a `pending_archive` entry, then the archive sweep. Keep the Taxonomy Mode subsections, renamed "Taxonomy", dropping "(`[taxonomy] enabled = true`)".
- Backups: `db/taxonomy/*.json` and `db/pending_archive*.json`, 10 per file, at the start of each `run`.
- Provider Architecture: `ImapService` and `GmailApiService` only.
- Webhook API: `/classify-and-move` selects INBOX, routes to the action folder and records the pending entry (needs `message_id`); known limitation: `PendingArchive` has no file lock, so an entry `serve` records while a `run` of the same account is in progress can be lost (the mail then stays in its action folder).
- Docker: rules only; no litellm; `config.docker.toml`.
- Configuration: `config.toml` sections `logging`, `imap`, `gmail`, `fast_parse`, `mlx`, `taxonomy`, `webhook`; `.env` holds only `IMAP_USER`, `IMAP_PASSWORD`, `WEBHOOK_API_KEY`.

- [ ] **Step 3: Rewrite the sub-`CLAUDE.md` files and docs site**

Make each module list match the files that exist (`ls src/mailtag src/mailtag/utils scripts tests`). Remove every entry for a deleted file or function.

- [ ] **Step 4: Stale data list for the owner**

Add to the PR E description (not to the repo):

```
Stale runtime files you can delete by hand (nothing reads them any more):
- data/pass3_manual_matching_*.json
- data/category_embeddings.npz, data/mailfilter.xml
- data/imap_folders.json, data/gmail_labels.json
- db/sender_classification_db.json, db/validated_classification_db.json, db/domain_classifications.json
- db/backups/sender_classification_db_*.json, db/backups/validated_classification_db_*.json, db/backups/domain_classifications_*.json
- logs/proposals.log
Keep: data/legacy_folders.json, data/non_commercial_domains.yaml, data/taxonomy_centroids.npz, db/taxonomy/, db/pending_archive*.json
```

- [ ] **Step 5: Verify**

Re-run the Step 1 grep. Expected: no output. Run `uv run pytest -q` (docs changes must not break anything) and, if the docs site uses mkdocs, `uv run --extra docs mkdocs build --strict`.

- [ ] **Step 6: Commit and open PR E**

```bash
rtk git add -A CLAUDE.md src/mailtag/CLAUDE.md src/mailtag/utils/CLAUDE.md scripts/CLAUDE.md tests/CLAUDE.md README.md docs mkdocs.yml
rtk git commit -m "docs: one classification mode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Final check across the branch: `find src scripts -name '*.py' | xargs wc -l | tail -1` and `find tests -name '*.py' | xargs wc -l | tail -1`, compared with 10 702 and 9 826 before; report the difference in PR E.
