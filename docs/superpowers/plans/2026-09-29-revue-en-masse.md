# Bulk review of `5-A revoir` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner decide categories per domain or per sender for the mails in `5-A revoir`, then move every covered mail to its PARA category folder in one command.

**Architecture:** A new `validated_domains.json` rule file in `TaxonomyStore`; a new module `src/mailtag/review_refile.py` (pure grouping/queue functions plus two provider functions: read review mails, refile covered mails); two `scripts/taxonomy_setup.py` commands (`review-scan`, `refile-review`); a fifth stage in `scripts/taxonomy_review.py`.

**Tech Stack:** Python 3.13, loguru, streamlit, pytest + pytest-mock, existing `ImapService` / `GmailApiService` providers, `MLXLLM.classify_batch`.

**Spec:** `docs/superpowers/specs/2026-09-29-revue-en-masse-design.md`

## Global Constraints

- No real IMAP/Gmail call and no MLX model load in tests; never read `.env` or `secrets/`.
- Line length 110 (ruff); match surrounding style; comments sparse, in English.
- Rule order in `category_for`: validated sender → learned sender (≥ `min_agreements`) → validated domain → computed domain; non-commercial domains (`is_non_commercial_domain_cached`) never get a domain rule.
- `replace_rules` (used by `build`) never touches `validated_domains`.
- Every mailbox-writing command is a dry run unless `--apply`.
- Commits end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp`
- Never `git add -A`, never `git stash`.

## Review Focus

- A domain group whose senders are only partly covered by rules: it stays in the queue, counted by its uncovered mails only.
- `refile-review --apply` on a mail whose Message-ID has no pending entry: move it anyway, nothing to remove.
- A mail in `5-A revoir` from an `own_addresses` sender: never moved by `refile-review`, never shown in the queue.
- `review-scan` run twice: Gemma suggestions already computed are reused, not recomputed.
- A domain validated then one of its senders validated to another category: the sender rule wins.

---

### Task 1: `validated_domains` in `TaxonomyStore`

**Files:**
- Modify: `src/mailtag/taxonomy_store.py`
- Test: `tests/test_taxonomy_store.py`

**Interfaces:**
- Produces: `TaxonomyStore.validated_domains: dict[str, str]`, `TaxonomyStore.set_validated_domain(domain: str, category: str) -> None`.

- [ ] **Step 1: failing tests** (append to `tests/test_taxonomy_store.py`, reuse its existing fixtures/style)

```python
def test_validated_domain_is_used_after_senders_and_before_computed_domains(tmp_path):
    store = TaxonomyStore(tmp_path)
    store.replace_rules({}, {"shop.ch": "Achats"})
    store.set_validated_domain("shop.ch", "Voyages & Loisirs")
    assert store.category_for("news@shop.ch") == "Voyages & Loisirs"
    store.set_validated("promo@shop.ch", "Achats")
    assert store.category_for("promo@shop.ch") == "Achats"


def test_validated_domain_survives_build_and_reload(tmp_path):
    store = TaxonomyStore(tmp_path)
    store.set_validated_domain("Shop.CH", "Achats")
    store.save()
    store.replace_rules({}, {})
    store.save()
    assert TaxonomyStore(tmp_path).category_for("a@shop.ch") == "Achats"


def test_non_commercial_domain_is_never_a_validated_domain_rule(tmp_path):
    store = TaxonomyStore(tmp_path)
    store.set_validated_domain("gmail.com", "Contacts")
    assert store.category_for("someone@gmail.com") is None
