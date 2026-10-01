# Logistic Regression for Pass 3 Implementation Plan

<!-- fmt:off -->
<!-- Code blocks below are plan fragments (class bodies, call arguments), not standalone modules. -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `[classifier] mode = "logreg"` switch in which a logistic regression over nomic embeddings alone decides Pass 3 (no Gemma, no centroids), with a `train` command that fits it from the corpus and an evaluation command that proposes its thresholds.

**Architecture:** A new `logreg_provider` module holds the pure functions (`embed`, `corpus_texts`, `train`, `predict`, `save_model`, `load_model`) and `LogRegClassifier`, which lazily loads `data/taxonomy_logreg.npz` and an `MLXEmbedder` once and returns `(category, probability)` per mail. scikit-learn fits the model (`taxonomy_setup.py train`, called by `build`); classifying is numpy only (`softmax(emb @ coef.T + intercept)`). `Classifier._classify_uncertain_detailed` delegates to it when `mode = "logreg"`, gating with `classify_threshold` / `learn_threshold`. `scripts/eval_embeddings.py logreg` trains per sender-grouped fold on the corpus and sweeps thresholds on the verified mails.

**Tech Stack:** Python 3.13, numpy, scikit-learn ≥ 1.5 (training only), sentence-transformers (nomic), pytest + pytest-mock, uv.

**Spec:** `docs/superpowers/specs/2026-10-01-logreg-pass3-design.md`

## Global Constraints

- `mode = "mlx"` stays the default; with it, behaviour is today's (existing tests unchanged and green). `laya` mode is untouched.
- Nothing is deleted: nomic centroids, Gemma, `crosscheck`, `review-scan`, Laya stay.
- Thresholds default to inert values: `classify_threshold = 1.01`, `learn_threshold = 1.01`; `C = 100.0`; `model_file = "data/taxonomy_logreg.npz"`.
- Model text is `nomic_text(sender_name, sender, subject, body)` embedded with the nomic prefix `"classification: "`, then L2-normalised.
- The `.npz` holds `classes`, `coef`, `intercept`, `embedding_model`; it is loaded with `allow_pickle=False`.
- scikit-learn is imported only inside training functions; classifying never imports it.
- In logreg mode, Gemma, centroids and Laya are never loaded. With `[mlx] enabled = false`, logreg mode sends every uncovered mail to `5-A revoir`.
- A failure of the model never stops a `run`: missing/invalid file or failed embedder load → review for the whole process; failed batch → that batch to review, next batch retries.
- Unknown `mode` → `ValueError` from the dataclass (`load_config` wraps it into `RuntimeError`).
- No test downloads a model or opens a network connection: tests use `tests/fake_embedder.py`.
- Line length 110, the repo's ruff rules, loguru for logging; code and docstrings in English like the rest of `src/`.
- Before every commit: `uv run ruff check . && uv run ruff format --check .` (CI also formats Python blocks inside Markdown).
- Commit messages end with:
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01M8Lt6kKGBKhRfA7hqfyHEL
  ```

## Review Focus

1. **Corpus with fewer than 3 categories**: scikit-learn then stores a single binary coefficient row and the softmax would be wrong. `train` must raise `ValueError`, and `taxonomy_setup.py train` must exit with a message instead of a traceback. Tests in Tasks 2 and 4.
2. **Model file trained with another embedding model** (`[mlx] embedding_model` changed after `train`): the classifier must send mail to review, never answer with mismatched vectors. Test in Task 2.
3. **Embedder fails to load** (offline, no cached weights): one attempt only, then review for the rest of the process — no reload per batch. Test in Task 2.
4. **`mode = "logreg"` with MLX disabled** (Docker): every uncovered mail goes to review, no network. Test in Task 3.
5. **Empty email list**: `classify([])` returns `[]` without loading anything. Test in Task 2.

---

### Task 1: Configuration and dependency

**Files:**
- Modify: `src/mailtag/config.py` (`ClassifierConfig`, new `LogRegConfig`, `AppConfig`, `load_config`)
- Modify: `config.toml` (`[classifier]` comment, new `[logreg]` section)
- Modify: `pyproject.toml` (dependency), `Dockerfile` (sed line), `uv.lock`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ClassifierConfig.mode` accepts `"logreg"`; `LogRegConfig(model_file: str = "data/taxonomy_logreg.npz", C: float = 100.0, classify_threshold: float = 1.01, learn_threshold: float = 1.01)`; `AppConfig.logreg: LogRegConfig` (default instance when absent); `load_config` reads `[logreg]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`)

```python
def test_logreg_defaults_and_mode():
    from mailtag.config import ClassifierConfig, LogRegConfig

    assert ClassifierConfig(mode="logreg").mode == "logreg"
    cfg = LogRegConfig()
    assert cfg.model_file == "data/taxonomy_logreg.npz"
    assert cfg.C == 100.0
    assert cfg.classify_threshold == 1.01
    assert cfg.learn_threshold == 1.01


def test_app_config_without_logreg_gets_defaults():
    from mailtag.config import (
        AppConfig,
        FastParseConfig,
        GmailConfig,
        ImapConfig,
        LoggingConfig,
        LogRegConfig,
        MLXConfig,
    )

    cfg = AppConfig(
        logging=LoggingConfig(level="INFO", file=""),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
    )
    assert cfg.logreg == LogRegConfig()


def test_load_config_reads_logreg(tmp_path, monkeypatch):
    from mailtag.config import load_config

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

[classifier]
mode = "logreg"

[logreg]
model_file = "m.npz"
C = 10.0
classify_threshold = 0.9
"""
    )

    cfg = load_config(toml)

    assert cfg.classifier.mode == "logreg"
    assert cfg.logreg.model_file == "m.npz"
    assert cfg.logreg.C == 10.0
    assert cfg.logreg.classify_threshold == 0.9
    assert cfg.logreg.learn_threshold == 1.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k logreg -v`
