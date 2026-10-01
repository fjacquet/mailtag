# Wider Training Corpus for the Logistic Regression Implementation Plan

<!-- fmt:off -->
<!-- Code blocks below are plan fragments (class bodies, call arguments), not standalone modules. -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train the Pass 3 logistic regression on a wider, more varied corpus harvested read-only from the IMAP category folders, keep `data/taxonomy_corpus.json` frozen as the test set, and let a domain-grouped evaluation decide whether the new corpus is adopted.

**Architecture:** `taxonomy_build` gains pure helpers (`read_folder_senders`, `harvest_refs`, `corpus_to_keep`) and `logreg_provider` gains `capped_indices`. `scripts/taxonomy_setup.py harvest` writes `data/training_corpus.json` from the category folders (a mail is kept only if its sender's rule gives its folder's category, at most N per sender); `train` prefers that file (capped to `[logreg] per_sender`); `build` stops overwriting the corpus with a half-empty re-read. `scripts/eval_embeddings.py logreg` groups folds by domain (by sender on non-commercial domains), compares the old corpus with the harvested one at several `per_sender` values, and proposes thresholds for the winner.

**Tech Stack:** Python 3.13, numpy, scikit-learn (`GroupKFold`, training only), IMAPClient via `ImapService`, pytest + pytest-mock, uv.

**Spec:** `docs/superpowers/specs/2026-10-01-logreg-corpus-design.md`

## Global Constraints

- Categories, folders and rules are unchanged. `[classifier] mode` stays `"mlx"`.
- `harvest` is read-only: folders are selected with `readonly=True`; no mail is moved, flagged or deleted. IMAP only (no Gmail).
- A harvested mail is kept only if `TaxonomyStore.category_for(sender)` equals its folder's category (this also excludes the owner's addresses, for which `category_for` returns `None`).
- `harvest --per-sender` defaults to 20; `[logreg] per_sender` defaults to 10. No per-category cap.
- Category folders: `category_folder(c)` for each `c` in `TAXONOMY` (one folder per category: `Domaines/…`, `Ressources/…` or `Archive/…`). Never `Promotions`, action folders or `INBOX`.
- `data/taxonomy_corpus.json` stays the test set (its `verified` mails) and the centroid source; `build` keeps the existing file when the re-read corpus has fewer than half its mails.
- `data/training_corpus.json` has the `fetch_corpus` row format: `sender`, `category`, `verified`, `sender_name`, `subject`, `body`. It is git-ignored (under `data/`): never commit it.
- Evaluation folds: 5, grouped by domain, by sender address on non-commercial domains; a fold never trains on a mail of its groups.
- Line length 110, the repo's ruff rules; before every commit `uv run ruff check . && uv run ruff format --check .` (CI also formats Python blocks inside Markdown; never run `ruff format .` over `docs/`).
- No test opens a network connection or downloads a model (IMAP is mocked; embeddings use `tests/fake_embedder.py`).
- Stage explicit paths (`git add <files>`), never `git commit -a`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01M8Lt6kKGBKhRfA7hqfyHEL
  ```

## Review Focus

1. **Same sender in several category folders** (mail moved by hand, or a rule that changed): only the folder matching the rule contributes, and the per-sender cap counts across all folders. Test in Task 2.
2. **Sender address with different case in headers** (`News@Shop.CH`): it must match the rule and count against one cap. Test in Task 2.
3. **`build` run today, after the migration** (re-read corpus nearly empty): the 403 verified test mails must survive. Test in Task 2.
4. **`data/training_corpus.json` present on disk while unit tests run** (the real file exists after Task 4): `train` tests must not pick it up. Fixture change in Task 1.
5. **A test group with no training mail left in a fold** (a domain holding every mail of a category): the evaluation still runs; the fold trains on the remaining categories. Test in Task 3 (`group_folds` never yields an empty training set for the test data used).

---

### Task 1: `per_sender`, `capped_indices`, and `train` reads the training corpus

**Files:**
- Modify: `src/mailtag/config.py` (`LogRegConfig`), `config.toml` (`[logreg]`)
- Modify: `src/mailtag/logreg_provider.py` (new `capped_indices`)
- Modify: `scripts/taxonomy_setup.py` (`TRAINING_CORPUS`, `train()`)
- Test: `tests/test_config.py`, `tests/test_logreg_provider.py`, `tests/test_taxonomy_setup.py`

**Interfaces:**
- Produces: `LogRegConfig.per_sender: int = 10`; `capped_indices(corpus: list[dict], per_sender: int) -> list[int]` in `mailtag.logreg_provider`; `scripts.taxonomy_setup.TRAINING_CORPUS = Path("data/training_corpus.json")`; `train()` uses `TRAINING_CORPUS` (capped) when it exists, else `CORPUS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_logreg_per_sender_default_and_toml(tmp_path, monkeypatch):
    from mailtag.config import LogRegConfig, load_config

    assert LogRegConfig().per_sender == 10
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[logging]
level = "INFO"
file = ""

