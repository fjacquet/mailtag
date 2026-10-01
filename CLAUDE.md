# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MailTag is a Python-based email automation tool that classifies emails into a 19-category taxonomy and files them into action and category folders. It supports both IMAP and Gmail, tries cheap rules before models, and runs on Apple Silicon via MLX for local inference.

## Development Commands

### Environment Setup

```bash
# Sync dependencies (updates to latest compatible versions)
uv sync -U --all-extras
```

### AI Model Configuration

One AI path: the **MLX local path**, configured in `config.toml [mlx]`. It uses `nomic-ai/nomic-embed-text-v1.5` for embeddings (nomic centroids) and `mlx-community/gemma-4-e4b-it-OptiQ-4bit` for the LLM (Gemma answers by category number). `[mlx] enabled = false` (the Docker image) means rules only: everything the rules do not cover goes to `5-A revoir`. There is no cloud or Ollama path and no `MODEL` variable.

**Laya (feasibility study)**: `[classifier] mode = "laya"` (default `"mlx"`) replaces nomic and Gemma in Pass 3 with the Laya classifier (`src/mailtag/laya_provider.py`, `uv sync --extra laya`; spec `docs/superpowers/specs/2026-10-01-laya-faisabilite-design.md`). A `laya.Router` sends each mail to the `english` or `multilingual` checkpoint (`[laya] routing`), which answers one `choice` question over the 19 categories (English labels from `TAXONOMY_EN` for the English checkpoint). A mail is classified at `answer_confidence ≥ classify_threshold` and counts as an agreement at `≥ learn_threshold`, both per checkpoint in `[laya]` and inert (1.01) until `uv run python scripts/eval_embeddings.py laya` proposes them. `data/laya_neutral_calibration.json` neutralises the English checkpoint's shipped temperatures, which sharpen confidence past 11 options. Zero-shot was measured and rejected (verdict in the spec); the default stays `mlx`.

### Testing

```bash
uv run pytest                                      # Run all tests
uv run pytest --cov --cov-branch --cov-report=xml  # With coverage
uv run pytest tests/test_taxonomy_store.py        # Single file
uv run pytest tests/test_taxonomy_store.py::test_unpromoted_sender_is_not_a_rule  # Single test
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
python src/main.py serve                           # Start webhook API server
python src/main.py serve --host 0.0.0.0 --reload   # Dev mode with auto-reload
```

Taxonomy preparation, migration and bulk review are `scripts/taxonomy_setup.py` subcommands (`scan`, `crosscheck`, `build`, `migrate`, `prune`, `reorganize`, `review-scan`, `refile-review`), described under Taxonomy below. `src/app.py` is a small Streamlit front end for `run` (`scripts/streamlit.sh`).

## Architecture

### Classification flow

`run` (`src/mailtag/utils/tasks.py`) works per account, IMAP or Gmail (`GmailApiService` is an `ImapService`), with a `PendingArchive` and one `TaxonomyStore`:

1. **Pass 1 (rules, headers only)** on the junk folder, then INBOX, in batches of `fast_parse.batch_size`: validated sender → learned sender → validated domain → computed domain. A match is routed to its action folder and recorded in the account's `pending_archive` file.
2. **Pass 3 (models, full body)** for the rest (`classifier.py`): nomic centroids classify at score ≥ `nomic_threshold`; otherwise Gemma must agree with nomic's top choice; otherwise the mail goes to `5-A revoir`. In laya mode, Laya alone decides (see AI Model Configuration). Routing to action folders (`routing.py`, `action_rules.py`) records a `pending_archive` entry per mail.
3. **Archive sweep** (`archive.py`): seen, unflagged mail older than `archive_after_days` moves into its category folder.

`--validate` moves nothing and writes nothing (`Classifier(read_only=True)`).

### Taxonomy

Spec: `docs/superpowers/specs/2026-09-27-taxonomie-19-categories-design.md`.
19 business-sector categories (`src/mailtag/taxonomy.py`) replace the 611 legacy IMAP folders.