Expected: FAIL (`ImportError: cannot import name 'LogRegConfig'`, and `ValueError` on `mode="logreg"`).

- [ ] **Step 3: Implement**

In `src/mailtag/config.py`, replace `ClassifierConfig` with:

```python
@dataclass
class ClassifierConfig:
    """Pass 3 model: "mlx" (nomic + Gemma), "laya" (docs/superpowers/specs/2026-10-01-laya-*)
    or "logreg" (docs/superpowers/specs/2026-10-01-logreg-pass3-design.md)."""

    mode: str = "mlx"

    def __post_init__(self):
        if self.mode not in ("mlx", "laya", "logreg"):
            raise ValueError(f"[classifier] mode must be 'mlx', 'laya' or 'logreg', got {self.mode!r}")
```

Add after `LayaConfig`:

```python
@dataclass
class LogRegConfig:
    """Logistic regression over nomic embeddings (mode = "logreg"). Thresholds on the top probability
    come from `scripts/eval_embeddings.py logreg` (1.01 = never)."""

    model_file: str = "data/taxonomy_logreg.npz"
    C: float = 100.0  # LogisticRegression regularisation
    classify_threshold: float = 1.01
    learn_threshold: float = 1.01
```

In `AppConfig`, add the field after `laya` and its default in `__post_init__`:

```python
    logreg: LogRegConfig = None  # type: ignore[assignment]
```

```python
        if self.logreg is None:
            self.logreg = LogRegConfig()
```

In `load_config`, add to the `AppConfig(...)` call after `laya=...`:

```python
            logreg=_dataclass_from_dict(LogRegConfig, data.get("logreg", {})),
```

In `config.toml`, replace the `[classifier]` comment and add `[logreg]` right after the `[laya]` section (before `[taxonomy]`):

```toml
[classifier]
# Pass 3 model: "mlx" (nomic + Gemma, above) | "laya" (feasibility study,
# docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md; needs `uv sync --extra laya`)
# | "logreg" (logistic regression over nomic, docs/superpowers/specs/2026-10-01-logreg-pass3-design.md)
mode = "mlx"
```

```toml
[logreg]
model_file = "data/taxonomy_logreg.npz"  # written by `scripts/taxonomy_setup.py train`
C = 100.0
# Thresholds on the top probability, set by `scripts/eval_embeddings.py logreg` (1.01 = never)
classify_threshold = 1.01
learn_threshold = 1.01
```

In `pyproject.toml`, add after the `"sentence-transformers>=2.2.0",` line:

```toml
    "scikit-learn>=1.5",
```

In `Dockerfile`, add `/^\s*"scikit-learn>=/d; ` to the sed expression, right after `/^\s*"sentence-transformers>=/d; `.

Then relock: `uv lock` (expect `scikit-learn` unchanged at its locked version; it was already a transitive dependency).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all PASS (including the existing `test_unknown_mode_or_routing_is_refused`).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/mailtag/config.py config.toml pyproject.toml Dockerfile uv.lock tests/test_config.py
git commit -m "feat(logreg): [classifier] mode = \"logreg\" and the [logreg] section"
```

---

### Task 2: `logreg_provider` — train, predict, model file, classifier

**Files:**
- Create: `src/mailtag/logreg_provider.py`
- Create: `tests/fake_embedder.py`
- Test: `tests/test_logreg_provider.py`

**Interfaces:**
- Consumes: `LogRegConfig` (Task 1); `nomic_text`, `TAXONOMY` from `mailtag.taxonomy`; `MLXEmbedder(model_name)` from `mailtag.mlx_provider` (`.encode(texts, prefix=...) -> np.ndarray`, `.model` property loads weights).
- Produces:
  - `PREFIX = "classification: "`
  - `embed(embedder, texts: list[str]) -> np.ndarray` (L2-normalised rows)
  - `corpus_texts(corpus: list[dict]) -> list[str]` (corpus rows have `sender_name`, `sender`, `subject`, `body`, `category`, `verified`)
  - `train(embeddings: np.ndarray, categories: list[str], C: float) -> dict` with keys `classes`, `coef`, `intercept`; `ValueError` if fewer than 3 categories
  - `predict(model: dict, embeddings: np.ndarray) -> tuple[list[str], np.ndarray]` (category and top probability per row)
  - `save_model(path: Path, model: dict, embedding_model: str) -> None`
  - `load_model(path: Path, embedding_model: str) -> dict` (`ValueError` on other embedding model or category outside `TAXONOMY`)
  - `LogRegClassifier(config: LogRegConfig, embedding_model: str)` with `classify(emails: list[Email]) -> list[tuple[str, float] | None]`
  - `tests/fake_embedder.py`: `FakeEmbedder` (reused in Task 4)

- [ ] **Step 1: Create the test double** `tests/fake_embedder.py`

```python
"""Stands in for mailtag.mlx_provider.MLXEmbedder in tests: no download, no network."""

import numpy as np

WORDS = ("pizza", "impot", "train")