[imap]
host = "imap.test.com"

[gmail]
credentials_file = "c.json"
token_file = "t.json"

[logreg]
per_sender = 5
"""
    )

    assert load_config(toml).logreg.per_sender == 5
```

Append to `tests/test_logreg_provider.py` (add `capped_indices` to the `mailtag.logreg_provider` import list, keeping it sorted):

```python
def test_capped_indices_keeps_the_first_mails_of_each_sender_in_order():
    corpus = [{"sender": s} for s in ["a", "b", "a", "a", "c", "b", "a"]]

    assert capped_indices(corpus, 2) == [0, 1, 2, 4, 5]
    assert capped_indices(corpus, 10) == list(range(7))
```

In `tests/test_taxonomy_setup.py`, make `_train_setup` also point `TRAINING_CORPUS` at a temp path (absent unless a test writes it), by adding after the `monkeypatch.setattr(setup, "CORPUS", corpus)` line:

```python
    monkeypatch.setattr(setup, "TRAINING_CORPUS", tmp_path / "training.json")
```

and append:

```python
HARVESTED = [
    {"sender": f"h{i % 3}@x.ch", "sender_name": "", "subject": word, "body": "", "category": cat,
     "verified": False}
    for i, (word, cat) in enumerate(
        [("pizza", "Achats"), ("impot", "Impôts & Administration"), ("train", "Transports & Mobilité")] * 6
    )
]  # fmt: skip


def test_train_prefers_the_training_corpus_capped_per_sender(tmp_path, monkeypatch, mocker):
    import mailtag.logreg_provider
    from mailtag.config import CONFIG, LogRegConfig

    setup, _ = _train_setup(tmp_path, monkeypatch, mocker, TRAIN_MAILS)
    (tmp_path / "training.json").write_text(json.dumps(HARVESTED), encoding="utf-8")
    monkeypatch.setattr(
        CONFIG, "logreg", LogRegConfig(model_file=str(tmp_path / "logreg.npz"), per_sender=5)
    )
    fit = mocker.spy(mailtag.logreg_provider, "train")

    setup.train()

    # 3 senders x 5 mails: neither the 18 harvested rows nor the 12 rows of TRAIN_MAILS
    assert len(fit.call_args.args[1]) == 15
    assert fit.call_args.args[0].shape[0] == 15


def test_train_falls_back_to_the_taxonomy_corpus(tmp_path, monkeypatch, mocker):
    import mailtag.logreg_provider

    setup, _ = _train_setup(tmp_path, monkeypatch, mocker, TRAIN_MAILS)
    fit = mocker.spy(mailtag.logreg_provider, "train")

    setup.train()

    assert fit.call_args.args[1] == [m["category"] for m in TRAIN_MAILS]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_logreg_provider.py tests/test_taxonomy_setup.py -k "per_sender or capped or prefers or falls_back" -v`
Expected: FAIL (`LogRegConfig` has no `per_sender`; `capped_indices` not importable; `TRAINING_CORPUS` missing).

- [ ] **Step 3: Implement**

`src/mailtag/config.py`, in `LogRegConfig` after `C`:

```python
    per_sender: int = 10  # mails per sender taken from data/training_corpus.json
```

`config.toml`, in `[logreg]` after `C = 100.0`:

```toml
per_sender = 10         # mails per sender taken from data/training_corpus.json (set by the evaluation)
```

`src/mailtag/logreg_provider.py`, after `corpus_texts`:

```python
def capped_indices(corpus: list[dict], per_sender: int) -> list[int]:
    """Indices of the first `per_sender` mails of each sender, in corpus order."""
    seen: dict[str, int] = {}
    keep = []
    for i, mail in enumerate(corpus):
        if seen.get(mail["sender"], 0) < per_sender:
            seen[mail["sender"]] = seen.get(mail["sender"], 0) + 1
            keep.append(i)
    return keep
```

`scripts/taxonomy_setup.py`: after `CORPUS = Path("data/taxonomy_corpus.json")` add

```python
TRAINING_CORPUS = Path("data/training_corpus.json")
```

and replace the body of `train()` up to the `embedding_model = ...` line with:

```python
    """Fit the [logreg] model on data/training_corpus.json (capped to [logreg] per_sender) if it
    exists, else on data/taxonomy_corpus.json (no IMAP, no rule touched)."""
    from mailtag.logreg_provider import capped_indices, corpus_texts, embed, save_model
    from mailtag.logreg_provider import train as fit
    from mailtag.mlx_provider import MLXEmbedder

    source = TRAINING_CORPUS if TRAINING_CORPUS.exists() else CORPUS
    if missing := missing_inputs([source]):
        sys.exit(f"Missing {missing[0]}: run `build` first")
    corpus = _read(source)
    if source == TRAINING_CORPUS:
        corpus = [corpus[i] for i in capped_indices(corpus, CONFIG.logreg.per_sender)]
    if len({m["category"] for m in corpus}) < 3:
        sys.exit(f"{source} needs mails in at least 3 categories to train")
```

and make the final log line name the source:

```python
    logger.info(
        f"Logistic regression from {len(corpus)} mails of {source}, {len(model['classes'])} categories "
        f"-> {CONFIG.logreg.model_file}"
    )
```

Note: `train` must keep importing `train as fit` inside the function (the spy test patches the module attribute).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_logreg_provider.py tests/test_taxonomy_setup.py -v`
Expected: all PASS (existing `train` tests included: the existing "too few categories" test still matches `"3 categories"`).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/mailtag/config.py config.toml src/mailtag/logreg_provider.py scripts/taxonomy_setup.py tests/test_config.py tests/test_logreg_provider.py tests/test_taxonomy_setup.py
git commit -m "feat(logreg): train prefers data/training_corpus.json, capped per sender"
```

---

### Task 2: `harvest`, and `build` keeps the corpus it cannot re-read

**Files:**
- Modify: `src/mailtag/taxonomy_build.py` (new `read_folder_senders`, `harvest_refs`, `corpus_to_keep`)
- Modify: `scripts/taxonomy_setup.py` (docstring, new `harvest()`, `build()`, `main()`)
- Test: `tests/test_taxonomy_build.py`, `tests/test_taxonomy_setup.py`

**Interfaces:**
- Consumes: `TRAINING_CORPUS` (Task 1); existing `fetch_corpus(provider, refs) -> list[dict]` (refs need `sender`, `category`, `verified`, `folder`, `uid`); `TaxonomyStore.category_for`, `.validated`; `normalize_address` from `mailtag.taxonomy_store`; `category_folder`, `TAXONOMY` from `mailtag.taxonomy`.
- Produces: `read_folder_senders(provider, folders: list[str]) -> dict[str, dict[str, str]]`; `harvest_refs(folder_senders: dict[str, dict[str, str]], folders: dict[str, str], rule_category, validated, per_sender: int) -> list[dict]`; `corpus_to_keep(new: list[dict], old: list[dict] | None) -> list[dict]`; `scripts.taxonomy_setup.harvest(per_sender: int) -> None`; CLI `harvest [--per-sender N]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_taxonomy_build.py` (add `corpus_to_keep`, `harvest_refs`, `read_folder_senders` to the `mailtag.taxonomy_build` import list, keeping it sorted):

```python
FOLDERS = {"Archive/Achats": "Achats", "Domaines/Santé": "Santé"}
RULES = {"shop@x.ch": "Achats", "doc@clinic.ch": "Santé", "moved@x.ch": "Santé"}


def test_harvest_refs_keep_mail_whose_rule_matches_the_folder():
    folder_senders = {
        "Archive/Achats": {"1": "shop@x.ch", "2": "unknown@x.ch", "3": "moved@x.ch"},
        "Domaines/Santé": {"7": "doc@clinic.ch", "8": "moved@x.ch"},
    }

    refs = harvest_refs(folder_senders, FOLDERS, RULES.get, {"doc@clinic.ch": "Santé"}, per_sender=20)

    assert sorted((r["folder"], r["uid"], r["sender"], r["category"], r["verified"]) for r in refs) == [
        ("Archive/Achats", 1, "shop@x.ch", "Achats", False),
        ("Domaines/Santé", 7, "doc@clinic.ch", "Santé", True),
        ("Domaines/Santé", 8, "moved@x.ch", "Santé", False),
    ]


def test_harvest_refs_cap_per_sender_across_folders_highest_uids_first():
    folder_senders = {
        "Domaines/Santé": {str(uid): "Doc@Clinic.CH" for uid in (3, 10, 7)},
        "Archive/Achats": {"5": "doc@clinic.ch"},  # rule says Santé: never counted here
    }

    refs = harvest_refs(folder_senders, FOLDERS, RULES.get, {}, per_sender=2)

    assert [(r["uid"], r["sender"]) for r in refs] == [(10, "doc@clinic.ch"), (7, "doc@clinic.ch")]


def test_harvest_refs_skip_senders_without_rule_or_owned():
    owned = {"me@home.ch": None}  # category_for returns None for the owner's addresses

    refs = harvest_refs({"Archive/Achats": {"1": "me@home.ch", "2": ""}}, FOLDERS, owned.get, {}, 20)

    assert refs == []


def test_read_folder_senders_reads_read_only_and_skips_unreadable_folders(mocker):
    provider = mocker.MagicMock()

    def select(folder, readonly):
        if folder == "Gone":
            raise imaplib.IMAP4.error("no such folder")

    provider.client.select_folder.side_effect = select
    provider.client.search.return_value = [1, 2]
    provider.get_email_headers.return_value = {"1": {"sender_address": "a@x.ch"}, "2": {"sender_address": ""}}

    result = read_folder_senders(provider, ["Archive/Achats", "Gone"])

    assert result == {"Archive/Achats": {"1": "a@x.ch", "2": ""}}
    provider.client.select_folder.assert_any_call("Archive/Achats", readonly=True)
    provider.client.move.assert_not_called()


def test_corpus_to_keep_refuses_a_re_read_that_lost_more_than_half():
    old = [{"i": i} for i in range(10)]

    assert corpus_to_keep([{"i": 0}] * 4, old) is old
    new = [{"i": 0}] * 5
    assert corpus_to_keep(new, old) is new
    assert corpus_to_keep(new, None) is new
```

Append to `tests/test_taxonomy_setup.py`:

```python
def _harvest_setup(tmp_path, monkeypatch, mocker, corpus):
    import scripts.taxonomy_setup as setup

    monkeypatch.setattr(setup, "TRAINING_CORPUS", tmp_path / "training.json")
    store = mocker.MagicMock()
    store.validated = {}
    mocker.patch.object(setup, "_store", return_value=store)
    mocker.patch.object(setup, "_imap")
    read = mocker.patch("mailtag.taxonomy_build.read_folder_senders", return_value={"Archive/Achats": {}})
    mocker.patch("mailtag.taxonomy_build.harvest_refs", return_value=[{"uid": 1}] if corpus else [])
    mocker.patch("mailtag.taxonomy_build.fetch_corpus", return_value=corpus)
    return setup, read


def test_harvest_reads_the_19_category_folders_and_writes_the_training_corpus(tmp_path, monkeypatch, mocker):
    from mailtag.taxonomy import TAXONOMY, category_folder

    setup, read = _harvest_setup(tmp_path, monkeypatch, mocker, HARVESTED)

    setup.harvest(per_sender=20)

    assert sorted(read.call_args.args[1]) == sorted(category_folder(c) for c in TAXONOMY)
    assert json.loads((tmp_path / "training.json").read_text(encoding="utf-8")) == HARVESTED


def test_harvest_with_nothing_collected_exits_without_writing(tmp_path, monkeypatch, mocker):
    setup, _ = _harvest_setup(tmp_path, monkeypatch, mocker, [])

    with pytest.raises(SystemExit, match="Nothing harvested"):
        setup.harvest(per_sender=20)
    assert not (tmp_path / "training.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_taxonomy_build.py tests/test_taxonomy_setup.py -k "harvest or read_folder or corpus_to_keep" -v`
Expected: FAIL (`ImportError` on the new `taxonomy_build` names; no `harvest` in the script).

- [ ] **Step 3: Implement**

`src/mailtag/taxonomy_build.py`: add `from .taxonomy_store import normalize_address` to the imports (check it creates no import cycle: `taxonomy_store` does not import `taxonomy_build`), and after `fetch_corpus`:

```python
def read_folder_senders(provider, folders: list[str]) -> dict[str, dict[str, str]]:
    """Folder -> {uid: sender address} for every mail, read-only; unreadable folders are skipped."""
    result: dict[str, dict[str, str]] = {}
    for folder in folders:
        try:
            provider.client.select_folder(folder, readonly=True)
            headers = provider.get_email_headers(provider.client.search(["ALL"]))
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not read folder {folder}: {e}")
            continue
        result[folder] = {str(uid): h["sender_address"] for uid, h in headers.items()}
    return result


def harvest_refs(
    folder_senders: dict[str, dict[str, str]], folders: dict[str, str], rule_category, validated, per_sender: int
) -> list[dict]:
    """References of mails whose sender's rule gives their folder's category, at most `per_sender` per
    sender over all folders, highest UIDs (most recent) first in each folder."""
    counts: Counter = Counter()
    refs = []
    for folder, senders in folder_senders.items():
        category = folders[folder]
        for uid in sorted(senders, key=int, reverse=True):
            sender = normalize_address(senders[uid])
            if not sender or counts[sender] >= per_sender or rule_category(sender) != category:
                continue
            counts[sender] += 1
            refs.append(
                {"sender": sender, "category": category, "verified": sender in validated,
                 "folder": folder, "uid": int(uid)}
            )  # fmt: skip
    return refs


def corpus_to_keep(new: list[dict], old: list[dict] | None) -> list[dict]:
    """The re-read corpus, unless it lost more than half of the existing one (its folders are gone)."""
    return old if old is not None and len(new) < len(old) / 2 else new
```

`scripts/taxonomy_setup.py`:

Module docstring, after the `train` line, add:

```
    uv run python scripts/taxonomy_setup.py harvest     # training corpus from the category folders (read-only)
```

(shorten the comment if the line exceeds 110 characters).

Add after `train()`:

```python
def harvest(per_sender: int) -> None:
    """Training corpus from the category folders: mails whose sender's rule gives their folder's
    category, at most `per_sender` per sender (read-only, IMAP)."""
    from mailtag.taxonomy import TAXONOMY, category_folder
    from mailtag.taxonomy_build import fetch_corpus, harvest_refs, read_folder_senders

    store = _store()
    folders = {category_folder(c): c for c in TAXONOMY}
    with _imap() as provider:
        refs = harvest_refs(
            read_folder_senders(provider, list(folders)), folders, store.category_for, store.validated,
            per_sender,
        )  # fmt: skip
        corpus = fetch_corpus(provider, refs) if refs else []
    if not corpus:
        sys.exit("Nothing harvested: no category-folder mail matches its sender's rule")
    write_json_atomic(TRAINING_CORPUS, corpus)
    logger.info(f"Wrote {TRAINING_CORPUS}: {len(corpus)} mails, {len({m['sender'] for m in corpus})} senders")
```

In `build()`, replace

```python
    with _imap() as provider:
        corpus = fetch_corpus(provider, corpus_refs(senders, store.validated, learned))
    write_json_atomic(CORPUS, corpus)
```

with

```python
    with _imap() as provider:
        corpus = fetch_corpus(provider, corpus_refs(senders, store.validated, learned))
    old = _read(CORPUS) if CORPUS.exists() else None
    kept = corpus_to_keep(corpus, old)
    if kept is corpus:
        write_json_atomic(CORPUS, corpus)
    else:
        logger.warning(f"Re-read only {len(corpus)} mails, {CORPUS} has {len(old)}: keeping {CORPUS}")
    corpus = kept
```

and add `corpus_to_keep` to `build()`'s `from mailtag.taxonomy_build import (...)` list.

In `main()`: add `"harvest"` to the `choices` list (keep the `# fmt: skip` layout and the 110-column limit), add

```python
    parser.add_argument("--per-sender", type=int, default=20, help="harvest: mails kept per sender")
```

and dispatch it before the final `else`:

```python
    elif args.command == "harvest":
        harvest(args.per_sender)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_taxonomy_build.py tests/test_taxonomy_setup.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/mailtag/taxonomy_build.py scripts/taxonomy_setup.py tests/test_taxonomy_build.py tests/test_taxonomy_setup.py
git commit -m "feat(logreg): taxonomy_setup.py harvest; build keeps a corpus it cannot re-read"
```

---

### Task 3: Domain-grouped evaluation comparing the two corpora

**Files:**
- Modify: `scripts/eval_embeddings.py` (docstring, replace `sender_folds` by `fold_group` + `group_folds`, rewrite `logreg_eval`, `main()`)
- Test: `tests/test_eval_embeddings.py` (replace the `sender_folds` test)

**Interfaces:**
- Consumes: `capped_indices`, `corpus_texts`, `embed`, `predict`, `train` from `mailtag.logreg_provider`; `extract_domain`, `is_non_commercial_domain_cached` from `mailtag.utils.domain_utils`; existing `leave_sender_out_top`, `confidence_sweep`, `best_threshold`, `learn_threshold` in the script.
- Produces: `fold_group(address: str) -> str`; `group_folds(train_groups: list[str], test_groups: list[str], n_splits: int = 5)` yielding `(train_idx: np.ndarray, test_pos: np.ndarray)`; `logreg_eval(C: float, min_precision: float, train_corpus: Path | None, per_senders: list[int]) -> None`; CLI `logreg [--train-corpus PATH] [--per-sender N ...] [--C C] [--min-precision P]`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_eval_embeddings.py`, replace `test_sender_folds_never_share_a_sender_and_test_each_verified_mail_once` with:

```python
def test_fold_group_is_the_domain_or_the_address_on_personal_domains():
    from scripts.eval_embeddings import fold_group

    assert fold_group("News@Shop.ch") == "shop.ch"
    assert fold_group("jane.doe@gmail.com") == "jane.doe@gmail.com"


def test_group_folds_never_share_a_group_and_test_each_mail_once():
    from scripts.eval_embeddings import group_folds

    train_groups = [f"d{i % 7}.ch" for i in range(60)]  # 7 domains in the training corpus
    test_groups = [f"d{i % 6}.ch" for i in range(30)]  # 6 of them in the test set

    tested = []
    for train, test in group_folds(train_groups, test_groups, n_splits=3):
        assert not {train_groups[i] for i in train} & {test_groups[i] for i in test}
        assert len(train) > 0
        tested += test.tolist()

    assert sorted(tested) == list(range(30))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_embeddings.py -v`
Expected: FAIL with `ImportError: cannot import name 'fold_group'`.

- [ ] **Step 3: Implement** in `scripts/eval_embeddings.py`

Docstring: replace the `logreg` usage line and the last sentence with

```
    uv run python scripts/eval_embeddings.py logreg [--train-corpus PATH] [--per-sender 5 10 20] [--min-precision 0.85]
```

(wrap to 110 columns if needed) and

```
The logistic regression is tested on the verified mails of data/taxonomy_corpus.json with 5 folds grouped by
domain (by sender on personal domains); each fold trains on the training corpus minus the fold's groups.
data/taxonomy_corpus.json and data/training_corpus.json (one row per --per-sender value) are compared.
```

Delete `sender_folds` and add, in its place:

```python
def fold_group(address: str) -> str:
    """Fold grouping key: the sender's domain, or the address itself on a non-commercial domain
    (Pass 3 only meets senders and domains no rule covers)."""
    from mailtag.utils.domain_utils import extract_domain, is_non_commercial_domain_cached

    address = address.strip().lower()
    domain = extract_domain(address) or address
    return address if is_non_commercial_domain_cached(domain) else domain


def group_folds(train_groups: list[str], test_groups: list[str], n_splits: int = 5):
    """(train indices, test positions): GroupKFold over the test mails by group; each fold trains on the
    training mails of every other group."""
    from sklearn.model_selection import GroupKFold

    train_arr, test_arr = np.array(train_groups), np.array(test_groups)
    for _, fold in GroupKFold(n_splits=n_splits).split(test_arr, groups=test_arr):
        yield np.where(~np.isin(train_arr, test_arr[fold]))[0], fold
```

Replace `logreg_eval` with:

```python
TAXONOMY_CORPUS = Path("data/taxonomy_corpus.json")
TRAINING_CORPUS = Path("data/training_corpus.json")


def logreg_eval(C: float, min_precision: float, train_corpus: Path | None, per_senders: list[int]) -> None:
    """Compare training corpora on the verified mails (domain-grouped folds), propose the [logreg]
    settings of the best one."""
    from mailtag.config import CONFIG
    from mailtag.logreg_provider import capped_indices, corpus_texts, embed, predict, train
    from mailtag.mlx_provider import MLXEmbedder

    corpus = json.loads(TAXONOMY_CORPUS.read_text(encoding="utf-8"))
    test = [m for m in corpus if m["verified"]]
    labels = [m["category"] for m in test]
    test_groups = [fold_group(m["sender"]) for m in test]
    embedder = MLXEmbedder(CONFIG.mlx.embedding_model)
    test_emb = embed(embedder, corpus_texts(test))

    def answers_for(rows: list[dict], emb: np.ndarray) -> list[tuple[str, float]]:
        answers: list = [None] * len(test)
        for train_idx, fold in group_folds([fold_group(m["sender"]) for m in rows], test_groups):
            model = train(emb[train_idx], [rows[i]["category"] for i in train_idx], C)
            cats, probs = predict(model, test_emb[fold])
            for i, c, p in zip(fold, cats, probs, strict=True):
                answers[int(i)] = (c, float(p))
        return answers

    # name -> (answers, training rows, per_sender or None)
    candidates: dict[str, tuple[list, list[dict], int | None]] = {}
    candidates[str(TAXONOMY_CORPUS)] = (answers_for(corpus, embed(embedder, corpus_texts(corpus))), corpus, None)
    harvested_path = train_corpus or (TRAINING_CORPUS if TRAINING_CORPUS.exists() else None)
    if harvested_path is not None and harvested_path != TAXONOMY_CORPUS:
        harvested = json.loads(harvested_path.read_text(encoding="utf-8"))
        harvested_emb = embed(embedder, corpus_texts(harvested))
        for n in per_senders:
            keep = capped_indices(harvested, n)
            rows = [harvested[i] for i in keep]
            candidates[f"{harvested_path} per_sender={n}"] = (answers_for(rows, harvested_emb[keep]), rows, n)

    # Centroids on the taxonomy corpus, same folds, for reference
    doc = embedder.encode(corpus_texts(corpus), prefix="search_document: ")
    query = embedder.encode(corpus_texts(test), prefix="search_query: ")
    centroid: list = [None] * len(test)
    for train_idx, fold in group_folds([fold_group(m["sender"]) for m in corpus], test_groups):
        top = leave_sender_out_top(
            doc[train_idx],
            [corpus[i]["category"] for i in train_idx],
            [corpus[i]["sender"] for i in train_idx],
            query[fold],
            [test[i]["sender"] for i in fold],
        )
        for i, (c, _) in zip(fold, top, strict=True):
            centroid[int(i)] = c
    print(f"\n{len(test)} verified mails, {len(set(test_groups))} fold groups (domains / personal senders), C={C:g}")
    print(f"centroids top-1: {np.mean([c == y for c, y in zip(centroid, labels, strict=True)]):.1%}")

    thresholds = [round(0.30 + 0.01 * i, 2) for i in range(70)]
    print(f"\n training corpus{'':48} mails  senders  top-1  classified@{min_precision:.0%}")
    scored = []
    for name, (answers, rows, n) in candidates.items():
        top1 = np.mean([a[0] == y for a, y in zip(answers, labels, strict=True)])
        best = best_threshold(confidence_sweep(answers, labels, thresholds), min_precision)
        coverage = best["auto"] if best else 0.0
        scored.append((coverage, top1, name))
        senders = len({m["sender"] for m in rows})
        print(f" {name:63} {len(rows):6} {senders:7} {top1:6.1%}  {coverage:6.1%}")

    _, _, winner = max(scored)
    answers, rows, n = candidates[winner]
    print(f"\nBest: {winner}")
    model = train(
        embed(embedder, corpus_texts(rows)), [m["category"] for m in rows], C
    )  # production cost per mail: embed + predict with the winner trained on all its rows
    start = time.perf_counter()
    predict(model, embed(embedder, corpus_texts(test)))
    print(f"{(time.perf_counter() - start) / len(test):.3f} s/email (embedding + prediction)")

    sweep = confidence_sweep(answers, labels, thresholds)
    print(" threshold  auto   precision  mails")
    for row in sweep:
        t, auto, precision, k = row["threshold"], row["auto"], row["precision"], row["classified"]
        print(f"   {t:.2f}    {auto:5.1%}  {precision:6.1%}  {k:5}")
    best = best_threshold(sweep, min_precision)
    classify = best["threshold"] if best else 1.01
    if best and best["classified"] < 30:
        print(f"WARNING: classify_threshold rests on {best['classified']} mails (< 30)")
    if not best:
        print(f"\nNo threshold reaches {min_precision:.0%} precision")
    print("\n[logreg]")
    if n is not None:
        print(f"per_sender = {n}")
    print(f"classify_threshold = {classify:.2f}\nlearn_threshold = {learn_threshold(sweep):.2f}")
```

Ruff will reflow long lines; keep logic identical. The `# production cost...` comment can move above the `model = train(...)` line if ruff format prefers.

In `main()`, replace the `logreg` subparser arguments and dispatch with:

```python
    p_logreg = sub.add_parser("logreg", help="Compare training corpora and propose the [logreg] settings")
    p_logreg.add_argument("--C", type=float, help="regularisation (default: [logreg] C)")
    p_logreg.add_argument("--min-precision", type=float, default=0.85)
    p_logreg.add_argument("--train-corpus", type=Path, help="harvested corpus (default: data/training_corpus.json)")
    p_logreg.add_argument("--per-sender", type=int, nargs="+", help="caps to compare (default: [logreg] per_sender)")
```

```python
    elif args.command == "logreg":
        from mailtag.config import CONFIG

        logreg_eval(
            args.C if args.C is not None else CONFIG.logreg.C,
            args.min_precision,
            args.train_corpus,
            args.per_sender or [CONFIG.logreg.per_sender],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_embeddings.py -v && uv run python scripts/eval_embeddings.py logreg --help`
Expected: all PASS; help lists `--train-corpus` and `--per-sender`. Do NOT run the evaluation itself (Task 4 does).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add scripts/eval_embeddings.py tests/test_eval_embeddings.py
git commit -m "feat(logreg): domain-grouped evaluation comparing training corpora"
```

---

### Task 4: Harvest the real mailbox, decide, document

**Files:**
- Modify: `config.toml` (`[logreg]` only, if the evaluation says so; `mode` stays `"mlx"`)
- Modify: `CLAUDE.md`, `scripts/CLAUDE.md`, `CHANGELOG.md`, `docs/superpowers/specs/2026-10-01-logreg-corpus-design.md` (append results)

**Interfaces:**
- Consumes: everything above; the real IMAP account (`.env` in the worktree), `data/taxonomy_corpus.json`, cached nomic weights.

- [ ] **Step 1: Harvest (read-only)**

Run: `uv run python scripts/taxonomy_setup.py harvest 2>&1 | tail -20` (timeout up to 45 minutes; it reads every category folder's headers, then the bodies of the kept mails).
Expected: `Wrote data/training_corpus.json: <N> mails, <S> senders`. `data/training_corpus.json` is git-ignored: never commit it. If it fails (connection, no mail kept), stop and report.

- [ ] **Step 2: Evaluate**

Run: `uv run python scripts/eval_embeddings.py logreg --per-sender 5 10 20 2>&1 | tee .superpowers/sdd/2026-10-01-logreg-corpus/logreg_corpus_eval.txt | tail -100` (timeout up to 30 minutes).
Expected: one row per candidate (`data/taxonomy_corpus.json`, then the harvested corpus at 5, 10, 20), `Best: …`, the sweep and a `[logreg]` block.

- [ ] **Step 3: Apply the decision**

- If `Best` is a `data/training_corpus.json per_sender=N` row: in `config.toml` `[logreg]`, set `per_sender = N` and the printed `classify_threshold` / `learn_threshold`; then run `uv run python scripts/taxonomy_setup.py train` (expect its log line to name `data/training_corpus.json`).
- If `Best` is `data/taxonomy_corpus.json`: set `[logreg] classify_threshold` / `learn_threshold` to the printed values (the domain-grouped protocol may move them), leave `per_sender = 10`, and move `data/training_corpus.json` to `data/training_corpus.rejected.json` so `train` keeps using the old corpus; then run `uv run python scripts/taxonomy_setup.py train` (expect its log line to name `data/taxonomy_corpus.json`).
- `[classifier] mode` stays `"mlx"` either way.

- [ ] **Step 4: Append results to the spec** — add to `docs/superpowers/specs/2026-10-01-logreg-corpus-design.md`:

```markdown
## Résultat (2026-10-01)

`harvest` : <N> mails, <S> expéditeurs. Évaluation (`eval_embeddings.py logreg --per-sender 5 10 20`), 403 mails vérifiés, plis groupés par domaine :

| Corpus d'entraînement | Mails | Expéditeurs | Top-1 | Classés à 85 % |
|---|---|---|---|---|
| taxonomy_corpus.json | … | … | … | … |
| training_corpus.json, per_sender=5 | … | … | … | … |
| training_corpus.json, per_sender=10 | … | … | … | … |
| training_corpus.json, per_sender=20 | … | … | … | … |

Centroïdes (mêmes plis) : … de top-1. Décision : <corpus retenu>, `classify_threshold = …` (<auto> classés, <précision> de précision, <k> mails), `learn_threshold = …`.
```

Fill every `…` and `<…>` from the evaluation output (French decimal commas), and add one sentence on the sampling noise if the threshold rests on fewer than 100 mails.

- [ ] **Step 5: Update the docs**

`CLAUDE.md`:
- In the **Logistic regression** paragraph, after the sentence about `train`, add: `` `scripts/taxonomy_setup.py harvest` (read-only, IMAP) builds `data/training_corpus.json` from the category folders: a mail counts only if its sender's rule gives its folder's category, at most 20 per sender; `train` prefers it, capped to `[logreg] per_sender`. `data/taxonomy_corpus.json` stays the test set (its verified mails) and the centroid source; `build` keeps it when a re-read loses more than half of it. The evaluation groups its folds by domain (by sender on personal domains). ``
- In the sentence listing the `scripts/taxonomy_setup.py` subcommands, add `harvest` after `train`.
- In **Data and backups**, add `data/training_corpus.json` to the `data/...` list.

`scripts/CLAUDE.md`: under `### taxonomy_setup.py` add `harvest` (read-only training corpus from the category folders, `--per-sender`, default 20); under `### eval_embeddings.py` update the `logreg` sentence: domain-grouped folds, compares `data/taxonomy_corpus.json` with `data/training_corpus.json` at each `--per-sender` value and proposes the `[logreg]` settings of the best.

`CHANGELOG.md`, under `## [Unreleased]`:

```markdown
### Added

- `scripts/taxonomy_setup.py harvest`: read-only training corpus for the logistic regression from the category folders (mail whose sender's rule matches its folder, at most 20 per sender); `train` prefers it, capped to `[logreg] per_sender`.

### Changed

- `scripts/eval_embeddings.py logreg` groups folds by domain (by sender on personal domains) and compares training corpora.

### Fixed

- `build` no longer overwrites `data/taxonomy_corpus.json` (the verified test set) with a re-read that lost more than half of it, as happens once legacy folders are migrated.
```

- [ ] **Step 6: Full verification**

Run: `make ci`
Expected: lint, format check, full test suite and build all pass.

- [ ] **Step 7: Commit**

```bash
git add config.toml CLAUDE.md scripts/CLAUDE.md CHANGELOG.md docs/superpowers/specs/2026-10-01-logreg-corpus-design.md
git commit -m "docs(logreg): harvested corpus results, decision, docs"
```
