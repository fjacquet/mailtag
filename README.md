# MailTag

MailTag is a Python-based email automation tool that classifies and organizes emails using on-device AI. It supports both IMAP and Gmail, using a 6-signal classification strategy with MLX-powered local inference on Apple Silicon.

[![CI Tests and Checks](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/fjacquet/mailtag)](https://github.com/fjacquet/mailtag/releases)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![codecov](https://codecov.io/gh/fjacquet/mailtag/branch/main/graph/badge.svg)](https://codecov.io/gh/fjacquet/mailtag)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://fjacquet.github.io/mailtag/)

## How It Works

MailTag classifies emails through 6 prioritized signals:

1. **Validated Database** — manually confirmed sender→category mappings (100% confidence)
2. **Server-Side Labels** — existing IMAP folders or Gmail labels (95%)
3. **Historical Database** — sender history patterns (90%+)
4. **Domain Classification** — commercial domain rules (90%)
5. **Semantic Router** — MLX embedding similarity via `nomic-embed-text-v1.5` (configurable threshold)
6. **MLX LLM** — local Gemma 4 E4B model returning JSON `{category, confidence, reason}` (0.85 threshold)

Each signal stops evaluation when it classifies an email. IMAP uses a 3-pass system (headers → domains → full body + AI) for efficiency.

### Taxonomy mode

With `[taxonomy] enabled = true` (as in the shipped `config.toml`), MailTag files mail into **19 business-sector categories** (Banque & Placements, Santé, Achats, Éditeurs IT & Cloud, Contacts…) instead of hundreds of IMAP folders. New mail first lands in an action folder (`1-A traiter`, `2-A payer`, `3-A lire`, `4-Pour info`, the provider's standard `Promotions`, or `5-A revoir` when unsure) and moves into its category once read and a week old. Category folders follow PARA: `Domaines/` (areas: bank, health, family…), `Ressources/` (topics: newsletters, IT vendors, media…) and the standard `Archive/` (purchases, parcels); projects are your own folders.

The chain: validated sender → learned sender (after two nomic/Gemma agreements) → business domain → nomic centroids (score ≥ `nomic_threshold`) → nomic and Gemma agreeing → `5-A revoir`. Filing a mail out of `5-A revoir` teaches MailTag its sender. The rules were learned from the legacy folders with `scripts/taxonomy_setup.py` and a local Streamlit review page; see the [usage docs](https://fjacquet.github.io/mailtag/getting-started/usage/).

## Prerequisites

- Python 3.13+
- macOS with Apple Silicon (MLX requires Metal)

## Installation

```bash
git clone https://github.com/fjacquet/mailtag.git
cd mailtag
uv sync -U --all-extras
```

## Configuration

Configuration uses two sources:

- **`config.toml`** — main config (IMAP/Gmail settings, classifier thresholds, MLX models, logging)
- **`.env`** — secrets and cloud AI provider selection

### Required `.env` variables

```bash
IMAP_USER=your-email@example.com
IMAP_PASSWORD=your-password
# Optional: cloud AI provider (MODEL defaults to MLX local inference)
# MODEL=gemini/gemini-2.5-flash
# GEMINI_API_KEY=your-key
```

### MLX Models (config.toml)

```toml
[mlx]
embedding_model = "nomic-ai/nomic-embed-text-v1.5"    # Signal 5: Semantic Router
llm_model = "mlx-community/gemma-4-e4b-it-OptiQ-4bit" # Signal 6: LLM fallback
llm_confidence = 0.85
llm_max_tokens = 128
```

### Gmail Setup

Gmail runs through the **Gmail API** (OAuth), not IMAP. Create an OAuth desktop client in
[Google Cloud Console](https://console.cloud.google.com/), save it as `secrets/credentials.json`, and run
`run --provider gmail --validate` once to open the browser and save `secrets/token.json`. See the
[configuration docs](https://fjacquet.github.io/mailtag/getting-started/configuration/#gmail-api-setup) for details.

## Usage

```bash
python src/main.py run --provider all              # Classify all providers
python src/main.py run --provider imap             # IMAP only
python src/main.py run --provider gmail             # Gmail (through the Gmail API) only
python src/main.py run --provider imap --validate  # Read-only (no moves)
python src/main.py filters                         # Generate email filters
python src/main.py analyze-domains                 # Find domain candidates
python src/main.py db-stats                        # Database health check
python src/main.py cleanup --consolidate           # Remove old pass3 files
```

Taxonomy setup and legacy folder migration (dry run unless `--apply`):

```bash
uv run python scripts/taxonomy_setup.py scan        # read-only pass over the legacy folders
uv run python scripts/taxonomy_setup.py crosscheck  # Gemma opinion per sender
uv run streamlit run scripts/taxonomy_review.py     # local review page
uv run python scripts/taxonomy_setup.py build       # rules and nomic centroids
uv run python scripts/taxonomy_setup.py migrate [--apply]  # move legacy folder mail into the categories
uv run python scripts/taxonomy_setup.py prune [--apply]    # delete the emptied legacy folders
uv run python scripts/taxonomy_setup.py reorganize [--apply]  # PARA folders, standard Promotions
```

Bulk review of `5-A revoir` (own the decision per domain or per sender instead of mail by mail; dry
run unless `--apply`):

```bash
uv run python scripts/taxonomy_setup.py review-scan --provider imap|gmail    # group, Gemma suggestion
uv run streamlit run scripts/taxonomy_review.py                              # stage 5: decide
uv run python scripts/taxonomy_setup.py refile-review --provider imap|gmail [--apply]  # move covered mail
```

## Data and Database

- `db/validated_classification_db.json`: Manually validated sender→category mappings (Signal 1)
- `db/sender_classification_db.json`: AI suggestions and historical patterns (Signal 3)
- `db/domain_classifications.json`: Domain-level classification rules (Signal 4)
- `data/category_embeddings.npz`: Pre-computed category embeddings for semantic routing (Signal 5)
- `data/imap_folders.json`: Cached IMAP folder structure (refreshed at startup)