```

- [ ] **Step 2:** `uv run pytest tests/test_taxonomy_store.py -q` → FAIL (`set_validated_domain` missing).

- [ ] **Step 3: implement**
  - `_FILES = ("validated", "senders", "domains", "folder_overrides", "validated_domains")`
  - `_apply`: new branch before the `"replace"` fallthrough:
    ```python
    if kind == "validate_domain":
        domain, category = args
        self.validated_domains[domain] = category
        return {"validated_domains"}
    ```
  - `_category_for`: after the learned-sender check,
    ```python
    domain = extract_domain(sender)
    if domain and not is_non_commercial_domain_cached(domain):
        return self.validated_domains.get(domain) or self.domains.get(domain)
    return None
    ```
  - Method:
    ```python
    def set_validated_domain(self, domain: str, category: str) -> None:
        """Owner's decision for every sender of a domain; `build` never replaces it."""
        self._record(("validate_domain", normalize_address(domain), category))
    ```
  - Class docstring / module docstring: mention the new file in one phrase.

- [ ] **Step 4:** tests pass; full `uv run pytest -q`.
- [ ] **Step 5:** commit `feat(taxonomy): validated domain rules that build never replaces`.

### Task 2: `review_refile.py` — grouping, queue, read and refile

**Files:**
- Create: `src/mailtag/review_refile.py`
- Modify: `src/mailtag/imap_service.py` (`_process_email_headers` adds `"sender_name"`)
- Test: `tests/test_review_refile.py`

**Interfaces:**
- Consumes: `TaxonomyStore.category_for` (any callable `str -> str | None`), provider with `.client` (`select_folder`, `search`, `folder_exists`), `get_email_headers(uids) -> {uid: {"sender_address", "sender_name", "subject", "message_id", ...}}`, `batch_move_emails(uids, folder)`; `PendingArchive` (`get`, `remove`, `save`); `REVIEW`, `category_folder` from `mailtag.taxonomy`; `extract_domain`, `is_non_commercial_domain_cached` from `mailtag.utils.domain_utils`; `llm_sender_static_prompt`, `llm_sender_part`, `parse_category_number` from `mailtag.taxonomy`.
- Produces (exact names used by Tasks 3-4):
  - `group_key(address: str) -> tuple[str, str]` → `("domain", domain)` or `("sender", address)`
  - `read_review_mails(provider) -> list[dict]` (`sender_address`, `sender_name`, `subject`, `message_id`, `uid`)
  - `review_groups(mails, category_for, own: set[str], max_subjects: int = 5) -> dict[str, dict]`
  - `suggest_categories(groups, llm, done: dict, batch_size: int = 8) -> dict[str, str | None]`
  - `review_queue(groups, category_for, split: set[str], skipped: set[str]) -> list[tuple[str, dict]]`
  - `coverage(groups, category_for) -> tuple[int, int]`
  - `refile_review(provider, category_for, pending, own: set[str], apply: bool) -> dict`

Group entry shape (JSON-serialisable, written by Task 3 to `data/review_scan_<provider>.json` under `"groups"`):
```python
{
    "kind": "domain" | "sender",
    "mails": 12,
    "senders": {"a@shop.ch": {"name": "Shop", "mails": 10}, "b@shop.ch": {"name": "", "mails": 2}},
    "subjects": ["...", "..."],
}  # at most max_subjects, first seen
```
Group keys: the domain for `"domain"` groups, the address for `"sender"` groups.

- [ ] **Step 1: failing tests** in `tests/test_review_refile.py`. Use tiny fakes: a `category_for` from a dict; a `FakeProvider` with `client` exposing `folder_exists`, `select_folder`, `search(["ALL"])`, plus `get_email_headers` returning a preset dict and `batch_move_emails` recording calls. Cover:
  - `group_key("a@Shop.ch") == ("domain", "shop.ch")`; `group_key("x@gmail.com") == ("sender", "x@gmail.com")`.
  - `review_groups`: mails from `a@shop.ch` ×2 and `b@shop.ch` ×1 → one domain group `shop.ch` with `mails == 3` and both senders; `x@gmail.com` → sender group; mail whose sender is covered by `category_for` excluded; own address excluded; subjects capped at `max_subjects`.
  - `review_queue`: sorted by uncovered mails desc; skipped keys dropped; a key in `split` is replaced by one `"sender"` entry per sender (with that sender's mail count, and the group's subjects); a group with every sender covered disappears; a partly covered domain group shows only its uncovered mail count in `mails`.
  - `coverage`: returns `(covered_mails, total_mails)` over all groups.
  - `suggest_categories`: keys already in `done` are not sent to the LLM (fake `llm.classify_batch` records its parts, answers `"1"` → `"Banque & Placements"` via `parse_category_number`).
  - `refile_review(apply=False)`: returns `{"moves": {"Achats": 2}, "left": 1}`, no `batch_move_emails`, pending untouched.
  - `refile_review(apply=True)`: `batch_move_emails(uids, category_folder(category))` per category, pending entries of moved mails removed, entry-less mail moved without error, `pending.save()` called once, own-address mail left in place.
  - `refile_review` when `5-A revoir` does not exist: `{"moves": {}, "left": 0}`.

- [ ] **Step 2:** run → FAIL (module missing).

- [ ] **Step 3: implement** `src/mailtag/review_refile.py`:

```python
"""Bulk review of 5-A revoir (spec docs/superpowers/specs/2026-09-29-revue-en-masse-design.md):
group review mails by domain or sender, then move the mails a rule now covers to their category."""

