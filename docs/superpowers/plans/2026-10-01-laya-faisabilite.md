# Laya Feasibility Study Implementation Plan

<!-- fmt:off -->
<!-- Code blocks below are plan fragments (class bodies, call arguments), not standalone modules. -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `[classifier] mode = "laya"` switch that replaces nomic + Gemma in Pass 3 with the Laya classifier, plus an evaluation command that measures it on the verified corpus and proposes per-checkpoint thresholds.

**Architecture:** A new `laya_provider.LayaClassifier` wraps one lazily built `laya.Router`: it routes each mail to the `english` or `multilingual` checkpoint, asks one `choice` question over the 19 categories in that checkpoint's language, and returns `(category, answer_confidence, checkpoint)`. `Classifier._classify_uncertain_detailed` uses it when `mode = "laya"`; per-checkpoint thresholds decide classify/learn. `scripts/eval_embeddings.py laya` runs the same provider on the corpus and sweeps thresholds.

**Tech Stack:** Python 3.13, `laya` 0.3.22 (optional extra, pulls `torch`), pytest + pytest-mock, uv.

**Spec:** `docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md`

## Global Constraints

- `mode = "mlx"` stays the default; with it, behaviour is byte-for-byte today's (existing tests unchanged and green).
- Nothing is deleted: nomic, Gemma, MLX, centroids, `crosscheck`, `review-scan` are untouched.
- `laya` is an optional extra: `laya = ["laya>=0.3.22"]`; `laya` is never imported in mlx mode, MLX never loaded in laya mode.
- Initial thresholds are inert: `classify_threshold = 1.01`, `learn_threshold = 1.01` for both checkpoints.
- Gate on `answer_confidence` (max p), never `confidence` or `act_probability`.
- Choice labels are semantic (category names), never `yes`/`no`/`true`/`false`.
- `USE_TF=0` is set (`os.environ.setdefault`) before `import laya`.
- Unknown `mode` or `routing` → `ValueError` from the dataclass (`load_config` wraps it into `RuntimeError`, as for every config error).
- No test downloads a model: tests use a fake `laya` module in `sys.modules`.
- Line length 110, ruff rules of the repo, loguru for logging, French comments are not required (code and docstrings are in English like the rest of `src/`).
- Commit messages end with:
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01M8Lt6kKGBKhRfA7hqfyHEL
  ```

## Review Focus

1. **Router returns a checkpoint we did not ask about** (e.g. `typed-decisions`, or an alias like `ml`): `LayaClassifier` must only ever send `english` or `multilingual`; anything else is treated as `multilingual`. Test in Task 3.
2. **Mail with empty subject and body** (only a sender): must not crash; it is classified or sent to review like any other mail. Test in Task 3.
3. **`predict_batch` raises on the first call** (checkpoint download fails offline): the whole batch goes to review, the next call retries. Test in Task 3.
4. **Threshold at exactly the confidence value**: `confidence >= classify_threshold` classifies (inclusive), and `learn_threshold = 1.01` never learns even at confidence 1.0. Test in Task 4.
5. **Eval checkpoint with fewer than 30 answered mails**: `learn_threshold` stays 1.01 and the report still prints. Test in Task 5.

---

### Task 1: Configuration (`[classifier]`, `[laya]`) and neutral calibration file

**Files:**
- Modify: `src/mailtag/config.py`
- Modify: `config.toml` (add two sections after `[mlx]`)
- Create: `data/laya_neutral_calibration.json`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `ClassifierConfig(mode: str = "mlx")`, raises `ValueError` if `mode not in ("mlx", "laya")`.
  - `LayaThresholds(classify_threshold: float = 1.01, learn_threshold: float = 1.01)`.
  - `LayaConfig(routing="router", device="auto", batch_size=16, head_max_len=512, max_len=1024, rotations=False, body_chars=1500, calibration="data/laya_neutral_calibration.json", english=LayaThresholds(), multilingual=LayaThresholds())`, raises `ValueError` if `routing not in ("router", "multilingual")`; method `thresholds(checkpoint: str) -> LayaThresholds` (`english` → `self.english`, anything else → `self.multilingual`).
  - `AppConfig.classifier: ClassifierConfig`, `AppConfig.laya: LayaConfig` (default instances when omitted).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`)

```python
def test_classifier_and_laya_defaults():
    from mailtag.config import ClassifierConfig, LayaConfig, LayaThresholds

    assert ClassifierConfig().mode == "mlx"
    cfg = LayaConfig()
    assert cfg.routing == "router"
    assert cfg.device == "auto"
    assert cfg.batch_size == 16
    assert cfg.head_max_len == 512
    assert cfg.max_len == 1024
    assert cfg.rotations is False
    assert cfg.body_chars == 1500
    assert cfg.calibration == "data/laya_neutral_calibration.json"
    assert cfg.english == LayaThresholds(classify_threshold=1.01, learn_threshold=1.01)
    assert cfg.multilingual == LayaThresholds(classify_threshold=1.01, learn_threshold=1.01)


def test_laya_thresholds_by_checkpoint():
    from mailtag.config import LayaConfig, LayaThresholds

    cfg = LayaConfig(english=LayaThresholds(0.5, 0.9), multilingual=LayaThresholds(0.6, 0.95))
    assert cfg.thresholds("english") == LayaThresholds(0.5, 0.9)
    assert cfg.thresholds("multilingual") == LayaThresholds(0.6, 0.95)
    assert cfg.thresholds("typed-decisions") == LayaThresholds(0.6, 0.95)


def test_unknown_mode_or_routing_is_refused():
    from mailtag.config import ClassifierConfig, LayaConfig

    with pytest.raises(ValueError, match="mode"):
        ClassifierConfig(mode="gemma")
    with pytest.raises(ValueError, match="routing"):
        LayaConfig(routing="english")


def test_app_config_without_classifier_or_laya_gets_defaults():
    from mailtag.config import (
        AppConfig,
        ClassifierConfig,
        FastParseConfig,
        GmailConfig,
        ImapConfig,
        LayaConfig,
        LoggingConfig,
        MLXConfig,
    )

    cfg = AppConfig(
        logging=LoggingConfig(level="INFO", file=""),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
    )
    assert cfg.classifier == ClassifierConfig()
    assert cfg.laya == LayaConfig()


def test_load_config_reads_classifier_and_laya(tmp_path, monkeypatch):
    from mailtag.config import LayaThresholds, load_config

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
mode = "laya"

[laya]
routing = "multilingual"
batch_size = 4
english = { classify_threshold = 0.7, learn_threshold = 0.95 }
multilingual = { classify_threshold = 0.8 }
"""
    )

    cfg = load_config(toml)

    assert cfg.classifier.mode == "laya"
    assert cfg.laya.routing == "multilingual"
    assert cfg.laya.batch_size == 4
    assert cfg.laya.english == LayaThresholds(0.7, 0.95)
    assert cfg.laya.multilingual == LayaThresholds(0.8, 1.01)


def test_load_config_refuses_unknown_mode(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[logging]\nlevel = "INFO"\nfile = ""\n[imap]\nhost = "h"\n'
        '[gmail]\ncredentials_file = "c"\ntoken_file = "t"\n[classifier]\nmode = "gemma"\n'
    )

    with pytest.raises(RuntimeError, match="mode"):
        load_config(toml)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v -k "classifier or laya or unknown_mode"`
