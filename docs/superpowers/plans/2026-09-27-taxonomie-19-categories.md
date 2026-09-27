# Taxonomie à 19 catégories — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Classer chaque mail IMAP entrant dans une des 19 catégories métier (ou `9-A revoir`), le déposer dans un dossier d'action, puis l'archiver automatiquement dans sa catégorie.

**Architecture :** Un mode `[taxonomy] enabled` s'ajoute à côté du flux actuel. Dans ce mode :
- les signaux 1 à 4 convertissent les anciens chemins de dossier en catégories (`to_category`) ;
- le signal 5 (nomic) donne son premier choix et un score ;
- le signal 6 (Gemma) répond par numéro, par lots, avec le début du prompt calculé une seule fois ;
- l'accord entre nomic et Gemma décide, sinon le mail va dans `9-A revoir`.

Les passes 1 à 3 déposent les mails dans les dossiers d'action via `routing.py`, et `archive.py` fait le ménage en fin de passage. Le flux actuel reste intact quand `enabled = false`.

**Tech Stack :** Python 3.13, IMAPClient, sentence-transformers (nomic-embed-text-v1.5), mlx-lm ≥ 0.31 (`batch_generate`, `make_prompt_cache`), pytest et pytest-mock, ruff.

**Spec :** `docs/superpowers/specs/2026-09-27-taxonomie-19-categories-design.md`

## Global Constraints

- Python ≥ 3.13, lignes de 110 caractères au plus (ruff) : `uv run ruff format --check . && uv run ruff check .` doit passer. Dans chaque tâche, lancer `ruff format` avant `ruff check`.
- Tests : `uv run pytest` (couverture activée via `addopts`). La CI tourne sur Ubuntu, sans MLX réel : tout test qui touche `mlx`/`mlx_lm`/`sentence_transformers` les simule via `mocker.patch.dict(sys.modules, …)`.
- `transformers>=5.16.1,<5.17` reste bloqué (nomic casse avec 5.17).
- `mlx-lm>=0.31.0` (nécessaire pour `batch_generate(..., prompt_caches=...)`).
- Les noms de dossiers et de catégories doivent être repris **exactement**, accents compris :
  - dossiers d'action : `1-A traiter`, `2-A payer`, `3-A lire`, `4-Pour info`, `5-Promos`, `9-A revoir` ;
  - catégories : les 19 clés de `TAXONOMY`.
- Valeurs par défaut de `[taxonomy]` : `enabled = false`, `nomic_threshold = 0.70`, `llm_batch_size = 8`, `archive_after_days = 7`.
- Le flux actuel (`enabled = false`) ne doit pas changer de comportement : toute la suite de tests existante doit passer.
- `--validate` ne déplace rien et n'écrit ni `pending_archive` ni la base validée.
- Le fournisseur Gmail garde le flux actuel, même quand `[taxonomy] enabled = true`.
- Messages de commit : Conventional Commits, terminés par :
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp
  ```

## Review Focus

1. **Mail sans en-tête `Message-ID` :** il est déposé dans son dossier d'action mais ne peut pas être suivi. Il doit rester en place, ne jamais être archivé ni faire planter le passage, et un avertissement doit être journalisé. Test : Task 9 (`test_mail_without_message_id_is_moved_but_not_tracked`).
2. **Ancienne valeur de base qui ne correspond à aucune catégorie** (`À Classer`, `Promotions`, `INBOX`, chaîne vide) : `to_category` renvoie `None` et le mail passe au signal suivant, sans erreur. Tests : Task 1 (`test_to_category_*`) et Task 7 (`test_rules_skip_unmappable_old_values`).
3. **Réponse de Gemma illisible ou hors bornes** (`"0"`, `"20"`, `"Banque"`, vide) : `parse_category_number` renvoie `None`, et le mail va dans `9-A revoir`. Tests : Task 1 (`test_parse_category_number`) et Task 7 (`test_chain_unparsable_llm_goes_to_review`).
4. **nomic qui lève une exception** (le cas `AttributeError` de transformers 5.17) : pas de plantage, et tous les mails non classés par règle vont dans `9-A revoir`. Test : Task 7 (`test_nomic_failure_sends_everything_to_review`).
5. **Dossier d'action ou de catégorie absent au moment du ménage** (premier passage, dossier supprimé à la main) : le ménage le saute sans erreur. Test : Task 10 (`test_missing_action_folder_is_skipped`).

---

## File Structure

| Fichier | Rôle |
|---|---|
| `src/mailtag/taxonomy.py` (créé, reprend `scripts/taxonomy.py`) | `TAXONOMY`, constantes des dossiers d'action, `map_folder`, `to_category`, prompt Gemma (`llm_static_prompt`, `llm_email_part`), `parse_category_number` |
| `src/mailtag/action_rules.py` (créé) | `choose_action(...)`, règles pures |
| `src/mailtag/pending_archive.py` (créé) | `PendingArchive` : stockage JSON atomique `Message-ID -> {category, sender, added}` |
| `src/mailtag/routing.py` (créé) | `RoutedMail`, `route_to_action_folders(...)` : choix de l'action, déplacement groupé, enregistrement |
| `src/mailtag/archive.py` (créé) | `run_archive(...)` : archivage des mails lus depuis N jours, apprentissage depuis `9-A revoir`, entrées orphelines |
| `src/mailtag/config.py` (modifié) | `TaxonomyConfig`, champ `AppConfig.taxonomy` |
| `src/mailtag/models.py` (modifié) | `Email.message_id`, `Email.has_unsubscribe`, `Email.is_bulk` |
| `src/mailtag/imap_service.py` (modifié) | lecture de `MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE` |
| `src/mailtag/semantic_router.py` (modifié) | `top_batch(texts)` |
| `src/mailtag/mlx_provider.py` (modifié) | `MLXLLM.classify_batch(static_prompt, email_parts, batch_size, max_tokens)` |
| `src/mailtag/classifier.py` (modifié) | mode taxonomie : `_classify_batch_taxonomy`, `_rule_category`, `_nomic_top`, `_llm_categories`, `_classify_uncertain` |
| `src/mailtag/utils/tasks.py` (modifié) | passes 1 à 3 routées via `routing.py` en mode taxonomie, ménage de fin de passage |
| `scripts/build_category_embeddings.py`, `scripts/eval_embeddings.py` (modifiés) | lecture de `data/legacy_folders.json` ; commande `chain` |
| `config.toml`, `pyproject.toml`, `CLAUDE.md` (modifiés) | section `[taxonomy]`, plancher de version mlx-lm, documentation |

---

### Task 1: Module `mailtag.taxonomy`

**Files:**
- Create: `src/mailtag/taxonomy.py` (à partir de `scripts/taxonomy.py`)
- Delete: `scripts/taxonomy.py`
- Modify: `scripts/eval_embeddings.py` (imports `from taxonomy import` → `from mailtag.taxonomy import`)
- Test: `tests/test_taxonomy.py`

**Interfaces:**
- Consumes : rien.
- Produces :
  - `TAXONOMY: dict[str, str]` (19 entrées, ordre fixe)
  - `ACTION_TODO = "1-A traiter"`, `ACTION_PAY = "2-A payer"`, `ACTION_READ = "3-A lire"`, `ACTION_INFO = "4-Pour info"`, `ACTION_PROMO = "5-Promos"`, `REVIEW = "9-A revoir"`
  - `ACTION_FOLDERS: tuple[str, ...]` (les 6, dans cet ordre)
  - `map_folder(folder: str) -> str | None`
  - `to_category(value: str | None) -> str | None`
  - `llm_static_prompt() -> str`
  - `llm_email_part(subject: str, sender: str, body: str) -> str`
  - `parse_category_number(text: str) -> str | None`

- [ ] **Step 1: Déplacer le module et les imports**

```bash
git mv scripts/taxonomy.py src/mailtag/taxonomy.py
sed -i '' 's/^from taxonomy import/from mailtag.taxonomy import/; s/^    from taxonomy import/    from mailtag.taxonomy import/' scripts/eval_embeddings.py
sed -i '' 's/^from scripts.taxonomy import/from mailtag.taxonomy import/' tests/test_taxonomy.py
grep -rn "from taxonomy\|scripts.taxonomy" scripts tests src
```
Expected: le dernier `grep` n'affiche rien.

- [ ] **Step 2: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_taxonomy.py` :

```python
from mailtag.taxonomy import (
    ACTION_FOLDERS,
    REVIEW,
    llm_email_part,
    llm_static_prompt,
    parse_category_number,
    to_category,
)


def test_action_folders_exact_names():
    assert ACTION_FOLDERS == ("1-A traiter", "2-A payer", "3-A lire", "4-Pour info", "5-Promos", "9-A revoir")
    assert REVIEW == "9-A revoir"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Banque & Placements", "Banque & Placements"),  # already a category
        ("Voyages/Sixt", "Voyages & Loisirs"),  # old folder path
        ("À Classer", None),
        ("Promotions", None),
        ("INBOX", None),
        ("", None),
        (None, None),
    ],
)
def test_to_category(value, expected):
    assert to_category(value) == expected


def test_llm_static_prompt_numbers_every_category_in_order():
    prompt = llm_static_prompt()
    for number, name in enumerate(TAXONOMY, 1):
        assert f"{number}. {name} : " in prompt
    assert prompt.endswith("Réponds uniquement par le numéro de la catégorie, sans autre texte.\n\n")


def test_llm_email_part_format():
    assert llm_email_part("Facture", "BCV <info@bcv.ch>", "Montant") == (
        "Sujet: Facture\nDe: BCV <info@bcv.ch>\nCorps: Montant"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", "Banque & Placements"),
        (" 19\n", "Contacts"),
        ("Catégorie 11", "Voyages & Loisirs"),
        ("0", None),
        ("20", None),
        ("Banque", None),
        ("", None),
    ],
)
def test_parse_category_number(text, expected):
    assert parse_category_number(text) == expected
```

- [ ] **Step 3: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_taxonomy.py -q`
Expected: FAIL, `ImportError: cannot import name 'ACTION_FOLDERS'`

- [ ] **Step 4: Implémenter**

Dans `src/mailtag/taxonomy.py` :
- remplacer la docstring du module par `"""Business-sector taxonomy: 19 categories, action folders and folder mapping."""` ;
- ajouter le bloc suivant **juste après** le dict `TAXONOMY` ;
- ajouter les fonctions suivantes **à la fin** du fichier.

```python
ACTION_TODO = "1-A traiter"
ACTION_PAY = "2-A payer"
ACTION_READ = "3-A lire"
ACTION_INFO = "4-Pour info"
ACTION_PROMO = "5-Promos"
REVIEW = "9-A revoir"
ACTION_FOLDERS = (ACTION_TODO, ACTION_PAY, ACTION_READ, ACTION_INFO, ACTION_PROMO, REVIEW)
```

```python
def to_category(value: str | None) -> str | None:
    """Return a taxonomy category for a stored value: a category name or an old folder path."""
    if not value:
        return None
    if value in TAXONOMY:
        return value
    return map_folder(value)


