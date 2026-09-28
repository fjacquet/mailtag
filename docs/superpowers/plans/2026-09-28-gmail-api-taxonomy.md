# Gmail through the API in Taxonomy Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `run --provider gmail` classifies the Gmail inbox through the Gmail API with the same taxonomy flow as Infomaniak, reusing Gmail's Promotions category.

**Architecture:** `GmailLabelClient` implements the small IMAPClient subset the taxonomy flow uses (`select_folder`, `search`, `fetch`, `move`, `folder_exists`, `create_folder`, `list_folders`, `logout`) on top of the Gmail API. `GmailApiService` subclasses `ImapService` and only replaces `connect()`, so `get_email_headers`, `get_full_emails`, `batch_move_emails`, `utils/tasks.py`, `routing.py` and `archive.py` run unchanged. The Gmail-over-IMAP path of PR #44 (`[gmail_imap]`) is removed.

**Tech Stack:** Python 3.13, google-api-python-client (already an optional extra, `gmail_auth.get_gmail_service`, scope `gmail.modify`), pytest + pytest-mock, ruff 110.

**Spec:** `docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md`

## Global Constraints

- Folder ↔ Gmail mapping (spec): `INBOX` → system `INBOX` **excluding** `category:promotions`; `Promotions` → `INBOX` + `CATEGORY_PROMOTIONS` (Gmail's own promo tab counts as the standard Promotions folder, like Infomaniak's own `Promotions`); junk → `SPAM`; every other folder (action folders, `Domaines/…`, `Ressources/…`, `Archive/…`) → user label of the same name, created on demand.
- Move S → D: D = `Promotions`: add `CATEGORY_PROMOTIONS`, remove the other `CATEGORY_*` (`CATEGORY_PERSONAL`, `CATEGORY_SOCIAL`, `CATEGORY_UPDATES`, `CATEGORY_FORUMS`), remove S if S is a user label, keep `INBOX`. Other D: add D's label id, remove S's label id (`INBOX`, `SPAM` or user label). Never touch any other label.
- Gmail `HttpError` surfaces as `ConnectionError` (every caller already catches it).
- Read-only when the flow asks for it: `--validate` never calls `move`/`create_folder` (already guaranteed by callers; `select_folder(readonly=True)` changes nothing on Gmail).
- `[gmail]` gains `pending_archive_file = "db/pending_archive_gmail.json"`, `folder_cache_file = "data/gmail_labels.json"`, `junk_folder_name = "SPAM"`, `use_gmail_extensions = false`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp`. Never commit `credentials.json`, `token.json`, `.env`, `data/`, `db/`, `.serena/`, `.claude/`, `.mcp.json`, `.rtk/`, `test.*.log`. No real Gmail/IMAP call from tests or from the implementer.

## Review Focus

1. A mail MailTag put in Promotions keeps `INBOX`: the next run's INBOX selection must not pick it up again — `INBOX` selection excludes `category:promotions` (Task 1 test).
2. User labels the owner already has (`github`, `TRAVELS`…) survive every move (Task 1 test).
3. Label names with `/`, `&`, accents (`Domaines/Énergie & Télécom`) — select/create by exact name via the label list, never via a `label:` search string (Task 1 test).
4. Numeric-looking Gmail ids: `ImapService.get_full_emails` turns digit strings into `int`; `fetch` must echo the keys it was given and accept ints (Task 1 test).
5. More than 500 ids in a list/move: pagination on `list`, `batchModify` chunks of 1,000 (Task 1 test).

---

### Task 1: `GmailLabelClient`

**Files:** Create `src/mailtag/gmail_api.py`; Test `tests/test_gmail_api.py`.

**Produces:**
- `selection(folder: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], str]` — `(labelIds, q)` for a folder name.
- `criteria_query(criteria: list | None) -> str` — IMAP criteria → Gmail query fragment.
- `move_changes(source: str, dest: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], list[str]]` — `(add, remove)`.
- `class GmailLabelClient(service)` with `list_folders()`, `folder_exists(name)`, `create_folder(name)`, `select_folder(name, readonly=False)`, `search(criteria=None)`, `fetch(uids, fields)`, `move(uids, dest)`, `logout()`, `is_login()`.

Pure helpers (write them verbatim):

```python
PROMOTIONS = "Promotions"
_CATEGORIES = ("CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS")