Expected: FAIL with `ImportError: cannot import name 'ClassifierConfig'`.

- [ ] **Step 3: Implement in `src/mailtag/config.py`**

Add after `MLXConfig`:

```python
@dataclass
class ClassifierConfig:
    """Pass 3 model: "mlx" (nomic + Gemma) or "laya" (docs/superpowers/specs/2026-10-01-laya-*)."""

    mode: str = "mlx"

    def __post_init__(self):
        if self.mode not in ("mlx", "laya"):
            raise ValueError(f"[classifier] mode must be 'mlx' or 'laya', got {self.mode!r}")


@dataclass
class LayaThresholds:
    """Per-checkpoint thresholds on Laya's answer_confidence (1.01 = never)."""

    classify_threshold: float = 1.01
    learn_threshold: float = 1.01


@dataclass
class LayaConfig:
    """Laya classifier (mode = "laya"); thresholds come from `scripts/eval_embeddings.py laya`."""

    routing: str = "router"  # "router" (language → english/multilingual) | "multilingual"
    device: str = "auto"  # auto | mps | cpu
    batch_size: int = 16
    head_max_len: int = 512
    max_len: int = 1024
    rotations: bool = False
    body_chars: int = 1500
    calibration: str = "data/laya_neutral_calibration.json"  # "" = the checkpoints' shipped temperatures
    english: LayaThresholds = field(default_factory=LayaThresholds)
    multilingual: LayaThresholds = field(default_factory=LayaThresholds)

    def __post_init__(self):
        if self.routing not in ("router", "multilingual"):
            raise ValueError(f"[laya] routing must be 'router' or 'multilingual', got {self.routing!r}")

    def thresholds(self, checkpoint: str) -> LayaThresholds:
        """Thresholds of `checkpoint`; anything but "english" is the multilingual checkpoint."""
        return self.english if checkpoint == "english" else self.multilingual
```

In `AppConfig`, add two fields after `taxonomy` and their defaults in `__post_init__`:

```python
    classifier: ClassifierConfig = None  # type: ignore[assignment]
    laya: LayaConfig = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.webhook is None:
            self.webhook = WebhookConfig()
        if self.taxonomy is None:
            self.taxonomy = TaxonomyConfig()
        if self.classifier is None:
            self.classifier = ClassifierConfig()
        if self.laya is None:
            self.laya = LayaConfig()
```

Add a helper below `_dataclass_from_dict`:

```python
def _laya_config(data: dict) -> LayaConfig:
    """`[laya]`, with its per-checkpoint threshold tables turned into LayaThresholds."""
    thresholds = {
        name: _dataclass_from_dict(LayaThresholds, data[name])
        for name in ("english", "multilingual")
        if name in data
    }
    return _dataclass_from_dict(LayaConfig, {**data, **thresholds})
```

In `load_config`, pass the two new sections to `AppConfig(...)`:

```python
            taxonomy=_dataclass_from_dict(TaxonomyConfig, data.get("taxonomy", {})),
            classifier=_dataclass_from_dict(ClassifierConfig, data.get("classifier", {})),
            laya=_laya_config(data.get("laya", {})),
```

(`ValueError` from `__post_init__` is already caught by `load_config`'s `except` and re-raised as `RuntimeError("Failed to load or parse config file: ...")`, whose message contains "mode".)

- [ ] **Step 4: Add the config sections and the calibration file**

In `config.toml`, insert after the `[mlx]` section (before `[taxonomy]`):

```toml
[classifier]
# Pass 3 model: "mlx" (nomic + Gemma, above) | "laya" (feasibility study,
# docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md; needs `uv sync --extra laya`)
mode = "mlx"

[laya]
routing = "router"      # "router" (language → english/multilingual checkpoint) | "multilingual"
device = "auto"         # auto | mps | cpu
batch_size = 16
head_max_len = 512      # room for the 19 options (~26 tokens each)
max_len = 1024
rotations = false       # average over 19 option orders (position bias), 19 rows per mail
body_chars = 1500
calibration = "data/laya_neutral_calibration.json"  # "" = shipped temperatures
# Thresholds on answer_confidence, set by `scripts/eval_embeddings.py laya` (1.01 = never)
english = { classify_threshold = 1.01, learn_threshold = 1.01 }
multilingual = { classify_threshold = 1.01, learn_threshold = 1.01 }
```

Create `data/laya_neutral_calibration.json`:

```json
{"temperature": [1.0, 1.0, 1.0], "temperature_by_options": {}}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/mailtag/config.py tests/test_config.py && uv run ruff format src/mailtag/config.py tests/test_config.py
git add src/mailtag/config.py tests/test_config.py config.toml data/laya_neutral_calibration.json
git commit -m "feat(config): [classifier] mode switch and [laya] settings"
```

---

### Task 2: English labels for the 19 categories (`TAXONOMY_EN`)

**Files:**
- Modify: `src/mailtag/taxonomy.py` (right after `TAXONOMY`)
- Test: `tests/test_taxonomy.py`

**Interfaces:**
- Produces: `TAXONOMY_EN: dict[str, tuple[str, str]]` — key = French category (same keys and order as `TAXONOMY`), value = `(english_label, english_description)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_taxonomy.py`)

