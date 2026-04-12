# MailTag

MailTag is a Python-based email automation tool that classifies and organizes emails using on-device AI. It supports both IMAP and Gmail, using a 6-signal classification strategy with MLX-powered local inference on Apple Silicon.

[![CI Tests and Checks](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml)

## How It Works

MailTag classifies emails through 6 prioritized signals:

1. **Validated Database** — manually confirmed sender→category mappings (100% confidence)
2. **Server-Side Labels** — existing IMAP folders or Gmail labels (95%)
3. **Historical Database** — sender history patterns (90%+)
4. **Domain Classification** — commercial domain rules (90%)
5. **Semantic Router** — MLX embedding similarity via `nomic-embed-text-v1.5` (configurable threshold)
6. **MLX LLM** — local Gemma 4 E4B model returning JSON `{category, confidence, reason}` (0.85 threshold)

Each signal stops evaluation when it classifies an email. IMAP uses a 3-pass system (headers → domains → full body + AI) for efficiency.

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

Requires OAuth credentials from the [Google Cloud Console](https://console.cloud.google.com/) — enable Gmail API, create OAuth Desktop credentials, save as `credentials.json`. See `config.toml` `[gmail]` section.

## Usage

```bash
python src/main.py run --provider all              # Classify all providers
python src/main.py run --provider imap             # IMAP only
python src/main.py run --provider imap --validate  # Read-only (no moves)
python src/main.py filters                         # Generate email filters
python src/main.py analyze-domains                 # Find domain candidates
python src/main.py db-stats                        # Database health check
python src/main.py cleanup --consolidate           # Remove old pass3 files
```

## Data and Database

- `db/validated_classification_db.json`: Manually validated sender→category mappings (Signal 1)
- `db/sender_classification_db.json`: AI suggestions and historical patterns (Signal 3)
- `db/domain_classifications.json`: Domain-level classification rules (Signal 4)
- `data/category_embeddings.npz`: Pre-computed category embeddings for semantic routing (Signal 5)
- `data/imap_folders.json`: Cached IMAP folder structure (refreshed at startup)
