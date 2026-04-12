# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MailTag is a Python-based email automation tool that classifies and organizes emails using AI. It supports both IMAP and Gmail, using a 6-signal classification strategy that prioritizes efficiency and accuracy. Runs on Apple Silicon via MLX for local inference.

## Development Commands

### Environment Setup

```bash
# Sync dependencies (updates to latest compatible versions)
uv sync -U --all-extras
```

### AI Model Configuration

Two AI paths coexist — the **MLX local path** (Signals 5+6, configured in `config.toml [mlx]`) and the **cloud/Ollama path** (configured via `.env`):

- **MLX (default for classification)**: Embedding model + LLM set in `config.toml` under `[mlx]`. Currently uses `nomic-ai/nomic-embed-text-v1.5` for embeddings and `mlx-community/gemma-4-e4b-it-OptiQ-4bit` for LLM fallback.
- **Cloud/Ollama**: Set `MODEL` in `.env` (e.g., `gemini/gemini-2.5-flash`, `ollama_chat/gemma3n`). Used for the litellm-based classification path.

### Testing

```bash
uv run pytest                                      # Run all tests
uv run pytest --cov --cov-branch --cov-report=xml  # With coverage
uv run pytest tests/test_database.py               # Single file
uv run pytest tests/test_database.py::test_func    # Single test
```

### Linting and Formatting

```bash
uv run ruff check . --fix   # Lint + auto-fix
uv run ruff format .        # Auto-format
uv run yamllint .           # Check YAML
uv run yamlfix .            # Fix YAML
```

### Running the Application

```bash
python src/main.py run --provider all              # Classify all providers
python src/main.py run --provider imap --validate  # Read-only validation mode
python src/main.py filters                         # Generate email filters
python src/main.py analyze-domains --output data/domain_candidates.json
python src/main.py db-stats                        # Database health check
python src/main.py cleanup --consolidate           # Remove old pass3 files
```

## Architecture

### Multi-Signal Classification Strategy (AMSC)

The core classification engine (`src/mailtag/classifier.py`) uses a hierarchical approach with 6 signals, evaluated in priority order:

1. **Validated Database** - Manually validated sender classifications (100% confidence)
2. **Server-Side Labels** - Existing IMAP folders or Gmail labels matching known categories (95%)
3. **Historical Database** - Sender history with high-confidence patterns (90%+, 10+ occurrences)
4. **Domain Classification** - Commercial domain-based rules (90%, skips gmail.com/yahoo.com etc.)
5. **Semantic Router** - MLX embedding-based classification via `nomic-embed-text-v1.5` (configurable score threshold)
6. **MLX LLM** - Fallback to local LLM (currently Gemma 4 E4B) returning JSON with `{category, confidence, reason}`. Below-threshold classifications (0.85) route to "À Classer"

Each signal can definitively classify an email, stopping further evaluation.

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

**Automatic Backups**: Databases are backed up to `db/backups/` once at the start of each classification run. Keeps 10 most recent backups per database.

### MLX Provider Architecture

`src/mailtag/mlx_provider.py` provides two classes for Apple Silicon inference:

- **MLXEmbedder** - Generates embeddings via `sentence-transformers` for the Semantic Router (Signal 5)
- **MLXLLM** - Text generation via `mlx-lm` for classification fallback (Signal 6). Uses `apply_chat_template` with `enable_thinking=False` for Gemma 4 models (prevents thinking tokens from consuming the token budget). Response parsing strips any residual `<|channel>thought...<channel|>` blocks before extracting JSON.

Both use lazy loading — models are only loaded on first use.

### Configuration System

Two config sources:

- **`config.toml`**: Main config — `general`, `classifier`, `imap`, `gmail`, `fast_parse`, `mlx`, `logging` sections. MLX model defaults live here (single source of truth). Dataclass defaults in `config.py` are fallbacks only.
- **`.env`**: Secrets and cloud AI provider selection (`IMAP_USER`, `IMAP_PASSWORD`, `MODEL`, `GEMINI_API_KEY`, etc.)

### Dynamic vs Static Classification

Controlled by `general.use_imap_folders_for_classification`:

- **Dynamic Mode (default)**: Uses live IMAP folder structure from `data/imap_folders.json` as categories. Refreshed at startup.
- **Static Mode**: Uses fixed categories from `data/classification_schema.yml` (legacy).

### Metrics

Classification metrics are automatically tracked per signal (hit rates, confidence scores, processing times, errors). Export via `classifier.export_metrics(Path("data/metrics"))` or log with `classifier.log_metrics_summary("INFO")`.

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
- Mock email data generated using `faker` library
- Coverage configured in `pyproject.toml` via `addopts`

## Code Style

- Line length: 110 characters (configured in ruff)
- Target: Python 3.13 (requires-python >= 3.13)
- Uses modern Python features: type hints, union types with `|`, match statements
- Ruff linter rules: pycodestyle, Pyflakes, flake8-bugbear, isort, pyupgrade
- Underscore-prefixed variables allowed for intentionally unused variables

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (90-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk vitest run          # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->