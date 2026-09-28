# Gmail as a Second IMAP Account — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `run --provider gmail` classifies new Gmail mail into the 19 taxonomy categories through IMAP, with the same flow as the Infomaniak account.

**Architecture:** A `[gmail_imap]` config section builds a second `ImapConfig`; `main.py` runs an `ImapService` for it. Taxonomy rules (`db/taxonomy/`) are shared; the pending archive, junk folder and folder cache are per account, carried on `ImapConfig`.

**Tech Stack:** Python 3.13, imapclient, click, pytest + pytest-mock, ruff (line length 110).

**Spec:** `docs/superpowers/specs/2026-09-28-gmail-imap-design.md`

## Global Constraints

- Credentials come from `.env`: `GMAIL_IMAP_USER`, `GMAIL_IMAP_PASSWORD`. Never print or log them.
- Section `[gmail_imap]` absent, or user/password missing or still `${...}`: no Gmail account, no error at load.
- Gmail defaults: host `imap.gmail.com`, `use_gmail_extensions = true`, `junk_folder_name = "[Gmail]/Spam"`, `pending_archive_file = "db/pending_archive_gmail.json"`, `folder_cache_file = "data/gmail_folders.json"`.
- Infomaniak account unchanged: `[fast_parse] junk_folder_name`, `[taxonomy] pending_archive_file`, `data/imap_folders.json`.
- The CLI no longer calls the Gmail API provider (`GmailService` file stays, unused).
- No `scan`/`migrate`/`prune` on Gmail. Old Gmail labels are never touched.
- Commits end with the two attribution lines (`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, `Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp`). Never commit `.env`, `.serena/`, `.claude/`, `.mcp.json`, `.rtk/`, `data/`, `db/`, `test.*.log`.

## Review Focus

1. `.env` has the Gmail user but no password (or the reverse): Gmail silently disabled, Infomaniak still runs — test in Task 1.
2. A Gmail run must never overwrite `data/imap_folders.json` (Infomaniak's folder cache) — test in Task 2.
3. Two accounts' pending archives never mix: Gmail's archive sweep must not see Infomaniak entries as orphans — test in Task 2.
4. `--provider all` with no `[gmail_imap]`: runs Infomaniak only, no error — test in Task 3.
5. `[Gmail]/Spam` missing (other UI language): Pass 1 skips it with a warning (existing `_run_fast_parse_on_folder` behaviour) — no new code, checked in the real dry run.

---

### Task 1: Gmail IMAP config

**Files:**
- Modify: `src/mailtag/config.py` (`ImapConfig`, `AppConfig`, `load_config`)
- Modify: `config.toml` (add `[gmail_imap]`), `.env.example` (add the two variables, empty values)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ImapConfig.pending_archive_file: str | None = None`, `ImapConfig.folder_cache_file: str = "data/imap_folders.json"`, `ImapConfig.junk_folder_name: str | None = None`; `AppConfig.gmail_imap: ImapConfig | None = None`; `_load_gmail_imap(data: dict) -> ImapConfig | None`.

- [ ] **Step 1: failing tests** (append to `tests/test_config.py`)

```python
GMAIL_SECTION = """
[gmail_imap]
host = "imap.gmail.com"
user = "${GMAIL_IMAP_USER}"
password = "${GMAIL_IMAP_PASSWORD}"
"""


def test_gmail_imap_reads_env_and_defaults(monkeypatch):
    from mailtag.config import _load_gmail_imap
    import tomllib

    monkeypatch.setenv("GMAIL_IMAP_USER", "me@gmail.com")
    monkeypatch.setenv("GMAIL_IMAP_PASSWORD", "apppassword")
    config = _load_gmail_imap(tomllib.loads(GMAIL_SECTION))

    assert config.host == "imap.gmail.com"
    assert config.user == "me@gmail.com" and config.password == "apppassword"
    assert config.use_gmail_extensions is True
    assert config.junk_folder_name == "[Gmail]/Spam"
    assert config.pending_archive_file == "db/pending_archive_gmail.json"
    assert config.folder_cache_file == "data/gmail_folders.json"


@pytest.mark.parametrize("user,password", [("me@gmail.com", None), (None, "apppassword"), (None, None)])
def test_gmail_imap_without_credentials_is_disabled(monkeypatch, user, password):
    from mailtag.config import _load_gmail_imap
    import tomllib

    for name, value in (("GMAIL_IMAP_USER", user), ("GMAIL_IMAP_PASSWORD", password)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert _load_gmail_imap(tomllib.loads(GMAIL_SECTION)) is None


def test_gmail_imap_absent_section_is_disabled():
    from mailtag.config import _load_gmail_imap

    assert _load_gmail_imap({}) is None


def test_imap_config_defaults_keep_infomaniak_behaviour():
    from mailtag.config import ImapConfig

    config = ImapConfig(host="h", user="u", password="p")
    assert config.folder_cache_file == "data/imap_folders.json"
    assert config.pending_archive_file is None and config.junk_folder_name is None
```

Also extend `test_load_config_success`: with no `[gmail_imap]` in the mock file, `config.gmail_imap is None`.

- [ ] **Step 2:** `uv run pytest tests/test_config.py -q` → FAIL (`_load_gmail_imap` missing).

- [ ] **Step 3: implement** in `src/mailtag/config.py`

```python
@dataclass
class ImapConfig:
    host: str
    user: str
    password: str
    use_gmail_extensions: bool = False
    # Per-account overrides (the Gmail account sets them; None = the global setting)
    pending_archive_file: str | None = None
    folder_cache_file: str = "data/imap_folders.json"
    junk_folder_name: str | None = None
```

```python
def _load_gmail_imap(data: dict) -> ImapConfig | None:
    """Gmail as a second IMAP account (app password); None when absent or without credentials."""
    section = data.get("gmail_imap")
    if not section:
        return None
    user = os.getenv("GMAIL_IMAP_USER") or section.get("user", "")
    password = os.getenv("GMAIL_IMAP_PASSWORD") or section.get("password", "")
    if not user or not password or user.startswith("${") or password.startswith("${"):
        logger.info("[gmail_imap] has no credentials in .env: Gmail account disabled")
        return None
    return ImapConfig(
        host=section.get("host", "imap.gmail.com"),
        user=user,
        password=password,
        use_gmail_extensions=section.get("use_gmail_extensions", True),
        pending_archive_file=section.get("pending_archive_file", "db/pending_archive_gmail.json"),
        folder_cache_file=section.get("folder_cache_file", "data/gmail_folders.json"),
        junk_folder_name=section.get("junk_folder_name", "[Gmail]/Spam"),
    )
```

Add `gmail_imap: ImapConfig | None = None` to `AppConfig` (after `taxonomy`), and `gmail_imap=_load_gmail_imap(data),` in the `AppConfig(...)` call of `load_config`. Import `logger` from loguru if `config.py` lacks it (check first; use the module's existing logging if any).

`config.toml`, after `[gmail]`:

```toml
[gmail_imap]
# Gmail as a second IMAP account (docs/superpowers/specs/2026-09-28-gmail-imap-design.md).
# Credentials: GMAIL_IMAP_USER and GMAIL_IMAP_PASSWORD (a Google app password) in .env
host = "imap.gmail.com"
user = "${GMAIL_IMAP_USER}"
password = "${GMAIL_IMAP_PASSWORD}"
use_gmail_extensions = true
junk_folder_name = "[Gmail]/Spam"
pending_archive_file = "db/pending_archive_gmail.json"
folder_cache_file = "data/gmail_folders.json"
```

`.env.example`: add `GMAIL_IMAP_USER=` and `GMAIL_IMAP_PASSWORD=` with a one-line comment (Google app password).

- [ ] **Step 4:** `uv run pytest -q` → all pass; `uv run ruff check . && uv run ruff format --check .`
- [ ] **Step 5: commit** `feat(config): Gmail as a second IMAP account ([gmail_imap])`

### Task 2: Per-account folder cache, pending archive and junk folder

**Files:**
- Modify: `src/mailtag/imap_service.py:49` (`folder_cache_path`)
- Modify: `src/mailtag/utils/tasks.py` (`run_classification`)
- Test: `tests/test_imap_service.py` (or the existing ImapService test module — find it with `grep -l "ImapService(" tests`), and a new `tests/test_tasks_accounts.py`

**Interfaces:**
- Consumes: Task 1 `ImapConfig` fields.
- Produces: `pending_archive_path(config: ImapConfig, default: str) -> Path` and `junk_folder(provider: ImapService) -> str | None` in `src/mailtag/utils/tasks.py`.

- [ ] **Step 1: failing tests**

```python
# tests/test_tasks_accounts.py
from pathlib import Path

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.utils.tasks import junk_folder, pending_archive_path

INFOMANIAK = ImapConfig(host="mail.infomaniak.com", user="u", password="p")
GMAIL = ImapConfig(host="imap.gmail.com", user="g", password="p", pending_archive_file="db/pending_archive_gmail.json",
                   folder_cache_file="data/gmail_folders.json", junk_folder_name="[Gmail]/Spam")  # fmt: skip
FAST = FastParseConfig(junk_folder_name="Junk", metrics_enabled=False)


def test_each_account_has_its_own_pending_archive():
    assert pending_archive_path(INFOMANIAK, "db/pending_archive.json") == Path("db/pending_archive.json")
    assert pending_archive_path(GMAIL, "db/pending_archive.json") == Path("db/pending_archive_gmail.json")


def test_each_account_has_its_own_junk_folder():
    assert junk_folder(ImapService(INFOMANIAK, FAST)) == "Junk"
    assert junk_folder(ImapService(GMAIL, FAST)) == "[Gmail]/Spam"


def test_gmail_never_writes_the_infomaniak_folder_cache():
    assert ImapService(INFOMANIAK, FAST).folder_cache_path == Path("data/imap_folders.json")
    assert ImapService(GMAIL, FAST).folder_cache_path == Path("data/gmail_folders.json")
```

(Check `FastParseConfig` accepts `metrics_enabled`; `tests/test_migration.py` builds `FastParseConfig(metrics_enabled=False)`.)

- [ ] **Step 2:** `uv run pytest tests/test_tasks_accounts.py -q` → FAIL (import error).

- [ ] **Step 3: implement**

`src/mailtag/imap_service.py`: `self.folder_cache_path = Path(config.folder_cache_file)`.

`src/mailtag/utils/tasks.py`:

```python
def pending_archive_path(config: ImapConfig, default: str) -> Path:
    """Each IMAP account keeps its own pending archive: one account's sweep cannot see the
    other's mails and would remove their entries as orphans."""
    return Path(config.pending_archive_file or default)


def junk_folder(provider: ImapService) -> str | None:
    return provider.config.junk_folder_name or provider.fast_parse_config.junk_folder_name
```

In `run_classification`, build `pending` from `pending_archive_path(provider_instance.config, CONFIG.taxonomy.pending_archive_file)` when `provider_instance` is an `ImapService` (keep `CONFIG.taxonomy.pending_archive_file` otherwise), and replace `junk_folder = provider.fast_parse_config.junk_folder_name` with `junk_folder = junk_folder(provider)` — rename the local variable (e.g. `junk`) so it does not shadow the function. Import `ImapConfig` from `mailtag.config`.

- [ ] **Step 4:** `uv run pytest -q` all pass; ruff clean.
- [ ] **Step 5: commit** `feat(tasks): per-account pending archive, junk folder and folder cache`

### Task 3: CLI wiring

**Files:**
- Modify: `src/main.py` (`start_classification_run`, `PROVIDER_CLASSES`, imports)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `CONFIG.gmail_imap: ImapConfig | None` (Task 1).

- [ ] **Step 1: failing tests** — in `tests/test_main.py`:
  - Replace `test_main_provider_selection_gmail` with a test where `mock_app_config.gmail_imap = ImapConfig(host="imap.gmail.com", user="g@gmail.com", password="p")`, `main.ImapService` patched; `run --provider gmail` → `ImapService` called once with `mock_app_config.gmail_imap` as first argument, `refresh_imap_folders` not called, `run_classification` called once.
  - New: `mock_app_config.gmail_imap = None`, `run --provider all` → `run_classification` called once (Infomaniak only), exit code 0.
  - New: `mock_app_config.gmail_imap = None`, `run --provider gmail` → `run_classification` not called, exit code 0.
  - Keep `test_main_run_classification_default_both_providers` and `test_main_validate_mode` (they now count Infomaniak + Gmail IMAP; set `mock_app_config.gmail_imap` to an `ImapConfig` in the fixture) and drop their `main.GmailService` patches.

- [ ] **Step 2:** `uv run pytest tests/test_main.py -q` → FAIL.

- [ ] **Step 3: implement** — in `start_classification_run`, replace the provider-building block with:

```python
    providers_to_run = []
    if provider in ("imap", "all") and CONFIG.imap:
        imap_service = ImapService(CONFIG.imap, CONFIG.fast_parse)
        # Refresh IMAP folders at startup if configured
        if CONFIG.general.use_imap_folders_for_classification:
            logger.info("Refreshing IMAP folders at startup...")
            refresh_imap_folders(imap_service)
        providers_to_run.append(imap_service)
    # Gmail runs over IMAP ([gmail_imap]); its folders never replace data/imap_folders.json
    if provider in ("gmail", "all") and CONFIG.gmail_imap:
        providers_to_run.append(ImapService(CONFIG.gmail_imap, CONFIG.fast_parse))
```

Delete `PROVIDER_CLASSES` and the `GmailService` import from `main.py` if nothing else uses them (`grep -n "PROVIDER_CLASSES\|GmailService" src/main.py`). Leave `src/mailtag/gmail_service.py` in place. The "No providers configured" warning stays.

- [ ] **Step 4:** `uv run pytest -q` all pass; ruff clean.
- [ ] **Step 5: commit** `feat(cli): --provider gmail runs the Gmail IMAP account`

### Task 4: Documentation

**Files:** `CLAUDE.md`, `README.md`, `CHANGELOG.md` (`[Unreleased]`), `docs-site/getting-started/configuration.md`, `docs-site/getting-started/usage.md`, `docs-site/getting-started/installation.md` (Gmail note).

- [ ] **Step 1:** Document, in English, matching each file's style:
  - Gmail runs as a second IMAP account: `[gmail_imap]` keys (table in configuration.md), `.env` variables, how to create a Google app password (2-Step Verification on, https://myaccount.google.com/apppasswords), IMAP always on in Gmail.
  - Shared: `db/taxonomy/` rules, centroids. Per account: pending archive, junk folder, folder cache.
  - `run --provider gmail|all`; Gmail labels act as folders (a move removes the source label and adds the target); old Gmail labels untouched; no `scan`/`migrate`/`prune` for Gmail.
  - The Gmail API/OAuth path is no longer used by the CLI: replace the "Gmail OAuth Setup" section of configuration.md and the `[gmail]` mentions accordingly; CLAUDE.md "Provider Architecture": note that `GmailService` is unused by the CLI.
  - CHANGELOG `[Unreleased]` → Added: Gmail as a second IMAP account.
- [ ] **Step 2:** `uv run mkdocs build --strict` (then `rm -rf site`); `uv run pytest -q`.
- [ ] **Step 3: commit** `docs: Gmail as a second IMAP account`

## After the tasks (controller, with the owner)

1. Final whole-branch review; PR; merge on the owner's OK.
2. Read-only check: `uv run python src/main.py run --provider gmail --validate` — connection, share classified, no move.
3. Owner runs the first real `run --provider gmail`.