from collections import defaultdict

from loguru import logger

from .taxonomy import (
    REVIEW,
    category_folder,
    llm_sender_part,
    llm_sender_static_prompt,
    parse_category_number,
)
from .taxonomy_store import normalize_address
from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached


def group_key(address: str) -> tuple[str, str]:
    address = normalize_address(address)
    domain = extract_domain(address)
    if domain and not is_non_commercial_domain_cached(domain):
        return "domain", domain
    return "sender", address


def read_review_mails(provider) -> list[dict]:
    client = provider.client
    if not client.folder_exists(REVIEW):
        return []
    client.select_folder(REVIEW, readonly=True)
    uids = client.search(["ALL"])
    headers = provider.get_email_headers(uids) if uids else {}
    return [{"uid": uid, **h} for uid, h in headers.items()]


def review_groups(mails, category_for, own, max_subjects=5):
    groups: dict[str, dict] = {}
    for m in mails:
        address = normalize_address(m["sender_address"])
        if not address or address in own or category_for(address):
            continue
        kind, key = group_key(address)
        g = groups.setdefault(key, {"kind": kind, "mails": 0, "senders": {}, "subjects": []})
        g["mails"] += 1
        s = g["senders"].setdefault(address, {"name": m.get("sender_name") or "", "mails": 0})
        s["mails"] += 1
        if m["subject"] and len(g["subjects"]) < max_subjects and m["subject"] not in g["subjects"]:
            g["subjects"].append(m["subject"])
    return groups


def suggest_categories(groups, llm, done, batch_size=8):
    results = dict(done)
    todo = [k for k in sorted(groups, key=lambda k: -groups[k]["mails"]) if k not in results]
    if not todo:
        return results
    parts = []
    for key in todo:
        g = groups[key]
        top = max(g["senders"].items(), key=lambda kv: kv[1]["mails"])
        name = top[1]["name"] if g["kind"] == "sender" else key
        parts.append(llm_sender_part(name, top[0], g["subjects"]))
    answers = llm.classify_batch(llm_sender_static_prompt(), parts, batch_size=batch_size)
    for key, answer in zip(todo, answers, strict=True):
        results[key] = parse_category_number(answer)
    return results


def _uncovered(group, category_for) -> dict[str, dict]:
    return {a: s for a, s in group["senders"].items() if not category_for(a)}