class FakeEmbedder:
    """One axis per keyword of WORDS found in the text, plus a constant axis so no vector is zero."""

    instances: list["FakeEmbedder"] = []
    fail_load = False

    def __init__(self, model_name: str = "fake"):
        self.model_name = model_name
        self.prefixes: list[str] = []
        self.fail = 0  # number of encode calls that raise
        FakeEmbedder.instances.append(self)

    @property
    def model(self):
        if FakeEmbedder.fail_load:
            raise OSError("no cached weights")
        return self

    def encode(self, texts, prefix="search_document: "):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("encode failed")
        self.prefixes.append(prefix)
        return np.array([[float(w in t.lower()) for w in WORDS] + [0.1] for t in texts])
```

- [ ] **Step 2: Write the failing tests** `tests/test_logreg_provider.py`

```python
import numpy as np
import pytest

from mailtag.config import LogRegConfig
from mailtag.logreg_provider import (
    PREFIX,
    LogRegClassifier,
    corpus_texts,
    embed,
    load_model,
    predict,
    save_model,
    train,
)
from mailtag.models import Email
from tests.fake_embedder import FakeEmbedder

CATS = ["Achats", "Impôts & Administration", "Transports & Mobilité"]
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEmbedder.instances = []
    FakeEmbedder.fail_load = False


def clusters(n=20, seed=0):
    """Three separable clusters in 4 dimensions, one per category of CATS."""
    rng = np.random.default_rng(seed)
    centers = np.array([[3, 0, 0, 0], [0, 3, 0, 0], [0, 0, 3, 0]], dtype=float)
    x = np.vstack([c + rng.normal(scale=0.5, size=(n, 4)) for c in centers])
    y = [cat for cat in CATS for _ in range(n)]
    return x, y


def mail(i=1, subject="pizza", body=""):
    return Email(msg_id=str(i), subject=subject, sender_address=f"s{i}@x.ch", sender_name="", body=body)


def trained_file(tmp_path, embedding_model=MODEL_NAME):
    """A model file trained on FakeEmbedder vectors of 'pizza'/'impot'/'train' mails."""
    texts = [w for w in ("pizza", "impot", "train") for _ in range(5)]
    model = train(embed(FakeEmbedder(), texts), [c for c in CATS for _ in range(5)], C=100.0)
    path = tmp_path / "logreg.npz"
    save_model(path, model, embedding_model)
    return path


def classifier(tmp_path, mocker, path=None):
    mocker.patch("mailtag.mlx_provider.MLXEmbedder", FakeEmbedder)
    config = LogRegConfig(model_file=str(path or tmp_path / "logreg.npz"))
    return LogRegClassifier(config, MODEL_NAME)


def test_predict_matches_scikit_learn_predict_proba():
    from sklearn.linear_model import LogisticRegression

    x, y = clusters()
    model = train(x, y, C=10.0)
    categories, probabilities = predict(model, x)

    reference = LogisticRegression(C=10.0, max_iter=3000).fit(x, y)
    proba = reference.predict_proba(x)
    assert categories == [str(c) for c in reference.classes_[proba.argmax(axis=1)]]
    assert probabilities == pytest.approx(proba.max(axis=1), abs=1e-6)


def test_train_refuses_fewer_than_three_categories():
    x, y = clusters()
    with pytest.raises(ValueError, match="3 categories"):
        train(x[:40], y[:40], C=10.0)


def test_embed_uses_the_classification_prefix_and_normalises():
    embedder = FakeEmbedder()

    emb = embed(embedder, ["pizza impot", "train"])

    assert embedder.prefixes == [PREFIX] == ["classification: "]
    assert np.linalg.norm(emb, axis=1) == pytest.approx([1.0, 1.0])


def test_corpus_texts_use_the_nomic_format():
    corpus = [{"sender_name": "Shop", "sender": "a@shop.ch", "subject": "Commande", "body": "Merci"}]

    assert corpus_texts(corpus) == ["Email from Shop: Commande\nMerci"]


def test_model_file_round_trip(tmp_path):
    x, y = clusters()
    model = train(x, y, C=10.0)
    save_model(tmp_path / "m.npz", model, MODEL_NAME)

    loaded = load_model(tmp_path / "m.npz", MODEL_NAME)

    assert loaded["classes"].tolist() == model["classes"].tolist()
    assert np.array_equal(loaded["coef"], model["coef"])
    assert np.array_equal(loaded["intercept"], model["intercept"])


def test_load_model_refuses_another_embedding_model(tmp_path):
    x, y = clusters()
    save_model(tmp_path / "m.npz", train(x, y, C=10.0), "other/model")

    with pytest.raises(ValueError, match="other/model"):
        load_model(tmp_path / "m.npz", MODEL_NAME)


def test_load_model_refuses_categories_outside_the_taxonomy(tmp_path):
    x, _ = clusters()
    y = [c for c in ("A", "B", "C") for _ in range(20)]
    save_model(tmp_path / "m.npz", train(x, y, C=10.0), MODEL_NAME)

    with pytest.raises(ValueError, match="taxonomy"):
        load_model(tmp_path / "m.npz", MODEL_NAME)


def test_classify_answers_category_and_probability(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))

    answers = clf.classify([mail(1, "pizza"), mail(2, "impot"), mail(3, "train")])

    assert [a[0] for a in answers] == CATS
    assert all(0.0 < a[1] <= 1.0 for a in answers)
    assert FakeEmbedder.instances[-1].prefixes == [PREFIX]


def test_classify_empty_list_loads_nothing(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))
    FakeEmbedder.instances = []

    assert clf.classify([]) == []
    assert FakeEmbedder.instances == []


def test_missing_model_file_sends_everything_to_review(tmp_path, mocker, caplog):
    clf = classifier(tmp_path, mocker)

    assert clf.classify([mail(1), mail(2)]) == [None, None]
    assert "taxonomy_setup.py train" in caplog.text


