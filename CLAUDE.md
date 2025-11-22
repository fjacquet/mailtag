# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MailTag is a Python-based email automation tool that classifies and organizes emails using AI. It supports both IMAP and Gmail, using a multi-signal classification strategy that prioritizes efficiency and accuracy.

## Development Commands

### Environment Setup
```bash
# Install dependencies (includes dev tools)
uv pip install -e ".[dev]"

# Install with Gmail support
uv pip install -e ".[gmail]"

# Sync dependencies (updates to latest compatible versions)
uv sync -U

# Start Ollama with optimized settings (required for AI classification)
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q4_0 OLLAMA_NUM_CTX=8192 ollama serve
```

**Ollama Configuration:**
- `OLLAMA_FLASH_ATTENTION=1`: Enables flash attention for faster inference
- `OLLAMA_KV_CACHE_TYPE=q4_0`: Uses 4-bit quantized KV cache to reduce memory usage
- `OLLAMA_NUM_CTX=8192`: Sets default context window to 8192 tokens (prevents prompt truncation with large category lists)
- These settings improve performance and reduce memory footprint for email classification

### Testing
```bash
# Run all tests with coverage
uv run pytest --cov --cov-branch --cov-report=xml

# Run tests without coverage (faster for development)
uv run pytest

# Run specific test file
uv run pytest tests/test_database.py

# Run specific test function
uv run pytest tests/test_database.py::test_function_name
```

### Linting and Formatting
```bash
# Check code with ruff linter
uv run ruff check .

# Auto-fix linting issues
uv run ruff check . --fix

# Check formatting
uv run ruff format --check .

# Auto-format code
uv run ruff format .

# Check YAML files
uv run yamllint .

# Auto-fix YAML files
uv run yamlfix .
```

### Running the Application
```bash
# CLI entry point - run classification on all providers
python src/main.py run --provider all

# Run on specific provider
python src/main.py run --provider imap
python src/main.py run --provider gmail

# Validation mode (read-only, no email moves)
python src/main.py run --provider all --validate

# Generate email filters
python src/main.py filters

# Analyze Pass 3 files to find domain candidates (NEW)
python src/main.py analyze-domains --output data/domain_candidates.json --min-emails 5 --top 50

# Update domain database from reviewed candidates (NEW)
python scripts/update_domain_db.py

# Streamlit UI (alternative interface)
streamlit run src/streamlit_app.py

# FastAPI webhook server
python src/webhook.py
```

## Architecture

### Multi-Signal Classification Strategy (AMSC)

The core classification engine (`src/mailtag/classifier.py`) uses a hierarchical approach with 5 signals, evaluated in priority order:

1. **Validated Database** - Manually validated sender classifications (highest confidence, 100%)
2. **Server-Side Labels** - Existing IMAP folders or Gmail labels that match known categories (95% confidence)
3. **Historical Database** - High-confidence classifications based on sender history (90%+ confidence, 10+ occurrences by default)
4. **Domain Classification** - Commercial domain-based rules (90% confidence, skips non-commercial domains like gmail.com, yahoo.com)
5. **AI Model** - Fallback to Ollama LLM via litellm with confidence scoring (configurable threshold: 0.85)

Each signal can definitively classify an email, stopping further evaluation. Only unclassified emails proceed to the next signal.

**Recent Improvements (2025-11-22)**:
- **AI Confidence Scoring**: AI now returns JSON with category, confidence (0-1.0), and reasoning. Classifications below threshold (0.85) route to "À Classer"
- **Classification Metrics**: Comprehensive tracking of signal hit rates, category distribution, confidence scores, and processing times
- **Smart Text Processing**: Email bodies intelligently truncated from 500→1500 chars with signature removal and keyword preservation
- **Domain Analysis Tools**: New `analyze-domains` command to identify commercial domains from Pass 3 files for database expansion

### Three-Pass Processing System (IMAP Only)

For IMAP providers, the classification runs in three passes for performance optimization (`src/mailtag/utils/tasks.py`):

- **Pass 1 (Fast Parse)**: Processes emails using only headers (sender, subject). Uses validated and historical databases for instant classification. Processes emails in configurable batches (default 100).
- **Pass 2 (Domain Classification)**: Groups remaining emails by commercial domain and applies domain-based rules in bulk. Generates manual matching files in `data/pass3_manual_matching_*.json` for review.
- **Pass 3 (AI Classification)**: Fetches full email bodies and uses AI classification for remaining emails.

Gmail providers use single-pass processing with the full AMSC strategy.

### Provider Architecture

The codebase uses a provider pattern (`src/mailtag/providers.py`):

- `EmailProvider`: Abstract base class defining the interface
- `ImapService` (`src/mailtag/imap_service.py`): IMAP implementation with batch operations and folder hierarchy support
- `GmailService` (`src/mailtag/gmail_service.py`): Gmail API implementation with OAuth authentication