def review_queue(groups, category_for, split, skipped):
    rows = []
    for key, g in groups.items():
        senders = _uncovered(g, category_for)
        if not senders:
            continue
        if key in split and g["kind"] == "domain":
            for address, s in senders.items():
                if address not in skipped:
                    rows.append(
                        (
                            address,
                            {
                                "kind": "sender",
                                "mails": s["mails"],
                                "senders": {address: s},
                                "subjects": g["subjects"],
                                "domain": key,
                            },
                        )
                    )
        elif key not in skipped:
            rows.append((key, {**g, "senders": senders, "mails": sum(s["mails"] for s in senders.values())}))
    return sorted(rows, key=lambda row: -row[1]["mails"])


def coverage(groups, category_for):
    total = sum(g["mails"] for g in groups.values())
    left = sum(s["mails"] for g in groups.values() for s in _uncovered(g, category_for).values())
    return total - left, total


def refile_review(provider, category_for, pending, own, apply):
    mails = read_review_mails(provider)
    moves: dict[str, list] = defaultdict(list)
    left = 0
    for m in mails:
        address = normalize_address(m["sender_address"])
        category = None if address in own else category_for(address)
        if category:
            moves[category].append(m)
        else:
            left += 1
    report = {"moves": {c: len(ms) for c, ms in moves.items()}, "left": left}
    if not apply:
        return report
    for category, ms in moves.items():
        try:
            provider.batch_move_emails([m["uid"] for m in ms], category_folder(category))
        except (
            ConnectionError,
            TimeoutError,
            OSError,
        ) as e:  # match archive.py's error set incl. imaplib.IMAP4.error
            logger.error(f"Could not move {len(ms)} emails to {category}: {e}")
            report["moves"][category] = 0
            continue
        for m in ms:
            if m.get("message_id") and pending.get(m["message_id"]):
                pending.remove(m["message_id"])
    pending.save()
    return report
