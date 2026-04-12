# Changelog

All notable changes to MailTag will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