def selection(folder: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], str]:
    """Gmail labelIds and query of a MailTag folder."""
    if folder == "INBOX":
        return ["INBOX"], "-category:promotions"  # promos stay in the inbox, under their own tab
    if folder == PROMOTIONS:
        return ["INBOX", "CATEGORY_PROMOTIONS"], ""
    if folder == junk:
        return ["SPAM"], ""
    return [label_ids[folder]], ""  # KeyError for an unknown folder, like a failed IMAP select


def criteria_query(criteria: list | None) -> str:
    """The IMAP searches the taxonomy flow uses, as a Gmail query."""
    if not criteria or criteria == ["ALL"]:
        return ""
    if criteria[:3] == ["SEEN", "UNFLAGGED", "BEFORE"]:
        return f"-is:unread -is:starred before:{criteria[3]:%Y/%m/%d}"
    if criteria[:2] == ["HEADER", "Message-ID"]:
        return f"rfc822msgid:{criteria[2]}"
    raise ValueError(f"Unsupported search: {criteria}")


def move_changes(source: str, dest: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], list[str]]:
    """Labels to add and remove when a mail moves from `source` to `dest`; nothing else is touched."""
    source_ids = {"INBOX": ["INBOX"], PROMOTIONS: [], junk: ["SPAM"]}.get(source, [label_ids.get(source)])
    if dest == PROMOTIONS:
        return ["CATEGORY_PROMOTIONS"], [*_CATEGORIES, *(i for i in source_ids if i not in ("INBOX", None))]
    return [label_ids[dest]], [i for i in source_ids if i]