def llm_static_prompt() -> str:
    """Instructions and numbered category list; identical for every email so it can be cached."""
    categories = "\n".join(f"{i}. {name} : {desc}" for i, (name, desc) in enumerate(TAXONOMY.items(), 1))
    return (
        "Classe cet email dans UNE des catégories suivantes, selon le métier de l'expéditeur :\n"
        f"{categories}\n\n"
        "Réponds uniquement par le numéro de la catégorie, sans autre texte.\n\n"
    )


def llm_email_part(subject: str, sender: str, body: str) -> str:
    """Per-email part of the prompt, appended after llm_static_prompt()."""
    return f"Sujet: {subject}\nDe: {sender}\nCorps: {body}"


def parse_category_number(text: str) -> str | None:
    """Map the LLM answer ('7', ' 7\\n', 'Catégorie 7') to a category name, or None."""
    match = re.search(r"\d+", text or "")
    if not match:
        return None
    number = int(match.group())
    names = list(TAXONOMY)
    return names[number - 1] if 1 <= number <= len(names) else None
```

Et ajouter `import re` en tête du fichier.

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_taxonomy.py tests/test_eval_embeddings.py -q`
Expected: PASS

- [ ] **Step 6: Lint et commit**

```bash
uv run ruff format src/mailtag/taxonomy.py tests/test_taxonomy.py scripts/eval_embeddings.py
uv run ruff check src/mailtag/taxonomy.py tests/test_taxonomy.py scripts/eval_embeddings.py
git add -A src/mailtag/taxonomy.py scripts/taxonomy.py scripts/eval_embeddings.py tests/test_taxonomy.py
git commit -m "feat(taxonomy): move taxonomy into mailtag with action folders and LLM prompt helpers"
```

---

### Task 2: Configuration `[taxonomy]`

**Files:**
- Modify: `src/mailtag/config.py` (dataclass et `AppConfig`, `load_config`)
- Modify: `config.toml` (nouvelle section après `[mlx]`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces :
  - `TaxonomyConfig(enabled: bool = False, nomic_threshold: float = 0.70, llm_batch_size: int = 8, archive_after_days: int = 7, pending_archive_file: str = "db/pending_archive.json", legacy_folders_file: str = "data/legacy_folders.json")`
  - `AppConfig.taxonomy: TaxonomyConfig`, qui vaut `TaxonomyConfig()` si absent

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_config.py` :

```python
def test_taxonomy_config_defaults():
    from mailtag.config import TaxonomyConfig

    cfg = TaxonomyConfig()
    assert cfg.enabled is False
    assert cfg.nomic_threshold == 0.70
    assert cfg.llm_batch_size == 8
    assert cfg.archive_after_days == 7
    assert cfg.pending_archive_file == "db/pending_archive.json"
    assert cfg.legacy_folders_file == "data/legacy_folders.json"


def test_app_config_without_taxonomy_gets_default():
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

    cfg = AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="INFO", file=""),
        classifier=ClassifierConfig(ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
    )
    assert cfg.taxonomy == TaxonomyConfig()