All providers implement:
- `connect()`: Context manager for connection lifecycle
- `get_emails()`: Fetch emails with optional filters
- `move_email()`: Move single email to destination folder/label

IMAP additionally supports:
- `batch_move_emails()`: Efficient bulk move operations
- `get_email_headers()`: Fetch headers without full body
- `get_folder_hierarchy()`: Retrieve and cache folder structure

### Database Layer

Three JSON databases managed by `ClassificationDatabase` (`src/mailtag/database.py`):

- `db/sender_classification_db.json`: AI suggestions and historical patterns per sender
- `db/validated_classification_db.json`: Manually validated sender-category mappings
- `db/domain_classifications.json`: Domain-level classification rules

All databases use lowercase normalization for sender addresses and domains to ensure consistent lookups.

### Configuration System

Configuration loaded from `config.toml` with environment variable substitution:

- `general`: Ollama model, API base URL, folder classification mode
- `classifier`: Confidence thresholds and minimum counts
- `imap`: Server settings (supports `${IMAP_USER}`, `${IMAP_PASSWORD}` env vars)
- `gmail`: OAuth credentials paths
- `fast_parse`: Batch sizes, retry configuration, metrics settings
- `logging`: Level and file path

Create a `.env` file for local development with:
```
IMAP_USER=your-email@example.com
IMAP_PASSWORD=your-password
OLLAMA_API_URL=http://localhost:11434
```

### Dynamic vs Static Classification

Two modes controlled by `general.use_imap_folders_for_classification`:

- **Dynamic Mode (default)**: Uses live IMAP folder structure from `data/imap_folders.json` as classification categories. AI can suggest new subfolders under existing parents. Folder structure is refreshed at startup.
- **Static Mode**: Uses fixed categories from `data/classification_schema.yml` (legacy YAML-based schema).

### Email Model

Pydantic model at `src/mailtag/models.py`:
```python
class Email(BaseModel):
    msg_id: str               # Unique identifier
    sender_address: str       # Email address
    sender_name: str          # Display name
    subject: str              # Subject line
    body: str                 # Full email body
    labels: list[str]         # Existing server-side labels/folders
```

### Utilities

- `src/mailtag/utils/domain_utils.py`: Domain extraction, normalization, and non-commercial domain detection with caching
- `src/mailtag/utils/domain_analyzer.py`: **NEW** - Analyze Pass 3 files to identify commercial domain candidates for classification DB
- `src/mailtag/utils/text_utils.py`: **NEW** - Intelligent email body processing (smart truncation, signature removal, keyword extraction)
- `src/mailtag/retry.py`: Retry logic with exponential backoff for transient failures
- `src/mailtag/metrics.py`: Performance metrics collection and reporting (extended with classification quality metrics)
- `src/mailtag/folder_analyzer.py`: IMAP folder hierarchy analysis and category extraction

### Classification Metrics (NEW)

After running classification, the system now tracks:
- **Signal Hit Rates**: Percentage of emails classified by each signal (validated_db, server_labels, historical_db, domain_db, ai_model)
- **Category Distribution**: Top 10 most-used categories
- **Confidence Scores**: Average, min, max confidence per signal
- **Processing Times**: Average time per signal in milliseconds
- **Error Tracking**: AI uncertainties, model errors, and other issues

Export metrics with:
```python
from mailtag.classifier import Classifier
classifier.export_metrics(Path("data/metrics"))  # Exports to JSON
classifier.log_metrics_summary("INFO")  # Logs formatted summary
```

Metrics are automatically tracked during classification and can be reviewed to:
- Identify which signals are most effective
- Detect classification bottlenecks
- Monitor AI model performance
- Track category usage patterns

## Key Patterns and Conventions

- Uses `loguru` for structured logging throughout the codebase
- Configuration uses dataclasses for type safety
- Email addresses and domains are normalized to lowercase for all database operations
- IMAP folder names are case-sensitive and use forward slash as delimiter
- AI prompts are in French (prompts in `classifier.py`)
- Uses context managers (`with` statements) for provider connections
- Batch operations preferred over individual operations for IMAP efficiency

## Testing Notes

- Tests use `pytest` with `pytest-mock` for mocking
- `conftest.py` provides common fixtures
- `tests/test_missing_google_deps.py` validates graceful handling when Gmail dependencies are missing
- Mock email data generated using `faker` library
- CI runs on Python 3.10 (minimum) but project requires Python 3.12+ locally

## Code Style

- Line length: 110 characters (configured in ruff)
- Target: Python 3.12
- Uses modern Python features: type hints, union types with `|`, match statements
- Ruff linter rules: pycodestyle, Pyflakes, flake8-bugbear, isort, pyupgrade
- Underscore-prefixed variables allowed for intentionally unused variables