- Gemma answers by category number, batched with a cached prompt prefix.
- Category folders follow PARA (`PARA`, `category_folder` in `taxonomy.py`): `Domaines/<category>`, `Ressources/<category>`, `Archive/<category>` (the standard Archive folder); pending entries and rules keep the bare category name. Promos go to the providers' standard `Promotions` folder. `scripts/taxonomy_setup.py reorganize [--apply]` renames flat category folders into PARA and merges `5-Promos`/`9-A revoir` (older names).
- Emails land in action folders (`src/mailtag/action_rules.py`), with their category remembered in `db/pending_archive.json`.
- `src/mailtag/archive.py` moves seen, unflagged emails older than `archive_after_days` into their category and learns sender rules from emails filed out of `5-A revoir`.
- Nomic centroids come from the frozen `data/legacy_folders.json`.

**Learned signals** (`docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md`): old folders map to categories through `map_folder`, overridden by the folder audit (`db/taxonomy/folder_overrides.json`). The rules (validated sender, learned sender, domains) come from `TaxonomyStore` (`db/taxonomy/validated.json`, `senders.json`, `domains.json`); nomic loads `data/taxonomy_centroids.npz`. A nomic/Gemma agreement counts for the sender; after `learn_min_agreements` (2) agreements the sender becomes a rule, and a contradiction removes it. Emails the user files out of `5-A revoir` go to `validated.json`. Preparation (no email is moved): `scripts/taxonomy_setup.py scan`, `crosscheck`, then `streamlit run scripts/taxonomy_review.py`, then `build`. `serve` (webhook API) and `run` can share these files on the same machine: each `TaxonomyStore` records its changes as operations, and `save()` takes an exclusive `flock` on `db/taxonomy/.lock`, replays them on top of what other processes wrote and writes all changed files at once; lookups reload files another process has saved, under a shared lock. `flock` does not cross the Docker Desktop VM boundary: do not run `serve` in Docker (with `db/` mounted) while a `run` works on the Mac. The review page (sidebar: folders, scan senders, senders learned during runs, rule control) lets the user confirm or correct senders promoted during runs; stage 2 only shows senders with at least `sender_min_mails` mails that no validated, learned or domain rule covers; stage 4 measures rule precision on 60 random rule-covered senders (`db/taxonomy/control.json`). Domain rules weigh each sender's validated category, else its audited folder category. `own_addresses` are never a rule and never learned from or validated: every `TaxonomyStore` (the classifier, `taxonomy_setup.py`, the review page) is built with `own_addresses`, and `is_own()` is the one source. Learning is separate from classifying: `Classifier.classify_detailed` returns `(category, agreed)` and learns nothing; `learn` runs only for mails whose move succeeded (`route_to_action_folders` returns the mails that moved), and `/classify` and `/classify-batch` never learn.

**Legacy folder migration** (`docs/superpowers/specs/2026-09-28-migration-dossiers-design.md`, `src/mailtag/migration.py`): `scripts/taxonomy_setup.py migrate` moves each legacy-folder mail to its sender's rule, else its folder's audited category, else `5-A revoir` (with a `db/pending_archive.json` entry so filing it teaches the rule); `prune` deletes emptied legacy folders, deepest first. Both are dry runs unless `--apply`; category, action and system folders are never touched. `migrate --apply` is re-runnable (moved mail leaves its folder). Do not run `run` or `serve` during `migrate --apply`.