def test_model_of_another_embedding_model_sends_everything_to_review(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path, embedding_model="other/model"))

    assert clf.classify([mail()]) == [None]


def test_failed_embedder_load_is_tried_once(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))
    FakeEmbedder.instances = []
    FakeEmbedder.fail_load = True

    assert clf.classify([mail()]) == [None]
    assert clf.classify([mail()]) == [None]
    assert len(FakeEmbedder.instances) == 1


def test_failed_batch_goes_to_review_and_next_batch_retries(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))
    FakeEmbedder.instances = []
    clf.classify([])  # nothing loaded yet
    first = clf.classify([mail(1, "pizza")])
    FakeEmbedder.instances[-1].fail = 1

    assert first[0][0] == "Achats"
    assert clf.classify([mail(2, "pizza")]) == [None]
    assert clf.classify([mail(3, "train")])[0][0] == "Transports & Mobilité"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_logreg_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mailtag.logreg_provider'`.

- [ ] **Step 4: Implement** `src/mailtag/logreg_provider.py`

```python
"""Logistic regression over nomic embeddings for Pass 3 (`[classifier] mode = "logreg"`).

Spec: docs/superpowers/specs/2026-10-01-logreg-pass3-design.md. scikit-learn fits the model
(`scripts/taxonomy_setup.py train`); classifying is numpy only: softmax(emb @ coef.T + intercept),
the formula of LogisticRegression.predict_proba for three classes or more.
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

from .config import LogRegConfig
from .models import Email
from .taxonomy import TAXONOMY, nomic_text

if TYPE_CHECKING:
    from .mlx_provider import MLXEmbedder

PREFIX = "classification: "  # nomic's task prefix for classification


def embed(embedder, texts: list[str]) -> np.ndarray:
    """L2-normalised nomic embeddings of `texts`, with the classification prefix."""
    emb = np.asarray(embedder.encode(texts, prefix=PREFIX), dtype=np.float64)
    return emb / np.linalg.norm(emb, axis=1, keepdims=True)


def corpus_texts(corpus: list[dict]) -> list[str]:
    """The production nomic text of each corpus mail."""
    return [nomic_text(m["sender_name"], m["sender"], m["subject"], m["body"]) for m in corpus]


def train(embeddings: np.ndarray, categories: list[str], C: float) -> dict:
    """Multinomial logistic regression; needs 3 categories or more (binary keeps a single row)."""
    if len(set(categories)) < 3:
        raise ValueError(f"Training needs mails in at least 3 categories, got {sorted(set(categories))}")
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=C, max_iter=3000).fit(embeddings, categories)
    return {"classes": model.classes_.astype(str), "coef": model.coef_, "intercept": model.intercept_}


def predict(model: dict, embeddings: np.ndarray) -> tuple[list[str], np.ndarray]:
    """Top category and its probability for each row."""
    logits = embeddings @ model["coef"].T + model["intercept"]
    logits -= logits.max(axis=1, keepdims=True)
    proba = np.exp(logits)
    proba /= proba.sum(axis=1, keepdims=True)
    best = proba.argmax(axis=1)
    return [str(model["classes"][i]) for i in best], proba[np.arange(len(best)), best]


def save_model(path: Path, model: dict, embedding_model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        classes=model["classes"],
        coef=model["coef"],
        intercept=model["intercept"],
        embedding_model=np.array(embedding_model),
    )


def load_model(path: Path, embedding_model: str) -> dict:
    """The model in `path`; ValueError if it was trained for another embedding model or taxonomy."""
    with np.load(path, allow_pickle=False) as data:
        model = {key: data[key] for key in ("classes", "coef", "intercept")}
        trained_with = str(data["embedding_model"])
    if trained_with != embedding_model:
        raise ValueError(f"{path} was trained with {trained_with}, [mlx] embedding_model is {embedding_model}")
    if unknown := sorted(set(model["classes"].tolist()) - set(TAXONOMY)):
        raise ValueError(f"{path} has categories outside the taxonomy: {unknown}")
    return model


class LogRegClassifier:
    """(category, probability) per mail, or None when the model could not answer."""

    def __init__(self, config: LogRegConfig, embedding_model: str):
        self.config = config
        self.embedding_model = embedding_model
        self._lock = threading.Lock()
        self._loaded = False
        self._model: dict | None = None
        self._embedder: MLXEmbedder | None = None

    def _load(self) -> bool:
        """Load the model file and the embedder once; False if either is unavailable."""
        with self._lock:
            if self._loaded:
                return self._model is not None
            self._loaded = True
            path = Path(self.config.model_file)
            if not path.is_file():
                logger.warning(
                    f"No logistic regression model at {path} (run `scripts/taxonomy_setup.py train`), "
                    "sending emails to review"
                )
                return False
            try:
                model = load_model(path, self.embedding_model)
                from .mlx_provider import MLXEmbedder

                embedder = MLXEmbedder(self.embedding_model)
                _ = embedder.model  # load the weights now: a failed load is not retried every batch
            except Exception as e:  # a missing model must never stop a run
                logger.error(
                    f"Failed to load the logistic regression model ({type(e).__name__}), "
                    f"sending emails to review: {e}"
                )
                return False
            self._model, self._embedder = model, embedder
            return True

    def classify(self, emails: list[Email]) -> list[tuple[str, float] | None]:
        if not emails:
            return []
        if not self._load():
            return [None] * len(emails)
        texts = [nomic_text(e.sender_name, e.sender_address, e.subject, e.body) for e in emails]
        try:
            categories, probabilities = predict(self._model, embed(self._embedder, texts))
        except Exception as e:  # torch, MPS...: never stop a run
            logger.error(f"Logistic regression batch failed ({type(e).__name__}), sending emails to review: {e}")
            return [None] * len(emails)
        return [(c, float(p)) for c, p in zip(categories, probabilities, strict=True)]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_logreg_provider.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/mailtag/logreg_provider.py tests/fake_embedder.py tests/test_logreg_provider.py
git commit -m "feat(logreg): logistic regression provider over nomic embeddings"
```