```python
def test_taxonomy_en_covers_every_category_with_distinct_labels():
    from mailtag.taxonomy import TAXONOMY, TAXONOMY_EN

    assert list(TAXONOMY_EN) == list(TAXONOMY)
    labels = [label for label, _ in TAXONOMY_EN.values()]
    assert len(set(labels)) == len(labels)
    assert all(label and description for label, description in TAXONOMY_EN.values())
    assert not {label.lower() for label in labels} & {"yes", "no", "true", "false"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_taxonomy.py::test_taxonomy_en_covers_every_category_with_distinct_labels -v`
Expected: FAIL with `ImportError: cannot import name 'TAXONOMY_EN'`.

- [ ] **Step 3: Add `TAXONOMY_EN` after `TAXONOMY` in `src/mailtag/taxonomy.py`**

```python
# English label and description per category, for Laya's English checkpoint (which cannot read French)
TAXONOMY_EN = {
    "Banque & Placements": ("Banking & Investments", "banks, credit cards, payments, stock market, crypto, crowdfunding, budget"),
    "Assurances & Retraite": ("Insurance & Pensions", "health, car, home and travel insurance, pension funds, retirement"),
    "Impôts & Administration": ("Taxes & Government", "taxes, municipality, public services, digital identity, legal"),
    "Énergie & Télécom": ("Energy & Telecom", "electricity, phone, internet, telecom bills"),
    "Santé": ("Health", "doctors, medical bills, connected health, wellness, hairdresser"),
    "Famille & École": ("Family & School", "children, school, daycare, family members"),
    "Logement & Maison": ("Housing & Home", "real estate, property management, rental, moving, maintenance, smart home"),
    "Achats": ("Shopping", "shops, e-commerce, supermarkets, orders, loyalty cards"),
    "Colis & Livraisons": ("Parcels & Deliveries", "parcel tracking, post office, carriers"),
    "Transports & Mobilité": ("Transport & Mobility", "trains, taxis, car, parking, bikes, carpooling"),
    "Voyages & Loisirs": ("Travel & Leisure", "flights, hotels, car rental, holidays, restaurants, spas, outings"),
    "Médias & Divertissement": ("Media & Entertainment", "newspapers, streaming, music, games, recipes, culture"),
    "Veille & Newsletters pro": ("Professional Newsletters", "professional newsletters, tech, marketing, startups, technical books"),
    "Éditeurs IT & Cloud": ("IT Vendors & Cloud", "enterprise software vendors, cloud, infrastructure, IT webinars"),
    "Outils & Services en ligne": ("Online Tools & Services", "online tools, development, AI, productivity, hosting, software"),
    "Sécurité & Comptes": ("Security & Accounts", "login alerts, passwords, antivirus, backups, bounced emails"),
    "Carrière & Formation": ("Career & Training", "jobs, recruiting, LinkedIn, certifications, courses"),
    "Associations & Communauté": ("Associations & Community", "associations, donations, communities, parish"),
    "Contacts": ("Personal Contacts", "people writing directly"),
}  # fmt: skip
```

- [ ] **Step 4: Run the taxonomy tests**

Run: `uv run pytest tests/test_taxonomy.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/mailtag/taxonomy.py tests/test_taxonomy.py
git add src/mailtag/taxonomy.py tests/test_taxonomy.py
git commit -m "feat(taxonomy): English labels for Laya's English checkpoint"
```

---

### Task 3: `LayaClassifier` and the `laya` extra

**Files:**
- Create: `src/mailtag/laya_provider.py`
- Modify: `pyproject.toml` (`[project.optional-dependencies]`), `uv.lock` (via `uv lock`)
- Test: `tests/test_laya_provider.py` (new)

**Interfaces:**
- Consumes: `LayaConfig` (Task 1), `TAXONOMY`, `TAXONOMY_EN` (Task 2), `Email` (`mailtag.models`), `smart_truncate(text, max_chars)` (`mailtag.utils.text_utils`).
- Produces:
  - `CHECKPOINTS = ("english", "multilingual")`
  - `category_questions(checkpoint: str, rotations: bool) -> dict` — Laya question dict.
  - `category_answer(answers: dict, checkpoint: str) -> tuple[str, float]` — French category and confidence.
  - `email_state(email: Email, body_chars: int) -> dict` — `{"from", "subject", "body"}`.
  - `class LayaClassifier(config: LayaConfig)` with `classify(emails: list[Email]) -> list[tuple[str, float, str] | None]` and `devices() -> dict[str, str]` (checkpoint → device of loaded checkpoints, for the eval report).

Laya API facts this task relies on (checked in `laya` 0.3.22 source):
- `laya.Router(device=None|"mps"|"cpu", default="multilingual", agent_kwargs={"calibration": path})` builds nothing until used.
- `Router.route_batch([{"state": s, "questions": q}, ...]) -> list[RouteDecision]`; `decision["model"]` is the checkpoint name.
- `Router.predict_batch(requests, batch_size=N, sort_by_length=True) -> list[dict]`; each request is `{"state", "questions", "model", "max_len", "head_max_len"}`; results keep input order; `result["answers"][question_id]` is `{"choice": label, "probabilities": {label: p}, "answer_confidence": float, ...}`.
- A `choice` question is `{"type": "choice", "instructions": str, "criteria": {label: description}}`, optionally `"option_order": [permutation]`; probabilities come back keyed by label whatever the order.
- `Router.loaded() -> list[str]`; `Router.load(name).device` is a `torch.device`.

- [ ] **Step 1: Add the extra and lock**

In `pyproject.toml` `[project.optional-dependencies]`, add after `gmail = [...]`:

```toml
# Laya classifier, `[classifier] mode = "laya"` (docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md)
laya = [
    "laya>=0.3.22",
]
```

Run: `uv lock && uv sync --all-extras`
Expected: resolves with the existing `transformers>=5.16.1,<5.17` pin. If resolution fails, STOP and report the conflict (do not change the transformers pin).