**Bulk review of `5-A revoir`** (`docs/superpowers/specs/2026-09-29-revue-en-masse-design.md`, `src/mailtag/review_refile.py`): rather than deciding mail by mail, the owner decides a category per **domain** or per **sender**, then one command refiles every mail a rule now covers. Rule order becomes validated sender → learned sender → **validated domain** → computed domain (`TaxonomyStore.validated_domains`, `db/taxonomy/validated_domains.json`; `set_validated_domain`; `build`'s `replace_rules` never touches it; a non-commercial domain never gets a domain rule, validated or not). `scripts/taxonomy_setup.py review-scan --provider imap|gmail` (read-only) groups `5-A revoir` mail by domain (or by sender for non-commercial domains like gmail.com), skips mail a rule already covers and the owner's own addresses, and writes `data/review_scan_<provider>.json` with a Gemma suggestion per group (resumable: existing suggestions are kept). The review page's stage 5 ("Mails en revue") shows both accounts' scans, covered/total mail counts, and buttons to confirm the suggestion, pick a category, split a domain group into one row per sender ("Par expéditeur", this session only), or skip. `scripts/taxonomy_setup.py refile-review --provider imap|gmail [--apply]` (dry run by default, run by the owner) moves mail a rule now covers to its category folder and drops the matching `pending_archive` entry; mail without a rule stays in `5-A revoir`; blocked while migration is blocked, like `migrate`.

### Provider Architecture

There is no provider base class: both providers are `ImapService` (`src/mailtag/imap_service.py`) objects.

- `ImapService`: IMAP implementation with `connect()` (context manager), `get_email_headers()` (headers only, Pass 1), `get_full_emails()` (bodies, Pass 3), `batch_move_emails()`, `select_folder()`
- `GmailApiService` (`src/mailtag/gmail_api.py`): the Gmail provider (`run --provider gmail`); subclasses `ImapService` and only replaces `connect()`, using `GmailLabelClient` — the same small IMAPClient subset the taxonomy flow uses, translated to Gmail API calls (labels, categories) — see below

### Data and backups

Rule state lives in JSON files, no database class:

- `db/taxonomy/`: `validated.json`, `senders.json`, `domains.json`, `validated_domains.json`, `folder_overrides.json`, `control.json` (managed by `TaxonomyStore`)
- `db/pending_archive.json`, `db/pending_archive_gmail.json`: category of each mail waiting in an action folder, keyed by Message-ID (`PendingArchive`)
- `data/taxonomy_centroids.npz`, `data/legacy_folders.json`, `data/non_commercial_domains.yaml`

All lookups lowercase-normalize sender addresses and domains. **Automatic backups**: `db/taxonomy/*.json` and `db/pending_archive*.json` are copied to `db/backups/` at the start of each `run` (`utils/db_backup.py`), 10 most recent copies per file.

### MLX Provider Architecture

`src/mailtag/mlx_provider.py` provides two classes for Apple Silicon inference:

- **MLXEmbedder** - Generates embeddings via `sentence-transformers` for the nomic centroids (`SemanticRouter`)
- **MLXLLM** - Text generation via `mlx-lm` for Gemma, which answers short prompts in batches (`classify_batch`). Uses `apply_chat_template` with `enable_thinking=False` for Gemma 4 models (prevents thinking tokens from consuming the token budget).

Both use lazy loading — models are only loaded on first use.

### Webhook API

FastAPI-based HTTP API (`src/mailtag/api/`) for external integrations (N8N, webhooks):

- **App factory**: `create_app()` in `src/mailtag/api/__init__.py` — lifespan manages the Classifier lifecycle
- **Routes**: `src/mailtag/api/routes/classify.py` (POST classify, classify-batch, classify-and-move) and `health.py` (GET health, status)
- **Auth**: `X-API-Key` header via `APIKeyMiddleware` — exempts `/health`, `/docs`, `/redoc`, `/openapi.json`
- **Schemas**: Pydantic models in `src/mailtag/api/schemas.py` with Swagger examples
- **State**: `AppState` singleton in `src/mailtag/api/dependencies.py`
- **Config**: `[webhook]` section in `config.toml` — host, port, api_key, allow_move, max_batch_size
- **Swagger UI**: Auto-generated at `/docs`, enriched with OpenAPI tags and schema examples
- **`/classify-and-move`**: selects INBOX, routes the mail to its action folder and records the pending entry, like `run`. `msg_id` must be the mail's **INBOX UID**; `message_id` must be its **Message-ID header**. Without `message_id` the mail is moved but not tracked, so it is never archived or learned from; a retry whose pending entry already exists is not learned from again.
- **Concurrency**: `PendingArchive.save()` takes an exclusive `flock` on `<file>.lock`, reloads the file and replays this instance's adds and removes, so `serve` handlers and a `run` of the same account never overwrite each other's entries (same machine only, like `TaxonomyStore`).

Route handlers use sync `def` (not `async def`) — FastAPI runs them in a thread pool, which is correct since Classifier/Providers are all synchronous.

### Docker Deployment

Multi-stage Docker build for running the API server without Apple Silicon. Rules only: no MLX, no litellm.

- `Dockerfile` — `python:3.13-slim` base, excludes MLX deps via uv overrides, non-root user, healthcheck
- `docker-compose.yml` — Volumes for `db/`, `data/`, `config.toml`; `MLX_ENABLED=false`
- `config.docker.toml` — Container-optimized template with env var placeholders

With `[mlx] enabled = false`, validated and learned senders and domain rules classify; nomic and Gemma are skipped, so everything else goes to `5-A revoir`.

```bash
docker compose build
docker compose up -d
curl http://localhost:8000/health
```

### Configuration System

Two config sources:

- **`config.toml`**: Main config — sections `logging`, `imap`, `gmail`, `fast_parse`, `mlx`, `classifier`, `laya`, `taxonomy`, `webhook`. MLX model defaults live here (single source of truth). Dataclass defaults in `config.py` are fallbacks only.
- **`.env`**: Secrets only — `IMAP_USER`, `IMAP_PASSWORD`, `WEBHOOK_API_KEY`. Gmail needs no `.env` entries, only `credentials_file`/`token_file` (OAuth).

### Gmail through the API

Spec: `docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md`. `run --provider gmail` uses
`GmailApiService` (`src/mailtag/gmail_api.py`), which authenticates via `gmail_auth.get_gmail_service`
(OAuth desktop client `secrets/credentials.json` + saved `secrets/token.json`, scope `gmail.modify`) and runs the same
taxonomy flow as Infomaniak: `GmailLabelClient` translates `select_folder`/`search`/`fetch`/`move`/
`folder_exists`/`create_folder`/`list_folders` into Gmail API calls. Folder ↔ Gmail mapping: `INBOX` →
system label `INBOX` excluding `category:promotions`; junk folder → system label `SPAM`; `Promotions` →
Gmail's own Promotions tab (`CATEGORY_PROMOTIONS`, mail stays in `INBOX`); every other folder (action
folders, `Domaines/…`, `Ressources/…`, `Archive/…`) → a user label of the same name, created on demand.
Moving a mail to `Promotions` adds `CATEGORY_PROMOTIONS`, drops the other `CATEGORY_*` labels and keeps
`INBOX`; moving it elsewhere adds the destination label and removes the source label only — other labels
on the mail (`github`, `TRAVELS`…) are never touched. `db/taxonomy/` rules and centroids are shared
between accounts; `pending_archive_file` and `junk_folder_name` are per account
(Gmail defaults: `db/pending_archive_gmail.json`, `"SPAM"`) so each account's archive sweep never
treats the other's mail as orphaned. Gmail is new-mail only: no `scan`/`migrate`/`prune`, and old Gmail
labels are never touched. While the OAuth app is in "Testing", the token expires after 7 days and the
browser consent flow runs again.

## Key Patterns and Conventions

- Uses `loguru` for structured logging throughout the codebase
- Configuration uses dataclasses for type safety
- Email addresses and domains are normalized to lowercase for all rule lookups
- IMAP folder names are case-sensitive and use forward slash as delimiter
- AI prompts are in French (prompts in `taxonomy.py`)
- Uses context managers (`with` statements) for provider connections
- Batch operations preferred over individual operations for IMAP efficiency

## Testing Notes

- Tests use `pytest` with `pytest-mock` for mocking
- `conftest.py` provides common fixtures
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

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