---

### Task 3: `Classifier` in logreg mode

**Files:**
- Modify: `src/mailtag/classifier.py` (import, `__init__`, class docstring, `_classify_uncertain_detailed`, new `_classify_logreg`)
- Test: `tests/test_classifier_taxonomy.py`

**Interfaces:**
- Consumes: `LogRegClassifier(config.logreg, config.mlx.embedding_model).classify(emails) -> list[tuple[str, float] | None]` (Task 2); `AppConfig.logreg` (Task 1).
- Produces: `Classifier._logreg: LogRegClassifier | None`; `Classifier._classify_logreg(emails) -> list[tuple[str, bool]]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_classifier_taxonomy.py`; add `LogRegConfig` to the `mailtag.config` import list, keeping it sorted)

```python
def _logreg_classifier(tmp_path, answers, mocker, classify=0.9, learn=0.97):
    config = _config(tmp_path)
    config.mlx = MLXConfig(enabled=True)
    config.classifier = ClassifierConfig(mode="logreg")
    config.logreg = LogRegConfig(classify_threshold=classify, learn_threshold=learn)
    classifier = Classifier(config=config)
    mocker.patch.object(classifier._logreg, "classify", return_value=answers)
    return classifier


def test_logreg_mode_applies_its_thresholds_inclusively(tmp_path, mocker):
    answers = [
        ("Santé", 0.89),  # below classify
        ("Santé", 0.9),  # exactly classify: inclusive
        ("Achats", 0.97),  # exactly learn: inclusive
        None,  # the model could not answer
    ]
    classifier = _logreg_classifier(tmp_path, answers, mocker)

    assert classifier._classify_uncertain_detailed([mail(i) for i in range(4)]) == [
        (REVIEW, False),
        ("Santé", False),
        ("Achats", True),
        (REVIEW, False),
    ]


def test_logreg_mode_never_learns_with_the_inert_default(tmp_path, mocker):
    classifier = _logreg_classifier(tmp_path, [("Santé", 1.0)], mocker, classify=0.5, learn=1.01)

    assert classifier._classify_uncertain_detailed([mail()]) == [("Santé", False)]


def test_logreg_mode_runs_rules_first_and_never_calls_gemma_or_centroids(tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    classifier = _logreg_classifier(tmp_path, [("Achats", 0.99)], mocker)
    mlx = mocker.patch.object(classifier, "_init_mlx_components")
    llm = mocker.patch.object(classifier, "_llm_categories")

    result = classifier.classify_detailed([mail(1, sender="v@x.ch"), mail(2, sender="new@shop.ch")])

    assert result == [("Santé", False), ("Achats", True)]
    assert [e.sender_address for e in classifier._logreg.classify.call_args.args[0]] == ["new@shop.ch"]
    mlx.assert_not_called()
    llm.assert_not_called()


def test_logreg_mode_agreements_teach_rules(tmp_path, mocker):
    classifier = _logreg_classifier(tmp_path, [("Santé", 0.98)], mocker)

    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])
    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])

    learned = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert learned["doc@clinic.ch"]["category"] == "Santé"


def test_logreg_mode_without_mlx_sends_uncovered_mail_to_review(tmp_path, mocker):
    network = mocker.patch("socket.socket.connect", side_effect=AssertionError("no network"))
    config = _config(tmp_path)  # MLX disabled
    config.classifier = ClassifierConfig(mode="logreg")
    classifier = Classifier(config=config)

    assert classifier._logreg is None
    assert classify_and_learn(classifier, [mail(sender="new@unknown.ch")]) == [REVIEW]
    network.assert_not_called()


def test_mlx_mode_builds_no_logreg_classifier(classifier):
    assert classifier._logreg is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_classifier_taxonomy.py -k logreg -v`
Expected: FAIL (`AttributeError: 'Classifier' object has no attribute '_logreg'`).

- [ ] **Step 3: Implement** in `src/mailtag/classifier.py`

Add the import next to the Laya one:

```python
from .logreg_provider import LogRegClassifier
```

Class docstring, last line becomes:

```python
    With [classifier] mode = "laya", Laya replaces nomic and the LLM; with mode = "logreg", a logistic
    regression over nomic embeddings does.
```

In `__init__`, right after the `self._laya = ...` line:

```python
        # Logistic regression over nomic replaces centroids + Gemma in Pass 3 (mode = "logreg")
        self._logreg = (
            LogRegClassifier(config.logreg, config.mlx.embedding_model)
            if config.classifier.mode == "logreg" and config.mlx.enabled
            else None
        )
```

At the top of `_classify_uncertain_detailed`, after the Laya delegation (`if self._laya is not None: return self._classify_laya(emails)`):

```python
        if self.config.classifier.mode == "logreg":
            return self._classify_logreg(emails)
```

Add the method after `_classify_laya`:

```python
    def _classify_logreg(self, emails: list[Email]) -> list[tuple[str, bool]]:
        """(category, sure enough to learn from) per email; below classify_threshold, or without MLX,
        → review."""
        if self._logreg is None:
            return [(REVIEW, False)] * len(emails)
        thresholds = self.config.logreg
        return [
            (answer[0], answer[1] >= thresholds.learn_threshold)
            if answer is not None and answer[1] >= thresholds.classify_threshold
            else (REVIEW, False)
            for answer in self._logreg.classify(emails)
        ]
```

