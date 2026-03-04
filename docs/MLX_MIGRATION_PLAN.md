# Plan: Migration vers MLX pour MailTag

## Décisions Prises

- **Architecture:** Option C - Hybride (Embeddings MLX + LLM MLX fallback)
- **Fallback litellm:** Non - MLX uniquement (projet Mac-only)
- **Embedding:** `nomic-embed-text-v1.5` (précis, contexte long, bon en français)
- **LLM:** `Mistral-7B-Instruct-v0.3-4bit` (équilibré, fiable)

---

## Architecture Cible

```
Signal 1: Validated DB (100%)
Signal 2: Server Labels (95%)
Signal 3: Historical DB (90%)
Signal 4: Domain Rules (90%)
Signal 5: Semantic Router MLX (85%) ← NOUVEAU - Embeddings instantanés
Signal 6: LLM MLX Fallback (0.85 threshold) ← Remplace litellm
```

### Configuration

```toml
[mlx]
enabled = true

# Semantic Router (Signal 5)
embedding_model = "nomic-ai/nomic-embed-text-v1.5"
score_threshold = 0.75

# LLM Fallback (Signal 6)
llm_model = "mlx-community/Mistral-7B-Instruct-v0.3-4bit"
llm_confidence = 0.85
```

---

## Gains Attendus

### Performance

- **5-6x plus rapide** pour la classification AI
- **Classification instantanée** via embeddings (nouveau signal)
- **32% mémoire économisée** vs Ollama

### Simplicité

- **Pas de serveur Ollama** à démarrer/maintenir
- Configuration unifiée dans `config.toml`
- Dépendances Python uniquement

### Coût

- **0 API calls** = gratuit
- Exécution 100% locale

### Flexibilité

- Changement de modèle via config uniquement
- Support des modèles mlx-community (1000+)

---

## Risques et Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Apple Silicon only | Accepté | Projet Mac-only confirmé |
| Qualité classification | Moyen | Tests A/B vs configuration actuelle |
| Nouvelles dépendances | Faible | mlx, mlx-lm sont stables |
| Accuracy embeddings | Moyen | Threshold 0.75 + LLM fallback |

---

## Plan d'Implémentation

### Phase 1: Infrastructure MLX

**Fichiers à créer:**

1. `src/mailtag/mlx_provider.py`

   ```python
   class MLXEmbedder:
       """Génère embeddings avec nomic-embed-text-v1.5"""
       def __init__(self, model_name: str)
       def encode(self, texts: list[str]) -> np.ndarray

   class MLXLLM:
       """Génère texte avec Mistral-7B via mlx-lm"""
       def __init__(self, model_name: str)
       def generate(self, prompt: str, max_tokens: int) -> str
   ```

2. `src/mailtag/config.py` - Ajouter:

   ```python
   @dataclass
   class MLXConfig:
       enabled: bool = True
       embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
       score_threshold: float = 0.75
       llm_model: str = "mlx-community/Mistral-7B-Instruct-v0.3-4bit"
       llm_confidence: float = 0.85
   ```

### Phase 2: Semantic Router

**Fichiers à créer:**

1. `src/mailtag/semantic_router.py`

   ```python
   class SemanticRouter:
       """Classification par similarité sémantique"""
       def __init__(self, embedder: MLXEmbedder, categories_file: Path)
       def build_category_embeddings(self, validated_db: dict)
       def route(self, text: str) -> tuple[str, float]  # (category, score)
       def save_embeddings(self, path: Path)
       def load_embeddings(self, path: Path)
   ```

2. `scripts/build_category_embeddings.py`
   - Charge `db/validated_classification_db.json`
   - Génère embeddings par catégorie (centroïde des exemples)
   - Sauvegarde dans `data/category_embeddings.npz`

### Phase 3: Intégration Classifier

**Fichier à modifier:**