```
  (Catch `imaplib.IMAP4.error` too, as `archive.py` does. Format with ruff.)

  In `src/mailtag/imap_service.py` `_process_email_headers`: keep `name, sender_address = self._parse_sender(sender_header)` (it is currently `_`) and add `"sender_name": name or ""` to the dict. Check `GmailApiService` inherits this (it does: it subclasses `ImapService`).

- [ ] **Step 4:** tests pass; full suite passes (fix any test asserting the exact header dict).
- [ ] **Step 5:** commit `feat(taxonomy): group review mails and refile the ones a rule covers`.

### Task 3: `taxonomy_setup.py review-scan` and `refile-review`

**Files:**
- Modify: `scripts/taxonomy_setup.py`
- Test: `tests/test_taxonomy_setup.py`

**Interfaces:**
- Consumes: Task 2 functions; `pending_archive_path(config, default)` from `mailtag.utils.tasks`; `GmailApiService` from `mailtag.gmail_api`; `ImapService`; `MLXLLM`.
- Produces: `REVIEW_SCAN = "data/review_scan_{provider}.json"` pattern; `review_scan_path(provider: str) -> Path`; commands `review-scan --provider imap|gmail`, `refile-review --provider imap|gmail [--apply]`.

- [ ] **Step 1: failing tests** (monkeypatch/mocker the provider factory and MLXLLM; no network):
  - `_account("gmail")` returns `(GmailApiService-like, CONFIG.gmail)`; `_account("imap")` → ImapService with `CONFIG.imap`. Test via mocker patching the classes.
  - `review_scan("gmail")` writes `data/review_scan_gmail.json` (use `tmp_path` + monkeypatch of `review_scan_path`) with `{"groups": {...}, "suggestions": {...}}`; existing suggestions reused (the fake LLM is not called for them).
  - `refile("gmail", apply=False)` calls `refile_review(..., apply=False)` and never `pending.save`; blocked by `migration_blocked` like `migrate`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement**
  - `review_scan_path(provider) -> Path("data") / f"review_scan_{provider}.json"`.
  - `_account(provider)`: imap → `(ImapService(CONFIG.imap, CONFIG.fast_parse), CONFIG.imap)`; gmail → `(GmailApiService(CONFIG.gmail, CONFIG.fast_parse), CONFIG.gmail)`; `sys.exit("No [gmail] section in config.toml")` when `CONFIG.gmail` is None.
  - `review_scan(provider)`: store (read-only lookups are fine: `TaxonomyStore(dir)`), own set, `with service.connect() as p: mails = read_review_mails(p)`; groups; previous file's `suggestions` as `done`; `MLXLLM(CONFIG.mlx.llm_model, max_tokens=4, temperature=0.0)` only if some group lacks a suggestion; write `{"groups", "suggestions"}` with `write_json_atomic`; log groups count and mails.
  - `refile(provider, apply)`: `migration_blocked` guard; warning line when `apply` ("do not run `run` or `serve` until it finishes"); `PendingArchive(pending_archive_path(config, CONFIG.taxonomy.pending_archive_file))`; call `refile_review`; log `moves` per category, total, `left`, `(dry run)` when not applying.
  - argparse: add `review-scan`, `refile-review` to `choices`; `--provider` (`choices=["imap","gmail"]`, default `"imap"`). Module docstring: two usage lines.
- [ ] **Step 4:** PASS + full suite.
- [ ] **Step 5:** commit `feat(taxonomy): review-scan and refile-review commands`.

### Task 4: Review page stage 5 + docs

**Files:**
- Modify: `scripts/taxonomy_review.py`, `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs-site/architecture/classification.md` (or the page that documents the review page and `taxonomy_setup.py` commands; `grep -rn "reorganize" docs-site` to find it)

**Interfaces:**
- Consumes: `review_scan_path`, `review_queue`, `coverage`, `TaxonomyStore.set_validated_domain`, `set_validated`.

- [ ] **Step 1: implement stage 5** (Streamlit; logic stays in Task 2's pure functions, already tested):
  - Load every existing `review_scan_path(p)` for `p in ("imap", "gmail")`; merge groups (same key from both accounts: add `mails`, merge `senders`, keep first subjects) and suggestions.
  - `split = st.session_state.setdefault("split", set())`; `queue = review_queue(groups, store.category_for, split, skipped)`.
  - The stage 5 page is shown even when `scan`/`crosscheck` files are missing: move the existing `st.error(... scan ... crosscheck)` stop so that it only blocks stages 1-4 (keep their behaviour), or load stage 5 before it.
  - `STAGES` gets `f"5. Mails en revue ({len(queue)})": "review"`.
  - Page: header = key; `covered, total = coverage(groups, store.category_for)` → caption `"{covered}/{total} mails couverts"`; line `"{mails} mails · {kind}"`; top 5 senders with counts; subjects; `Gemma : **{suggestion or '(illisible)'}**`.
  - Buttons: `Confirmer : <suggestion>` (if any), `category_buttons(...)` with the pick → `store.set_validated_domain(key, c)` for `"domain"` rows, `store.set_validated(key, c)` for `"sender"` rows; `Par expéditeur` for domain rows (adds key to `split`, rerun); `skip_button(key)`.
  - Module docstring: mention stage 5 and `review-scan`.
- [ ] **Step 2:** `uv run python -c "import ast,sys; ast.parse(open('scripts/taxonomy_review.py').read())"`, full pytest, ruff.
- [ ] **Step 3: docs**: README + CLAUDE.md taxonomy section (validated domains, `review-scan`, stage 5, `refile-review [--apply]`, dry run default, run by the owner), docs-site page, CHANGELOG `### Added` line.
- [ ] **Step 4:** `uv run mkdocs build --strict` then `rm -rf site`; ruff check/format.
- [ ] **Step 5:** commit `feat(taxonomy): review page stage for mails in 5-A revoir` (+ docs in same or separate `docs:` commit).

## After the tasks

1. Final branch review, PR, merge on the owner's OK.
2. `review-scan --provider gmail` (reads Gmail, runs Gemma locally), owner reviews stage 5.
3. `refile-review --provider gmail` dry run → report; owner runs `--apply`; read-only label check.