Also update the `_classify_uncertain_detailed` docstring's last line to: `In laya mode, Laya alone with its per-checkpoint thresholds; in logreg mode, the logistic regression alone.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_classifier_taxonomy.py -v`
Expected: all PASS (existing mlx and laya tests unchanged).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/mailtag/classifier.py tests/test_classifier_taxonomy.py
git commit -m "feat(logreg): Classifier uses the logistic regression alone in logreg mode"
```

---

### Task 4: `taxonomy_setup.py train` (and `build` calls it)

**Files:**
- Modify: `scripts/taxonomy_setup.py` (docstring, new `train()`, end of `build()`, `main()`)
- Test: `tests/test_taxonomy_setup.py`

**Interfaces:**
- Consumes: `corpus_texts`, `embed`, `train`, `save_model` from `mailtag.logreg_provider` (Task 2); `CONFIG.logreg` (Task 1); `tests.fake_embedder.FakeEmbedder` (Task 2).
- Produces: `scripts.taxonomy_setup.train() -> None` (reads module-level `CORPUS`, writes `CONFIG.logreg.model_file`; `sys.exit` with a message when the corpus is missing or has fewer than 3 categories).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_taxonomy_setup.py`)

```python
TRAIN_MAILS = [
    {"sender": f"s{i}@x.ch", "sender_name": "", "subject": word, "body": "", "category": cat, "verified": False}
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_taxonomy_setup.py -k train -v`
Expected: FAIL (`AttributeError: module 'scripts.taxonomy_setup' has no attribute 'train'`).

- [ ] **Step 3: Implement** in `scripts/taxonomy_setup.py`

Module docstring: after the `build` line add

```
    uv run python scripts/taxonomy_setup.py train       # logistic regression from the corpus (also run by build)
```

Add after `build()`:

```python
def train() -> None:
    """Fit the [logreg] model on every corpus mail (no IMAP, no rule touched)."""
    from mailtag.logreg_provider import corpus_texts, embed, save_model
    from mailtag.logreg_provider import train as fit
    from mailtag.mlx_provider import MLXEmbedder

    if missing := missing_inputs([CORPUS]):
        sys.exit(f"Missing {missing[0]}: run `build` first")
    corpus = _read(CORPUS)
    if len({m["category"] for m in corpus}) < 3:
        sys.exit(f"{CORPUS} needs mails in at least 3 categories to train")
    embedding_model = CONFIG.mlx.embedding_model
    embeddings = embed(MLXEmbedder(embedding_model), corpus_texts(corpus))
    model = fit(embeddings, [m["category"] for m in corpus], CONFIG.logreg.C)
    save_model(Path(CONFIG.logreg.model_file), model, embedding_model)
    logger.info(
        f"Logistic regression from {len(corpus)} mails, {len(model['classes'])} categories "
        f"-> {CONFIG.logreg.model_file}"
    )
```

At the end of `build()`, after the centroid log line:

```python
    train()
```

In `main()`, add `"train"` to the `choices` list (after `"build"`) and to the final dispatch dict:

```python
        {"scan": scan, "crosscheck": crosscheck, "build": build, "train": train}[args.command]()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_taxonomy_setup.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add scripts/taxonomy_setup.py tests/test_taxonomy_setup.py
git commit -m "feat(logreg): taxonomy_setup.py train, run by build after the centroids"
```

---

### Task 5: `eval_embeddings.py logreg`

**Files:**
- Modify: `scripts/eval_embeddings.py` (docstring, new `sender_folds`, new `logreg_eval`, `main()`)
- Test: `tests/test_eval_embeddings.py`

**Interfaces:**
- Consumes: `corpus_texts`, `embed`, `train`, `predict` from `mailtag.logreg_provider` (Task 2); existing `leave_sender_out_top`, `confidence_sweep`, `best_threshold`, `learn_threshold` in the same script; `CONFIG.logreg.C` (Task 1).
- Produces: `sender_folds(senders: list[str], test_idx: list[int], n_splits: int = 5)` yielding `(train: np.ndarray, test: np.ndarray)` index arrays; `logreg_eval(C: float, min_precision: float) -> None`; CLI `logreg [--C C] [--min-precision P]`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_embeddings.py`)

```python
def test_sender_folds_never_share_a_sender_and_test_each_verified_mail_once():
    from scripts.eval_embeddings import sender_folds

    senders = [f"s{i % 7}@x.ch" for i in range(40)]  # 7 senders
    test_idx = [i for i in range(40) if i % 2 == 0]  # the "verified" mails

    tested = []
    for train, test in sender_folds(senders, test_idx, n_splits=3):
        assert not {senders[i] for i in train} & {senders[i] for i in test}
        assert set(test) <= set(test_idx)
        assert len(train) > 0
        tested += test.tolist()

    assert sorted(tested) == test_idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_eval_embeddings.py -k sender_folds -v`
Expected: FAIL with `ImportError: cannot import name 'sender_folds'`.

- [ ] **Step 3: Implement** in `scripts/eval_embeddings.py`

Module docstring becomes:

```python
"""Measure the taxonomy chain (Signals 5-6) on verified mails and pick the nomic threshold,
measure Laya and propose its per-checkpoint thresholds, or measure the logistic regression
and propose the [logreg] thresholds.

    uv run python scripts/eval_embeddings.py chain -n 500
    uv run python scripts/eval_embeddings.py laya -n 500 [--routing multilingual] [--rotations]
    uv run python scripts/eval_embeddings.py logreg [--C 100] [--min-precision 0.85]

Category centroids are built leave-sender-out from data/taxonomy_corpus.json, and the LLM step
runs through Classifier._llm_categories, so results reflect what production would do. Laya runs
through LayaClassifier with the [laya] settings of config.toml (overridable by flag). The logistic
regression trains per fold on the corpus minus the fold's senders, with logreg_provider's functions.
"""
```

Add after `laya_eval`:

```python
def sender_folds(senders: list[str], test_idx: list[int], n_splits: int = 5):
    """(train, test) index arrays: each fold tests some of `test_idx`, grouped by sender, and trains on
    every corpus mail whose sender is not among the fold's senders (as Pass 3 meets unknown senders)."""
    from sklearn.model_selection import GroupKFold

    senders_arr = np.array(senders)
    test_arr = np.array(test_idx)
    for _, fold in GroupKFold(n_splits=n_splits).split(test_arr, groups=senders_arr[test_arr]):
        test = test_arr[fold]
        yield np.where(~np.isin(senders_arr, senders_arr[test]))[0], test