Run: `USE_TF=0 uv run python -c "import laya; print(laya.__version__)"`
Expected: `0.3.22` (or newer).

- [ ] **Step 2: Write the failing tests** (`tests/test_laya_provider.py`)

```python
import sys
import types

import pytest

from mailtag.config import LayaConfig
from mailtag.laya_provider import LayaClassifier, category_answer, category_questions, email_state
from mailtag.models import Email
from mailtag.taxonomy import TAXONOMY, TAXONOMY_EN


def mail(i=1, sender="news@shop.ch", name="Shop", subject="Votre commande", body="Merci pour votre achat"):
    return Email(msg_id=str(i), subject=subject, sender_address=sender, sender_name=name, body=body)


class FakeRouter:
    """Stands in for laya.Router: routes by a marker in the subject, answers the first option."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests = []
        self.batch_size = None
        self.fail = 0
        FakeRouter.instances.append(self)

    def route_batch(self, requests):
        return [{"model": "english" if "EN" in r["state"]["subject"] else "multilingual"} for r in requests]

    def predict_batch(self, requests, batch_size=None, sort_by_length=False):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("checkpoint download failed")
        self.requests += requests
        self.batch_size = batch_size
        results = []
        for r in requests:
            answers = {}
            for qid, q in r["questions"].items():
                labels = list(q["criteria"])
                probs = {label: 0.0 for label in labels}
                probs[labels[1]] = 0.8
                probs[labels[0]] = 0.2
                answers[qid] = {"choice": labels[1], "probabilities": probs, "answer_confidence": 0.8}
            results.append({"answers": answers, "routing": {"model": r["model"]}})
        return results

    def loaded(self):
        return ["multilingual"]

    def load(self, name):
        return types.SimpleNamespace(device="mps")


@pytest.fixture
def fake_laya(monkeypatch):
    FakeRouter.instances = []
    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(Router=FakeRouter))
    return FakeRouter


def test_questions_use_the_checkpoint_language():
    fr = category_questions("multilingual", rotations=False)["category"]
    en = category_questions("english", rotations=False)["category"]

    assert fr["type"] == en["type"] == "choice"
    assert fr["criteria"] == TAXONOMY
    assert en["criteria"] == dict(TAXONOMY_EN.values())


def test_rotations_put_every_option_in_every_slot():
    questions = category_questions("multilingual", rotations=True)

    assert len(questions) == len(TAXONOMY)
    k = len(TAXONOMY)
    firsts = {q["option_order"][0] for q in questions.values()}
    assert firsts == set(range(k))
    assert all(sorted(q["option_order"]) == list(range(k)) for q in questions.values())


def test_english_answer_maps_back_to_the_french_category():
    label = TAXONOMY_EN["Santé"][0]
    answers = {"category": {"choice": label, "probabilities": {label: 0.9}, "answer_confidence": 0.9}}

    assert category_answer(answers, "english") == ("Santé", 0.9)


def test_rotated_answers_are_averaged():
    answers = {
        "category_0": {"choice": "Achats", "probabilities": {"Achats": 0.6, "Santé": 0.4}, "answer_confidence": 0.6},
        "category_1": {"choice": "Santé", "probabilities": {"Achats": 0.2, "Santé": 0.8}, "answer_confidence": 0.8},
    }

    category, confidence = category_answer(answers, "multilingual")

    assert category == "Santé"
    assert confidence == pytest.approx(0.6)


def test_email_state_with_and_without_a_name():
    assert email_state(mail(), 1500) == {
        "from": "Shop <news@shop.ch>",
        "subject": "Votre commande",
        "body": "Merci pour votre achat",
    }
    assert email_state(mail(name=""), 1500)["from"] == "news@shop.ch"


def test_classify_routes_and_asks_in_the_checkpoint_language(fake_laya):
    config = LayaConfig(batch_size=4, head_max_len=384, max_len=900, device="mps")
    classifier = LayaClassifier(config)

    result = classifier.classify([mail(1), mail(2, subject="EN order")])

    router = fake_laya.instances[0]
    assert router.kwargs["device"] == "mps"
    assert router.kwargs["default"] == "multilingual"
    assert router.kwargs["agent_kwargs"] == {"calibration": "data/laya_neutral_calibration.json"}
    assert router.batch_size == 4
    assert [r["model"] for r in router.requests] == ["multilingual", "english"]
    assert all(r["max_len"] == 900 and r["head_max_len"] == 384 for r in router.requests)
    second = list(TAXONOMY)[1]  # the fake answers the second option; English labels map back to it
    assert result == [(second, 0.8, "multilingual"), (second, 0.8, "english")]


def test_auto_device_and_no_calibration(fake_laya):
    LayaClassifier(LayaConfig(device="auto", calibration="")).classify([mail()])

    router = fake_laya.instances[0]
    assert router.kwargs["device"] is None
    assert router.kwargs["agent_kwargs"] == {}


def test_multilingual_routing_skips_language_detection(fake_laya, mocker):
    classifier = LayaClassifier(LayaConfig(routing="multilingual"))
    route = mocker.spy(FakeRouter, "route_batch")

    classifier.classify([mail(subject="EN order")])

    route.assert_not_called()
    assert fake_laya.instances[0].requests[0]["model"] == "multilingual"


def test_unexpected_checkpoint_is_treated_as_multilingual(fake_laya, mocker):
    mocker.patch.object(FakeRouter, "route_batch", return_value=[{"model": "typed-decisions"}])

    result = LayaClassifier(LayaConfig()).classify([mail()])

    assert fake_laya.instances[0].requests[0]["model"] == "multilingual"
    assert result[0][2] == "multilingual"


def test_empty_mail_is_classified_without_error(fake_laya):
    result = LayaClassifier(LayaConfig()).classify([mail(subject="", body="", name="")])

    assert result[0] is not None


def test_failed_batch_goes_to_review_and_next_batch_retries(fake_laya):
    classifier = LayaClassifier(LayaConfig())
    classifier.classify([])  # builds nothing
    assert fake_laya.instances == []

    classifier._load().fail = 1
    assert classifier.classify([mail(1), mail(2)]) == [None, None]
    assert classifier.classify([mail(3)])[0] is not None
    assert len(fake_laya.instances) == 1  # the Router is built once


def test_missing_laya_sends_everything_to_review(monkeypatch):
    monkeypatch.setitem(sys.modules, "laya", None)  # import laya -> ImportError

    classifier = LayaClassifier(LayaConfig())

    assert classifier.classify([mail(1), mail(2)]) == [None, None]
    assert classifier.classify([mail(3)]) == [None]


def test_devices_reports_loaded_checkpoints(fake_laya):
    classifier = LayaClassifier(LayaConfig())
    assert classifier.devices() == {}
    classifier.classify([mail()])

    assert classifier.devices() == {"multilingual": "mps"}
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_laya_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mailtag.laya_provider'`.