def test_load_config_reads_taxonomy_section(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setenv("MODEL", "test-model")
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[general]\napi_base = ""\n'
        '[logging]\nlevel = "INFO"\nfile = "x.log"\n'
        "[classifier]\nai_confidence_threshold = 0.7\nhistorical_confidence_threshold = 0.9\nmin_count = 3\n"
        '[imap]\nhost = "h"\n'
        '[gmail]\ncredentials_file = "c"\ntoken_file = "t"\n'
        "[taxonomy]\nenabled = true\nnomic_threshold = 0.72\n",
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert cfg.taxonomy.enabled is True
    assert cfg.taxonomy.nomic_threshold == 0.72
    assert cfg.taxonomy.llm_batch_size == 8
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_config.py -q -k taxonomy`
Expected: FAIL, `ImportError: cannot import name 'TaxonomyConfig'`

- [ ] **Step 3: Implémenter**

Dans `src/mailtag/config.py`, après la classe `WebhookConfig` :

```python
@dataclass
class TaxonomyConfig:
    """19-category taxonomy with action folders (see docs/superpowers/specs/2026-09-27-*)."""

    enabled: bool = False
    nomic_threshold: float = 0.70
    llm_batch_size: int = 8
    archive_after_days: int = 7
    pending_archive_file: str = "db/pending_archive.json"
    legacy_folders_file: str = "data/legacy_folders.json"
```

Dans `AppConfig`, ajouter le champ après `webhook` et compléter `__post_init__` :

```python
    webhook: WebhookConfig = None  # type: ignore[assignment]
    taxonomy: TaxonomyConfig = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.webhook is None:
            self.webhook = WebhookConfig()
        if self.taxonomy is None:
            self.taxonomy = TaxonomyConfig()
```

Dans `load_config`, passer `taxonomy=_dataclass_from_dict(TaxonomyConfig, data.get("taxonomy", {})),` à `AppConfig(...)`, juste après `webhook=webhook_config,`.

Dans `config.toml`, après la section `[mlx]` :

```toml
[taxonomy]
# 19-category taxonomy + action folders (spec docs/superpowers/specs/2026-09-27-*)
# Keep false until `scripts/eval_embeddings.py chain` meets the success criteria
enabled = false
nomic_threshold = 0.70
llm_batch_size = 8
archive_after_days = 7
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/mailtag/config.py tests/test_config.py && uv run ruff check src/mailtag/config.py tests/test_config.py
git add src/mailtag/config.py config.toml tests/test_config.py
git commit -m "feat(config): add [taxonomy] section"
```

---

### Task 3: Règles d'action `choose_action`

**Files:**
- Create: `src/mailtag/action_rules.py`
- Test: `tests/test_action_rules.py`

**Interfaces:**
- Consumes : `mailtag.taxonomy` (`ACTION_*`, `REVIEW`).
- Produces : `choose_action(category: str, sender_address: str, subject: str, *, has_unsubscribe: bool, is_bulk: bool) -> str`. `category` vaut soit une clé de `TAXONOMY`, soit `REVIEW`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_action_rules.py` :

```python
import pytest

from mailtag.action_rules import choose_action


def act(category, sender="alice@example.ch", subject="Bonjour", *, unsub=False, bulk=False):
    return choose_action(category, sender, subject, has_unsubscribe=unsub, is_bulk=bulk)


def test_review_category_goes_to_review():
    assert act("9-A revoir") == "9-A revoir"


@pytest.mark.parametrize(
    "subject",
    ["Votre facture de mars", "FACTURE disponible", "Échéance proche", "Rappel de paiement", "Invoice 42",
     "Ihre Rechnung", "Montant dû", "Your bill is ready", "Payment due soon"],
)  # fmt: skip
def test_bill_in_money_category_is_to_pay(subject):
    assert act("Banque & Placements", "noreply@bcv.ch", subject, unsub=True, bulk=True) == "2-A payer"


@pytest.mark.parametrize(
    "category", ["Énergie & Télécom", "Assurances & Retraite", "Impôts & Administration"]
)
def test_other_money_categories_are_to_pay(category):
    assert act(category, "billing@swisscom.com", "Facture septembre", bulk=True) == "2-A payer"


def test_bill_word_outside_money_category_is_not_to_pay():
    assert act("Achats", "shop@example.ch", "Votre facture", bulk=True) == "4-Pour info"


def test_billet_is_not_a_bill():
    assert act("Banque & Placements", "info@bcv.ch", "Gagnez un billet", bulk=True) == "4-Pour info"


def test_bill_from_a_person_is_to_pay_not_to_do():
    assert act("Banque & Placements", "jean.dupont@bcv.ch", "Facture jointe") == "2-A payer"


def test_person_is_to_do():
    assert act("Contacts", "yann@gmail.com", "On se voit demain ?") == "1-A traiter"


@pytest.mark.parametrize(
    "sender",
    ["noreply@x.ch", "no-reply@x.ch", "notifications@x.ch", "newsletter@x.ch", "info@x.ch", "news@x.ch"],
)
def test_automated_sender_is_not_to_do(sender):
    assert act("Outils & Services en ligne", sender, "Hello") == "4-Pour info"


def test_bulk_mail_is_not_to_do():
    assert act("Outils & Services en ligne", "team@x.ch", "Hello", bulk=True) == "4-Pour info"


@pytest.mark.parametrize("subject", ["-30% sur tout", "Offre spéciale", "Soldes d'été", "Promo", "Big SALE", "Rabatt"])
def test_promo_with_unsubscribe_is_promo(subject):
    assert act("Achats", "shop@x.ch", subject, unsub=True, bulk=True) == "5-Promos"


def test_promo_word_without_unsubscribe_is_not_promo():
    assert act("Achats", "shop@x.ch", "Offre spéciale", bulk=True) == "4-Pour info"


@pytest.mark.parametrize("category", ["Veille & Newsletters pro", "Médias & Divertissement"])
def test_reading_categories_are_to_read(category):
    assert act(category, "news@x.ch", "Édition du jour", unsub=True, bulk=True) == "3-A lire"


def test_default_is_info():
    assert act("Colis & Livraisons", "noreply@post.ch", "Votre colis arrive", bulk=True) == "4-Pour info"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_action_rules.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'mailtag.action_rules'`

- [ ] **Step 3: Implémenter**

`src/mailtag/action_rules.py` :

```python
"""Pick the action folder for a classified email (spec section 4). Pure functions, no I/O."""

import re
import unicodedata

from .taxonomy import ACTION_INFO, ACTION_PAY, ACTION_PROMO, ACTION_READ, ACTION_TODO, REVIEW

_MONEY_CATEGORIES = {
    "Banque & Placements",
    "Énergie & Télécom",
    "Assurances & Retraite",
    "Impôts & Administration",
}
_READING_CATEGORIES = {"Veille & Newsletters pro", "Médias & Divertissement"}

# Matched on accent-stripped, lower-cased subjects
_BILL_RE = re.compile(
    r"\b(facture|echeance|rappel|paiement|montant du|invoice|rechnung|mahnung|bill|payment due)\b"
)
_PROMO_RE = re.compile(r"%|\b(offre|promo|rabais|soldes|reduction|sale|rabatt|angebot)\b")
_AUTOMATED_LOCAL_PART_RE = re.compile(r"no-?reply|notification|newsletter")
_AUTOMATED_LOCAL_PARTS = {"info", "news"}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _is_person(sender_address: str, is_bulk: bool) -> bool:
    if is_bulk:
        return False
    local_part = (sender_address or "").split("@")[0].lower()
    return not (_AUTOMATED_LOCAL_PART_RE.search(local_part) or local_part in _AUTOMATED_LOCAL_PARTS)


def choose_action(
    category: str, sender_address: str, subject: str, *, has_unsubscribe: bool, is_bulk: bool
) -> str:
    """Return the action folder for an email; the first matching rule wins."""
    if category == REVIEW:
        return REVIEW
    normalized_subject = _normalize(subject)
    if category in _MONEY_CATEGORIES and _BILL_RE.search(normalized_subject):
        return ACTION_PAY
    if _is_person(sender_address, is_bulk):
        return ACTION_TODO
    if has_unsubscribe and _PROMO_RE.search(normalized_subject):
        return ACTION_PROMO
    if category in _READING_CATEGORIES:
        return ACTION_READ
    return ACTION_INFO
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_action_rules.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/mailtag/action_rules.py tests/test_action_rules.py && uv run ruff check src/mailtag/action_rules.py tests/test_action_rules.py
git add src/mailtag/action_rules.py tests/test_action_rules.py
git commit -m "feat(taxonomy): add action folder rules"
```

---

### Task 4: En-têtes `Message-ID` et listes de diffusion

**Files:**
- Modify: `src/mailtag/models.py`
- Modify: `src/mailtag/imap_service.py` (`_process_email_headers` l.235-270, `get_email_headers` l.290, `_process_full_emails` l.301-340, nouvelle fonction module `list_header_flags`)
- Modify: `tests/mock_imap_client.py:18` (clé de l'en-tête)
- Test: `tests/test_imap_service.py`

**Interfaces:**
- Produces :
  - `Email.message_id: str = ""`, `Email.has_unsubscribe: bool = False`, `Email.is_bulk: bool = False`
  - `list_header_flags(msg: email.message.Message) -> tuple[str, bool, bool]` qui renvoie `(message_id, has_unsubscribe, is_bulk)`
  - `ImapService.get_email_headers(...)` : chaque entrée a en plus les clés `"message_id": str`, `"has_unsubscribe": bool`, `"is_bulk": bool`
  - `HEADER_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_imap_service.py` :

```python
import email as email_lib


def test_list_header_flags_newsletter():
    from mailtag.imap_service import list_header_flags

    msg = email_lib.message_from_string(
        "Message-ID: <abc@x>\nList-Unsubscribe: <mailto:u@x>\nList-Id: <news.x>\n\nbody"
    )
    assert list_header_flags(msg) == ("<abc@x>", True, True)


def test_list_header_flags_precedence_bulk_without_unsubscribe():
    from mailtag.imap_service import list_header_flags

    msg = email_lib.message_from_string("Message-ID: <m@x>\nPrecedence: Bulk\n\nbody")
    assert list_header_flags(msg) == ("<m@x>", False, True)


def test_list_header_flags_person_without_message_id():
    from mailtag.imap_service import list_header_flags

    assert list_header_flags(email_lib.message_from_string("Subject: hi\n\nbody")) == ("", False, False)


def test_get_email_headers_includes_list_flags(mock_imap_client, mocker):
    from mailtag.config import FastParseConfig, ImapConfig
    from mailtag.imap_service import ImapService

    mock_imap_client.mailboxes["INBOX"][1][
        b"BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"
    ] = b"From: Shop <shop@x.ch>\r\nSubject: Promo\r\nMessage-ID: <p@x>\r\nList-Unsubscribe: <u>\r\n"
    service = ImapService(ImapConfig(host="h", user="u", password="p"), FastParseConfig(metrics_enabled=False))
    service.client = mock_imap_client
    mock_imap_client.select_folder("INBOX")

    headers = service.get_email_headers([1])

    assert headers["1"] == {
        "sender_address": "shop@x.ch",
        "subject": "Promo",
        "message_id": "<p@x>",
        "has_unsubscribe": True,
        "is_bulk": True,
    }
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_imap_service.py -q`
Expected: FAIL, `ImportError: cannot import name 'list_header_flags'`

- [ ] **Step 3: Implémenter**

`src/mailtag/models.py`, ajouter à `Email` :

```python
    message_id: str = ""
    has_unsubscribe: bool = False
    is_bulk: bool = False
```

`src/mailtag/imap_service.py`, avant `class ImapService` :

```python
HEADER_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"


def list_header_flags(msg) -> tuple[str, bool, bool]:
    """Return (message_id, has_unsubscribe, is_bulk) from a parsed message's headers."""
    message_id = str(msg.get("Message-ID") or "").strip()
    has_unsubscribe = msg.get("List-Unsubscribe") is not None
    precedence = str(msg.get("Precedence") or "").strip().lower()
    is_bulk = has_unsubscribe or msg.get("List-Id") is not None or precedence in ("bulk", "list", "junk")
    return message_id, has_unsubscribe, is_bulk
```

Dans `_process_email_headers` :
- remplacer `k.startswith(b"BODY[HEADER.FIELDS (FROM SUBJECT)")` par `k.startswith(b"BODY[HEADER.FIELDS (FROM SUBJECT")` ;
- remplacer la construction de `headers[str(msg_id)]` par :

```python
                message_id, has_unsubscribe, is_bulk = list_header_flags(msg)
                headers[str(msg_id)] = {
                    "sender_address": sender_address or "",
                    "subject": subject_header or "",
                    "message_id": message_id,
                    "has_unsubscribe": has_unsubscribe,
                    "is_bulk": is_bulk,
                }
```

Dans `get_email_headers`, remplacer `[b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"]` par `[HEADER_FETCH]`.

Dans `_process_full_emails`, juste avant `emails[msg_id] = Email(`, ajouter `message_id, has_unsubscribe, is_bulk = list_header_flags(msg)`, puis passer `message_id=message_id, has_unsubscribe=has_unsubscribe, is_bulk=is_bulk,` au constructeur `Email(...)`.

Dans `tests/mock_imap_client.py:18`, remplacer la clé `b"BODY[HEADER.FIELDS (FROM SUBJECT)]"` par `b"BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)]"`.

- [ ] **Step 4: Lancer toute la suite (le changement touche passes 1 et 2)**

Run: `uv run pytest -q`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Commit**

```bash
uv run ruff format src tests && uv run ruff check src tests
git add src/mailtag/models.py src/mailtag/imap_service.py tests/mock_imap_client.py tests/test_imap_service.py
git commit -m "feat(imap): read Message-ID and mailing-list headers"
```

---

### Task 5: `SemanticRouter.top_batch`

**Files:**
- Modify: `src/mailtag/semantic_router.py` (`route_batch`, l.189-225)
- Test: `tests/test_semantic_router.py`

**Interfaces:**
- Produces : `SemanticRouter.top_batch(texts: list[str]) -> list[tuple[str, float]]`, qui renvoie la catégorie la plus proche et son score **sans seuil**. Renvoie `[("", 0.0)] * len(texts)` si aucun centroïde n'est chargé. `route_batch` garde exactement son comportement actuel.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_semantic_router.py` :

```python
def test_top_batch_ignores_threshold(mocker):
    import numpy as np

    from mailtag.semantic_router import SemanticRouter

    embedder = mocker.MagicMock()
    embedder.encode.return_value = np.array([[1.0, 0.0], [0.6, 0.8]])
    router = SemanticRouter(embedder, score_threshold=0.99)
    router.category_embeddings = {"A": np.array([1.0, 0.0]), "B": np.array([0.0, 1.0])}
    router.categories = ["A", "B"]
    router._build_embedding_matrix()

    top = router.top_batch(["x", "y"])

    assert [c for c, _ in top] == ["A", "B"]
    assert top[1][1] == pytest.approx(0.8)
    assert router.route_batch(["x", "y"])[1] == ("", pytest.approx(0.8))


def test_top_batch_without_centroids(mocker):
    from mailtag.semantic_router import SemanticRouter

    assert SemanticRouter(mocker.MagicMock()).top_batch(["x"]) == [("", 0.0)]
```

(Ajouter `import pytest` en tête si absent.)

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_semantic_router.py -q -k top_batch`
Expected: FAIL, `AttributeError: 'SemanticRouter' object has no attribute 'top_batch'`

- [ ] **Step 3: Implémenter**

Dans `src/mailtag/semantic_router.py`, remplacer toute la méthode `route_batch` par :

```python
    def top_batch(self, texts: list[str]) -> list[tuple[str, float]]:
        """Return the nearest category and its similarity for each text, without threshold."""
        if not self.categories or self._embedding_matrix is None:
            return [("", 0.0)] * len(texts)
        if not texts:
            return []

        query_embeddings = self.embedder.encode(texts, prefix="search_query: ")
        norms = np.linalg.norm(query_embeddings, axis=1, keepdims=True)
        similarities = np.dot(query_embeddings / norms, self._embedding_matrix.T)

        best = np.argmax(similarities, axis=1)
        return [(self.categories[j], float(similarities[i][j])) for i, j in enumerate(best)]

    def route_batch(self, texts: list[str]) -> list[tuple[str, float]]:
        """Route multiple texts to categories in a single batch (more efficient than per-item).

        Args:
            texts: List of input texts to classify

        Returns:
            List of (category, similarity_score) tuples, one per input text.
            Returns ("", score) for texts where no category meets threshold.
        """
        return [
            (category, score) if category and score >= self.score_threshold else ("", score)
            for category, score in self.top_batch(texts)
        ]
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_semantic_router.py -q`
Expected: PASS (anciens et nouveaux)

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/mailtag/semantic_router.py tests/test_semantic_router.py && uv run ruff check src/mailtag/semantic_router.py tests/test_semantic_router.py
git add src/mailtag/semantic_router.py tests/test_semantic_router.py
git commit -m "feat(router): add top_batch returning nearest category without threshold"
```

---

### Task 6: `MLXLLM.classify_batch` (cache du début du prompt et lots)

**Files:**
- Modify: `src/mailtag/mlx_provider.py` (classe `MLXLLM` : `__init__`, nouvelle méthode après `classify`)
- Modify: `pyproject.toml:36` (`"mlx-lm>=0.18.0"` → `"mlx-lm>=0.31.0"`), puis `uv lock`
- Test: `tests/test_mlx_provider.py`

**Interfaces:**
- Consumes : rien des tâches précédentes (le prompt est passé en argument).
- Produces : `MLXLLM.classify_batch(static_prompt: str, email_parts: list[str], batch_size: int = 8, max_tokens: int = 4) -> list[str]`. Renvoie le texte brut de la réponse pour chaque mail, dans l'ordre. Le début du prompt (`static_prompt`) n'est calculé qu'une fois par valeur distincte.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_mlx_provider.py` :

```python
class TestMLXLLMClassifyBatch:
    def _fake_mlx(self, mocker):
        fake_mlx_lm = mocker.MagicMock()
        fake_mlx_lm.batch_generate.side_effect = lambda model, tok, prompts, **kw: mocker.MagicMock(
            texts=[f" {i + 1}\n" for i in range(len(prompts))]
        )
        fake_generate = mocker.MagicMock()
        fake_generate.generate_step.return_value = iter([])
        fake_cache = mocker.MagicMock()
        fake_cache.make_prompt_cache.return_value = ["kv"]
        mocker.patch.dict(
            sys.modules,
            {
                "mlx": mocker.MagicMock(),
                "mlx.core": mocker.MagicMock(),
                "mlx_lm": fake_mlx_lm,
                "mlx_lm.generate": fake_generate,
                "mlx_lm.models": mocker.MagicMock(),
                "mlx_lm.models.cache": fake_cache,
                "mlx_lm.sample_utils": mocker.MagicMock(),
            },
        )
        return fake_mlx_lm, fake_generate

    def _llm(self, mocker):
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        llm._model = mocker.MagicMock()
        tokenizer = mocker.MagicMock()
        tokenizer.apply_chat_template.return_value = "<bos>PRE<<<EMAIL>>>POST"
        tokenizer.encode.side_effect = lambda text, add_special_tokens=True: list(range(len(text)))
        llm._tokenizer = tokenizer
        return llm

    def test_batches_and_returns_raw_answers(self, mocker):
        fake_mlx_lm, _ = self._fake_mlx(mocker)
        llm = self._llm(mocker)

        answers = llm.classify_batch("STATIC", ["a", "b", "c"], batch_size=2)

        assert answers == ["1", "2", "1"]
        assert fake_mlx_lm.batch_generate.call_count == 2
        first_call = fake_mlx_lm.batch_generate.call_args_list[0]
        assert len(first_call.kwargs["prompt_caches"]) == 2
        assert first_call.kwargs["max_tokens"] == 4

    def test_prefix_computed_once_per_static_prompt(self, mocker):
        _, fake_generate = self._fake_mlx(mocker)
        llm = self._llm(mocker)

        llm.classify_batch("STATIC", ["a"])
        llm.classify_batch("STATIC", ["b"])
        llm.classify_batch("OTHER", ["c"])

        assert fake_generate.generate_step.call_count == 2

    def test_empty_input(self, mocker):
        self._fake_mlx(mocker)
        assert self._llm(mocker).classify_batch("STATIC", []) == []
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_mlx_provider.py -q -k ClassifyBatch`
Expected: FAIL, `AttributeError: 'MLXLLM' object has no attribute 'classify_batch'`

- [ ] **Step 3: Implémenter**

Dans `MLXLLM.__init__`, après `self._sampler = None`, ajouter :

```python
        self._prefix_key: str | None = None
        self._prefix_cache = None
        self._prefix_post = ""
```

Ajouter la méthode après `classify` :

```python
    def classify_batch(
        self, static_prompt: str, email_parts: list[str], batch_size: int = 8, max_tokens: int = 4
    ) -> list[str]:
        """Answer one short prompt per email, reusing the KV cache of the shared static prefix.

        The chat-formatted prompt is `static_prompt + email_part`; the static part is prefilled once
        per distinct value and each email only prefills its own tokens. Emails run in batches.
        """
        import copy

        import mlx.core as mx
        from mlx_lm import batch_generate
        from mlx_lm.generate import generate_step
        from mlx_lm.models.cache import make_prompt_cache
        from mlx_lm.sample_utils import make_sampler

        if not email_parts:
            return []

        if self._prefix_key != static_prompt:
            marker = "<<<EMAIL>>>"
            messages = [{"role": "user", "content": static_prompt + marker}]
            try:
                template = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
                )
            except TypeError:
                template = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            pre, self._prefix_post = template.split(marker)
            cache = make_prompt_cache(self.model)
            for _ in generate_step(mx.array(self.tokenizer.encode(pre)), self.model, max_tokens=0, prompt_cache=cache):
                pass
            self._prefix_cache, self._prefix_key = cache, static_prompt

        suffixes = [self.tokenizer.encode(part + self._prefix_post, add_special_tokens=False) for part in email_parts]
        sampler = make_sampler(temp=0.0)
        texts: list[str] = []
        for start in range(0, len(suffixes), batch_size):
            chunk = suffixes[start : start + batch_size]
            response = batch_generate(
                self.model,
                self.tokenizer,
                chunk,
                prompt_caches=[copy.deepcopy(self._prefix_cache) for _ in chunk],
                max_tokens=max_tokens,
                sampler=sampler,
            )
            texts.extend(text.strip() for text in response.texts)
        return texts
```

Dans `pyproject.toml`, passer `"mlx-lm>=0.18.0"` à `"mlx-lm>=0.31.0"`, puis lancer `uv lock`.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_mlx_provider.py -q`
Expected: PASS

- [ ] **Step 5: Vérification sur la vraie machine (Apple Silicon)**

```bash
uv run python -c "
import sys; sys.path.insert(0,'src')
from mailtag.mlx_provider import MLXLLM
from mailtag.taxonomy import llm_static_prompt, llm_email_part, parse_category_number
llm = MLXLLM('mlx-community/gemma-4-e4b-it-OptiQ-4bit')
out = llm.classify_batch(llm_static_prompt(), [llm_email_part('Votre facture Swisscom', 'Swisscom <bill@swisscom.com>', 'Montant: 59 CHF')])
print(out, parse_category_number(out[0]))"
```
Expected : une réponse numérique, par exemple `['4'] Énergie & Télécom`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format src/mailtag/mlx_provider.py tests/test_mlx_provider.py && uv run ruff check src/mailtag/mlx_provider.py tests/test_mlx_provider.py
git add src/mailtag/mlx_provider.py tests/test_mlx_provider.py pyproject.toml uv.lock
git commit -m "feat(mlx): batched LLM classification with cached static prompt prefix"
```

---

### Task 7: Chaîne de classification du mode taxonomie dans `Classifier`

**Files:**
- Modify: `src/mailtag/classifier.py` (`__init__` l.52-60, `classify_email` l.548, `classify_emails_batch` l.680, nouvelles méthodes avant `export_metrics`)
- Test: `tests/test_classifier_taxonomy.py` (créé)

**Interfaces:**
- Consumes :
  - `mailtag.taxonomy` : `TAXONOMY`, `REVIEW`, `to_category`, `llm_static_prompt`, `llm_email_part`, `parse_category_number`
  - `SemanticRouter.top_batch` (Task 5)
  - `MLXLLM.classify_batch` (Task 6)
  - `config.taxonomy` (Task 2)
- Produces :
  - En mode taxonomie, `Classifier.classify_emails_batch(emails) -> list[str]` et `Classifier.classify_email(email) -> str` renvoient une clé de `TAXONOMY` ou `REVIEW`.
  - `Classifier._classify_uncertain(emails: list[Email]) -> list[str]` : signaux 5 et 6 et vérification d'accord, réutilisée par la commande `chain` de la Task 11.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_classifier_taxonomy.py` :

```python
from collections import defaultdict

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
from mailtag.database import ClassificationDatabase
from mailtag.models import Email
from mailtag.taxonomy import REVIEW, TAXONOMY


@pytest.fixture
def db(mocker):
    db = mocker.MagicMock(spec=ClassificationDatabase)
    db.get_dominant_classification.return_value = None
    db.get_sender_classifications.return_value = {}
    db.get_category_by_domain.return_value = None
    db.suggestion_db = defaultdict(lambda: defaultdict(int))
    return db


@pytest.fixture
def classifier(db, mocker):
    config = AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(enabled=True, nomic_threshold=0.70, llm_batch_size=8),
    )
    return Classifier(config=config, database=db)


def mail(i=1, sender="x@shop.ch", subject="S", body="B", labels=None):
    return Email(msg_id=str(i), subject=subject, sender_address=sender, sender_name="", body=body, labels=labels or [])


def test_categories_are_the_taxonomy(classifier):
    assert classifier.categories == list(TAXONOMY)


def test_validated_old_path_is_mapped(classifier, db, mocker):
    db.get_dominant_classification.return_value = "Voyages/Sixt"
    uncertain = mocker.patch.object(classifier, "_classify_uncertain")

    assert classifier.classify_emails_batch([mail()]) == ["Voyages & Loisirs"]
    uncertain.assert_not_called()


def test_domain_rule_is_mapped(classifier, db, mocker):
    db.get_category_by_domain.return_value = "Finance/Local/BCV"
    mocker.patch.object(classifier, "_classify_uncertain")

    assert classifier.classify_emails_batch([mail(sender="a@bcv.ch")]) == ["Banque & Placements"]


def test_rules_skip_unmappable_old_values(classifier, db, mocker):
    db.get_dominant_classification.return_value = "À Classer"
    mocker.patch.object(classifier, "_classify_uncertain", return_value=[REVIEW])

    assert classifier.classify_emails_batch([mail()]) == [REVIEW]


def test_classify_email_delegates_to_batch(classifier, mocker):
    mocker.patch.object(classifier, "_classify_uncertain", return_value=["Achats"])

    assert classifier.classify_email(mail()) == "Achats"


def test_chain_nomic_above_threshold_wins(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.75)])
    llm = mocker.patch.object(classifier, "_llm_categories")

    assert classifier._classify_uncertain([mail()]) == ["Achats"]
    llm.assert_not_called()


def test_chain_agreement_classifies(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    assert classifier._classify_uncertain([mail()]) == ["Santé"]


def test_chain_disagreement_goes_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Achats"])

    assert classifier._classify_uncertain([mail()]) == [REVIEW]


def test_chain_unparsable_llm_goes_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=[None])

    assert classifier._classify_uncertain([mail()]) == [REVIEW]


def test_chain_mixed_batch_keeps_order(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.9), ("Santé", 0.5), ("Contacts", 0.4)])
    llm = mocker.patch.object(classifier, "_llm_categories", return_value=["Santé", "Achats"])

    result = classifier._classify_uncertain([mail(1), mail(2), mail(3)])

    assert result == ["Achats", "Santé", REVIEW]
    assert [e.msg_id for e in llm.call_args.args[0]] == ["2", "3"]


def test_nomic_failure_sends_everything_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    router = mocker.MagicMock()
    router.num_categories = 3
    router.top_batch.side_effect = AttributeError("'NomicBertModel' object has no attribute 'x'")
    classifier._semantic_router = router
    mocker.patch.object(classifier, "_llm_categories", return_value=["Achats", "Santé"])

    assert classifier._classify_uncertain([mail(1), mail(2)]) == [REVIEW, REVIEW]


def test_nomic_top_maps_old_folder_to_category(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    router = mocker.MagicMock()
    router.num_categories = 3
    router.top_batch.return_value = [("Voyages/Sixt", 0.8), ("INBOX", 0.9)]
    classifier._semantic_router = router

    assert classifier._nomic_top([mail(1), mail(2)]) == [("Voyages & Loisirs", 0.8), (None, 0.9)]


def test_llm_categories_parses_numbers(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    llm = mocker.MagicMock()
    llm.classify_batch.return_value = ["8", "abc"]
    classifier._mlx_llm = llm

    assert classifier._llm_categories([mail(1), mail(2, body="x" * 2000)]) == ["Achats", None]
    static, parts = llm.classify_batch.call_args.args[:2]
    assert static.startswith("Classe cet email")
    assert len(parts[1]) < 700  # body truncated to 500 chars
    assert llm.classify_batch.call_args.kwargs["batch_size"] == 8


def test_llm_failure_returns_none(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    llm = mocker.MagicMock()
    llm.classify_batch.side_effect = RuntimeError("metal")
    classifier._mlx_llm = llm

    assert classifier._llm_categories([mail()]) == [None]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_classifier_taxonomy.py -q`
Expected: FAIL (`categories` ne vaut pas la taxonomie, et `_classify_uncertain` n'existe pas)

- [ ] **Step 3: Implémenter**

Imports en tête de `src/mailtag/classifier.py` :

```python
from .taxonomy import REVIEW, TAXONOMY, llm_email_part, llm_static_prompt, parse_category_number, to_category
```

Dans `__init__`, remplacer le bloc `# Use either folder analyzer or static schema...` par :

```python
        # Use the taxonomy, the folder analyzer or the static schema based on configuration
        if config.taxonomy.enabled:
            self.folder_analyzer = None
            self.categories = list(TAXONOMY)
            logger.info(f"Using the {len(self.categories)}-category taxonomy")
        elif config.general.use_imap_folders_for_classification:
            self.folder_analyzer = FolderAnalyzer()
            self.categories = self.folder_analyzer.get_all_categories()
            logger.info(f"Using dynamic IMAP folder structure with {len(self.categories)} categories")
        else:
            self.folder_analyzer = None
            self.categories = self._load_categories_from_schema()
            logger.info(f"Using static classification schema with {len(self.categories)} categories")
```

Première instruction de `classify_email` (avant `start_time = ...`) :

```python
        if self.config.taxonomy.enabled:
            return self._classify_batch_taxonomy([email])[0]
```

Première instruction de `classify_emails_batch` (avant `results: list[str | None] = ...`) :

```python
        if self.config.taxonomy.enabled:
            return self._classify_batch_taxonomy(emails)
```

Nouvelles méthodes, juste avant `def export_metrics` :

```python
    # --- Taxonomy mode (spec docs/superpowers/specs/2026-09-27-taxonomie-19-categories-design.md) ---

    def _rule_category(self, email: Email) -> str | None:
        """Signals 1-4 with stored values (old folder paths or categories) mapped to the taxonomy."""
        category = to_category(self._get_category_from_validated_db(email))
        if category:
            return category
        for label in email.labels:
            category = to_category(label)
            if category:
                return category
        return to_category(self._get_category_from_history(email)) or to_category(
            self._get_category_from_domain(email)
        )

    def _nomic_top(self, emails: list[Email]) -> list[tuple[str | None, float]]:
        """Signal 5: nearest old folder per email, mapped to its category, with its similarity."""
        unavailable = [(None, 0.0)] * len(emails)
        if not self._init_mlx_components() or not self._semantic_router:
            return unavailable
        if self._semantic_router.num_categories == 0:
            return unavailable
        texts = []
        for e in emails:
            text = f"Email from {e.sender_name or e.sender_address or 'Unknown'}: {e.subject}"
            body = self._truncate_body(e.body, max_chars=500) if e.body else ""
            texts.append(f"{text}\n{body}" if body else text)
        try:
            top = self._semantic_router.top_batch(texts)
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.error(f"Semantic router failed, sending emails to review: {e}")
            return unavailable
        return [(to_category(folder), score) for folder, score in top]

    def _llm_categories(self, emails: list[Email]) -> list[str | None]:
        """Signal 6: one category (or None) per email from the LLM, answered by number."""
        if not self._init_mlx_components() or self._mlx_llm is None:
            return [None] * len(emails)
        parts = [
            llm_email_part(
                e.subject,
                f"{e.sender_name} <{e.sender_address}>" if e.sender_name else e.sender_address,
                self._truncate_body(e.body, max_chars=500),
            )
            for e in emails
        ]
        try:
            answers = self._mlx_llm.classify_batch(
                llm_static_prompt(), parts, batch_size=self.config.taxonomy.llm_batch_size
            )
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as e:
            logger.error(f"LLM batch failed, sending emails to review: {e}")
            return [None] * len(emails)
        return [parse_category_number(answer) for answer in answers]

    def _classify_uncertain(self, emails: list[Email]) -> list[str]:
        """Signals 5-6: nomic above threshold, else LLM when it agrees with nomic's top choice, else REVIEW."""
        results: list[str] = [REVIEW] * len(emails)
        need_llm: list[tuple[int, str | None]] = []
        for i, (category, score) in enumerate(self._nomic_top(emails)):
            if category and score >= self.config.taxonomy.nomic_threshold:
                results[i] = category
            else:
                need_llm.append((i, category))
        if need_llm:
            answers = self._llm_categories([emails[i] for i, _ in need_llm])
            for (i, nomic_category), llm_category in zip(need_llm, answers, strict=True):
                if llm_category and llm_category == nomic_category:
                    results[i] = llm_category
        return results

    def _classify_batch_taxonomy(self, emails: list[Email]) -> list[str]:
        """Taxonomy mode: rules first, then the nomic/LLM chain for the rest."""
        results: list[str | None] = [self._rule_category(e) for e in emails]
        pending = [i for i, category in enumerate(results) if category is None]
        if pending:
            for i, category in zip(pending, self._classify_uncertain([emails[i] for i in pending]), strict=True):
                results[i] = category
                if category != REVIEW:
                    self.database.update_suggestion(emails[i].sender_address, category)
        logger.info(
            f"Taxonomy batch: {len(emails) - len(pending)} by rules, "
            f"{sum(1 for i in pending if results[i] != REVIEW)} by models, "
            f"{sum(1 for r in results if r == REVIEW)} to review"
        )
        return results  # type: ignore[return-value]
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent, puis toute la suite**

Run: `uv run pytest tests/test_classifier_taxonomy.py -q && uv run pytest -q`
Expected: PASS (le mode par défaut n'est pas modifié)

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/mailtag/classifier.py tests/test_classifier_taxonomy.py && uv run ruff check src/mailtag/classifier.py tests/test_classifier_taxonomy.py
git add src/mailtag/classifier.py tests/test_classifier_taxonomy.py
git commit -m "feat(classifier): taxonomy mode with nomic/LLM agreement chain"
```

---

### Task 8: Stockage `PendingArchive`

**Files:**
- Create: `src/mailtag/pending_archive.py`
- Test: `tests/test_pending_archive.py`

**Interfaces:**
- Produces : classe `PendingArchive(path: Path)` avec :
  - `.add(message_id: str, category: str | None, sender: str, added: str) -> None`
  - `.get(message_id: str) -> dict | None` (clés `"category"`, `"sender"`, `"added"`)
  - `.remove(message_id: str) -> None` (sans effet si l'identifiant est absent)
  - `.items() -> list[tuple[str, dict]]` (copie)
  - `.save() -> None` (écriture atomique)

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_pending_archive.py` :

```python
import json

from mailtag.pending_archive import PendingArchive


def test_add_get_remove_and_persist(tmp_path):
    path = tmp_path / "pending.json"
    store = PendingArchive(path)
    store.add("<a@x>", "Achats", "shop@x.ch", "2026-09-27")
    store.add("<b@x>", None, "p@x.ch", "2026-09-27")
    store.remove("<missing@x>")
    store.save()

    reloaded = PendingArchive(path)
    assert reloaded.get("<a@x>") == {"category": "Achats", "sender": "shop@x.ch", "added": "2026-09-27"}
    assert reloaded.get("<b@x>")["category"] is None
    reloaded.remove("<a@x>")
    assert [mid for mid, _ in reloaded.items()] == ["<b@x>"]


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "pending.json"
    store = PendingArchive(path)
    store.add("<a@x>", "Santé", "d@x.ch", "2026-09-27")
    store.save()

    assert json.loads(path.read_text(encoding="utf-8"))["<a@x>"]["category"] == "Santé"
    assert [p.name for p in tmp_path.iterdir()] == ["pending.json"]


def test_missing_or_corrupt_file_starts_empty(tmp_path):
    assert PendingArchive(tmp_path / "none.json").items() == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert PendingArchive(bad).items() == []
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_pending_archive.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'mailtag.pending_archive'`

- [ ] **Step 3: Implémenter**

`src/mailtag/pending_archive.py` :

```python
"""Category of each email waiting in an action folder, keyed by Message-ID (spec sections 2, 5, 6)."""

import json
import os
import tempfile
from pathlib import Path

from loguru import logger


class PendingArchive:
    """JSON store `Message-ID -> {category, sender, added}` with atomic saves."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error(f"Could not parse {self.path}, starting with an empty pending archive")
            return {}

    def add(self, message_id: str, category: str | None, sender: str, added: str) -> None:
        self._entries[message_id] = {"category": category, "sender": sender, "added": added}

    def get(self, message_id: str) -> dict | None:
        return self._entries.get(message_id)

    def remove(self, message_id: str) -> None:
        self._entries.pop(message_id, None)

    def items(self) -> list[tuple[str, dict]]:
        return list(self._entries.items())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_pending_archive.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff format src/mailtag/pending_archive.py tests/test_pending_archive.py && uv run ruff check src/mailtag/pending_archive.py tests/test_pending_archive.py
git add src/mailtag/pending_archive.py tests/test_pending_archive.py
git commit -m "feat(taxonomy): add atomic pending-archive store"
```

---

### Task 9: Dépôt dans les dossiers d'action (`routing.py`) et passes 1 à 3

**Files:**
- Create: `src/mailtag/routing.py`
- Modify: `src/mailtag/utils/tasks.py` (`_run_fast_parse_on_folder` l.19-75, `_run_domain_classification_pass` l.78-185, bloc IMAP de `run_classification` l.187-245)
- Test: `tests/test_routing.py`

**Interfaces:**
- Consumes :
  - `choose_action` (Task 3)
  - `PendingArchive` (Task 8)
  - `REVIEW`, `to_category` (Task 1)
  - les en-têtes de la Task 4 (`message_id`, `has_unsubscribe`, `is_bulk`)
  - `ImapService.batch_move_emails(uids, destination)`
- Produces :
  - `RoutedMail` : dataclass avec `uid: str`, `category: str`, `sender_address: str`, `subject: str`, `message_id: str`, `has_unsubscribe: bool`, `is_bulk: bool`
  - `RoutedMail.from_headers(uid: str, category: str, header: dict) -> RoutedMail`
  - `RoutedMail.from_email(email: Email, category: str) -> RoutedMail`
  - `route_to_action_folders(provider, pending: PendingArchive, mails: list[RoutedMail], validate: bool, today: date) -> int` (nombre de mails déplacés)
  - Dans `tasks.py`, les fonctions de passe prennent en plus un argument `pending: PendingArchive | None = None`. `None` signifie le flux actuel.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_routing.py` :

```python
from datetime import date

import pytest

from mailtag.models import Email
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders

TODAY = date(2026, 9, 27)


def routed(uid, category, sender="noreply@x.ch", subject="Info", mid=None, unsub=False, bulk=True):
    return RoutedMail(uid, category, sender, subject, mid if mid is not None else f"<{uid}@x>", unsub, bulk)


@pytest.fixture
def pending(tmp_path):
    return PendingArchive(tmp_path / "pending.json")


def test_groups_moves_by_action_folder_and_records_category(mocker, pending):
    provider = mocker.MagicMock()
    mails = [
        routed("1", "Banque & Placements", subject="Votre facture"),
        routed("2", "Médias & Divertissement"),
        routed("3", "Médias & Divertissement"),
        routed("4", "9-A revoir"),
    ]

    moved = route_to_action_folders(provider, pending, mails, validate=False, today=TODAY)

    assert moved == 4
    calls = {c.args[1]: c.args[0] for c in provider.batch_move_emails.call_args_list}
    assert calls == {"2-A payer": ["1"], "3-A lire": ["2", "3"], "9-A revoir": ["4"]}
    assert pending.get("<1@x>") == {"category": "Banque & Placements", "sender": "noreply@x.ch", "added": "2026-09-27"}
    assert pending.get("<4@x>")["category"] is None
    assert (pending.path).exists()


def test_validate_moves_nothing_and_records_nothing(mocker, pending):
    provider = mocker.MagicMock()

    assert route_to_action_folders(provider, pending, [routed("1", "Achats")], validate=True, today=TODAY) == 0
    provider.batch_move_emails.assert_not_called()
    assert pending.items() == []


def test_failed_move_is_not_recorded(mocker, pending):
    provider = mocker.MagicMock()
    provider.batch_move_emails.side_effect = ConnectionError("down")

    assert route_to_action_folders(provider, pending, [routed("1", "Achats")], validate=False, today=TODAY) == 0
    assert pending.items() == []


def test_mail_without_message_id_is_moved_but_not_tracked(mocker, pending):
    provider = mocker.MagicMock()

    moved = route_to_action_folders(provider, pending, [routed("1", "Achats", mid="")], validate=False, today=TODAY)

    assert moved == 1
    assert pending.items() == []


def test_from_headers_and_from_email():
    header = {"sender_address": "a@x", "subject": "S", "message_id": "<m>", "has_unsubscribe": True, "is_bulk": True}
    assert RoutedMail.from_headers("7", "Achats", header) == RoutedMail("7", "Achats", "a@x", "S", "<m>", True, True)

    email = Email(msg_id="8", subject="S", sender_address="a@x", sender_name="", message_id="<n>", is_bulk=True)
    assert RoutedMail.from_email(email, "Santé") == RoutedMail("8", "Santé", "a@x", "S", "<n>", False, True)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_routing.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'mailtag.routing'`

- [ ] **Step 3: Implémenter `routing.py`**

`src/mailtag/routing.py` :

```python
"""Move classified emails into action folders and remember their category (spec section 5)."""

import imaplib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from loguru import logger

from .action_rules import choose_action
from .models import Email
from .pending_archive import PendingArchive
from .taxonomy import REVIEW


@dataclass(frozen=True)
class RoutedMail:
    uid: str
    category: str
    sender_address: str
    subject: str
    message_id: str
    has_unsubscribe: bool
    is_bulk: bool

    @classmethod
    def from_headers(cls, uid: str, category: str, header: dict) -> "RoutedMail":
        return cls(
            uid,
            category,
            header["sender_address"],
            header["subject"],
            header.get("message_id", ""),
            header.get("has_unsubscribe", False),
            header.get("is_bulk", False),
        )

    @classmethod
    def from_email(cls, email: Email, category: str) -> "RoutedMail":
        return cls(
            email.msg_id,
            category,
            email.sender_address,
            email.subject,
            email.message_id,
            email.has_unsubscribe,
            email.is_bulk,
        )


def route_to_action_folders(
    provider, pending: PendingArchive, mails: list[RoutedMail], validate: bool, today: date
) -> int:
    """Move each email to its action folder and record its category; return the number moved."""
    by_folder: dict[str, list[RoutedMail]] = defaultdict(list)
    for m in mails:
        folder = choose_action(
            m.category, m.sender_address, m.subject, has_unsubscribe=m.has_unsubscribe, is_bulk=m.is_bulk
        )
        logger.info(f'Email "{m.subject}" from {m.sender_address} -> {m.category} / {folder}')
        by_folder[folder].append(m)

    if validate:
        return 0

    moved = 0
    for folder, group in by_folder.items():
        try:
            provider.batch_move_emails([m.uid for m in group], folder)
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"Could not move {len(group)} emails to {folder}: {e}")
            continue
        moved += len(group)
        for m in group:
            if not m.message_id:
                logger.warning(f"No Message-ID for UID {m.uid} ({m.sender_address}); it will not be archived")
                continue
            category = None if m.category == REVIEW else m.category
            pending.add(m.message_id, category, m.sender_address, today.isoformat())
    pending.save()
    return moved
```

- [ ] **Step 4: Lancer les tests de routage pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_routing.py -q`
Expected: PASS

- [ ] **Step 5: Brancher les passes 1 à 3 dans `tasks.py`**

Imports à ajouter dans `src/mailtag/utils/tasks.py` :

```python
from datetime import date, datetime

from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders
from mailtag.taxonomy import to_category
```

(et retirer l'ancien `from datetime import datetime`).

**Passe 1**, `_run_fast_parse_on_folder` :
- ajouter le paramètre `pending: PendingArchive | None = None` en dernier ;
- remplacer la boucle `for uid, header_data in headers.items():` et le déplacement qui la suit par :

```python
        emails_to_move = {}
        routed: list[RoutedMail] = []
        for uid, header_data in headers.items():
            sender_address = header_data["sender_address"]
            subject = header_data["subject"]
            classification = database.get_dominant_classification(sender_address)
            if pending is not None:
                classification = to_category(classification)
            if classification:
                logger.info(f'Email "{subject}" from {sender_address} -> Category: {classification} (Pass 1)')
                if pending is not None:
                    routed.append(RoutedMail.from_headers(uid, classification, header_data))
                else:
                    emails_to_move.setdefault(classification, []).append(uid)
            else:
                uids_to_process_pass2.append(uid)
                pass2_headers[uid] = header_data

        if routed:
            route_to_action_folders(provider, pending, routed, validate, date.today())
        for classification, uids in emails_to_move.items():
            if not validate:
                provider.batch_move_emails(uids, classification)
```

**Passe 2**, `_run_domain_classification_pass` :
- ajouter le paramètre `pending: PendingArchive | None = None` en dernier ;
- juste après `category = database.get_category_by_domain(domain)`, ajouter :

```python
        if pending is not None:
            category = to_category(category)
```

- dans la branche `if category:`, remplacer le bloc `# Batch move all emails from this domain` (le `if not validate ...` et son `try/except`) par :

```python
            if pending is not None:
                emails_moved += route_to_action_folders(
                    provider,
                    pending,
                    [RoutedMail.from_headers(uid, category, headers[uid]) for uid in domain_uids],
                    validate,
                    date.today(),
                )
            elif not validate and category not in ["Unclassified", "À Classer", "(Model Error)"]:
                try:
                    provider.batch_move_emails(domain_uids, category)
                    emails_moved += len(domain_uids)
                    logger.info(f"Moved {len(domain_uids)} emails from {domain} to {category}")
                except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                    logger.error(f"Could not move emails from domain {domain}: {e}")
                    uids_for_pass3.extend(domain_uids)
```

**`run_classification` :**
- ajouter `import dataclasses` aux imports du module ;
- remplacer `classifier = Classifier(CONFIG, database)` par le bloc suivant. La spec exclut Gmail : il garde le flux actuel.

```python
        if isinstance(provider_instance, ImapService):
            classifier = Classifier(CONFIG, database)
        else:
            gmail_config = dataclasses.replace(
                CONFIG, taxonomy=dataclasses.replace(CONFIG.taxonomy, enabled=False)
            )
            classifier = Classifier(gmail_config, database)
        pending = PendingArchive(Path(CONFIG.taxonomy.pending_archive_file)) if CONFIG.taxonomy.enabled else None
```

- passer `pending=pending` aux trois appels `_run_fast_parse_on_folder(...)` et `_run_domain_classification_pass(...)` ;
- dans la passe 3, remplacer le bloc qui va de `# Accumulate moves by category` jusqu'à la fin de la boucle `# Execute batch moves per category` par :

```python
                    if pending is not None:
                        route_to_action_folders(
                            provider,
                            pending,
                            [RoutedMail.from_email(e, c) for e, c in zip(full_emails, categories, strict=True)],
                            validate,
                            date.today(),
                        )
                    else:
                        # Accumulate moves by category for batch IMAP operations
                        moves: dict[str, list[str]] = {}
                        for email_obj, category in zip(full_emails, categories, strict=True):
                            logger.info(
                                f'Email "{email_obj.subject}" from {email_obj.sender_address}'
                                f" -> Category: {category}"
                            )
                            if not validate and category not in [
                                "Unclassified",
                                "À Classer",
                                "(Model Error)",
                            ]:
                                moves.setdefault(category, []).append(email_obj.msg_id)

                        # Execute batch moves per category
                        for category, uids in moves.items():
                            try:
                                provider.batch_move_emails(uids, category)
                            except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                                logger.error(f"Could not batch-move {len(uids)} emails to {category}: {e}")
```

- [ ] **Step 6: Test d'intégration des passes en mode taxonomie**

Ajouter à `tests/test_routing.py` :

```python
def test_pass1_routes_known_sender_in_taxonomy_mode(mocker, pending):
    from mailtag.utils import tasks

    provider = mocker.MagicMock()
    provider.client.search.return_value = [1, 2]
    provider.fast_parse_config.batch_size = 100
    provider.get_email_headers.return_value = {
        "1": {"sender_address": "a@sixt.ch", "subject": "Réservation", "message_id": "<1>",
              "has_unsubscribe": False, "is_bulk": True},
        "2": {"sender_address": "new@x.ch", "subject": "Hi", "message_id": "<2>",
              "has_unsubscribe": False, "is_bulk": False},
    }  # fmt: skip
    database = mocker.MagicMock()
    database.get_dominant_classification.side_effect = lambda s: "Voyages/Sixt" if s == "a@sixt.ch" else None

    uids, headers = tasks._run_fast_parse_on_folder(provider, database, "INBOX", False, pending=pending)

    assert uids == ["2"]
    provider.batch_move_emails.assert_called_once_with(["1"], "4-Pour info")
    assert pending.get("<1>")["category"] == "Voyages & Loisirs"
```

Run: `uv run pytest tests/test_routing.py -q && uv run pytest -q`
Expected: PASS (le flux actuel n'est pas modifié quand `pending` vaut `None`)

- [ ] **Step 7: Commit**

```bash
uv run ruff format src tests && uv run ruff check src tests
git add src/mailtag/routing.py src/mailtag/utils/tasks.py tests/test_routing.py
git commit -m "feat(taxonomy): route classified emails to action folders in passes 1-3"
```

---

### Task 10: Ménage de fin de passage (`archive.py`), branchement et documentation

**Files:**
- Create: `src/mailtag/archive.py`
- Modify: `src/mailtag/utils/tasks.py` (fin de la branche IMAP de `run_classification`)
- Modify: `scripts/build_category_embeddings.py` (valeur par défaut de `--folders`)
- Modify: `CLAUDE.md` (section Architecture)
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes :
  - `PendingArchive` (Task 8)
  - `ACTION_FOLDERS`, `REVIEW`, `TAXONOMY` (Task 1)
  - `ClassificationDatabase.promote_to_validated(sender, category)`
  - `ImapService.batch_move_emails`
  - `provider.client` (IMAPClient : `folder_exists`, `select_folder`, `search`, `fetch`)
- Produces : `run_archive(provider, pending: PendingArchive, database, days: int, today: date, validate: bool = False) -> dict[str, int]`, qui renvoie les clés `"archived"`, `"learned"` et `"orphans"`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_archive.py` :

```python
from datetime import date

import pytest

from mailtag.archive import run_archive
from mailtag.pending_archive import PendingArchive

TODAY = date(2026, 9, 27)


class FakeClient:
    """Folders of {uid: {"mid": str, "seen": bool, "flagged": bool, "old": bool}}."""

    def __init__(self, folders):
        self.folders = folders
        self.current = None

    def folder_exists(self, name):
        return name in self.folders

    def select_folder(self, name, readonly=False):
        self.current = name

    def search(self, criteria):
        mails = self.folders[self.current]
        if criteria == ["ALL"]:
            return list(mails)
        if criteria[:2] == ["HEADER", "Message-ID"]:
            return [u for u, m in mails.items() if m["mid"] == criteria[2]]
        assert criteria[:3] == ["SEEN", "UNFLAGGED", "BEFORE"]
        assert criteria[3] == date(2026, 9, 20)
        return [u for u, m in mails.items() if m["seen"] and not m["flagged"] and m["old"]]

    def fetch(self, uids, fields):
        key = b"BODY[HEADER.FIELDS (MESSAGE-ID)]"
        return {u: {key: f"Message-ID: {self.folders[self.current][u]['mid']}\r\n".encode()} for u in uids}


def mail(mid, seen=True, flagged=False, old=True):
    return {"mid": mid, "seen": seen, "flagged": flagged, "old": old}


@pytest.fixture
def pending(tmp_path):
    return PendingArchive(tmp_path / "pending.json")


def setup(mocker, folders):
    provider = mocker.MagicMock()
    provider.client = FakeClient(folders)
    return provider, mocker.MagicMock()


def test_archives_only_seen_unflagged_old_known_mails(mocker, pending):
    provider, db = setup(mocker, {
        "4-Pour info": {1: mail("<a>"), 2: mail("<b>", seen=False), 3: mail("<c>", flagged=True),
                        4: mail("<d>", old=False), 5: mail("<unknown>")},
    })  # fmt: skip
    for mid in ("<a>", "<b>", "<c>", "<d>"):
        pending.add(mid, "Achats", "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    provider.batch_move_emails.assert_called_once_with([1], "Achats")
    assert result == {"archived": 1, "learned": 0, "orphans": 0}
    assert pending.get("<a>") is None
    assert pending.get("<b>") is not None


def test_review_folder_is_never_archived(mocker, pending):
    provider, db = setup(mocker, {"9-A revoir": {1: mail("<r>")}})
    pending.add("<r>", None, "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    provider.batch_move_emails.assert_not_called()
    assert result["archived"] == 0
    assert pending.get("<r>") is not None


def test_mail_moved_from_review_to_category_becomes_rule(mocker, pending):
    provider, db = setup(mocker, {"9-A revoir": {}, "Santé": {9: mail("<r>")}})
    pending.add("<r>", None, "doc@clinic.ch", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    db.promote_to_validated.assert_called_once_with("doc@clinic.ch", "Santé")
    assert result["learned"] == 1
    assert pending.items() == []


def test_orphan_entries_are_removed(mocker, pending):
    provider, db = setup(mocker, {"4-Pour info": {}})
    pending.add("<gone>", "Achats", "s@x", "2026-09-01")
    pending.add("<gone-review>", None, "s@x", "2026-09-01")

    result = run_archive(provider, pending, db, days=7, today=TODAY)

    assert result["orphans"] == 2
    assert pending.items() == []
    db.promote_to_validated.assert_not_called()


def test_missing_action_folder_is_skipped(mocker, pending):
    provider, db = setup(mocker, {})

    assert run_archive(provider, pending, db, days=7, today=TODAY) == {"archived": 0, "learned": 0, "orphans": 0}


def test_validate_changes_nothing(mocker, pending):
    provider, db = setup(mocker, {"4-Pour info": {1: mail("<a>")}, "Santé": {2: mail("<r>")}})
    pending.add("<a>", "Achats", "s@x", "2026-09-01")
    pending.add("<r>", None, "s@x", "2026-09-01")

    run_archive(provider, pending, db, days=7, today=TODAY, validate=True)

    provider.batch_move_emails.assert_not_called()
    db.promote_to_validated.assert_not_called()
    assert len(pending.items()) == 2
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest tests/test_archive.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'mailtag.archive'`

- [ ] **Step 3: Implémenter**

`src/mailtag/archive.py` :

```python
"""End-of-run sweep: archive read emails, learn from review, drop orphan entries (spec section 6)."""

import email
import imaplib
from collections import defaultdict
from datetime import date, timedelta

from loguru import logger

from .pending_archive import PendingArchive
from .taxonomy import ACTION_FOLDERS, REVIEW, TAXONOMY

_MESSAGE_ID_FETCH = b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"


def _message_ids(client, uids: list[int]) -> dict[int, str]:
    if not uids:
        return {}
    ids = {}
    for uid, data in client.fetch(uids, [_MESSAGE_ID_FETCH]).items():
        key = next((k for k in data if k.startswith(b"BODY[HEADER.FIELDS")), None)
        if key:
            mid = str(email.message_from_bytes(data[key]).get("Message-ID") or "").strip()
            if mid:
                ids[uid] = mid
    return ids


def _learn_from_review(client, pending: PendingArchive, database, present: set[str], validate: bool) -> int:
    """Entries sent to review that the user filed into a category become validated sender rules."""
    waiting = {mid: e for mid, e in pending.items() if e["category"] is None and mid not in present}
    learned = 0
    for category in TAXONOMY:
        if not waiting or not client.folder_exists(category):
            continue
        client.select_folder(category)
        for mid in list(waiting):
            if client.search(["HEADER", "Message-ID", mid]):
                logger.info(f"Learned rule from review: {waiting[mid]['sender']} -> {category}")
                if not validate:
                    database.promote_to_validated(waiting[mid]["sender"], category)
                    pending.remove(mid)
                del waiting[mid]
                learned += 1
    return learned


def run_archive(provider, pending: PendingArchive, database, days: int, today: date, validate: bool = False) -> dict:
    """Archive seen, unflagged emails received `days` ago or more into their category."""
    client = provider.client
    cutoff = today - timedelta(days=days)
    present: set[str] = set()
    archived = 0

    for folder in ACTION_FOLDERS:
        if not client.folder_exists(folder):
            continue
        client.select_folder(folder)
        ids = _message_ids(client, client.search(["ALL"]))
        present.update(ids.values())
        if folder == REVIEW:
            continue

        eligible = set(client.search(["SEEN", "UNFLAGGED", "BEFORE", cutoff]))
        moves: dict[str, list[int]] = defaultdict(list)
        for uid, mid in ids.items():
            entry = pending.get(mid)
            if uid in eligible and entry and entry["category"]:
                moves[entry["category"]].append(uid)

        for category, uids in moves.items():
            logger.info(f"Archiving {len(uids)} emails from {folder} to {category}")
            if validate:
                continue
            try:
                provider.batch_move_emails(uids, category)
            except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                logger.error(f"Could not archive {len(uids)} emails to {category}: {e}")
                continue
            for uid in uids:
                pending.remove(ids[uid])
                present.discard(ids[uid])
            archived += len(uids)

    learned = _learn_from_review(client, pending, database, present, validate)

    orphans = [mid for mid, _ in pending.items() if mid not in present]
    if not validate:
        for mid in orphans:
            pending.remove(mid)
        pending.save()

    logger.info(f"Archive sweep: {archived} archived, {learned} learned, {len(orphans)} orphan entries")
    return {"archived": archived, "learned": learned, "orphans": len(orphans)}
```

Remarque pour l'implémenteur :
- Dans `test_orphan_entries_are_removed`, `<gone-review>` n'est trouvé dans aucune catégorie (le dict `folders` ne contient que `4-Pour info`), donc rien n'est appris, et l'entrée compte bien comme orpheline.
- En mode `validate`, les entrées apprises restent dans `pending` et sont comptées comme orphelines dans le résultat, mais rien n'est supprimé.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/test_archive.py -q`
Expected: PASS

- [ ] **Step 5: Brancher le ménage et l'instantané**

Dans `src/mailtag/utils/tasks.py`, ajouter `from mailtag.archive import run_archive`. À la fin de la branche `if isinstance(provider, ImapService):`, juste après `logger.info("Pass 3 complete.")`, ajouter :

```python
                if pending is not None:
                    run_archive(
                        provider, pending, database, CONFIG.taxonomy.archive_after_days, date.today(), validate
                    )
```

Dans `scripts/build_category_embeddings.py`, changer la valeur par défaut de `--folders` en `Path("data/legacy_folders.json")`, et le texte d'aide en `"Path to the frozen folder snapshot (see [taxonomy] legacy_folders_file)"`.

Dans `scripts/eval_embeddings.py`, fonction `category_examples()`, remplacer `Path("data/imap_folders.json")` par :

```python
Path("data/legacy_folders.json") if Path("data/legacy_folders.json").exists() else Path("data/imap_folders.json")
```

Créer l'instantané (une seule fois, le fichier reste local car `data/` est ignoré par git), et vérifier que les centroïdes sont identiques :

```bash
cp data/imap_folders.json data/legacy_folders.json
python3 -c "import json; print(len(json.load(open('data/legacy_folders.json'))))"
```
Expected: `611`

Dans `CLAUDE.md`, section Architecture, ajouter après « Three-Pass Processing System » :

```markdown
### Taxonomy Mode (`[taxonomy] enabled = true`)

Spec: `docs/superpowers/specs/2026-09-27-taxonomie-19-categories-design.md`.
19 business-sector categories (`src/mailtag/taxonomy.py`) replace the 611 IMAP folders.
- Signals 1-4 map stored old folder paths with `to_category`.
- Signal 5 (nomic) classifies at score ≥ `nomic_threshold`.
- Otherwise Signal 6 (Gemma, answers by category number, batched with a cached prompt prefix) must agree with nomic's top choice, else the email goes to `9-A revoir`.
- Emails land in action folders (`src/mailtag/action_rules.py`), with their category remembered in `db/pending_archive.json`.
- `src/mailtag/archive.py` moves seen, unflagged emails older than `archive_after_days` into their category and learns sender rules from emails filed out of `9-A revoir`.
- Nomic centroids come from the frozen `data/legacy_folders.json`.
```

- [ ] **Step 6: Suite complète et vérification en lecture seule sur la vraie boîte**

```bash
uv run pytest -q
uv run ruff format --check . && uv run ruff check .
```
Expected: PASS

Puis, **en lecture seule** : passer temporairement `enabled = true` dans `config.toml`, sans commiter ce changement, et lancer :

```bash
python src/main.py run --provider imap --validate
```
Expected : pour chaque mail de l'INBOX, le journal affiche des lignes `Email "…" from … -> <catégorie> / <dossier d'action>`, suivies de `Archive sweep: 0 archived, 0 learned, 0 orphan entries`. Aucun déplacement. Remettre ensuite `enabled = false`.

- [ ] **Step 7: Commit**

```bash
git add src/mailtag/archive.py src/mailtag/utils/tasks.py scripts/build_category_embeddings.py scripts/eval_embeddings.py tests/test_archive.py CLAUDE.md
git commit -m "feat(taxonomy): end-of-run archive sweep and review learning"
```

---

### Task 11: Commande de mesure `chain`

**Files:**
- Modify: `scripts/eval_embeddings.py` (nouvelle fonction `chain_eval`, sous-commande `chain`)
- Test: `tests/test_eval_embeddings.py`

**Interfaces:**
- Consumes :
  - `Classifier._classify_uncertain` (Task 7)
  - `map_folder` et `REVIEW` (Task 1)
  - le jeu de données `data/eval/embedding_eval_set.json`
- Produces :
  - `chain_metrics(results: list[str], labels: list[str], llm_seconds: float, llm_calls: int) -> dict`, avec les clés `"auto"` (part des mails classés), `"precision"`, `"sec_per_llm_email"` et `"passed"` (bool)
  - la commande `uv run python scripts/eval_embeddings.py chain -n 500`

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_eval_embeddings.py` :

```python
def test_chain_metrics_success_criteria():
    from scripts.eval_embeddings import chain_metrics

    labels = ["A"] * 10
    results = ["A"] * 5 + ["B"] * 0 + ["9-A revoir"] * 5  # 50% auto, 100% precise
    m = chain_metrics(results, labels, llm_seconds=6.0, llm_calls=5)
    assert m == {"auto": 0.5, "precision": 1.0, "sec_per_llm_email": 1.2, "passed": True}

    bad = chain_metrics(["A", "B", "9-A revoir", "9-A revoir"], ["A"] * 4, llm_seconds=8.0, llm_calls=4)
    assert bad["precision"] == 0.5
    assert bad["passed"] is False
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_eval_embeddings.py -q -k chain`
Expected: FAIL, `ImportError: cannot import name 'chain_metrics'`

- [ ] **Step 3: Implémenter**

Dans `scripts/eval_embeddings.py`, avant `def main():` :

```python
def chain_metrics(results: list[str], labels: list[str], llm_seconds: float, llm_calls: int) -> dict:
    """Spec success criteria: >= 45% auto-classified, >= 90% precision, <= 1.5 s per LLM email."""
    from mailtag.taxonomy import REVIEW

    classified = [(r, lab) for r, lab in zip(results, labels, strict=True) if r != REVIEW]
    auto = len(classified) / len(labels)
    precision = sum(r == lab for r, lab in classified) / len(classified) if classified else 0.0
    sec = llm_seconds / llm_calls if llm_calls else 0.0
    return {
        "auto": auto,
        "precision": precision,
        "sec_per_llm_email": sec,
        "passed": auto >= 0.45 and precision >= 0.90 and sec <= 1.5,
    }


def chain_eval(sample_path: Path, n: int, seed: int) -> None:
    """Replay the production signals 5-6 chain (no sender rules) on n labeled emails."""
    import dataclasses
    import random

    from mailtag.classifier import Classifier
    from mailtag.config import CONFIG
    from mailtag.database import ClassificationDatabase
    from mailtag.models import Email
    from mailtag.taxonomy import map_folder

    samples = [s for s in json.loads(sample_path.read_text(encoding="utf-8")) if map_folder(s["folder"])]
    picked = random.Random(seed).sample(samples, n)
    labels = [map_folder(s["folder"]) for s in picked]
    emails = [
        Email(msg_id=str(i), subject=s["subject"], sender_address=s["sender_address"],
              sender_name=s["sender_name"], body=s["body"])
        for i, s in enumerate(picked)
    ]  # fmt: skip

    config = dataclasses.replace(CONFIG, taxonomy=dataclasses.replace(CONFIG.taxonomy, enabled=True))
    classifier = Classifier(
        config,
        ClassificationDatabase(
            Path("db/sender_classification_db.json"), Path("db/validated_classification_db.json")
        ),
    )
    llm_seconds, llm_calls = 0.0, 0
    original = classifier._llm_categories

    def timed_llm(batch):
        nonlocal llm_seconds, llm_calls
        start = time.perf_counter()
        out = original(batch)
        llm_seconds += time.perf_counter() - start
        llm_calls += len(batch)
        logger.info(f"LLM {llm_calls} emails ({llm_seconds / llm_calls:.2f} s/email)")
        return out

    classifier._llm_categories = timed_llm
    results = []
    for start in range(0, n, 50):
        results += classifier._classify_uncertain(emails[start : start + 50])

    m = chain_metrics(results, labels, llm_seconds, llm_calls)
    print(f"\n{n} emails (seed {seed})")
    print(f"auto-classified: {m['auto']:.1%}  (target >= 45%)")
    print(f"precision:       {m['precision']:.1%}  (target >= 90%)")
    print(f"LLM:             {m['sec_per_llm_email']:.2f} s/email on {llm_calls} emails  (target <= 1.5 s)")
    print("PASS" if m["passed"] else "FAIL")
```

Dans `main()`, avant `args = parser.parse_args()` :

```python
    p_chain = sub.add_parser("chain", help="Replay the taxonomy signals 5-6 chain and check success criteria")
    p_chain.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    p_chain.add_argument("-n", type=int, default=500)
    p_chain.add_argument("--seed", type=int, default=3)
```

puis, dans l'aiguillage, avant `elif args.command == "taxonomy":` :

```python
    elif args.command == "chain":
        chain_eval(args.sample, args.n, args.seed)
```

Ajouter aussi à la docstring du module :

```
Step 5 - replay the taxonomy chain and check the spec success criteria:
    uv run python scripts/eval_embeddings.py chain -n 500
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `uv run pytest tests/test_eval_embeddings.py -q`
Expected: PASS

- [ ] **Step 5: Mesure réelle (environ 8 minutes, en tâche de fond, sur Apple Silicon)**

```bash
uv run python scripts/eval_embeddings.py chain -n 500 2>&1 | grep --line-buffered -vE "Batches|arn" | tee /tmp/chain.log
```
Expected : la dernière ligne vaut `PASS` ou `FAIL`. Rapporter les trois chiffres tels quels. **Ne pas** activer `[taxonomy] enabled = true` : c'est la décision de l'utilisateur, prise sur ces chiffres.

- [ ] **Step 6: Commit**

```bash
uv run ruff format scripts/eval_embeddings.py tests/test_eval_embeddings.py && uv run ruff check scripts/eval_embeddings.py tests/test_eval_embeddings.py
git add scripts/eval_embeddings.py tests/test_eval_embeddings.py
git commit -m "feat(eval): add chain command checking taxonomy success criteria"
```