def logreg_eval(C: float, min_precision: float) -> None:
    """Train per sender-grouped fold, test on the verified mails, propose the [logreg] thresholds."""
    from mailtag.config import CONFIG
    from mailtag.logreg_provider import corpus_texts, embed, predict, train
    from mailtag.mlx_provider import MLXEmbedder

    corpus = json.loads(Path("data/taxonomy_corpus.json").read_text(encoding="utf-8"))
    senders = [m["sender"] for m in corpus]
    categories = [m["category"] for m in corpus]
    test_idx = [i for i, m in enumerate(corpus) if m["verified"]]
    embedder = MLXEmbedder(CONFIG.mlx.embedding_model)
    texts = corpus_texts(corpus)
    emb = embed(embedder, texts)
    doc = embedder.encode(texts, prefix="search_document: ")
    query = embedder.encode(texts, prefix="search_query: ")

    answers: dict[int, tuple[str, float]] = {}
    centroid: dict[int, str | None] = {}
    for train_idx, fold in sender_folds(senders, test_idx):
        model = train(emb[train_idx], [categories[i] for i in train_idx], C)
        cats, probs = predict(model, emb[fold])
        answers.update({int(i): (c, float(p)) for i, c, p in zip(fold, cats, probs, strict=True)})
        top = leave_sender_out_top(
            doc[train_idx],
            [categories[i] for i in train_idx],
            [senders[i] for i in train_idx],
            query[fold],
            [senders[i] for i in fold],
        )
        centroid.update({int(i): c for i, (c, _) in zip(fold, top, strict=True)})

    # Production cost per mail: embed + predict with a model trained on the whole corpus
    model = train(emb, categories, C)
    start = time.perf_counter()
    predict(model, embed(embedder, [texts[i] for i in test_idx]))
    seconds = (time.perf_counter() - start) / len(test_idx)

    labels = [categories[i] for i in test_idx]
    ordered = [answers[i] for i in test_idx]
    logreg_top1 = np.mean([a[0] == y for a, y in zip(ordered, labels, strict=True)])
    centroid_top1 = np.mean([centroid[i] == categories[i] for i in test_idx])
    print(f"\n{len(test_idx)} verified mails, {len({senders[i] for i in test_idx})} senders, C={C:g}")
    print(f"top-1: logistic regression {logreg_top1:.1%}, centroids {centroid_top1:.1%}")
    print(f"{seconds:.3f} s/email (embedding + prediction)")

    sweep = confidence_sweep(ordered, labels, [round(0.30 + 0.01 * i, 2) for i in range(70)])
    print(" threshold  auto   precision  mails")
    for row in sweep:
        t, auto, precision, n = row["threshold"], row["auto"], row["precision"], row["classified"]
        print(f"   {t:.2f}    {auto:5.1%}  {precision:6.1%}  {n:5}")

    best = best_threshold(sweep, min_precision)
    classify = best["threshold"] if best else 1.01
    if best:
        print(f"\nclassify_threshold {classify:.2f}: {best['auto']:.1%} classified at {best['precision']:.1%}")
        if best["classified"] < 30:
            print(f"WARNING: classify_threshold rests on {best['classified']} mails (< 30)")
    else:
        print(f"\nNo threshold reaches {min_precision:.0%} precision")
    print(f"\n[logreg]\nclassify_threshold = {classify:.2f}\nlearn_threshold = {learn_threshold(sweep):.2f}")
```

Note: keep the imports inside `logreg_eval` grouped as ruff's isort wants (one block `from mailtag...`); run `uv run ruff check . --fix` if isort reorders them.

In `main()`, add the subparser after `p_laya`'s arguments:

```python
    p_logreg = sub.add_parser("logreg", help="Measure the logistic regression and propose its thresholds")
    p_logreg.add_argument("--C", type=float, help="regularisation (default: [logreg] C)")
    p_logreg.add_argument("--min-precision", type=float, default=0.85)
```

and the dispatch after the `laya` branch:

```python
    elif args.command == "logreg":
        from mailtag.config import CONFIG

        logreg_eval(args.C if args.C is not None else CONFIG.logreg.C, args.min_precision)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_embeddings.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add scripts/eval_embeddings.py tests/test_eval_embeddings.py