- [ ] **Step 4: Implement `src/mailtag/laya_provider.py`**

```python
"""Laya classifier for Pass 3 (`[classifier] mode = "laya"`).

One `choice` question over the 19 categories per mail, asked in the language of the checkpoint the
mail is routed to (docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md).
"""

import os
import threading
from typing import TYPE_CHECKING

from loguru import logger

from .config import LayaConfig
from .models import Email
from .taxonomy import TAXONOMY, TAXONOMY_EN
from .utils.text_utils import smart_truncate

if TYPE_CHECKING:
    from laya import Router

CHECKPOINTS = ("english", "multilingual")
QUESTION_ID = "category"

_INSTRUCTIONS = {
    "multilingual": "Dans quelle catégorie ranger ce mail ?",
    "english": "Which category should this email be filed in?",
}
_CRITERIA = {"multilingual": dict(TAXONOMY), "english": dict(TAXONOMY_EN.values())}
# Label the model answers with -> French category
_TO_CATEGORY = {
    "multilingual": {category: category for category in TAXONOMY},
    "english": {label: category for category, (label, _) in TAXONOMY_EN.items()},
}


def category_questions(checkpoint: str, rotations: bool) -> dict:
    """The category question for `checkpoint`; with rotations, one copy per option order."""
    question = {"type": "choice", "instructions": _INSTRUCTIONS[checkpoint], "criteria": _CRITERIA[checkpoint]}
    if not rotations:
        return {QUESTION_ID: question}
    k = len(question["criteria"])
    return {
        f"{QUESTION_ID}_{r}": dict(question, option_order=[(i + r) % k for i in range(k)]) for r in range(k)
    }


def category_answer(answers: dict, checkpoint: str) -> tuple[str, float]:
    """(French category, answer_confidence); rotated answers are averaged over every option order."""
    if QUESTION_ID in answers:
        answer = answers[QUESTION_ID]
        label, confidence = answer["choice"], float(answer["answer_confidence"])
    else:
        totals: dict[str, float] = {}
        for answer in answers.values():
            for name, p in answer["probabilities"].items():
                totals[name] = totals.get(name, 0.0) + p / len(answers)
        label = max(totals, key=totals.__getitem__)
        confidence = totals[label]
    return _TO_CATEGORY[checkpoint][label], confidence


def email_state(email: Email, body_chars: int) -> dict:
    """What Laya reads: sender, subject and the start of the body."""
    sender = f"{email.sender_name} <{email.sender_address}>" if email.sender_name else email.sender_address
    body = smart_truncate(email.body, max_chars=body_chars) if email.body else ""
    return {"from": sender, "subject": email.subject, "body": body}


class LayaClassifier:
    """(category, answer_confidence, checkpoint) per mail, or None when Laya could not answer."""

    def __init__(self, config: LayaConfig):
        self.config = config
        self._lock = threading.Lock()
        self._router: "Router | None" = None
        self._loaded = False

    def _load(self) -> "Router | None":
        """Build the Router once (checkpoints load on first predict); None if laya is unavailable."""
        with self._lock:
            if self._loaded:
                return self._router
            self._loaded = True
            os.environ.setdefault("USE_TF", "0")  # transformers' TensorFlow probe can hang Laya's load
            try:
                from laya import Router
            except ImportError as e:
                logger.warning(f"laya is not installed (uv sync --extra laya), sending emails to review: {e}")
                return None
            agent_kwargs = {"calibration": self.config.calibration} if self.config.calibration else {}
            try:
                self._router = Router(
                    device=None if self.config.device == "auto" else self.config.device,
                    default="multilingual",
                    agent_kwargs=agent_kwargs,
                )
            except (OSError, RuntimeError, ValueError, TypeError) as e:
                logger.error(f"Failed to build the Laya router, sending emails to review: {e}")
            return self._router

    def _checkpoints(self, router: "Router", states: list[dict]) -> list[str]:
        if self.config.routing == "multilingual":
            return ["multilingual"] * len(states)
        decisions = router.route_batch([{"state": s, "questions": {}} for s in states])
        return [d["model"] if d["model"] in CHECKPOINTS else "multilingual" for d in decisions]

    def classify(self, emails: list[Email]) -> list[tuple[str, float, str] | None]:
        if not emails:
            return []
        router = self._load()
        if router is None:
            return [None] * len(emails)
        states = [email_state(e, self.config.body_chars) for e in emails]
        try:
            checkpoints = self._checkpoints(router, states)
            requests = [
                {
                    "state": state,
                    "questions": category_questions(checkpoint, self.config.rotations),
                    "model": checkpoint,
                    "max_len": self.config.max_len,
                    "head_max_len": self.config.head_max_len,
                }
                for state, checkpoint in zip(states, checkpoints, strict=True)
            ]
            results = router.predict_batch(requests, batch_size=self.config.batch_size, sort_by_length=True)
            return [
                (*category_answer(result["answers"], checkpoint), checkpoint)
                for result, checkpoint in zip(results, checkpoints, strict=True)
            ]
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as e:
            logger.error(f"Laya batch failed, sending emails to review: {e}")
            return [None] * len(emails)

    def devices(self) -> dict[str, str]:
        """Device of each loaded checkpoint (for the evaluation report)."""
        if self._router is None:
            return {}
        return {name: str(self._router.load(name).device) for name in self._router.loaded()}
```

