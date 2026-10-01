# MailTag

MailTag is a Python-based email automation tool that classifies and organizes emails into a 19-category business taxonomy using on-device AI. It supports both IMAP and Gmail, with MLX-powered local inference on Apple Silicon.

[![CI Tests and Checks](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/fjacquet/mailtag)](https://github.com/fjacquet/mailtag/releases)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![codecov](https://codecov.io/gh/fjacquet/mailtag/branch/main/graph/badge.svg)](https://codecov.io/gh/fjacquet/mailtag)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://fjacquet.github.io/mailtag/)

## How It Works

MailTag files mail into **19 business-sector categories** (Banque & Placements, Santé, Achats, Éditeurs IT & Cloud, Contacts…) instead of hundreds of IMAP folders. New mail first lands in an action folder (`1-A traiter`, `2-A payer`, `3-A lire`, `4-Pour info`, the provider's standard `Promotions`, or `5-A revoir` when unsure) and moves into its category once read and a week old. Category folders follow PARA: `Domaines/` (areas: bank, health, family…), `Ressources/` (topics: newsletters, IT vendors, media…) and the standard `Archive/` (purchases, parcels); projects are your own folders.

The classification chain, first match wins:

1. **Validated sender** — a sender you confirmed
2. **Learned sender** — a sender that became a rule after two nomic/Gemma agreements
3. **Validated domain**, then **computed domain** — commercial domain rules (never for gmail.com and the like)
4. **Nomic centroids** — MLX embeddings with `nomic-embed-text-v1.5`, accepted at a score of at least `nomic_threshold`
5. **Nomic and Gemma agreeing** — local Gemma 4 E4B answers by category number and must agree with nomic's top choice
6. **`5-A revoir`** — anything else

IMAP runs in two steps: rules on message headers first (junk folder and INBOX), then the models on the full body of the rest (Pass 3, nomic + Gemma, is currently at rest with `[mlx] enabled = false`: the rules classify and everything else goes to `5-A revoir`). Filing a mail out of `5-A revoir` teaches MailTag its sender. The rules were learned from the legacy folders with `scripts/taxonomy_setup.py` and a local Streamlit review page; see the [usage docs](https://fjacquet.github.io/mailtag/getting-started/usage/). Day-to-day use (folders, archiving, teaching MailTag, Gmail) is in the [user guide](https://fjacquet.github.io/mailtag/user-guide/).

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

- **`config.toml`** — main config (`logging`, `imap`, `gmail`, `fast_parse`, `mlx`, `taxonomy`, `webhook`)
- **`.env`** — secrets only (`IMAP_USER`, `IMAP_PASSWORD`, `WEBHOOK_API_KEY`)

### Required `.env` variables

```bash
IMAP_USER=your-email@example.com
IMAP_PASSWORD=your-password
# Only for `serve`: WEBHOOK_API_KEY=your-key
```

### MLX Models (config.toml)

```toml
[mlx]
enabled = true
embedding_model = "nomic-ai/nomic-embed-text-v1.5"    # nomic centroids
llm_model = "mlx-community/gemma-4-e4b-it-OptiQ-4bit" # Gemma second opinion
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
python src/main.py serve                           # Webhook API server
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

- `db/taxonomy/`: validated, learned and domain rules (`validated.json`, `senders.json`, `domains.json`, `validated_domains.json`, `folder_overrides.json`, `control.json`)
- `db/pending_archive*.json`: category of each mail waiting in an action folder (one file per account)
- `db/backups/`: copies of both, taken at the start of each `run` (10 per file)
- `data/taxonomy_centroids.npz`: nomic centroids per category
- `data/legacy_folders.json`: frozen list of the legacy folders (migration, centroids)
- `data/non_commercial_domains.yaml`: domains that never get a domain rule

## Docker

The Docker image runs the webhook API with rules only (no MLX): validated and learned senders and domain rules classify; everything else goes to `5-A revoir`. Do not run `serve` in Docker (with `db/` mounted) while a `run` works on the Mac: `flock` does not cross the Docker Desktop VM boundary.
