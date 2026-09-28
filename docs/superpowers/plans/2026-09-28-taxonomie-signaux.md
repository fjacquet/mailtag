# Refonte des 6 signaux pour la taxonomie — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Apprendre la catégorie des expéditeurs et des domaines à partir de la boîte existante (double contrôle par Gemma, revue humaine des désaccords), remplacer les 611 centroïdes synthétiques par 19 centroïdes réels, et apprendre automatiquement les nouveaux expéditeurs quand nomic et Gemma concordent.

**Architecture :**
- Quatre étapes de préparation, lancées à la main : `scan` (lecture seule d'IMAP), `crosscheck` (Gemma par expéditeur), `review` (page Streamlit locale), `build` (règles et centroïdes).
- En mode taxonomie, les signaux 1, 3 et 4 lisent un stockage dédié, `TaxonomyStore` (`db/taxonomy/*.json`). Le signal 2 est retiré. nomic charge les 19 centroïdes (`data/taxonomy_centroids.npz`).
- Un accord nomic-Gemma incrémente un compteur par expéditeur ; à 2 accords, l'expéditeur est promu en règle ; une contradiction supprime l'entrée.
- Le flux actuel (`enabled = false`) et Gmail ne changent pas.

**Tech Stack :** Python 3.13, IMAPClient, sentence-transformers (nomic-embed-text-v1.5), mlx-lm (`MLXLLM.classify_batch`), Streamlit, numpy, pytest et pytest-mock, ruff.

**Spec :** `docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md`

## Global Constraints

- Python ≥ 3.13, lignes de 110 caractères au plus. Dans chaque tâche : `uv run ruff format <fichiers>` puis `uv run ruff check <fichiers>`.
- Tests : `uv run pytest -q`. La CI tourne sur Ubuntu sans MLX : aucun test ne charge nomic, Gemma ou Streamlit ; ils sont simulés.
- Noms exacts, accents compris : les 19 clés de `TAXONOMY`, `REVIEW = "9-A revoir"`.
- Fichiers : `db/taxonomy/validated.json`, `db/taxonomy/senders.json`, `db/taxonomy/domains.json`, `data/taxonomy_centroids.npz`, `data/mailbox_scan.json`, `data/sender_crosscheck.json`, `data/taxonomy_corpus.json`.
- Valeurs par défaut de `[taxonomy]` : `taxonomy_db_dir = "db/taxonomy"`, `centroids_file = "data/taxonomy_centroids.npz"`, `learn_min_agreements = 2`, `domain_min_purity = 0.90`, `sender_min_mails = 2`. `enabled` reste `false`.
- `--validate` n'écrit rien : ni `db/taxonomy/*`, ni `pending_archive`, ni les anciennes bases.
- Aucune étape de préparation ne déplace de mail. Toute lecture IMAP de préparation se fait avec `select_folder(..., readonly=True)` et `BODY.PEEK`.
- Le flux actuel (`enabled = false`) et Gmail gardent leur comportement : toute la suite existante passe.
- Adresses d'expéditeur toujours en minuscules et sans espaces autour dans les fichiers et les recherches.
- Écritures JSON atomiques (fichier temporaire dans le même dossier, puis `os.replace`).
- Messages de commit : Conventional Commits, terminés par :
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp
  ```

## Review Focus

1. **Adresse en majuscules ou avec espaces** (`" A@Shop.CH "`) : trouvée dans les règles comme `a@shop.ch`, et enregistrée ainsi. Test : Task 2 (`test_lookup_normalizes_address`).
2. **Fichier `db/taxonomy/*.json` absent ou illisible** : le stockage démarre vide, sans plantage ; les mails passent à nomic et Gemma. Test : Task 2 (`test_missing_or_corrupt_files_start_empty`).
3. **En-tête `From` sans adresse ou mal encodé pendant le scan** : le mail est ignoré, le scan continue. Test : Task 3 (`test_mail_without_sender_is_ignored`).
4. **`crosscheck` interrompu** (Gemma lève une exception au milieu) : ce qui a été enregistré avant est conservé, et une relance ne refait que le reste. Test : Task 4 (`test_resume_skips_done_and_keeps_progress_on_failure`).
5. **`build` lancé avant `scan` ou `crosscheck`** : rien n'est écrit, un message dit quel fichier manque. Test : Task 9 (`test_missing_inputs`).

---

## File Structure

| Fichier | Rôle |
|---|---|
| `src/mailtag/taxonomy.py` (modifié) | `llm_sender_static_prompt`, `llm_sender_part`, `nomic_text` |
| `src/mailtag/config.py`, `config.toml` (modifiés) | nouveaux champs de `[taxonomy]` |
| `src/mailtag/taxonomy_store.py` (créé) | `write_json_atomic`, `TaxonomyStore` : règles validées, apprises, domaines ; apprentissage par accords |
| `src/mailtag/mailbox_scan.py` (créé) | `scan_mailbox` : lecture seule des en-têtes des dossiers existants |
| `src/mailtag/sender_crosscheck.py` (créé) | `crosscheck_senders` : Gemma par expéditeur, avec reprise |
| `src/mailtag/taxonomy_build.py` (créé) | file de revue, expéditeurs appris, domaines, échantillon et centroïdes |
| `src/mailtag/classifier.py` (modifié) | règles via `TaxonomyStore`, centroïdes dédiés, apprentissage sur accord |
| `src/mailtag/utils/tasks.py`, `src/mailtag/archive.py` (modifiés) | passe 1 via `TaxonomyStore`, passe 2 sautée en mode taxonomie, apprentissage depuis `9-A revoir` vers `validated.json` |
| `scripts/taxonomy_setup.py` (créé) | commandes `scan`, `crosscheck`, `build` |
| `scripts/taxonomy_review.py` (créé) | page Streamlit de revue |
| `scripts/eval_embeddings.py` (modifié) | `chain` sur les données vérifiées, balayage du seuil, précision des règles |
| `CLAUDE.md` (modifié) | documentation |

---

### Task 1: Configuration et fonctions de prompt

**Files:**
- Modify: `src/mailtag/config.py` (`TaxonomyConfig`)
- Modify: `config.toml` (section `[taxonomy]`)
- Modify: `src/mailtag/taxonomy.py`
- Test: `tests/test_config.py`, `tests/test_taxonomy.py`

**Interfaces:**
- Produces :
  - `TaxonomyConfig.taxonomy_db_dir: str = "db/taxonomy"`, `centroids_file: str = "data/taxonomy_centroids.npz"`, `learn_min_agreements: int = 2`, `domain_min_purity: float = 0.90`, `sender_min_mails: int = 2`
  - `llm_sender_static_prompt() -> str`
  - `llm_sender_part(name: str, address: str, subjects: list[str]) -> str`
  - `nomic_text(sender_name: str, sender_address: str, subject: str, body: str) -> str` (texte exact envoyé à nomic, identique à celui de `Classifier._nomic_top`)

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_config.py` :

```python
def test_taxonomy_signal_defaults():
    from mailtag.config import TaxonomyConfig

    cfg = TaxonomyConfig()
    assert cfg.taxonomy_db_dir == "db/taxonomy"
    assert cfg.centroids_file == "data/taxonomy_centroids.npz"
    assert cfg.learn_min_agreements == 2
    assert cfg.domain_min_purity == 0.90
    assert cfg.sender_min_mails == 2
```

Ajouter à `tests/test_taxonomy.py` :

```python
def test_llm_sender_prompt_lists_categories_and_asks_for_a_number():
    from mailtag.taxonomy import TAXONOMY, llm_sender_static_prompt

    prompt = llm_sender_static_prompt()
    assert prompt.startswith("Classe cet expéditeur dans UNE des catégories suivantes")
    assert "19. Contacts : personnes qui écrivent directement" in prompt
    assert len([line for line in prompt.splitlines() if line[:1].isdigit()]) == len(TAXONOMY)
    assert prompt.endswith("Réponds uniquement par le numéro de la catégorie, sans autre texte.\n\n")


def test_llm_sender_part():
    from mailtag.taxonomy import llm_sender_part

    assert llm_sender_part("BCV", "info@bcv.ch", ["Relevé", "Alerte"]) == (
        "Expéditeur: BCV <info@bcv.ch>\nSujets:\n- Relevé\n- Alerte"
    )
    assert llm_sender_part("", "a@x.ch", []) == "Expéditeur: a@x.ch\nSujets:\n- (aucun)"


def test_nomic_text_matches_production_format():
    from mailtag.taxonomy import nomic_text

    assert nomic_text("BCV", "info@bcv.ch", "Relevé", "") == "Email from BCV: Relevé"
    assert nomic_text("", "info@bcv.ch", "Relevé", "") == "Email from info@bcv.ch: Relevé"
    assert nomic_text("", "", "S", "") == "Email from Unknown: S"
    assert nomic_text("BCV", "info@bcv.ch", "Relevé", "Votre solde") == "Email from BCV: Relevé\nVotre solde"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_config.py tests/test_taxonomy.py`
Expected: FAIL (`AttributeError` sur `taxonomy_db_dir`, `ImportError` sur `llm_sender_static_prompt`).

- [ ] **Step 3: Implémenter**

Dans `src/mailtag/config.py`, compléter `TaxonomyConfig` (après `legacy_folders_file`) :

```python
    taxonomy_db_dir: str = "db/taxonomy"
    centroids_file: str = "data/taxonomy_centroids.npz"
    learn_min_agreements: int = 2
    domain_min_purity: float = 0.90
    sender_min_mails: int = 2
```

Dans `config.toml`, à la fin de la section `[taxonomy]` :

```toml
# Learned rules and centroids (docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md)
taxonomy_db_dir = "db/taxonomy"
centroids_file = "data/taxonomy_centroids.npz"
learn_min_agreements = 2   # nomic+Gemma agreements before a sender becomes a rule
domain_min_purity = 0.90   # share of a domain's mails in one category to make a domain rule
sender_min_mails = 2       # mails needed before a folder/Gemma agreement becomes a sender rule
```

Dans `src/mailtag/taxonomy.py`, ajouter l'import en tête (après `import re`) :

```python
from .utils.text_utils import smart_truncate
```

et ajouter après `llm_email_part` :

```python
def llm_sender_static_prompt() -> str:
    """Same numbered list as llm_static_prompt(), asking for the sender's category."""
    return llm_static_prompt().replace("Classe cet email", "Classe cet expéditeur", 1)


def llm_sender_part(name: str, address: str, subjects: list[str]) -> str:
    """Per-sender part of the prompt, appended after llm_sender_static_prompt()."""
    sender = f"{name} <{address}>" if name else address
    lines = "\n".join(f"- {s}" for s in subjects) or "- (aucun)"
    return f"Expéditeur: {sender}\nSujets:\n{lines}"


def nomic_text(sender_name: str, sender_address: str, subject: str, body: str) -> str:
    """Text embedded by nomic for one email (the production Signal 5 format)."""
    text = f"Email from {sender_name or sender_address or 'Unknown'}: {subject}"
    body = smart_truncate(body, max_chars=500) if body else ""
    return f"{text}\n{body}" if body else text
```

Vérifier que `src/mailtag/utils/text_utils.py` n'importe pas `mailtag.taxonomy` (pas d'import circulaire) : `grep -n "import" src/mailtag/utils/text_utils.py`.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_config.py tests/test_taxonomy.py`
Expected: PASS.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/config.py src/mailtag/taxonomy.py tests/test_config.py tests/test_taxonomy.py
uv run ruff check src/mailtag/config.py src/mailtag/taxonomy.py tests/test_config.py tests/test_taxonomy.py
uv run pytest -q
git add src/mailtag/config.py config.toml src/mailtag/taxonomy.py tests/test_config.py tests/test_taxonomy.py
git commit -m "feat(taxonomy): config and prompts for learned signals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 2: Stockage `TaxonomyStore`

**Files:**
- Create: `src/mailtag/taxonomy_store.py`
- Test: `tests/test_taxonomy_store.py`

**Interfaces:**
- Consumes : `extract_domain`, `is_non_commercial_domain_cached` (`mailtag.utils.domain_utils`).
- Produces :
  - `write_json_atomic(path: Path, data) -> None`
  - `normalize_address(address: str) -> str`
  - `TaxonomyStore(directory: Path, min_agreements: int = 2, read_only: bool = False)` avec :
    - attributs `validated: dict[str, str]`, `senders: dict[str, dict]` (`{"category": str, "agreements": int}`), `domains: dict[str, str]`
    - `category_for(sender_address: str) -> str | None` : signal 1, puis 3 (seulement si `agreements >= min_agreements`), puis 4 (domaines non grand public)
    - `record_agreement(sender_address: str, category: str) -> None`
    - `set_validated(sender_address: str, category: str) -> None`
    - `replace_rules(learned: dict[str, dict], domains: dict[str, str]) -> None`
    - `save() -> None` (sans effet si `read_only`)

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_taxonomy_store.py` :

```python
import json

import pytest

from mailtag.taxonomy_store import TaxonomyStore, write_json_atomic


@pytest.fixture(autouse=True)
def personal_domains(monkeypatch):
    monkeypatch.setattr(
        "mailtag.taxonomy_store.is_non_commercial_domain_cached", lambda d: d in {"gmail.com", "bluewin.ch"}
    )


def store(tmp_path, **files):
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return TaxonomyStore(tmp_path, min_agreements=2)


def test_rule_order_validated_then_learned_then_domain(tmp_path):
    s = store(
        tmp_path,
        validated={"a@shop.ch": "Santé"},
        senders={"a@shop.ch": {"category": "Achats", "agreements": 5},
                 "b@shop.ch": {"category": "Achats", "agreements": 2}},
        domains={"shop.ch": "Colis & Livraisons"},
    )  # fmt: skip
    assert s.category_for("a@shop.ch") == "Santé"
    assert s.category_for("b@shop.ch") == "Achats"
    assert s.category_for("c@shop.ch") == "Colis & Livraisons"
    assert s.category_for("c@other.ch") is None


def test_unpromoted_sender_is_not_a_rule(tmp_path):
    s = store(tmp_path, senders={"b@x.ch": {"category": "Achats", "agreements": 1}})
    assert s.category_for("b@x.ch") is None


def test_personal_domain_is_never_a_rule(tmp_path):
    s = store(tmp_path, domains={"gmail.com": "Contacts"})
    assert s.category_for("someone@gmail.com") is None


def test_lookup_normalizes_address(tmp_path):
    s = store(tmp_path, validated={"a@shop.ch": "Santé"})
    assert s.category_for("  A@Shop.CH ") == "Santé"
    s.set_validated(" B@Shop.CH", "Achats")
    assert s.validated["b@shop.ch"] == "Achats"


def test_two_agreements_promote_a_sender(tmp_path):
    s = store(tmp_path)
    s.record_agreement("n@new.ch", "Santé")
    assert s.category_for("n@new.ch") is None
    s.record_agreement("n@new.ch", "Santé")
    assert s.category_for("n@new.ch") == "Santé"


def test_contradiction_removes_the_entry(tmp_path):
    s = store(tmp_path, senders={"n@new.ch": {"category": "Santé", "agreements": 3}})
    s.record_agreement("n@new.ch", "Achats")
    assert "n@new.ch" not in s.senders
    assert s.category_for("n@new.ch") is None


def test_validated_sender_is_not_learned(tmp_path):
    s = store(tmp_path, validated={"v@x.ch": "Santé"})
    s.record_agreement("v@x.ch", "Achats")
    assert "v@x.ch" not in s.senders


def test_set_validated_drops_learned_entry(tmp_path):
    s = store(tmp_path, senders={"n@x.ch": {"category": "Achats", "agreements": 2}})
    s.set_validated("n@x.ch", "Santé")
    assert "n@x.ch" not in s.senders
    assert s.category_for("n@x.ch") == "Santé"


def test_replace_rules_keeps_runtime_learning_for_unknown_senders(tmp_path):
    s = store(tmp_path, senders={"runtime@x.ch": {"category": "Santé", "agreements": 1},
                                 "old@x.ch": {"category": "Santé", "agreements": 2}})  # fmt: skip
    s.replace_rules({"old@x.ch": {"category": "Achats", "agreements": 2}}, {"x.ch": "Achats"})
    assert s.senders == {
        "runtime@x.ch": {"category": "Santé", "agreements": 1},
        "old@x.ch": {"category": "Achats", "agreements": 2},
    }
    assert s.domains == {"x.ch": "Achats"}


def test_save_writes_all_files_and_reloads(tmp_path):
    s = store(tmp_path)
    s.set_validated("v@x.ch", "Santé")
    s.record_agreement("n@x.ch", "Achats")
    s.replace_rules({}, {"x.ch": "Achats"})
    s.save()

    again = TaxonomyStore(tmp_path)
    assert again.validated == {"v@x.ch": "Santé"}
    assert again.senders == {"n@x.ch": {"category": "Achats", "agreements": 1}}
    assert again.domains == {"x.ch": "Achats"}


def test_read_only_never_writes(tmp_path):
    s = TaxonomyStore(tmp_path, read_only=True)
    s.set_validated("v@x.ch", "Santé")
    s.record_agreement("n@x.ch", "Achats")
    s.save()
    assert list(tmp_path.iterdir()) == []


def test_missing_or_corrupt_files_start_empty(tmp_path):
    (tmp_path / "senders.json").write_text("{not json", encoding="utf-8")
    s = TaxonomyStore(tmp_path)
    assert s.validated == {} and s.senders == {} and s.domains == {}


def test_write_json_atomic_creates_parent_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "sub" / "f.json"
    write_json_atomic(target, {"é": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"é": 1}
    assert [p.name for p in target.parent.iterdir()] == ["f.json"]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_taxonomy_store.py`
Expected: FAIL (`ModuleNotFoundError: mailtag.taxonomy_store`).

- [ ] **Step 3: Implémenter**

`src/mailtag/taxonomy_store.py` :

```python
"""Taxonomy rules: validated senders, learned senders and domains (spec sections 2 to 5)."""

import json
import os
import tempfile
from pathlib import Path

from loguru import logger

from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached

_FILES = ("validated", "senders", "domains")


def write_json_atomic(path: Path, data) -> None:
    """Write JSON through a temp file in the same folder, then rename it over the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def normalize_address(address: str) -> str:
    return (address or "").strip().lower()


def _load(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error(f"Could not parse {path}, starting empty")
        return {}
    return data if isinstance(data, dict) else {}


class TaxonomyStore:
    """Signals 1, 3 and 4 of the taxonomy mode, and learning from nomic/Gemma agreements."""

    def __init__(self, directory: Path, min_agreements: int = 2, read_only: bool = False):
        self.directory = Path(directory)
        self.min_agreements = min_agreements
        self.read_only = read_only
        self.validated: dict[str, str] = _load(self.directory / "validated.json")
        self.senders: dict[str, dict] = _load(self.directory / "senders.json")
        self.domains: dict[str, str] = _load(self.directory / "domains.json")
        self._dirty: set[str] = set()

    def category_for(self, sender_address: str) -> str | None:
        sender = normalize_address(sender_address)
        if sender in self.validated:
            return self.validated[sender]
        entry = self.senders.get(sender)
        if entry and entry["agreements"] >= self.min_agreements:
            return entry["category"]
        domain = extract_domain(sender)
        if domain and not is_non_commercial_domain_cached(domain):
            return self.domains.get(domain)
        return None

    def record_agreement(self, sender_address: str, category: str) -> None:
        sender = normalize_address(sender_address)
        if not sender or sender in self.validated:
            return
        entry = self.senders.get(sender)
        if entry is None:
            self.senders[sender] = {"category": category, "agreements": 1}
        elif entry["category"] == category:
            entry["agreements"] += 1
        else:
            logger.info(f"Contradiction for {sender}: {entry['category']} vs {category}, entry removed")
            del self.senders[sender]
        self._dirty.add("senders")

    def set_validated(self, sender_address: str, category: str) -> None:
        sender = normalize_address(sender_address)
        self.validated[sender] = category
        self._dirty.add("validated")
        if self.senders.pop(sender, None) is not None:
            self._dirty.add("senders")

    def replace_rules(self, learned: dict[str, dict], domains: dict[str, str]) -> None:
        """Install rules from `build`; runtime entries for senders `build` does not know are kept."""
        self.senders = {**self.senders, **learned}
        self.domains = dict(domains)
        self._dirty.update({"senders", "domains"})

    def save(self) -> None:
        if self.read_only:
            return
        for name in _FILES:
            if name in self._dirty:
                write_json_atomic(self.directory / f"{name}.json", getattr(self, name))
        self._dirty.clear()
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_taxonomy_store.py`
Expected: PASS (13 tests).

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/taxonomy_store.py tests/test_taxonomy_store.py
uv run ruff check src/mailtag/taxonomy_store.py tests/test_taxonomy_store.py
uv run pytest -q
git add src/mailtag/taxonomy_store.py tests/test_taxonomy_store.py
git commit -m "feat(taxonomy): store for validated, learned and domain rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 3: Parcours de la boîte `scan_mailbox`

**Files:**
- Create: `src/mailtag/mailbox_scan.py`
- Test: `tests/test_mailbox_scan.py`

**Interfaces:**
- Consumes : `to_category` (`mailtag.taxonomy`), `extract_domain`, `parse_sender` (`mailtag.utils.email_parsing`), `ImapService._parse_header_value` (décodage RFC 2047), `normalize_address` (Task 2).
- Produces : `scan_mailbox(provider: ImapService, folders: list[str], batch_size: int = 500) -> dict` qui renvoie :
  ```python
  {
      "senders": {
          "a@shop.ch": {
              "name": "Shop",
              "domain": "shop.ch",
              "categories": {"Achats": 12},      # mails par catégorie
              "subjects": ["...", ...],          # 5 au plus, premiers vus
              "refs": [["Achats/Shop", 42], ...] # 5 au plus, (dossier, uid)
          }
      },
      "skipped_folders": ["..."],
  }
  ```

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_mailbox_scan.py` :

```python
import imaplib

import pytest

from mailtag.config import FastParseConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.mailbox_scan import scan_mailbox

KEY = b"BODY[HEADER.FIELDS (FROM SUBJECT)]"


class FakeClient:
    def __init__(self, folders, broken=()):
        self.folders = folders
        self.broken = set(broken)
        self.current = None
        self.readonly_calls = []

    def select_folder(self, name, readonly=False):
        self.readonly_calls.append(readonly)
        if name in self.broken:
            raise imaplib.IMAP4.error(f"cannot select {name}")
        self.current = name

    def search(self, criteria):
        assert criteria == ["ALL"]
        return list(self.folders[self.current])

    def fetch(self, uids, fields):
        assert fields == [b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"]
        return {u: {KEY: self.folders[self.current][u].encode()} for u in uids}


@pytest.fixture
def provider():
    service = ImapService(ImapConfig(host="h", user="u", password="p"), FastParseConfig(metrics_enabled=False))
    return service


def header(sender, subject):
    return f"From: {sender}\r\nSubject: {subject}\r\n"


def test_counts_per_category_with_decoded_subjects(provider):
    provider.client = FakeClient({
        "Voyages": {1: header("Sixt <res@Sixt.ch>", "=?utf-8?Q?R=C3=A9servation?="),
                    2: header("res@sixt.ch", "Facture")},
        "Voyages/Transport": {7: header("res@sixt.ch", "Parking")},
        "Promotions": {9: header("res@sixt.ch", "Promo")},
    })  # fmt: skip

    result = scan_mailbox(provider, ["Voyages", "Voyages/Transport", "Promotions"], batch_size=1)

    entry = result["senders"]["res@sixt.ch"]
    assert entry["name"] == "Sixt"
    assert entry["domain"] == "sixt.ch"
    assert entry["categories"] == {"Voyages & Loisirs": 2, "Transports & Mobilité": 1}
    assert entry["subjects"] == ["Réservation", "Facture", "Parking"]
    assert entry["refs"] == [["Voyages", 1], ["Voyages", 2], ["Voyages/Transport", 7]]
    assert result["skipped_folders"] == []
    assert all(provider.client.readonly_calls)


def test_samples_are_capped_at_five(provider):
    provider.client = FakeClient({"Voyages": {i: header("a@x.ch", f"S{i}") for i in range(1, 9)}})

    entry = scan_mailbox(provider, ["Voyages"])["senders"]["a@x.ch"]

    assert entry["categories"] == {"Voyages & Loisirs": 8}
    assert len(entry["subjects"]) == 5 and len(entry["refs"]) == 5


def test_unreadable_folder_is_skipped(provider):
    provider.client = FakeClient(
        {"Voyages": {1: header("a@x.ch", "S")}, "Voyages/Transport": {}}, broken={"Voyages/Transport"}
    )

    result = scan_mailbox(provider, ["Voyages/Transport", "Voyages"])

    assert result["skipped_folders"] == ["Voyages/Transport"]
    assert "a@x.ch" in result["senders"]


def test_mail_without_sender_is_ignored(provider):
    provider.client = FakeClient({"Voyages": {1: "Subject: no from\r\n", 2: header("a@x.ch", "ok")}})

    assert list(scan_mailbox(provider, ["Voyages"])["senders"]) == ["a@x.ch"]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_mailbox_scan.py`
Expected: FAIL (`ModuleNotFoundError: mailtag.mailbox_scan`).

- [ ] **Step 3: Implémenter**

`src/mailtag/mailbox_scan.py` :

```python
"""Read-only pass over the existing folders: category counts per sender (spec section 1.1)."""

import email
import imaplib

from loguru import logger

from .taxonomy import to_category
from .taxonomy_store import normalize_address
from .utils.domain_utils import extract_domain
from .utils.email_parsing import parse_sender

_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"
_SAMPLES = 5


def scan_mailbox(provider, folders: list[str], batch_size: int = 500) -> dict:
    """Sender -> name, domain, mails per category, sample subjects and (folder, uid) references."""
    client = provider.client
    senders: dict[str, dict] = {}
    skipped: list[str] = []

    for folder in folders:
        category = to_category(folder)
        if category is None:
            continue
        try:
            client.select_folder(folder, readonly=True)
            uids = client.search(["ALL"])
            for start in range(0, len(uids), batch_size):
                chunk = uids[start : start + batch_size]
                for uid, data in client.fetch(chunk, [_FETCH]).items():
                    key = next((k for k in data if k.startswith(b"BODY[HEADER.FIELDS")), None)
                    if key is None:
                        continue
                    msg = email.message_from_bytes(data[key])
                    name, address = parse_sender(provider._parse_header_value(msg.get("From")))
                    address = normalize_address(address)
                    if not address:
                        continue
                    entry = senders.setdefault(
                        address,
                        {"name": name, "domain": extract_domain(address), "categories": {},
                         "subjects": [], "refs": []},
                    )  # fmt: skip
                    entry["categories"][category] = entry["categories"].get(category, 0) + 1
                    if len(entry["refs"]) < _SAMPLES:
                        entry["subjects"].append(provider._parse_header_value(msg.get("Subject")))
                        entry["refs"].append([folder, int(uid)])
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not scan folder {folder}: {e}")
            skipped.append(folder)
            continue
        logger.info(f"Scanned {folder} -> {category}")

    logger.info(f"Scan: {len(senders)} senders, {len(skipped)} folders skipped")
    return {"senders": senders, "skipped_folders": skipped}
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_mailbox_scan.py`
Expected: PASS (4 tests). Si `parse_sender` renvoie une adresse non vide pour un `From` absent, corriger en testant `msg.get("From")` avant l'appel, et le noter dans le rapport.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/mailbox_scan.py tests/test_mailbox_scan.py
uv run ruff check src/mailtag/mailbox_scan.py tests/test_mailbox_scan.py
uv run pytest -q
git add src/mailtag/mailbox_scan.py tests/test_mailbox_scan.py
git commit -m "feat(taxonomy): read-only mailbox scan of senders per category

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 4: Double contrôle `crosscheck_senders`

**Files:**
- Create: `src/mailtag/sender_crosscheck.py`
- Test: `tests/test_sender_crosscheck.py`

**Interfaces:**
- Consumes : `llm_sender_static_prompt`, `llm_sender_part`, `parse_category_number` (Task 1 et `mailtag.taxonomy`) ; un objet `llm` avec `classify_batch(static_prompt, parts, batch_size=...) -> list[str]` (`MLXLLM`).
- Produces : `crosscheck_senders(senders: dict, llm, done: dict[str, str | None], batch_size: int = 8, save_every: int = 100, on_save=None) -> dict[str, str | None]`. Traite les expéditeurs absents de `done`, par nombre de mails décroissant, et appelle `on_save(results)` après chaque groupe de `save_every`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_sender_crosscheck.py` :

```python
import pytest

from mailtag.sender_crosscheck import crosscheck_senders
from mailtag.taxonomy import llm_sender_static_prompt


def sender(name, n, subjects=("S",)):
    return {"name": name, "domain": "x.ch", "categories": {"Achats": n}, "subjects": list(subjects), "refs": []}


def test_answers_are_parsed_in_volume_order(mocker):
    senders = {"small@x.ch": sender("Small", 1), "big@x.ch": sender("Big", 50, ["Facture"])}
    llm = mocker.MagicMock()
    llm.classify_batch.return_value = ["8", "banana"]

    result = crosscheck_senders(senders, llm, done={})

    assert result == {"big@x.ch": "Achats", "small@x.ch": None}
    static, parts = llm.classify_batch.call_args.args
    assert static == llm_sender_static_prompt()
    assert parts[0] == "Expéditeur: Big <big@x.ch>\nSujets:\n- Facture"
    assert llm.classify_batch.call_args.kwargs == {"batch_size": 8}


def test_resume_skips_done_and_keeps_progress_on_failure(mocker):
    senders = {f"s{i}@x.ch": sender("", 10 - i) for i in range(4)}
    llm = mocker.MagicMock()
    llm.classify_batch.side_effect = [["1", "2"], RuntimeError("metal crash")]
    saved = []

    with pytest.raises(RuntimeError):
        crosscheck_senders(senders, llm, done={"s0@x.ch": "Santé"}, save_every=2, on_save=saved.append)

    assert saved == [{"s0@x.ch": "Santé", "s1@x.ch": "Banque & Placements", "s2@x.ch": "Assurances & Retraite"}]
    assert llm.classify_batch.call_args_list[0].args[1][0].startswith("Expéditeur: s1@x.ch")


def test_nothing_to_do(mocker):
    llm = mocker.MagicMock()
    assert crosscheck_senders({"a@x.ch": sender("", 1)}, llm, done={"a@x.ch": None}) == {"a@x.ch": None}
    llm.classify_batch.assert_not_called()
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_sender_crosscheck.py`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémenter**

`src/mailtag/sender_crosscheck.py` :

```python
"""Second opinion per sender: Gemma classifies each scanned sender once (spec section 1.2)."""

from loguru import logger

from .taxonomy import llm_sender_part, llm_sender_static_prompt, parse_category_number


def crosscheck_senders(
    senders: dict, llm, done: dict, batch_size: int = 8, save_every: int = 100, on_save=None
) -> dict:
    """Gemma category (or None if unreadable) for every sender not in `done`, biggest senders first."""
    results = dict(done)
    todo = sorted(
        (s for s in senders if s not in results), key=lambda s: -sum(senders[s]["categories"].values())
    )
    static = llm_sender_static_prompt()
    for start in range(0, len(todo), save_every):
        chunk = todo[start : start + save_every]
        parts = [llm_sender_part(senders[s]["name"], s, senders[s]["subjects"]) for s in chunk]
        answers = llm.classify_batch(static, parts, batch_size=batch_size)
        for sender, answer in zip(chunk, answers, strict=True):
            results[sender] = parse_category_number(answer)
        if on_save:
            on_save(results)
        logger.info(f"Crosscheck: {len(results)}/{len(senders)} senders")
    return results
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_sender_crosscheck.py`
Expected: PASS. Note : `on_save` reçoit le même dictionnaire à chaque appel ; le test compare la liste `saved` après l'exception, donc son unique élément est l'état au moment du premier enregistrement. Si le test échoue parce que `saved[0]` a été modifié après coup, passer `dict(results)` à `on_save` et le noter dans le rapport.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/sender_crosscheck.py tests/test_sender_crosscheck.py
uv run ruff check src/mailtag/sender_crosscheck.py tests/test_sender_crosscheck.py
uv run pytest -q
git add src/mailtag/sender_crosscheck.py tests/test_sender_crosscheck.py
git commit -m "feat(taxonomy): Gemma crosscheck per sender with resume

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 5: Construction des règles (`taxonomy_build.py`, partie règles)

**Files:**
- Create: `src/mailtag/taxonomy_build.py`
- Test: `tests/test_taxonomy_build.py`

**Interfaces:**
- Consumes : format du scan (Task 3), `is_non_commercial_domain_cached`.
- Produces :
  - `mail_count(entry: dict) -> int`
  - `folder_category(entry: dict) -> str` (catégorie majoritaire ; en cas d'égalité, la première rencontrée)
  - `review_queue(senders: dict, crosscheck: dict, validated: dict) -> list[str]`
  - `learned_senders(senders: dict, crosscheck: dict, validated: dict, min_mails: int, agreements: int) -> dict[str, dict]` (valeurs `{"category", "agreements"}`)
  - `domain_rules(senders: dict, validated: dict, learned: dict, min_purity: float) -> dict[str, str]`
  - `rules_precision(senders: dict, crosscheck: dict, validated: dict) -> tuple[int, float]` : nombre d'expéditeurs revus où dossier = Gemma, et part de ceux où cette catégorie égale ta décision.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/test_taxonomy_build.py` :

```python
import pytest

from mailtag.taxonomy_build import (
    domain_rules,
    folder_category,
    learned_senders,
    review_queue,
    rules_precision,
)


@pytest.fixture(autouse=True)
def personal_domains(monkeypatch):
    monkeypatch.setattr("mailtag.taxonomy_build.is_non_commercial_domain_cached", lambda d: d == "gmail.com")


def entry(domain, **categories):
    return {"name": "", "domain": domain, "categories": categories, "subjects": [], "refs": []}


SENDERS = {
    "big@shop.ch": entry("shop.ch", Achats=40),
    "mixed@shop.ch": entry("shop.ch", Achats=1, Santé=3),
    "one@shop.ch": entry("shop.ch", Achats=1),
    "doc@clinic.ch": entry("clinic.ch", Santé=9),
    "friend@gmail.com": entry("gmail.com", Contacts=5),
}
CROSS = {"big@shop.ch": "Achats", "mixed@shop.ch": "Achats", "one@shop.ch": "Achats",
         "doc@clinic.ch": "Santé", "friend@gmail.com": None}  # fmt: skip


def test_folder_category_is_the_majority():
    assert folder_category(SENDERS["mixed@shop.ch"]) == "Santé"


def test_review_queue_disagreements_first_then_by_volume():
    queue = review_queue(SENDERS, CROSS, validated={"doc@clinic.ch": "Santé"})
    assert queue == ["friend@gmail.com", "mixed@shop.ch", "big@shop.ch", "one@shop.ch"]


def test_learned_senders_need_agreement_and_enough_mails():
    learned = learned_senders(SENDERS, CROSS, validated={"big@shop.ch": "Santé"}, min_mails=2, agreements=2)
    assert learned == {"doc@clinic.ch": {"category": "Santé", "agreements": 2}}


def test_domain_rules_use_corrected_categories_and_purity():
    validated = {"mixed@shop.ch": "Achats"}
    learned = {"big@shop.ch": {"category": "Achats", "agreements": 2},
               "doc@clinic.ch": {"category": "Santé", "agreements": 2}}  # fmt: skip
    senders = {**SENDERS, "x@clinic.ch": entry("clinic.ch", Achats=2)}
    learned_with_x = {**learned, "x@clinic.ch": {"category": "Achats", "agreements": 2}}

    assert domain_rules(SENDERS, validated, learned, min_purity=0.9) == {"shop.ch": "Achats", "clinic.ch": "Santé"}
    # clinic.ch: 9 Santé vs 2 Achats = 82 % < 90 %
    assert "clinic.ch" not in domain_rules(senders, validated, learned_with_x, min_purity=0.9)


def test_personal_domains_never_become_rules():
    validated = {"friend@gmail.com": "Contacts"}
    assert domain_rules(SENDERS, validated, {}, min_purity=0.9) == {}


def test_rules_precision():
    validated = {"big@shop.ch": "Achats", "doc@clinic.ch": "Santé", "one@shop.ch": "Colis & Livraisons",
                 "mixed@shop.ch": "Santé"}  # fmt: skip
    # mixed: dossier Santé != Gemma Achats -> hors mesure ; 3 accords dont 2 justes
    assert rules_precision(SENDERS, CROSS, validated) == (3, pytest.approx(2 / 3))
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_taxonomy_build.py`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémenter**

`src/mailtag/taxonomy_build.py` :

```python
"""Build learned rules, domain rules, the review queue and the centroid corpus (spec section 1)."""

from collections import Counter, defaultdict

from .utils.domain_utils import is_non_commercial_domain_cached


def mail_count(entry: dict) -> int:
    return sum(entry["categories"].values())


def folder_category(entry: dict) -> str:
    return max(entry["categories"], key=entry["categories"].get)


def review_queue(senders: dict, crosscheck: dict, validated: dict) -> list[str]:
    """Senders to review: folder/Gemma disagreements first, then agreements, biggest senders first."""
    todo = [s for s in senders if s not in validated]
    disagree = [s for s in todo if crosscheck.get(s) != folder_category(senders[s])]
    agree = [s for s in todo if crosscheck.get(s) == folder_category(senders[s])]

    def by_volume(sender: str) -> int:
        return -mail_count(senders[sender])

    return sorted(disagree, key=by_volume) + sorted(agree, key=by_volume)


def learned_senders(senders: dict, crosscheck: dict, validated: dict, min_mails: int, agreements: int) -> dict:
    """Senders whose folder category and Gemma agree, with enough mails, not already validated."""
    return {
        s: {"category": folder_category(e), "agreements": agreements}
        for s, e in senders.items()
        if s not in validated and mail_count(e) >= min_mails and crosscheck.get(s) == folder_category(e)
    }


def _sender_category(sender: str, validated: dict, learned: dict) -> str | None:
    return validated.get(sender) or (learned.get(sender) or {}).get("category")


def domain_rules(senders: dict, validated: dict, learned: dict, min_purity: float) -> dict[str, str]:
    """Business domains whose mails go to one category at least `min_purity` of the time."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for sender, entry in senders.items():
        category = _sender_category(sender, validated, learned)
        domain = entry["domain"]
        if category and domain and not is_non_commercial_domain_cached(domain):
            counts[domain][category] += mail_count(entry)
    rules = {}
    for domain, by_category in counts.items():
        category, n = by_category.most_common(1)[0]
        if n / sum(by_category.values()) >= min_purity:
            rules[domain] = category
    return rules


def rules_precision(senders: dict, crosscheck: dict, validated: dict) -> tuple[int, float]:
    """On reviewed senders where folder and Gemma agree, how often that agreement matches the user."""
    agreed = [
        s for s in validated if s in senders and crosscheck.get(s) == folder_category(senders[s])
    ]
    if not agreed:
        return 0, 0.0
    right = sum(folder_category(senders[s]) == validated[s] for s in agreed)
    return len(agreed), right / len(agreed)
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_taxonomy_build.py`
Expected: PASS.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/taxonomy_build.py tests/test_taxonomy_build.py
uv run ruff check src/mailtag/taxonomy_build.py tests/test_taxonomy_build.py
uv run pytest -q
git add src/mailtag/taxonomy_build.py tests/test_taxonomy_build.py
git commit -m "feat(taxonomy): learned sender, domain rules and review queue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 6: Échantillon et centroïdes (`taxonomy_build.py`, partie nomic)

**Files:**
- Modify: `src/mailtag/taxonomy_build.py`
- Test: `tests/test_taxonomy_build.py`

**Interfaces:**
- Consumes : `nomic_text` (Task 1), `ImapService.get_full_emails(uids) -> list[Email]` (dossier sélectionné), `SemanticRouter(embedder, score_threshold=...)`, `SemanticRouter.build_from_examples(dict[str, list[str]])`.
- Produces :
  - `corpus_refs(senders: dict, validated: dict, learned: dict, per_category: int = 200) -> list[dict]` : clés `sender`, `category`, `verified` (bool, expéditeur validé), `folder`, `uid`
  - `fetch_corpus(provider, refs: list[dict]) -> list[dict]` : clés `sender`, `category`, `verified`, `sender_name`, `subject`, `body`
  - `build_centroids(embedder, corpus: list[dict]) -> SemanticRouter`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_taxonomy_build.py` :

```python
import imaplib

from mailtag.models import Email
from mailtag.taxonomy_build import build_centroids, corpus_refs, fetch_corpus


def with_refs(domain, refs, **categories):
    e = entry(domain, **categories)
    e["refs"] = refs
    return e


def test_corpus_refs_take_verified_or_learned_senders_capped_per_category():
    senders = {
        "a@x.ch": with_refs("x.ch", [["F", 1], ["F", 2]], Achats=9),
        "b@x.ch": with_refs("x.ch", [["F", 3]], Achats=1),
        "c@x.ch": with_refs("x.ch", [["G", 4]], Santé=5),
        "unknown@x.ch": with_refs("x.ch", [["F", 5]], Achats=3),
    }
    refs = corpus_refs(
        senders, validated={"c@x.ch": "Santé"}, learned={"a@x.ch": {"category": "Achats", "agreements": 2},
                                                         "b@x.ch": {"category": "Achats", "agreements": 2}},
        per_category=2,
    )  # fmt: skip
    assert refs == [
        {"sender": "a@x.ch", "category": "Achats", "verified": False, "folder": "F", "uid": 1},
        {"sender": "a@x.ch", "category": "Achats", "verified": False, "folder": "F", "uid": 2},
        {"sender": "c@x.ch", "category": "Santé", "verified": True, "folder": "G", "uid": 4},
    ]


def test_fetch_corpus_reads_each_folder_read_only(mocker):
    provider = mocker.MagicMock()
    provider.get_full_emails.side_effect = lambda uids: [
        Email(msg_id=str(u), subject=f"S{u}", sender_address="a@x.ch", sender_name="A", body=f"B{u}") for u in uids
    ]
    refs = [{"sender": "a@x.ch", "category": "Achats", "verified": True, "folder": "F", "uid": 1},
            {"sender": "a@x.ch", "category": "Achats", "verified": True, "folder": "F", "uid": 2}]  # fmt: skip

    corpus = fetch_corpus(provider, refs)

    provider.client.select_folder.assert_called_once_with("F", readonly=True)
    assert corpus[1] == {"sender": "a@x.ch", "category": "Achats", "verified": True,
                         "sender_name": "A", "subject": "S2", "body": "B2"}  # fmt: skip


def test_fetch_corpus_skips_unreadable_folder(mocker):
    provider = mocker.MagicMock()
    provider.client.select_folder.side_effect = imaplib.IMAP4.error("gone")
    refs = [{"sender": "a@x.ch", "category": "Achats", "verified": True, "folder": "F", "uid": 1}]

    assert fetch_corpus(provider, refs) == []


def test_build_centroids_groups_production_texts_by_category(mocker):
    router_cls = mocker.patch("mailtag.taxonomy_build.SemanticRouter")
    corpus = [
        {"sender": "a@x.ch", "category": "Achats", "verified": True, "sender_name": "A", "subject": "S", "body": ""},
        {"sender": "b@x.ch", "category": "Santé", "verified": False, "sender_name": "", "subject": "T", "body": "B"},
    ]

    build_centroids("EMBEDDER", corpus)

    router_cls.assert_called_once_with("EMBEDDER", score_threshold=0.0)
    router_cls.return_value.build_from_examples.assert_called_once_with(
        {"Achats": ["Email from A: S"], "Santé": ["Email from b@x.ch: T\nB"]}
    )
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_taxonomy_build.py`
Expected: FAIL (`ImportError: cannot import name 'build_centroids'`).

- [ ] **Step 3: Implémenter**

Dans `src/mailtag/taxonomy_build.py`, compléter les imports :

```python
import imaplib
from collections import Counter, defaultdict

from loguru import logger

from .semantic_router import SemanticRouter
from .taxonomy import nomic_text
from .utils.domain_utils import is_non_commercial_domain_cached
```

Vérifier que `mailtag.semantic_router` n'importe pas MLX au chargement du module (`grep -n "^import\|^from" src/mailtag/semantic_router.py`) ; s'il le fait, importer `SemanticRouter` dans `build_centroids` et patcher `mailtag.semantic_router.SemanticRouter` dans le test, en le notant dans le rapport.

Ajouter à la fin :

```python
def corpus_refs(senders: dict, validated: dict, learned: dict, per_category: int = 200) -> list[dict]:
    """Mail references of validated or learned senders, biggest senders first, capped per category."""
    by_category: dict[str, list[dict]] = defaultdict(list)
    for sender, entry in sorted(senders.items(), key=lambda kv: -mail_count(kv[1])):
        category = _sender_category(sender, validated, learned)
        if not category:
            continue
        for folder, uid in entry["refs"]:
            by_category[category].append(
                {"sender": sender, "category": category, "verified": sender in validated,
                 "folder": folder, "uid": uid}
            )  # fmt: skip
    return [ref for refs in by_category.values() for ref in refs[:per_category]]


def fetch_corpus(provider, refs: list[dict]) -> list[dict]:
    """Read the referenced mails (read-only) and keep what nomic needs."""
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for ref in refs:
        by_folder[ref["folder"]].append(ref)
    corpus = []
    for folder, folder_refs in by_folder.items():
        try:
            provider.client.select_folder(folder, readonly=True)
            emails = {e.msg_id: e for e in provider.get_full_emails([r["uid"] for r in folder_refs])}
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not read folder {folder}: {e}")
            continue
        for ref in folder_refs:
            mail = emails.get(str(ref["uid"]))
            if mail:
                corpus.append(
                    {"sender": ref["sender"], "category": ref["category"], "verified": ref["verified"],
                     "sender_name": mail.sender_name, "subject": mail.subject, "body": mail.body}
                )  # fmt: skip
    return corpus


def build_centroids(embedder, corpus: list[dict]) -> SemanticRouter:
    """One nomic centroid per category, from the production text of real mails."""
    examples: dict[str, list[str]] = defaultdict(list)
    for mail in corpus:
        examples[mail["category"]].append(
            nomic_text(mail["sender_name"], mail["sender"], mail["subject"], mail["body"])
        )
    router = SemanticRouter(embedder, score_threshold=0.0)
    router.build_from_examples(dict(examples))
    return router
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_taxonomy_build.py`
Expected: PASS.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/taxonomy_build.py tests/test_taxonomy_build.py
uv run ruff check src/mailtag/taxonomy_build.py tests/test_taxonomy_build.py
uv run pytest -q
git add src/mailtag/taxonomy_build.py tests/test_taxonomy_build.py
git commit -m "feat(taxonomy): real-mail corpus and 19 nomic centroids

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 7: Chaîne du `Classifier` en mode taxonomie

**Files:**
- Modify: `src/mailtag/classifier.py` (`__init__`, `_init_mlx_components`, `_rule_category`, `_nomic_top`, `_classify_uncertain`, `_classify_batch_taxonomy`)
- Modify: `tests/test_classifier_taxonomy.py`

**Interfaces:**
- Consumes : `TaxonomyStore` (Task 2), `nomic_text` (Task 1), `config.taxonomy.taxonomy_db_dir`, `learn_min_agreements`, `centroids_file`.
- Produces :
  - `Classifier.taxonomy_store: TaxonomyStore | None` (créé seulement en mode taxonomie ; `read_only` repris de `database.read_only` s'il existe)
  - `Classifier._embeddings_path() -> Path` : `centroids_file` en mode taxonomie, sinon `mlx.embeddings_file`
  - `Classifier._classify_uncertain_detailed(emails) -> list[tuple[str, bool]]` : `(catégorie, accord nomic-Gemma)`
  - `Classifier._classify_uncertain(emails) -> list[str]` (inchangé pour les appelants, dont `chain`)

- [ ] **Step 1: Adapter les tests**

Dans `tests/test_classifier_taxonomy.py` :

1. Ajouter `import json` aux imports en tête du fichier, puis remplacer la fixture `classifier` par une fonction de configuration et une fixture qui l'utilise (un seul endroit construit la configuration) :

```python
def _config(tmp_path):
    return AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3
        ),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(
            enabled=True, nomic_threshold=0.70, llm_batch_size=8, taxonomy_db_dir=str(tmp_path)
        ),
    )


@pytest.fixture
def classifier(db, tmp_path):
    return Classifier(config=_config(tmp_path), database=db)
```

2. Supprimer `test_validated_old_path_is_mapped`, `test_domain_rule_is_mapped` et `test_rules_skip_unmappable_old_values` (les anciennes bases ne sont plus lues en mode taxonomie).

3. Ajouter :

```python
def write(tmp_path, name, data):
    (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_rules_come_from_the_taxonomy_store(db, tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    write(tmp_path, "senders", {"l@x.ch": {"category": "Achats", "agreements": 2}})
    write(tmp_path, "domains", {"bcv.ch": "Banque & Placements"})
    mocker.patch("mailtag.taxonomy_store.is_non_commercial_domain_cached", return_value=False)
    uncertain = mocker.patch.object(Classifier, "_classify_uncertain_detailed")
    # the fixture's classifier was built before the files existed: build a fresh one
    classifier = Classifier(config=_config(tmp_path), database=db)

    result = classifier.classify_emails_batch(
        [mail(1, sender="v@x.ch"), mail(2, sender="l@x.ch"), mail(3, sender="info@bcv.ch")]
    )

    assert result == ["Santé", "Achats", "Banque & Placements"]
    uncertain.assert_not_called()
    db.get_dominant_classification.assert_not_called()


def test_labels_are_ignored_in_taxonomy_mode(classifier, mocker):
    mocker.patch.object(classifier, "_classify_uncertain_detailed", return_value=[(REVIEW, False)])

    assert classifier.classify_emails_batch([mail(labels=["Voyages/Sixt"])]) == [REVIEW]


def test_two_agreements_make_a_rule(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classifier.classify_emails_batch([mail(1, sender="doc@clinic.ch")])
    classifier.classify_emails_batch([mail(2, sender="doc@clinic.ch")])

    saved = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert saved == {"doc@clinic.ch": {"category": "Santé", "agreements": 2}}
    nomic = mocker.patch.object(classifier, "_nomic_top")
    assert classifier.classify_emails_batch([mail(3, sender="doc@clinic.ch")]) == ["Santé"]
    nomic.assert_not_called()


def test_nomic_alone_does_not_learn(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.95)])

    assert classifier.classify_emails_batch([mail(sender="shop@x.ch")]) == ["Achats"]
    assert not (tmp_path / "senders.json").exists()


def test_read_only_database_means_no_learning_written(db, tmp_path, mocker):
    db.read_only = True
    classifier = Classifier(config=_config(tmp_path), database=db)
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classifier.classify_emails_batch([mail(sender="doc@clinic.ch")])

    assert list(tmp_path.iterdir()) == []


def test_no_suggestion_db_writes_in_taxonomy_mode(classifier, db, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classifier.classify_emails_batch([mail()])

    db.update_suggestion.assert_not_called()


def test_embeddings_path_uses_taxonomy_centroids(classifier):
    assert str(classifier._embeddings_path()) == "data/taxonomy_centroids.npz"


def test_detailed_chain_reports_agreement(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.9), ("Santé", 0.5), ("Santé", 0.5)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé", "Achats"])

    assert classifier._classify_uncertain_detailed([mail(1), mail(2), mail(3)]) == [
        ("Achats", False), ("Santé", True), (REVIEW, False)
    ]
```

Les tests existants qui patchent `_classify_uncertain` pour `classify_emails_batch` (`test_classify_email_delegates_to_batch`) doivent patcher `_classify_uncertain_detailed` et renvoyer `[("Achats", False)]`.

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_classifier_taxonomy.py`
Expected: FAIL (`_classify_uncertain_detailed` absent, `taxonomy_store` absent).

- [ ] **Step 3: Implémenter**

Dans `src/mailtag/classifier.py` :

1. Imports : remplacer la ligne `from .taxonomy import ...` par

```python
from .taxonomy import REVIEW, TAXONOMY, llm_email_part, llm_static_prompt, nomic_text, parse_category_number, to_category
from .taxonomy_store import TaxonomyStore
```

(ruff format coupera la ligne).

2. Dans `__init__`, dans la branche `if config.taxonomy.enabled:`, ajouter après `self.categories = list(TAXONOMY)` :

```python
            self.taxonomy_store = TaxonomyStore(
                Path(config.taxonomy.taxonomy_db_dir),
                min_agreements=config.taxonomy.learn_min_agreements,
                read_only=getattr(database, "read_only", False) is True,
            )
```

et, avant le bloc `if config.taxonomy.enabled:`, initialiser `self.taxonomy_store: TaxonomyStore | None = None`.

3. Ajouter la méthode :

```python
    def _embeddings_path(self) -> Path:
        """Taxonomy mode loads the 19 real-mail centroids; the legacy flow its folder centroids."""
        if self.config.taxonomy.enabled:
            return Path(self.config.taxonomy.centroids_file)
        return Path(self.config.mlx.embeddings_file)
```

et, dans `_init_mlx_components`, remplacer `embeddings_path = Path(self.config.mlx.embeddings_file)` par `embeddings_path = self._embeddings_path()`.

4. Remplacer `_rule_category` par :

```python
    def _rule_category(self, email: Email) -> str | None:
        """Signals 1, 3 and 4 from the taxonomy store (Signal 2, labels, is not used in taxonomy mode)."""
        return self.taxonomy_store.category_for(email.sender_address)
```

5. Dans `_nomic_top`, remplacer la construction de `texts` par :

```python
        texts = [nomic_text(e.sender_name, e.sender_address, e.subject, e.body) for e in emails]
```

6. Remplacer `_classify_uncertain` par :

```python
    def _classify_uncertain_detailed(self, emails: list[Email]) -> list[tuple[str, bool]]:
        """Signals 5-6: (category, nomic and LLM agreed) — nomic above threshold, else LLM agreement."""
        results: list[tuple[str, bool]] = [(REVIEW, False)] * len(emails)
        need_llm: list[tuple[int, str | None]] = []
        for i, (category, score) in enumerate(self._nomic_top(emails)):
            if category and score >= self.config.taxonomy.nomic_threshold:
                results[i] = (category, False)
            else:
                need_llm.append((i, category))
        if need_llm:
            answers = self._llm_categories([emails[i] for i, _ in need_llm])
            for (i, nomic_category), llm_category in zip(need_llm, answers, strict=True):
                if llm_category and llm_category == nomic_category:
                    results[i] = (llm_category, True)
        return results

    def _classify_uncertain(self, emails: list[Email]) -> list[str]:
        """Signals 5-6 categories only (used by the `chain` measurement)."""
        return [category for category, _ in self._classify_uncertain_detailed(emails)]
```

7. Remplacer `_classify_batch_taxonomy` par :

```python
    def _classify_batch_taxonomy(self, emails: list[Email]) -> list[str]:
        """Taxonomy mode: rules first, then the nomic/LLM chain; agreements teach the sender rules."""
        results: list[str | None] = [self._rule_category(e) for e in emails]
        pending = [i for i, category in enumerate(results) if category is None]
        if pending:
            detailed = self._classify_uncertain_detailed([emails[i] for i in pending])
            for i, (category, agreed) in zip(pending, detailed, strict=True):
                results[i] = category
                if agreed:
                    self.taxonomy_store.record_agreement(emails[i].sender_address, category)
            self.taxonomy_store.save()
        logger.info(
            f"Taxonomy batch: {len(emails) - len(pending)} by rules, "
            f"{sum(1 for i in pending if results[i] != REVIEW)} by models, "
            f"{sum(1 for r in results if r == REVIEW)} to review"
        )
        return results  # type: ignore[return-value]
```

Supprimer ensuite les imports que ce changement laisse inutilisés (`ruff check` les signale), sans toucher aux autres.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_classifier_taxonomy.py`
Expected: PASS. Puis `uv run pytest -q` : toute la suite passe (le flux actuel ne crée pas de `TaxonomyStore`).

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/classifier.py tests/test_classifier_taxonomy.py
uv run ruff check src/mailtag/classifier.py tests/test_classifier_taxonomy.py
uv run pytest -q
git add src/mailtag/classifier.py tests/test_classifier_taxonomy.py
git commit -m "feat(classifier): taxonomy rules from TaxonomyStore, learning on nomic/LLM agreement

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 8: Passes IMAP et apprentissage depuis `9-A revoir`

**Files:**
- Modify: `src/mailtag/utils/tasks.py` (`_run_fast_parse_on_folder`, `run_classification`)
- Modify: `src/mailtag/archive.py` (`_learn_from_review`, `run_archive`)
- Modify: `tests/test_routing.py`, `tests/test_archive.py`

**Interfaces:**
- Consumes : `Classifier.taxonomy_store` (Task 7), `TaxonomyStore.category_for`, `set_validated`, `save` (Task 2).
- Produces :
  - `_run_fast_parse_on_folder(provider, database, folder_name, validate, pending=None, rules=None)` : en mode taxonomie (`pending` non `None`), la catégorie vient de `rules.category_for(sender_address)`.
  - En mode taxonomie, la passe 2 est sautée : tous les mails non classés en passe 1 vont en passe 3 (les domaines sont déjà dans `category_for`).
  - `run_archive(provider, pending, rules, days, today, validate=False)` : `rules` a `set_validated(sender, category)` et `save()` ; `save()` est appelé en fin de ménage sauf en `--validate`.

- [ ] **Step 1: Adapter les tests**

Dans `tests/test_routing.py`, remplacer `test_pass1_routes_known_sender_in_taxonomy_mode` par :

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
    rules = mocker.MagicMock()
    rules.category_for.side_effect = lambda s: "Voyages & Loisirs" if s == "a@sixt.ch" else None

    uids, headers = tasks._run_fast_parse_on_folder(
        provider, database, "INBOX", False, pending=pending, rules=rules
    )

    assert uids == ["2"]
    provider.batch_move_emails.assert_called_once_with(["1"], "4-Pour info")
    assert pending.get("<1>")["category"] == "Voyages & Loisirs"
    database.get_dominant_classification.assert_not_called()
```

Dans `tests/test_archive.py` :

- dans `test_mail_moved_from_review_to_category_becomes_rule`, remplacer `db.promote_to_validated.assert_called_once_with("doc@clinic.ch", "Santé")` par :

```python
    db.set_validated.assert_called_once_with("doc@clinic.ch", "Santé")
    db.save.assert_called_once()
```

- dans `test_validate_changes_nothing`, ajouter à la fin :

```python
    db.set_validated.assert_not_called()
    db.save.assert_not_called()
```

(la variable reste nommée `db` dans ces tests ; c'est le second objet renvoyé par `setup`).

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_routing.py tests/test_archive.py`
Expected: FAIL (`unexpected keyword argument 'rules'`, `set_validated` non appelé).

- [ ] **Step 3: Implémenter**

Dans `src/mailtag/utils/tasks.py` :

1. Signature de `_run_fast_parse_on_folder` : ajouter `rules=None` après `pending: PendingArchive | None = None,`.

2. Dans sa boucle, remplacer :

```python
            classification = database.get_dominant_classification(sender_address)
            if pending is not None:
                classification = to_category(classification)
```

par :

```python
            if pending is not None:
                classification = rules.category_for(sender_address)
            else:
                classification = database.get_dominant_classification(sender_address)
```

3. Dans `run_classification`, passer `rules=classifier.taxonomy_store` aux deux appels de `_run_fast_parse_on_folder` (Junk et INBOX).

4. Remplacer le bloc de la passe 2 :

```python
                # --- Pass 2: Domain-based classification ---
                uids_to_process_pass3 = _run_domain_classification_pass(
                    ...
                )
                database.flush()
```

par :

```python
                # --- Pass 2: Domain-based classification (taxonomy mode: domains are in Pass 1 rules) ---
                if pending is not None:
                    uids_to_process_pass3 = uids_to_process_pass2
                else:
                    uids_to_process_pass3 = _run_domain_classification_pass(
                        provider,
                        database,
                        uids_to_process_pass2,
                        validate,
                        prefetched_headers=pass2_headers,
                    )
                    database.flush()
```

5. Dans l'appel à `run_archive`, remplacer l'argument `database` par `classifier.taxonomy_store`.

6. Dans `_run_domain_classification_pass`, la branche `pending is not None` n'est plus atteinte : la supprimer (paramètre `pending`, conversion `to_category`, appel `route_to_action_folders`), pour revenir au code du flux actuel. Supprimer l'import `to_category` s'il n'est plus utilisé. Vérifier avec `grep -n "pending\|to_category" src/mailtag/utils/tasks.py` que la passe 2 n'y fait plus référence.

Dans `src/mailtag/archive.py` :

1. `_learn_from_review(client, pending, database, present, validate)` devient `_learn_from_review(client, pending, rules, present, validate)`, et `database.promote_to_validated(waiting[mid]["sender"], category)` devient `rules.set_validated(waiting[mid]["sender"], category)`.

2. `run_archive(provider, pending, database, days, today, validate=False)` devient `run_archive(provider, pending, rules, days, today, validate=False)` ; passer `rules` à `_learn_from_review`, et dans le bloc final :

```python
    if not validate:
        for mid in orphans:
            pending.remove(mid)
        pending.save()
        rules.save()
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_routing.py tests/test_archive.py`
Expected: PASS. Puis `uv run pytest -q` : toute la suite passe. Si un test de la passe 2 en mode taxonomie existe ailleurs (`grep -rn "pending=" tests`), l'adapter au nouveau comportement (passe 2 sautée) et le noter.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format src/mailtag/utils/tasks.py src/mailtag/archive.py tests/test_routing.py tests/test_archive.py
uv run ruff check src/mailtag/utils/tasks.py src/mailtag/archive.py tests/test_routing.py tests/test_archive.py
uv run pytest -q
git add src/mailtag/utils/tasks.py src/mailtag/archive.py tests/test_routing.py tests/test_archive.py
git commit -m "feat(taxonomy): IMAP passes use learned rules, review learning writes validated rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 9: Commandes de préparation et page de revue

**Files:**
- Create: `scripts/taxonomy_setup.py`
- Create: `scripts/taxonomy_review.py`
- Modify: `CLAUDE.md`
- Test: `tests/test_taxonomy_setup.py`

**Interfaces:**
- Consumes : `scan_mailbox` (Task 3), `crosscheck_senders` (Task 4), `review_queue`, `learned_senders`, `domain_rules`, `corpus_refs`, `fetch_corpus`, `build_centroids`, `folder_category`, `mail_count` (Tasks 5 et 6), `TaxonomyStore`, `write_json_atomic` (Task 2), `ImapService`, `MLXLLM`, `MLXEmbedder`, `CONFIG`.
- Produces :
  - `missing_inputs(paths: list[Path]) -> list[Path]`
  - commandes `uv run python scripts/taxonomy_setup.py scan|crosscheck|build`
  - page `uv run streamlit run scripts/taxonomy_review.py`

- [ ] **Step 1: Écrire le test qui échoue**

`tests/test_taxonomy_setup.py` :

```python
def test_missing_inputs(tmp_path):
    from scripts.taxonomy_setup import missing_inputs

    present = tmp_path / "scan.json"
    present.write_text("{}")
    absent = tmp_path / "crosscheck.json"

    assert missing_inputs([present, absent]) == [absent]
    assert missing_inputs([present]) == []
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest -q tests/test_taxonomy_setup.py`
Expected: FAIL (`ModuleNotFoundError: scripts.taxonomy_setup`).

- [ ] **Step 3: Implémenter**

`scripts/taxonomy_setup.py` :

```python
"""Taxonomy preparation (docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md, section 1).

    uv run python scripts/taxonomy_setup.py scan        # read-only header pass over existing folders
    uv run python scripts/taxonomy_setup.py crosscheck  # Gemma category per sender (resumable, ~1 s/sender)
    uv run streamlit run scripts/taxonomy_review.py     # review disagreements
    uv run python scripts/taxonomy_setup.py build       # rules, corpus and the 19 nomic centroids

No step moves an email.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mailtag.config import CONFIG
from mailtag.taxonomy_store import TaxonomyStore, write_json_atomic

SCAN = Path("data/mailbox_scan.json")
CROSSCHECK = Path("data/sender_crosscheck.json")
CORPUS = Path("data/taxonomy_corpus.json")


def missing_inputs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _imap():
    from mailtag.imap_service import ImapService

    return ImapService(CONFIG.imap, CONFIG.fast_parse).connect()


def scan() -> None:
    from mailtag.mailbox_scan import scan_mailbox

    folders = json.loads(Path(CONFIG.taxonomy.legacy_folders_file).read_text(encoding="utf-8"))
    with _imap() as provider:
        result = scan_mailbox(provider, folders)
    write_json_atomic(SCAN, result)
    logger.info(f"Wrote {SCAN}: {len(result['senders'])} senders")


def crosscheck() -> None:
    from mailtag.mlx_provider import MLXLLM
    from mailtag.sender_crosscheck import crosscheck_senders

    if missing := missing_inputs([SCAN]):
        sys.exit(f"Missing {missing[0]}: run `scan` first")
    done = _read(CROSSCHECK) if CROSSCHECK.exists() else {}
    llm = MLXLLM(CONFIG.mlx.llm_model, max_tokens=4, temperature=0.0)
    crosscheck_senders(
        _read(SCAN)["senders"], llm, done, batch_size=CONFIG.taxonomy.llm_batch_size,
        on_save=lambda results: write_json_atomic(CROSSCHECK, results),
    )  # fmt: skip


def build() -> None:
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.taxonomy_build import build_centroids, corpus_refs, domain_rules, fetch_corpus, learned_senders

    if missing := missing_inputs([SCAN, CROSSCHECK]):
        sys.exit(f"Missing {missing[0]}: run `scan` and `crosscheck` first")
    cfg = CONFIG.taxonomy
    senders, cross = _read(SCAN)["senders"], _read(CROSSCHECK)
    store = TaxonomyStore(Path(cfg.taxonomy_db_dir), min_agreements=cfg.learn_min_agreements)
    learned = learned_senders(
        senders, cross, store.validated, min_mails=cfg.sender_min_mails, agreements=cfg.learn_min_agreements
    )
    domains = domain_rules(senders, store.validated, learned, min_purity=cfg.domain_min_purity)
    store.replace_rules(learned, domains)
    store.save()
    logger.info(f"Rules: {len(store.validated)} validated, {len(learned)} learned, {len(domains)} domains")

    with _imap() as provider:
        corpus = fetch_corpus(provider, corpus_refs(senders, store.validated, learned))
    write_json_atomic(CORPUS, corpus)
    router = build_centroids(MLXEmbedder(CONFIG.mlx.embedding_model), corpus)
    router.save_embeddings(Path(cfg.centroids_file))
    logger.info(f"Centroids for {router.num_categories} categories from {len(corpus)} mails")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["scan", "crosscheck", "build"])
    {"scan": scan, "crosscheck": crosscheck, "build": build}[parser.parse_args().command]()


if __name__ == "__main__":
    main()
```

Vérifier la signature réelle de `MLXLLM.__init__` (`grep -n "def __init__" -A6 src/mailtag/mlx_provider.py`) et de `ImapService.connect` (context manager qui renvoie le service) ; adapter l'appel si les noms diffèrent, et le noter.

`scripts/taxonomy_review.py` :

```python
"""Local review page: settle folder/Gemma disagreements, biggest senders first (spec section 1.3).

    uv run streamlit run scripts/taxonomy_review.py

Every click is written to db/taxonomy/validated.json at once. Nothing leaves this machine.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st

from mailtag.config import CONFIG
from mailtag.taxonomy import TAXONOMY
from mailtag.taxonomy_build import folder_category, mail_count, review_queue
from mailtag.taxonomy_store import TaxonomyStore

SCAN = Path("data/mailbox_scan.json")
CROSSCHECK = Path("data/sender_crosscheck.json")

st.set_page_config(page_title="MailTag — revue des expéditeurs", layout="wide")

if not SCAN.exists() or not CROSSCHECK.exists():
    st.error("Lance d'abord `scan` puis `crosscheck` (scripts/taxonomy_setup.py).")
    st.stop()

senders = json.loads(SCAN.read_text(encoding="utf-8"))["senders"]
cross = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
store = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir))
skipped = st.session_state.setdefault("skipped", set())
queue = [s for s in review_queue(senders, cross, store.validated) if s not in skipped]

st.caption(f"{len(store.validated)} expéditeurs validés · {len(queue)} restants")
if not queue:
    st.success("Revue terminée.")
    st.stop()

sender = queue[0]
entry = senders[sender]
st.header(sender)
st.write(f"**{entry['name'] or '(sans nom)'}** · {mail_count(entry)} mails · domaine `{entry['domain']}`")
st.write(f"Dossier : **{folder_category(entry)}** · Gemma : **{cross.get(sender) or '(illisible)'}**")
for subject in entry["subjects"]:
    st.write(f"- {subject}")

columns = st.columns(4)
for i, category in enumerate(TAXONOMY):
    if columns[i % 4].button(category, key=f"{sender}-{category}"):
        store.set_validated(sender, category)
        store.save()
        st.rerun()
if st.button("Passer"):
    skipped.add(sender)
    st.rerun()
```

Dans `CLAUDE.md`, section `### Taxonomy mode` (ajoutée par la spec 1), ajouter à la fin :

```markdown
**Learned signals** (`docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md`): in taxonomy mode, Signals 1, 3 and 4 come from `TaxonomyStore` (`db/taxonomy/validated.json`, `senders.json`, `domains.json`); Signal 2 (labels) is not used; nomic loads `data/taxonomy_centroids.npz`. A nomic/Gemma agreement counts for the sender; after `learn_min_agreements` (2) agreements the sender becomes a rule, and a contradiction removes it. Emails the user files out of `9-A revoir` go to `validated.json`. Preparation (no email is moved): `scripts/taxonomy_setup.py scan`, `crosscheck`, then `streamlit run scripts/taxonomy_review.py`, then `build`.
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_taxonomy_setup.py`
Expected: PASS. Puis vérifier que les deux scripts se chargent sans erreur de syntaxe : `uv run python -c "import ast,sys; [ast.parse(open(f).read()) for f in sys.argv[1:]]" scripts/taxonomy_setup.py scripts/taxonomy_review.py` et `uv run python scripts/taxonomy_setup.py --help`.

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format scripts/taxonomy_setup.py scripts/taxonomy_review.py tests/test_taxonomy_setup.py
uv run ruff check scripts/taxonomy_setup.py scripts/taxonomy_review.py tests/test_taxonomy_setup.py
uv run pytest -q
git add scripts/taxonomy_setup.py scripts/taxonomy_review.py tests/test_taxonomy_setup.py CLAUDE.md
git commit -m "feat(taxonomy): scan/crosscheck/build commands and local review page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

### Task 10: Mesure `chain` sur les données vérifiées

**Files:**
- Modify: `scripts/eval_embeddings.py` (`chain_eval`, sous-commande `chain`)
- Test: `tests/test_eval_embeddings.py`

**Interfaces:**
- Consumes : `data/taxonomy_corpus.json` (Task 9), `data/mailbox_scan.json`, `data/sender_crosscheck.json`, `TaxonomyStore.validated`, `rules_precision` (Task 5), `nomic_text` (Task 1), `Classifier._llm_categories`, `MLXEmbedder.encode`, `chain_metrics` (existant).
- Produces :
  - `leave_sender_out_top(doc_emb, doc_categories, doc_senders, query_emb, query_senders) -> list[tuple[str | None, float]]` : pour chaque requête, catégorie du centroïde le plus proche et similarité cosinus, les documents de l'expéditeur de la requête étant exclus de tous les centroïdes
  - `threshold_sweep(nomic: list[tuple[str | None, float]], llm: list[str | None], labels: list[str], thresholds: list[float]) -> list[dict]` (clés `threshold`, `auto`, `precision`)
  - `best_threshold(sweep: list[dict], min_precision: float = 0.90) -> dict | None` : ligne de plus forte couverture dont la précision atteint `min_precision`
  - commande `uv run python scripts/eval_embeddings.py chain -n 500`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_eval_embeddings.py` :

```python
import numpy as np


def test_leave_sender_out_excludes_the_query_sender():
    from scripts.eval_embeddings import leave_sender_out_top

    doc = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    cats = ["Achats", "Achats", "Santé"]
    senders = ["a@x", "b@x", "c@x"]
    query = np.array([[1.0, 0.0], [1.0, 0.1]])

    top = leave_sender_out_top(doc, cats, senders, query, ["a@x", "c@x"])

    assert top[0][0] == "Achats" and top[0][1] == pytest.approx(1.0)  # b@x still defines Achats
    assert top[1][0] == "Achats"  # Santé has no document left once c@x is excluded


def test_leave_sender_out_with_no_centroid_left():
    from scripts.eval_embeddings import leave_sender_out_top

    top = leave_sender_out_top(np.array([[1.0, 0.0]]), ["Achats"], ["a@x"], np.array([[1.0, 0.0]]), ["a@x"])

    assert top == [(None, 0.0)]


def test_threshold_sweep_and_best():
    from scripts.eval_embeddings import best_threshold, threshold_sweep

    nomic = [("A", 0.9), ("A", 0.6), ("B", 0.65), ("B", 0.5)]
    llm = [None, "A", None, "C"]
    labels = ["A", "A", "C", "B"]

    sweep = threshold_sweep(nomic, llm, labels, [0.6, 0.8])

    assert sweep[0] == {"threshold": 0.6, "auto": 0.75, "precision": pytest.approx(2 / 3)}
    assert sweep[1] == {"threshold": 0.8, "auto": 0.5, "precision": 1.0}
    assert best_threshold(sweep) == sweep[1]
    assert best_threshold(sweep, min_precision=1.1) is None
```

(ajouter `import pytest` en tête du fichier s'il n'y est pas).

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `uv run pytest -q tests/test_eval_embeddings.py`
Expected: FAIL (`ImportError: cannot import name 'leave_sender_out_top'`).

- [ ] **Step 3: Implémenter**

Dans `scripts/eval_embeddings.py`, ajouter avant `chain_eval` :

```python
def leave_sender_out_top(doc_emb, doc_categories, doc_senders, query_emb, query_senders):
    """Nearest category centroid per query, excluding every document of the query's own sender."""
    categories = sorted(set(doc_categories))
    cat_index = {c: i for i, c in enumerate(categories)}
    cats = np.array([cat_index[c] for c in doc_categories])
    sums = np.zeros((len(categories), doc_emb.shape[1]))
    counts = np.zeros(len(categories))
    np.add.at(sums, cats, doc_emb)
    np.add.at(counts, cats, 1)
    doc_senders = np.array(doc_senders)

    results = []
    for q, sender in zip(query_emb, query_senders, strict=True):
        own = doc_senders == sender
        s = sums.copy()
        n = counts.copy()
        np.subtract.at(s, cats[own], doc_emb[own])
        np.subtract.at(n, cats[own], 1)
        valid = n > 0
        if not valid.any():
            results.append((None, 0.0))
            continue
        centroids = s[valid] / n[valid][:, None]
        sims = centroids @ q / (np.linalg.norm(centroids, axis=1) * np.linalg.norm(q))
        best = int(np.argmax(sims))
        results.append((np.array(categories)[valid][best].item(), float(sims[best])))
    return results


def threshold_sweep(nomic, llm, labels, thresholds):
    """Chain result for each nomic threshold: nomic above it, else nomic/LLM agreement, else review."""
    from mailtag.taxonomy import REVIEW

    rows = []
    for t in thresholds:
        results = [
            cat if cat and score >= t else (answer if answer and answer == cat else REVIEW)
            for (cat, score), answer in zip(nomic, llm, strict=True)
        ]
        m = chain_metrics(results, labels, 0.0, 0)
        rows.append({"threshold": t, "auto": m["auto"], "precision": m["precision"]})
    return rows


def best_threshold(sweep, min_precision=0.90):
    """Row with the highest coverage whose precision reaches `min_precision`, or None."""
    ok = [row for row in sweep if row["precision"] >= min_precision]
    return max(ok, key=lambda row: (row["auto"], row["threshold"])) if ok else None
```

Remplacer `chain_eval` par :

```python
def chain_eval(n: int, seed: int) -> None:
    """Replay signals 5-6 on verified mails (leave-sender-out centroids) and pick the nomic threshold."""
    import dataclasses
    import random

    from mailtag.classifier import Classifier
    from mailtag.config import CONFIG
    from mailtag.database import ClassificationDatabase
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.models import Email
    from mailtag.taxonomy import nomic_text
    from mailtag.taxonomy_build import rules_precision
    from mailtag.taxonomy_store import TaxonomyStore

    corpus = json.loads(Path("data/taxonomy_corpus.json").read_text(encoding="utf-8"))
    validated = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir)).validated
    senders = json.loads(Path("data/mailbox_scan.json").read_text(encoding="utf-8"))["senders"]
    cross = json.loads(Path("data/sender_crosscheck.json").read_text(encoding="utf-8"))

    agreed, precision = rules_precision(senders, cross, validated)
    print(f"Learned rules: {precision:.1%} right on {agreed} reviewed senders where folder and Gemma agree")

    verified = [m for m in corpus if m["verified"]]
    test = random.Random(seed).sample(verified, min(n, len(verified)))
    embedder = MLXEmbedder(CONFIG.mlx.embedding_model)

    def texts(mails):
        return [nomic_text(m["sender_name"], m["sender"], m["subject"], m["body"]) for m in mails]

    doc_emb = embedder.encode(texts(corpus), prefix="search_document: ")
    query_emb = embedder.encode(texts(test), prefix="search_query: ")
    nomic = leave_sender_out_top(
        doc_emb, [m["category"] for m in corpus], [m["sender"] for m in corpus], query_emb, [m["sender"] for m in test]
    )

    config = dataclasses.replace(CONFIG, taxonomy=dataclasses.replace(CONFIG.taxonomy, enabled=True))
    classifier = Classifier(config, ClassificationDatabase(Path("db/sender_classification_db.json"),
                                                           Path("db/validated_classification_db.json"),
                                                           read_only=True))  # fmt: skip
    emails = [
        Email(msg_id=str(i), subject=m["subject"], sender_address=m["sender"], sender_name=m["sender_name"],
              body=m["body"])
        for i, m in enumerate(test)
    ]  # fmt: skip
    start = time.perf_counter()
    llm = []
    for i in range(0, len(emails), 50):
        llm += classifier._llm_categories(emails[i : i + 50])
        logger.info(f"LLM {len(llm)}/{len(emails)} ({(time.perf_counter() - start) / len(llm):.2f} s/email)")

    labels = [m["category"] for m in test]
    sweep = threshold_sweep(nomic, llm, labels, [round(0.50 + 0.01 * i, 2) for i in range(41)])
    print(f"\n{len(test)} verified mails (seed {seed})\n threshold  auto   precision")
    for row in sweep:
        print(f"   {row['threshold']:.2f}    {row['auto']:5.1%}  {row['precision']:6.1%}")
    best = best_threshold(sweep)
    if best:
        print(f"\nnomic_threshold = {best['threshold']:.2f}: {best['auto']:.1%} classified at {best['precision']:.1%}")
    print("PASS" if best and precision >= 0.90 else "FAIL")
```

Dans `main()`, remplacer les trois lignes de `p_chain` par :

```python
    p_chain = sub.add_parser("chain", help="Measure signals 5-6 on verified mails and pick the nomic threshold")
    p_chain.add_argument("-n", type=int, default=500)
    p_chain.add_argument("--seed", type=int, default=3)
```

et l'appel par `chain_eval(args.n, args.seed)`. Mettre à jour la ligne `chain` de la docstring du module.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest -q tests/test_eval_embeddings.py`
Expected: PASS (dont `test_chain_metrics_success_criteria`, inchangé).

- [ ] **Step 5: Lint et commit**

```bash
uv run ruff format scripts/eval_embeddings.py tests/test_eval_embeddings.py
uv run ruff check scripts/eval_embeddings.py tests/test_eval_embeddings.py
uv run pytest -q
git add scripts/eval_embeddings.py tests/test_eval_embeddings.py
git commit -m "feat(eval): chain measures verified mails and picks the nomic threshold

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UhWHGNw3cmgF8EUkdP8sCp"
```

---

## Après l'implémentation (avec toi, pas par les sous-agents)

Ces étapes utilisent ta vraie boîte ; aucune ne déplace de mail.

1. `uv run python scripts/taxonomy_setup.py scan` (quelques minutes).
2. `uv run python scripts/taxonomy_setup.py crosscheck` en tâche de fond (environ 1 s par expéditeur ; reprise possible).
3. Ta revue : `uv run streamlit run scripts/taxonomy_review.py` (environ 1 heure).
4. `uv run python scripts/taxonomy_setup.py build`.
5. `uv run python scripts/eval_embeddings.py chain -n 500` : fixe `nomic_threshold` dans `config.toml` et vérifie les 90 %.
6. Essai à blanc avec le mode activé pour ce seul processus : couverture ≥ 60 % attendue.
7. Tu décides de passer `[taxonomy] enabled = true`.