Note: `test_failed_batch_goes_to_review_and_next_batch_retries` calls `classifier._load()` to reach the fake Router; that is intended.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_laya_provider.py -v`
Expected: all PASS. If `test_classify_routes_and_asks_in_the_checkpoint_language` fails on the result tuple, check that `_TO_CATEGORY["english"]` maps the English label back (the fake answers the second label of the criteria it was given).

- [ ] **Step 6: Lint, full suite, commit**

```bash
uv run ruff check . && uv run ruff format src/mailtag/laya_provider.py tests/test_laya_provider.py
uv run pytest -q
git add pyproject.toml uv.lock src/mailtag/laya_provider.py tests/test_laya_provider.py
git commit -m "feat(laya): LayaClassifier routes mails and asks the 19 categories per checkpoint"
```

---

### Task 4: `Classifier` uses Laya when `mode = "laya"`

**Files:**
- Modify: `src/mailtag/classifier.py` (`__init__`, `_classify_uncertain_detailed`, new `_classify_laya`)
- Test: `tests/test_classifier_taxonomy.py`

**Interfaces:**
- Consumes: `LayaClassifier(config.laya).classify(emails) -> list[tuple[str, float, str] | None]` (Task 3), `config.classifier.mode`, `config.laya.thresholds(checkpoint) -> LayaThresholds` (Task 1).
- Produces: unchanged public API: `classify_detailed(emails) -> list[tuple[str, bool]]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_classifier_taxonomy.py`)

```python
from mailtag.config import ClassifierConfig, LayaConfig, LayaThresholds


def _laya_classifier(tmp_path, answers, mocker, **thresholds):
    config = _config(tmp_path)
    config.classifier = ClassifierConfig(mode="laya")
    config.laya = LayaConfig(
        english=thresholds.get("english", LayaThresholds(0.7, 0.95)),
        multilingual=thresholds.get("multilingual", LayaThresholds(0.6, 0.9)),
    )
    classifier = Classifier(config=config)
    mocker.patch.object(classifier._laya, "classify", return_value=answers)
    return classifier


def test_laya_mode_applies_each_checkpoints_thresholds(tmp_path, mocker):
    answers = [
        ("Santé", 0.65, "english"),  # below english classify (0.7)
        ("Santé", 0.65, "multilingual"),  # above multilingual classify (0.6), below learn
        ("Achats", 0.95, "english"),  # exactly english learn: inclusive
        ("Achats", 0.6, "multilingual"),  # exactly multilingual classify: inclusive
        None,  # Laya could not answer
    ]
    classifier = _laya_classifier(tmp_path, answers, mocker)

    assert classifier._classify_uncertain_detailed([mail(i) for i in range(5)]) == [
        (REVIEW, False),
        ("Santé", False),
        ("Achats", True),
        ("Achats", False),
        (REVIEW, False),
    ]


def test_laya_mode_never_learns_with_the_inert_default(tmp_path, mocker):
    classifier = _laya_classifier(
        tmp_path, [("Santé", 1.0, "multilingual")], mocker, multilingual=LayaThresholds(0.5, 1.01)
    )

    assert classifier._classify_uncertain_detailed([mail()]) == [("Santé", False)]


def test_laya_mode_runs_rules_first_and_never_loads_mlx(tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    classifier = _laya_classifier(tmp_path, [("Achats", 0.99, "multilingual")], mocker)
    mlx = mocker.patch.object(classifier, "_init_mlx_components")

    result = classifier.classify_detailed([mail(1, sender="v@x.ch"), mail(2, sender="new@shop.ch")])

    assert result == [("Santé", False), ("Achats", True)]
    classifier._laya.classify.assert_called_once()
    assert [e.sender_address for e in classifier._laya.classify.call_args.args[0]] == ["new@shop.ch"]
    mlx.assert_not_called()


def test_laya_mode_agreements_teach_rules(tmp_path, mocker):
    classifier = _laya_classifier(tmp_path, [("Santé", 0.97, "multilingual")], mocker)

    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])
    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])

    learned = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert learned["doc@clinic.ch"]["category"] == "Santé"


def test_mlx_mode_builds_no_laya_classifier(classifier):
    assert classifier._laya is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_classifier_taxonomy.py -v -k laya`
Expected: FAIL with `AttributeError: 'Classifier' object has no attribute '_laya'`.

- [ ] **Step 3: Implement in `src/mailtag/classifier.py`**

Add the import next to the other local imports:

```python
from .laya_provider import LayaClassifier
```

(`laya_provider` imports `laya` only inside `LayaClassifier._load`, so this import is safe without the extra.)

At the end of `Classifier.__init__`, before the `logger.info(...)` line:

```python
        # Laya replaces nomic + Gemma in Pass 3 (feasibility study, mode = "laya")
        self._laya = LayaClassifier(config.laya) if config.classifier.mode == "laya" else None
```

Replace the start of `_classify_uncertain_detailed` and add `_classify_laya` right after it:

```python
    def _classify_uncertain_detailed(self, emails: list[Email]) -> list[tuple[str, bool]]:
        """Signals 5-6: (category, nomic and LLM agreed) — nomic above threshold, else LLM agreement.
        In laya mode, Laya alone with its per-checkpoint thresholds."""
        if self._laya is not None:
            return self._classify_laya(emails)
        results: list[tuple[str, bool]] = [(REVIEW, False)] * len(emails)
        # ... rest of the existing body unchanged ...

    def _classify_laya(self, emails: list[Email]) -> list[tuple[str, bool]]:
        """(category, confident enough to learn from) per email; below classify_threshold → review."""
        results: list[tuple[str, bool]] = []
        for answer in self._laya.classify(emails):
            if answer is None:
                results.append((REVIEW, False))
                continue
            category, confidence, checkpoint = answer
            thresholds = self.config.laya.thresholds(checkpoint)
            if confidence >= thresholds.classify_threshold:
                results.append((category, confidence >= thresholds.learn_threshold))
            else:
                results.append((REVIEW, False))
        return results
```

Update the `Classifier` class docstring's last sentence to: `"... else nomic and the LLM must agree; anything else goes to review. With [classifier] mode = "laya", Laya replaces nomic and the LLM."`

- [ ] **Step 4: Run the classifier tests and the full suite**

Run: `uv run pytest tests/test_classifier_taxonomy.py -v && uv run pytest -q`
Expected: all PASS (existing mlx-mode tests unchanged).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format src/mailtag/classifier.py tests/test_classifier_taxonomy.py
git add src/mailtag/classifier.py tests/test_classifier_taxonomy.py
git commit -m "feat(classifier): Laya replaces nomic and Gemma in laya mode"
```