```

`GmailLabelClient` behaviour:
- Keeps `self._labels: dict[str, str]` name → id, loaded from `users().labels().list` (user labels; system ids map to themselves). `list_folders()` returns `[((), b"/", name) for name in user label names] + [((), b"/", "INBOX")]` (shape of IMAPClient: name at index 2).
- `create_folder(name)` → `labels().create(body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"})`, then caches the id.
- `select_folder(name, readonly=False)` stores the selected name after checking `selection()` succeeds (raises `KeyError` for an unknown folder).
- `search(criteria=None)` → `messages().list(userId="me", labelIds=…, q=" ".join(non-empty parts), includeSpamTrash=folder is junk, pageToken=…)` over all pages; returns the ids.
- `fetch(uids, fields)`: for each uid (key echoed as given, id = `str(uid)`): if a field contains `b"BODY[]"` or `b"BODY.PEEK[]"` → `messages().get(format="raw")`, value under key `b"BODY[]"` = `base64.urlsafe_b64decode(raw)`; if a field contains `HEADER.FIELDS (` → `messages().get(format="metadata", metadataHeaders=[names parsed from the field])`, value under the field with `.PEEK` removed = `"Name: value\r\n"` lines encoded UTF-8. Ignore `X-GM-LABELS`. Use a batch request (`service.new_batch_http_request`, ≤ 50 per batch) — or sequential `get` if simpler; correctness first.
- `move(uids, dest)`: `add, remove = move_changes(selected, dest, …)`; `messages().batchModify(userId="me", body={"ids": chunk, "addLabelIds": add, "removeLabelIds": remove})` per 1,000 ids.
- Every `googleapiclient.errors.HttpError` → `raise ConnectionError(str(e)) from e`.
- `logout()` no-op; `is_login()` → True.

- [ ] **Step 1: failing tests** in `tests/test_gmail_api.py` — pure helpers:
  - `selection("INBOX", …) == (["INBOX"], "-category:promotions")`; `selection("Promotions", …) == (["INBOX", "CATEGORY_PROMOTIONS"], "")`; `selection("SPAM", {}, "SPAM") == (["SPAM"], "")`; `selection("Domaines/Énergie & Télécom", {"Domaines/Énergie & Télécom": "Label_9"}, "SPAM") == (["Label_9"], "")`; unknown folder raises `KeyError`.
  - `criteria_query(None) == ""`, `["ALL"]` → `""`, `["SEEN", "UNFLAGGED", "BEFORE", date(2026, 9, 21)]` → `"-is:unread -is:starred before:2026/09/21"`, `["HEADER", "Message-ID", "<a@b>"]` → `"rfc822msgid:<a@b>"`.
  - `move_changes("INBOX", "1-A traiter", {"1-A traiter": "L1"}, "SPAM") == (["L1"], ["INBOX"])`; `move_changes("1-A traiter", "Domaines/Santé", {"1-A traiter": "L1", "Domaines/Santé": "L2"}, "SPAM") == (["L2"], ["L1"])`; `move_changes("INBOX", "Promotions", {}, "SPAM") == (["CATEGORY_PROMOTIONS"], ["CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"])` (INBOX kept); `move_changes("Promotions", "Archive/Achats", {"Archive/Achats": "L3"}, "SPAM") == (["L3"], [])`; `move_changes("SPAM", "4-Pour info", {"4-Pour info": "L4"}, "SPAM") == (["L4"], ["SPAM"])`.
  - Client with a `FakeGmail` test double (in the test file) holding `labels` and `messages {id: {"labelIds": set, "raw": bytes, "headers": {name: value}}}`, recording `list`/`batchModify` calls, paginating `list` by 2: `search()` returns every id across pages; `fetch(["123", 124], [b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]"])` returns keys `"123"` and `124` with `b"BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]"` header bytes parseable by `email.message_from_bytes`; `fetch([...], [b"BODY.PEEK[]"])` returns `b"BODY[]"` raw bytes; `move` from INBOX to a new label creates it and sends one `batchModify` removing only `INBOX` (the message's `Label_github` survives); `move` of 1,500 ids sends two `batchModify` calls; a fake `HttpError` becomes `ConnectionError`.
- [ ] **Step 2:** run, see failures. **Step 3:** implement. **Step 4:** `uv run pytest -q`, ruff. **Step 5:** commit `feat(gmail): GmailLabelClient, IMAP-like access to Gmail labels through the API`.

### Task 2: `GmailApiService`, config and CLI; remove the Gmail IMAP path

**Files:** Modify `src/mailtag/gmail_api.py`, `src/mailtag/config.py` (`GmailConfig`, remove `_load_gmail_imap` and `AppConfig.gmail_imap`), `config.toml` (`[gmail]` keys, remove `[gmail_imap]`), `.env.example` (remove `GMAIL_IMAP_*`), `src/main.py`, `src/mailtag/utils/tasks.py` (type hint of `pending_archive_path`), tests `tests/test_config.py`, `tests/test_main.py`, `tests/test_tasks_accounts.py`.

**Produces:** `GmailApiService(config: GmailConfig, fast_parse_config: FastParseConfig)` — subclass of `ImapService`; `connect()` context manager: `self.client = GmailLabelClient(get_gmail_service(config.credentials_file, config.token_file))`, raises `ConnectionError` when the service is `None`; yields `self`; never starts the IMAP metrics thread. `GmailConfig` gains `pending_archive_file: str | None = "db/pending_archive_gmail.json"`, `folder_cache_file: str = "data/gmail_labels.json"`, `junk_folder_name: str | None = "SPAM"`, `use_gmail_extensions: bool = False` (read with `_dataclass_from_dict` or explicit `.get` defaults, keeping `credentials_file`/`token_file` required as today).

- [ ] **Step 1: failing tests**
  - `test_config`: `[gmail]` defaults (the four new fields); `load_config` has no `gmail_imap` attribute any more; remove the `_load_gmail_imap` tests.
  - `test_tasks_accounts`: Gmail entry built from `GmailConfig(credentials_file="c", token_file="t")` → `pending_archive_path` gives `db/pending_archive_gmail.json`, `junk_folder` gives `"SPAM"`, folder cache `data/gmail_labels.json`.
  - `test_main`: `run --provider gmail` constructs `main.GmailApiService` with `CONFIG.gmail` and `CONFIG.fast_parse`, no `refresh_imap_folders`; `run --provider all` runs 2 providers; `run --provider gmail` with `CONFIG.gmail = None` runs nothing.
  - `test_gmail_api`: `GmailApiService.connect()` with `get_gmail_service` patched to a `FakeGmail` yields a service whose `client` is a `GmailLabelClient`; `get_email_headers(["m1"])` returns `sender_address`, `subject`, `message_id`, `has_unsubscribe`, `is_bulk` for a fake message (runs `ImapService._process_email_headers` unchanged); `batch_move_emails(["m1"], "1-A traiter")` after `client.select_folder("INBOX")` creates the label and removes `INBOX`.
- [ ] **Step 2–4:** implement; in `main.py`, the `gmail`/`all` branch appends `GmailApiService(CONFIG.gmail, CONFIG.fast_parse)` when `CONFIG.gmail`; drop the `[gmail_imap]` code. `run_classification` needs no change (the service is an `ImapService`). Full suite + ruff green.
- [ ] **Step 5:** commit `feat(gmail): Gmail API provider for the taxonomy flow, replacing Gmail over IMAP`.

### Task 3: End-to-end flow on a fake Gmail

**Files:** Test `tests/test_gmail_api.py`.

- [ ] **Step 1:** test that `run_archive(GmailApiService-with-FakeGmail, pending, rules, days=7, today=…)` moves a read, unstarred, old mail carrying label `4-Pour info` and a pending entry (`category="Santé"`) to `Domaines/Santé` (label created, `4-Pour info` removed, the mail's other labels kept), and learns `Santé` for a sender whose review mail (`5-A revoir` pending entry, category `None`) is now under `Domaines/Santé` (search `rfc822msgid:`). The FakeGmail `list` must honour `labelIds`, and for `q` only the fragments the code emits (`-category:promotions`, `-is:unread`, `-is:starred`, `before:`, `rfc822msgid:`) — keep that interpreter tiny and inside the test file.
- [ ] **Step 2:** also `route_to_action_folders` with a `Promotions` mail: keeps `INBOX`, gains `CATEGORY_PROMOTIONS`, pending entry recorded.
- [ ] **Step 3:** fix whatever the tests reveal (in `gmail_api.py` only). Commit `test(gmail): archive sweep and routing through the Gmail API`.

### Task 4: Documentation

**Files:** `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs-site/getting-started/configuration.md`, `docs-site/getting-started/usage.md`, `docs-site/getting-started/installation.md`, `docs-site/architecture/classification.md`.

- [ ] Replace the Gmail-over-IMAP docs (app password, `[gmail_imap]`) with: Gmail through the API (OAuth desktop client `credentials.json`, first run opens the browser, `token.json`, 7-day token while the OAuth app is in "Testing"); the folder ↔ label table from the spec (Promotions = Gmail's Promotions tab; Achats stays a label because the API does not expose Purchases); `[gmail]` keys; `run --provider gmail --validate` first. CHANGELOG `[Unreleased]`: "Changed — Gmail uses the Gmail API (OAuth) instead of IMAP; Gmail's Promotions category is reused". CLAUDE.md "Provider Architecture": `GmailApiService` (IMAP-like over the API) is the Gmail provider; `GmailService` is unused. `uv run mkdocs build --strict`, then `rm -rf site`. Commit `docs: Gmail through the API`.

## After the tasks (controller, with the owner)

1. Final branch review (most capable model), PR, merge on the owner's OK.
2. `uv run python src/main.py run --provider gmail --validate` (read-only) → report per action folder and category, and duration.
3. Owner runs the first real `run --provider gmail`; read-only check afterwards.