git commit -m "feat(logreg): eval_embeddings.py logreg — sender-grouped folds, proposed thresholds"
```

---

### Task 6: Train on the real corpus, measure, set thresholds, document

**Files:**
- Modify: `config.toml` (`[logreg]` thresholds only; `mode` stays `"mlx"`)
- Modify: `CLAUDE.md`, `src/mailtag/CLAUDE.md`, `scripts/CLAUDE.md`, `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-10-01-logreg-pass3-design.md` (append measured results)

**Interfaces:**
- Consumes: everything above; real `data/taxonomy_corpus.json` (2 525 mails, 403 verified) and the cached nomic weights on this Mac.

- [ ] **Step 1: Train the production model**

Run: `uv run python scripts/taxonomy_setup.py train`
Expected: log line `Logistic regression from 2525 mails, 19 categories -> data/taxonomy_logreg.npz` (the file is git-ignored under `data/`; do not commit it).

- [ ] **Step 2: Run the evaluation**

Run: `uv run python scripts/eval_embeddings.py logreg 2>&1 | tee /tmp/logreg_eval.txt | tail -90`
Expected (from the spike; small differences are fine): top-1 near 51 % for the logistic regression and near 37 % for the centroids, a proposed `classify_threshold` near 0.90 at about 21 % classified and about 85 % precision, `learn_threshold = 1.01`. If the numbers differ by more than 5 points from these, stop and report them instead of continuing.

- [ ] **Step 3: Write the proposed thresholds** into `config.toml` `[logreg]` (replace the two `1.01` lines with the printed `classify_threshold` / `learn_threshold` values). Leave `[classifier] mode = "mlx"`.

- [ ] **Step 4: Append the results to the spec** `docs/superpowers/specs/2026-10-01-logreg-pass3-design.md`:

```markdown
## Résultat (2026-10-01)

`uv run python scripts/eval_embeddings.py logreg` sur 403 mails vérifiés (94 expéditeurs), 5 plis groupés par expéditeur :

| | Valeur |
|---|---|
| Top-1 régression logistique | <printed> |
| Top-1 centroïdes (mêmes plis) | <printed> |
| `classify_threshold` proposé | <printed> (<auto> classés, <precision> de précision) |
| `learn_threshold` proposé | <printed> |
| Secondes par mail | <printed> |

Seuils écrits dans `config.toml` ; `mode` reste `mlx` jusqu'à la bascule par le propriétaire.
```

Replace each `<printed>`/`<auto>`/`<precision>` with the actual numbers from `/tmp/logreg_eval.txt` before committing.

- [ ] **Step 5: Update the docs**

`CLAUDE.md`:
- After the **Laya (feasibility study)** paragraph, add:

```markdown
**Logistic regression**: `[classifier] mode = "logreg"` replaces nomic centroids and Gemma in Pass 3 with a logistic regression over nomic embeddings (`src/mailtag/logreg_provider.py`; spec `docs/superpowers/specs/2026-10-01-logreg-pass3-design.md`). `scripts/taxonomy_setup.py train` (also run by `build`) fits it on `data/taxonomy_corpus.json` and writes `data/taxonomy_logreg.npz` (classes, coefficients, intercepts, embedding model; numpy only at run time). A mail is classified at top probability ≥ `[logreg] classify_threshold` and counts as an agreement at ≥ `learn_threshold`; `uv run python scripts/eval_embeddings.py logreg` proposes both (target 85 % precision on unknown senders). Gemma stays for `crosscheck` and `review-scan`; with `[mlx] enabled = false` logreg mode sends uncovered mail to `5-A revoir`.
```

- In the Pass 3 line of **Classification flow**, change `In laya mode, Laya alone decides (see AI Model Configuration).` to `In laya mode Laya alone decides, in logreg mode the logistic regression alone (see AI Model Configuration).`
- In **Configuration System**, the section list becomes `logging`, `imap`, `gmail`, `fast_parse`, `mlx`, `classifier`, `laya`, `logreg`, `taxonomy`, `webhook`.
- In the sentence listing `scripts/taxonomy_setup.py` subcommands, add `train` after `build`.
- In **Data and backups**, add `data/taxonomy_logreg.npz` to the `data/...` list.

`src/mailtag/CLAUDE.md`: after the `laya_provider.py` line add

```markdown
- **logreg_provider.py** - `LogRegClassifier`: logistic regression over nomic embeddings, `(category, probability)` per mail (mode = "logreg"); `train`, `predict`, `save_model`, `load_model`
```

`scripts/CLAUDE.md`: under `### taxonomy_setup.py` mention `train` (fits `data/taxonomy_logreg.npz` from the corpus; `build` runs it); under `### eval_embeddings.py`, after the `chain` sentence add: `` `logreg` trains per sender-grouped fold and proposes the `[logreg]` thresholds (`--min-precision`, default 0.85). ``

`CHANGELOG.md`, under `## [Unreleased]`:

```markdown
### Added

- `[classifier] mode = "logreg"`: a logistic regression over nomic embeddings alone decides Pass 3 (no Gemma, no centroids), with `[logreg]` thresholds; `scripts/taxonomy_setup.py train` (also run by `build`) fits it and `scripts/eval_embeddings.py logreg` measures it on unknown senders and proposes the thresholds. The default mode stays `mlx`.
```

- [ ] **Step 6: Full verification**

Run: `make ci`
Expected: lint, format check, full test suite and build all pass.

- [ ] **Step 7: Commit**

```bash
git add config.toml CLAUDE.md src/mailtag/CLAUDE.md scripts/CLAUDE.md CHANGELOG.md docs/superpowers/specs/2026-10-01-logreg-pass3-design.md
git commit -m "docs(logreg): measured thresholds, CLAUDE.md, changelog"
```