---

### Task 5: Evaluation command `scripts/eval_embeddings.py laya`

**Files:**
- Modify: `scripts/eval_embeddings.py` (module docstring, two helpers, `laya_eval`, `main`)
- Test: `tests/test_eval_embeddings.py`

**Interfaces:**
- Consumes: `chain_metrics(results, labels, llm_seconds, llm_calls) -> dict`, `best_threshold(sweep, min_precision=0.90) -> dict | None` (existing), `LayaClassifier` (Task 3), `LayaConfig` / `CONFIG.laya` (Task 1).
- Produces:
  - `confidence_sweep(answers: list[tuple[str, float] | None], labels: list[str], thresholds: list[float]) -> list[dict]` — rows `{"threshold", "auto", "precision", "classified"}`.
  - `learn_threshold(sweep: list[dict], min_precision: float = 0.97, min_mails: int = 30) -> float` — lowest threshold reaching both, else `1.01`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_eval_embeddings.py`)

```python
def test_confidence_sweep():
    from scripts.eval_embeddings import confidence_sweep

    answers = [("A", 0.9), ("B", 0.6), ("C", 0.95), None]
    labels = ["A", "A", "C", "B"]

    sweep = confidence_sweep(answers, labels, [0.5, 0.8])

    assert sweep[0] == {"threshold": 0.5, "auto": 0.75, "precision": pytest.approx(2 / 3), "classified": 3}
    assert sweep[1] == {"threshold": 0.8, "auto": 0.5, "precision": 1.0, "classified": 2}


def test_learn_threshold_needs_precision_and_enough_mails():
    from scripts.eval_embeddings import learn_threshold

    sweep = [
        {"threshold": 0.8, "auto": 0.9, "precision": 0.95, "classified": 90},
        {"threshold": 0.9, "auto": 0.5, "precision": 0.98, "classified": 50},
        {"threshold": 0.95, "auto": 0.2, "precision": 1.0, "classified": 20},
    ]

    assert learn_threshold(sweep) == 0.9
    assert learn_threshold(sweep, min_mails=60) == 1.01
    assert learn_threshold([]) == 1.01
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_eval_embeddings.py -v -k "confidence_sweep or learn_threshold"`
Expected: FAIL with `ImportError: cannot import name 'confidence_sweep'`.

- [ ] **Step 3: Add the helpers after `best_threshold` in `scripts/eval_embeddings.py`**

```python
def confidence_sweep(answers, labels, thresholds):
    """Laya result for each threshold: its category at or above it, else review."""
    from mailtag.taxonomy import REVIEW

    rows = []
    for t in thresholds:
        results = [a[0] if a and a[1] >= t else REVIEW for a in answers]
        m = chain_metrics(results, labels, 0.0, 0)
        classified = sum(r != REVIEW for r in results)
        rows.append({"threshold": t, "auto": m["auto"], "precision": m["precision"], "classified": classified})
    return rows


def learn_threshold(sweep, min_precision=0.97, min_mails=30):
    """Lowest threshold whose precision reaches `min_precision` on at least `min_mails` mails, else 1.01."""
    ok = [row for row in sweep if row["precision"] >= min_precision and row["classified"] >= min_mails]
    return min(row["threshold"] for row in ok) if ok else 1.01
```

- [ ] **Step 4: Run the helper tests**

Run: `uv run pytest tests/test_eval_embeddings.py -v`
Expected: all PASS.

- [ ] **Step 5: Add `laya_eval` after `chain_eval`**

```python
def laya_eval(n: int, seed: int, overrides: dict) -> None:
    """Run Laya on the verified mails `chain` uses, sweep thresholds per checkpoint, propose them."""
    import dataclasses
    import random

    from mailtag.config import CONFIG
    from mailtag.laya_provider import LayaClassifier
    from mailtag.models import Email
    from mailtag.taxonomy import REVIEW

    config = dataclasses.replace(CONFIG.laya, **overrides)
    corpus = json.loads(Path("data/taxonomy_corpus.json").read_text(encoding="utf-8"))
    verified = [m for m in corpus if m["verified"]]
    test = random.Random(seed).sample(verified, min(n, len(verified)))
    emails = [
        Email(msg_id=str(i), subject=m["subject"], sender_address=m["sender"], sender_name=m["sender_name"],
              body=m["body"])
        for i, m in enumerate(test)
    ]  # fmt: skip
    labels = [m["category"] for m in test]

    classifier = LayaClassifier(config)
    start = time.perf_counter()
    answers = []
    for i in range(0, len(emails), 50):
        answers += classifier.classify(emails[i : i + 50])
        logger.info(f"Laya {len(answers)}/{len(emails)} ({(time.perf_counter() - start) / len(answers):.2f} s/email)")
    seconds = time.perf_counter() - start

    print(f"\n{len(test)} verified mails (seed {seed}), {config}")
    print(f"devices: {classifier.devices()}, {seconds / len(emails):.2f} s/email")
    print(f"unanswered: {sum(a is None for a in answers)}")

    thresholds = [round(0.30 + 0.01 * i, 2) for i in range(70)]
    proposed = {}
    for checkpoint in ("english", "multilingual"):
        idx = [i for i, a in enumerate(answers) if a and a[2] == checkpoint]
        if not idx:
            continue
        sub_answers = [answers[i][:2] for i in idx]
        sub_labels = [labels[i] for i in idx]
        top1 = sum(a[0] == lab for a, lab in zip(sub_answers, sub_labels, strict=True)) / len(idx)
        sweep = confidence_sweep(sub_answers, sub_labels, thresholds)
        print(f"\n[{checkpoint}] {len(idx)} mails ({len(idx) / len(test):.0%}), top-1 accuracy {top1:.1%}")
        print(" threshold  auto   precision  classified")
        for row in sweep[::5]:
            print(f"   {row['threshold']:.2f}    {row['auto']:5.1%}  {row['precision']:6.1%}  {row['classified']:6d}")
        best = best_threshold(sweep)
        proposed[checkpoint] = (best["threshold"] if best else 1.01, learn_threshold(sweep))

    print("\nProposed [laya] thresholds:")
    for checkpoint, (classify_t, learn_t) in proposed.items():
        print(f"{checkpoint} = {{ classify_threshold = {classify_t:.2f}, learn_threshold = {learn_t:.2f} }}")

    results = [
        a[0] if a and a[1] >= proposed.get(a[2], (1.01, 1.01))[0] else REVIEW for a in answers
    ]
    m = chain_metrics(results, labels, seconds, len(emails))
    print(
        f"\nWith these thresholds: {m['auto']:.1%} classified at {m['precision']:.1%}, "
        f"{m['sec_per_llm_email']:.2f} s/email -> {'PASS' if m['passed'] else 'FAIL'}"
    )
    print(f"Compare with: uv run python scripts/eval_embeddings.py chain -n {n} --seed {seed}")
