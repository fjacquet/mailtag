# Changelog

All notable changes to MailTag will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `scripts/taxonomy_setup.py harvest`: read-only training corpus for the logistic regression from the category folders (mail whose sender's rule matches its folder, at most 20 per sender); `train` prefers it, capped to `[logreg] per_sender`.

### Changed

- `scripts/eval_embeddings.py logreg` groups folds by domain (by sender on personal domains) and compares training corpora.
- `[logreg]` settings from the domain-grouped evaluation: both thresholds at 1.01 (never), because no threshold reaches 85 % precision on unseen domains (top-1 44.4 %, centroids 34.2 %), and `per_sender` stays 10. The harvested corpus gained 2 points of top-1 but classifies no more mail at 85 % than `data/taxonomy_corpus.json` (0 % vs 0 %), so `train` keeps the old corpus. `logreg` mode classifies nothing; the default stays `mlx`.

### Fixed

- `build` no longer overwrites `data/taxonomy_corpus.json` (the verified test set) with a re-read that lost more than half of it, as happens once legacy folders are migrated.

## [2.1.0] - 2026-10-01

Logistic regression for Pass 3, behind a switch: on unknown senders it finds the right category first 51.4 % of the time (nomic centroids: 37.5 %) and classifies 20.3 % of them at 85.4 % precision, in 0.021 s per mail. The default mode stays `mlx`.

### Added

- `[classifier] mode = "logreg"`: a logistic regression over nomic embeddings alone decides Pass 3 (no Gemma, no centroids), with `[logreg]` thresholds; `scripts/taxonomy_setup.py train` (also run by `build`) fits it and `scripts/eval_embeddings.py logreg` measures it on unknown senders and proposes the thresholds. The default mode stays `mlx` (#59).

## [2.0.0] - 2026-10-01

Taxonomy-only release: the 19-category taxonomy is now the only classification mode, and the legacy modes are removed. A 1.x `config.toml` needs the new `[taxonomy]` section and loses its legacy sections.

### Added

- **User guide** (`docs-site/user-guide.md`): folders, daily routine, archiving, teaching MailTag, bulk review, Gmail specifics
- **Taxonomy** (`[taxonomy]`, the only classification mode): 19 business-sector categories replace the 611 IMAP folders; new mail goes to action folders (`1-A traiter` … `5-A revoir`) and is archived into its category after `archive_after_days` (#36)
- **Learned taxonomy rules** in `db/taxonomy/`: validated senders, senders learned after two nomic/Gemma agreements, business domain rules, and 19 nomic centroids built from verified mail (#38)
- **Taxonomy setup** `scripts/taxonomy_setup.py` (`scan`, `crosscheck`, `build`) and the local Streamlit review page `scripts/taxonomy_review.py` (folder audit, sender review, runtime-learned senders, rule control sample) (#38, #39, #40, #41)
- **Owner's addresses** (`own_addresses`) are never a rule and never learned from (#41)
- **Legacy folder migration**: `taxonomy_setup.py migrate` and `prune`, dry run unless `--apply` (#43)
- **PARA folders**: categories live under `Domaines/`, `Ressources/` and the standard `Archive/`; `taxonomy_setup.py reorganize [--apply]` renames existing folders and merges duplicate system folders (`Archives`, `Junk`, `Deleted Messages`, `Sent Messages`) into Infomaniak's (`Archive`, `Spam`, `Trash`, `Sent`); Pass 1 now reads `Spam`
- **Gmail through the API**: `run --provider gmail` (`GmailApiService`) classifies the Gmail inbox through the Gmail API (OAuth) with the same taxonomy flow as Infomaniak; shared `db/taxonomy/` rules, per-account pending archive, junk label and folder cache (#44, #48)
- **Bulk review of `5-A revoir`**: validated domain rules (`db/taxonomy/validated_domains.json`, never replaced by `build`); `taxonomy_setup.py review-scan --provider imap|gmail` groups review mail by domain or sender with a Gemma suggestion; the review page's stage 5 lets the owner decide per domain or per sender; `taxonomy_setup.py refile-review --provider imap|gmail [--apply]` moves the mail a rule now covers to its category, dry run by default
- **Laya feasibility mode** (`[classifier] mode = "laya"`, optional extra `uv sync --extra laya`): the Laya classifier can replace nomic and Gemma in Pass 3, with per-checkpoint thresholds (inert by default) and `scripts/eval_embeddings.py laya` to measure it. Zero-shot was measured and rejected (13-24 % top-1 against 38.5 % for nomic); the default stays `mlx` (#58)
- **Automatic backups** of `db/taxonomy/*.json` and `db/pending_archive*.json` to `db/backups/` at the start of each `run`

### Changed

- Promos go to the providers' standard `Promotions` folder (was `5-Promos`); the review folder is `5-A revoir` (was `9-A revoir`)
- Domain rules weigh each sender's validated category, else its audited folder category; the review page only shows senders no rule covers (#41)
- `nomic_threshold` set to 0.90 in `config.toml` (#42)
- Gmail OAuth files live in the git-ignored `secrets/` directory (`secrets/credentials.json`, `secrets/token.json`)
- AI classification proposals are written to `logs/proposals.log` (was `proposals.log` at the repository root); the old `CLASSIFICATION_IMPROVEMENTS_SPEC.md` moved to `docs/classification-improvements-spec.md`; the unused `old/` files were removed
- Gmail uses the Gmail API (OAuth) instead of IMAP; Gmail's Promotions category is reused (#48); long fetches log their progress and back off on rate limits (#52, #53, #54)
- The webhook API is taxonomy-only: `/classify-and-move` routes the mail to its action folder and records its pending entry like `run`
- The Docker image runs rules only (no MLX, no litellm): what the rules do not cover goes to `5-A revoir`

### Removed

- Legacy classification modes and their modules, scripts and tests: Pass 2, label-based classification, the classification database, the pass-3 manual matching dump, the metrics module, the folder cache
- The cloud/Ollama path (litellm) and the `MODEL` variable; MLX keeps only what the taxonomy chain uses
- Legacy `config.toml` sections and the taxonomy on/off flag; CLI commands other than `run` and `serve`

### Fixed

- Tests no longer write `test.log` at the repository root
- `TaxonomyStore` shared safely between threads and between `serve` and `run` processes (file lock, operation replay) (#39)
- RFC 2047 encoded sender names decoded; `--validate` leaves the databases untouched (#37)
- Senders are learned only from mails whose move succeeded; `/classify` and `/classify-batch` never learn; `own_addresses` handled in one place, the store (#56)
- `PendingArchive` saves lock and replay, so `serve` and `run` never overwrite each other's entries (#56)
- `--validate` skips database backups; an incomplete `[gmail]` section is reported as a config error

## [1.1.1] - 2026-09-13

### Fixed

- **Version drift**: align `pyproject.toml` (and the locked `uv.lock` entry) with the latest published git tag (`v1.1.0`) so wheels/sdists no longer embed a stale `1.0.1` version

## [1.0.1] - 2026-06-03

### Fixed

- **CI test job**: install the `dev` extra (`uv sync -U --extra dev`) so `pytest-cov` is present; previously `pytest --cov` failed with `unrecognized arguments: --cov` (#17)
- **Config validation**: tolerate unsubstituted `${...}` template placeholders in the IMAP email-format check (mirrors existing `api_base` handling), fixing import-time `ValueError: Invalid email format: ${IMAP_USER}` during test collection when `IMAP_USER` is unset (e.g. in CI)

## [0.3.0] - 2026-04-12

### Added

- **Gemma 4 E4B model** as default MLX LLM, replacing Mistral 7B Instruct v0.3 (see ADR-002)
- Thinking mode suppression for Gemma 4 via `enable_thinking=False` in `apply_chat_template`
- Response parsing strips `<|channel>thought...<channel|>` blocks as safety net
- Config loader helper `_dataclass_from_dict()` to eliminate duplicated defaults
- ADR documentation (`docs/ADR-001-mlx-migration.md`, `docs/ADR-002-gemma4-model-switch.md`)
- Product Requirements Document (`docs/PRD.md`)
- **Batch semantic routing** via `route_batch()` for Signal 5 embeddings
- **Batch IMAP moves** accumulated by category in Pass 3
- **Deferred database writes** with dirty-flag pattern and `flush()` for batch I/O
- **Cached LLM prompt prefix** to avoid rebuilding ~600-900 token category list per call
- **Pass 1→2 header forwarding** to eliminate duplicate IMAP fetch
- **Folder existence caching** in IMAP `batch_move_emails`
- **psutil.Process throttling** (5s interval) for memory metrics
- **Buffered proposal writes** with `flush_proposals()`
- KV cache quantization (`kv_bits=8`) with graceful fallback for unsupported models

### Changed

- Default MLX LLM model: `mlx-community/Mistral-7B-Instruct-v0.3-4bit` → `mlx-community/gemma-4-e4b-it-OptiQ-4bit`
- `llm_max_tokens` reduced from 256 → 128 (JSON classification responses are <80 tokens)
- `FastParseConfig` fields now all have defaults (no required fields), enabling dict unpacking in loader
- Config TOML loader uses `_dataclass_from_dict()` instead of manual `.get()` calls with duplicated defaults
- `config.toml` is now the single source of truth for model names (dataclass defaults are fallbacks only)
- Python target upgraded to 3.13 (requires-python >= 3.13)
- Updated all dependencies via `uv sync -U`
- CLAUDE.md rewritten: corrected signal count (5→6), added MLX Provider section, trimmed stale content
- `classifier.min_count` default reduced from 10 → 5 for faster historical DB matches
- `fast_parse.batch_size` increased from 100 → 500 for larger IMAP batches
- All database mutation methods now use `threading.RLock` for thread safety
- Tests migrated from `unittest.mock` to `pytest-mock` (`mocker` fixture)

### Fixed

- Gemma 4 thinking mode consuming entire token budget before producing JSON output
- JSON regex in `classify()` now handles nested braces correctly
- Broken f-strings in `tasks.py` log messages (Pass 2 count, Top senders)
- `restore_database()` argument order in error recovery tests
- Gmail classification path now flushes proposals and database on completion
- KV cache quantization fallback catches `NotImplementedError` for unsupported model architectures

## [0.2.0] - 2026-01-10

### Added

- **Thread safety** for concurrent email processing (classifier, metrics, IMAP daemon)
- Thread-safe lazy initialization for MLX components with RLock
- Thread-safe AI cache with concurrent read/write protection
- Thread-safe metrics collection with deep copy pattern for consistent reads
- Graceful IMAP daemon thread lifecycle with Event-based shutdown
- Comprehensive integration tests for 3-pass classification workflow
- Error recovery tests for database corruption, network failures, and AI fallback
- Retry logic tests achieving 100% coverage of retry decorator
- Security documentation (`docs/SECURITY.md`) covering authentication, data security, and best practices
- Shared email parsing utilities (`src/mailtag/utils/email_parsing.py`) to eliminate code duplication
- Configuration validation on startup (email format, password, API URLs, thresholds)
- `get_sender_classifications()` public method in `ClassificationDatabase` for proper encapsulation
- **mypy type checking** configured with comprehensive type safety rules

### Changed

- **BREAKING**: Removed insecure fallback configuration - application now fails fast on invalid config
- Retry decorator uses explicit parameters instead of fragile introspection
- Email parsing consolidated from IMAP and Gmail services into shared utility module
- Improved type hints across codebase (config.py, retry.py, imap_service.py, gmail_service.py)
- Configuration validation moved to dedicated `_validate_config()` function
- Application exits with clear error messages on configuration failures

### Fixed

- Linting issues in config.py, gmail_service.py, and test files
- Encapsulation violations where code directly accessed `database.suggestion_db`
- Dependency injection in retry decorator (removed args[0] introspection)
- Duplicate import of `base64` in gmail_service.py
- Mock configuration in test_classification_metrics.py for `get_sender_classifications`

### Security

- **CRITICAL**: Removed fallback config that created insecure default credentials
- Added validation to reject empty passwords and invalid email formats
- Added URL format validation for API endpoints
- Configuration now fails immediately rather than silently using insecure defaults
- Comprehensive security documentation with best practices and recommendations

## [0.1.0] - Initial Release

- 6-signal classification strategy (AMSC): validated DB → server labels → historical DB → domain rules → semantic router → MLX LLM
- Three-pass IMAP processing (headers → domain → AI)
- AI confidence scoring with JSON responses and configurable thresholds
- MLX on-device inference for Apple Silicon (embeddings + LLM)
- Comprehensive metrics tracking (signal hit rates, category distribution, processing times)
- Domain analysis tools for database expansion
- Automatic database backups with rotation (10 most recent)
- Data management CLI (cleanup, consolidation, stats, pruning)
- Gmail OAuth and IMAP authentication
- Dynamic folder-based classification with live IMAP structure
- Email filter generation for server-side rules

---

For detailed changes, see the [commit history](https://github.com/fjacquet/mailtag/commits/main).