1. `src/mailtag/classifier.py`
   - Supprimer import litellm
   - Ajouter `_get_category_from_semantic_router()` (Signal 5)
   - Modifier `_get_category_from_ai()` pour utiliser `MLXLLM` (Signal 6)
   - Lazy loading des modèles MLX

### Phase 4: Configuration

**Fichiers à modifier:**

1. `config.toml` - Ajouter section:

   ```toml
   [mlx]
   enabled = true
   embedding_model = "nomic-ai/nomic-embed-text-v1.5"
   score_threshold = 0.75
   llm_model = "mlx-community/Mistral-7B-Instruct-v0.3-4bit"
   llm_confidence = 0.85
   ```

2. `pyproject.toml` - Modifier dépendances:

   ```toml
   dependencies = [
       # Remplacer litellm par:
       "mlx>=0.18",
       "mlx-lm>=0.18",
       "sentence-transformers>=2.2",  # Pour nomic embeddings
       "numpy>=1.24",
   ]
   ```

### Phase 5: Tests

**Fichiers à créer:**

1. `tests/test_mlx_provider.py`
2. `tests/test_semantic_router.py`

---

## Fichiers Impactés (Résumé)

| Fichier | Action | Lignes estimées |
|---------|--------|-----------------|
| `src/mailtag/mlx_provider.py` | Créer | ~150 |
| `src/mailtag/semantic_router.py` | Créer | ~120 |
| `src/mailtag/classifier.py` | Modifier | ~50 changées |
| `src/mailtag/config.py` | Modifier | ~20 ajoutées |
| `config.toml` | Modifier | ~10 ajoutées |
| `pyproject.toml` | Modifier | ~5 changées |
| `scripts/build_category_embeddings.py` | Créer | ~80 |
| `tests/test_mlx_provider.py` | Créer | ~100 |
| `tests/test_semantic_router.py` | Créer | ~100 |

**Total:** ~9 fichiers, ~635 lignes

---

## Réutilisation des Données Existantes

| Fichier | Usage actuel | Usage MLX |
|---------|--------------|-----------|
| `db/validated_classification_db.json` | Signal 1 (100%) | **Inchangé** + source pour embeddings catégories |
| `db/sender_classification_db.json` | Signal 3 (historique) | **Inchangé** |
| `db/domain_classifications.json` | Signal 4 (domaines) | **Inchangé** |
| `data/imap_folders.json` | Liste catégories | **Inchangé** |
| `data/category_embeddings.npz` | N/A | **NOUVEAU** - Généré depuis validated_db |

### Génération des Embeddings Catégories

Le script `build_category_embeddings.py`:

```python
# 1. Charge validated_db
validated_db = load("db/validated_classification_db.json")
# {"sender@shop.com": "Inbox/Commerce", ...}

# 2. Regroupe par catégorie + récupère exemples de subjects/bodies
categories = {}
for sender, category in validated_db.items():
    if category not in categories:
        categories[category] = []
    # Ajoute des exemples représentatifs (depuis historical_db ou imap_folders)
    categories[category].append(f"Email de {sender}")

# 3. Calcule embedding centroïde par catégorie
for category, examples in categories.items():
    embeddings = model.encode(examples)
    category_embeddings[category] = embeddings.mean(axis=0)

# 4. Sauvegarde
np.savez("data/category_embeddings.npz", **category_embeddings)
```

**Important:** Les Signals 1-4 restent identiques. MLX ajoute seulement Signal 5 (semantic) et remplace litellm pour Signal 6 (LLM).

---

## Ordre d'Exécution

1. Config (`config.py`, `config.toml`, `pyproject.toml`)
2. MLX Provider (`mlx_provider.py`)
3. Semantic Router (`semantic_router.py`)
4. Script embeddings (`build_category_embeddings.py`)
5. Intégration Classifier (`classifier.py`)
6. Tests
7. Documentation (CLAUDE.md)
8. **Générer embeddings initiaux** via `python scripts/build_category_embeddings.py`