```

- [ ] **Step 6: Wire the subcommand in `main()`**

After the `p_chain` arguments:

```python
    p_laya = sub.add_parser("laya", help="Measure Laya on verified mails and propose its thresholds")
    p_laya.add_argument("-n", type=int, default=500)
    p_laya.add_argument("--seed", type=int, default=3)
    p_laya.add_argument("--routing", choices=["router", "multilingual"])
    p_laya.add_argument("--rotations", action="store_true", default=None)
    p_laya.add_argument("--head-max-len", type=int)
    p_laya.add_argument("--max-len", type=int)
    p_laya.add_argument("--body-chars", type=int)
    p_laya.add_argument("--calibration", help='calibration JSON path, "" for the shipped temperatures')
```

After the `chain` dispatch:

```python
    elif args.command == "laya":
        overrides = {
            key: value
            for key, value in {
                "routing": args.routing,
                "rotations": args.rotations,
                "head_max_len": args.head_max_len,
                "max_len": args.max_len,
                "body_chars": args.body_chars,
                "calibration": args.calibration,
            }.items()
            if value is not None
        }
        laya_eval(args.n, args.seed, overrides)
```

Update the module docstring's usage block to:

```python
"""Measure the taxonomy chain (Signals 5-6) on verified mails and pick the nomic threshold,
or measure Laya and propose its per-checkpoint thresholds.

    uv run python scripts/eval_embeddings.py chain -n 500
    uv run python scripts/eval_embeddings.py laya -n 500 [--routing multilingual] [--rotations]

Category centroids are built leave-sender-out from data/taxonomy_corpus.json, and the LLM step
runs through Classifier._llm_categories, so results reflect what production would do. Laya runs
through LayaClassifier with the [laya] settings of config.toml (overridable by flag).
"""
```

- [ ] **Step 7: Check the command parses, run tests, commit**

Run: `uv run python scripts/eval_embeddings.py laya --help`
Expected: help listing `--routing`, `--rotations`, `--head-max-len`, `--max-len`, `--body-chars`, `--calibration`.

```bash
uv run ruff check . && uv run ruff format scripts/eval_embeddings.py tests/test_eval_embeddings.py
uv run pytest -q
git add scripts/eval_embeddings.py tests/test_eval_embeddings.py
git commit -m "feat(eval): laya subcommand sweeps thresholds per checkpoint"
```

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md` (section "AI Model Configuration" and "Classification flow" step 2)
- Modify: `src/mailtag/CLAUDE.md` if it lists the modules (add one line for `laya_provider.py`)

- [ ] **Step 1: Update `CLAUDE.md`**

In "AI Model Configuration", append this paragraph:

```markdown
**Laya (feasibility study)**: `[classifier] mode = "laya"` (default `"mlx"`) replaces nomic and Gemma in Pass 3 with the Laya classifier (`src/mailtag/laya_provider.py`, `uv sync --extra laya`; spec `docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md`). A `laya.Router` sends each mail to the `english` or `multilingual` checkpoint (`[laya] routing`), which answers one `choice` question over the 19 categories (English labels from `TAXONOMY_EN` for the English checkpoint). A mail is classified at `answer_confidence ≥ classify_threshold` and counts as an agreement at `≥ learn_threshold`, both per checkpoint in `[laya]` and inert (1.01) until `uv run python scripts/eval_embeddings.py laya` proposes them. `data/laya_neutral_calibration.json` neutralises the English checkpoint's shipped temperatures, which flatten confidence to 1.0 past 11 options.
```

In "Classification flow", step 2, append: `In laya mode, Laya alone decides (see AI Model Configuration).`

- [ ] **Step 2: Update `src/mailtag/CLAUDE.md`**

Run: `grep -n "mlx_provider" src/mailtag/CLAUDE.md`
If the file lists modules, add next to the `mlx_provider.py` line:

```markdown
- `laya_provider.py` — `LayaClassifier`: Laya Router, one 19-category `choice` question per mail, `(category, answer_confidence, checkpoint)` (mode = "laya")
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md src/mailtag/CLAUDE.md
git commit -m "docs: Laya mode in CLAUDE.md"
```

---

### Task 7: Run the feasibility measurement and record the verdict (controller, on the Mac)

Not for a subagent: it downloads ~1.5 GB of checkpoints and reads the owner's corpus. The controller runs it and reports to the owner.

- [ ] **Step 1: Baseline** — `uv run python scripts/eval_embeddings.py chain -n 500 --seed 3` → note auto %, precision, s/email.
- [ ] **Step 2: Laya zero-shot, routed** — `uv run python scripts/eval_embeddings.py laya -n 500 --seed 3` → note per-checkpoint mails, top-1, proposed thresholds, PASS/FAIL, s/email, devices.
- [ ] **Step 3: Levers (spec option C)**, one run each, same seed: `--routing multilingual`; `--rotations`; `--head-max-len 384`; `--calibration ""`.
- [ ] **Step 4: Verdict** — append a `## Verdict` section to the spec with the numbers of steps 1-3 and the decision (GO / fine-tuning / STOP, as defined in the spec); if GO or fine-tuning, paste the best proposed thresholds into `config.toml` `[laya]` (mode stays `"mlx"`).
- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md config.toml
git commit -m "docs: Laya feasibility verdict"
```
