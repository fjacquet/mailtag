# tests/

Test suite using pytest with mocking support.

## Test Organization

### Classification and rules

- **test_classifier_taxonomy.py** - rules, nomic threshold, nomic/Gemma agreement, review
- **test_taxonomy.py**, **test_taxonomy_store.py**, **test_taxonomy_build.py** - categories, rule store (locking, learning), build
- **test_semantic_router.py**, **test_mlx_provider.py** - nomic centroids, embedder and LLM wrappers
- **test_action_rules.py**, **test_routing.py**, **test_pending_archive.py**, **test_archive.py** - action folders, routing, pending archive, sweep
- **test_run_classification.py** - end-to-end `run_classification`, IMAP mocked (also `--validate` read-only)
- **test_tasks_accounts.py** - per-account pending archive and junk folder

### Preparation and maintenance

- **test_taxonomy_setup.py**, **test_mailbox_scan.py**, **test_sender_crosscheck.py** - `taxonomy_setup.py` subcommands and helpers
- **test_migration.py** - legacy folder migration, prune, PARA reorganize
- **test_review_refile.py** - bulk review of `5-A revoir`
- **test_eval_embeddings.py** - `scripts/eval_embeddings.py`

### Providers and API

- **test_imap_service.py** - IMAP operations with mock client
- **test_gmail_api.py** - `GmailApiService` and `GmailLabelClient`
- **test_gmail_auth.py**, **test_missing_google_deps.py** - OAuth flow, graceful handling when Gmail deps are missing
- **test_webhook_api.py** - FastAPI routes

### Core and utilities

- **test_config.py** - configuration loading and validation
- **test_main.py** - CLI entry point
- **test_text_utils.py**, **test_non_commercial_domains.py** - text and domain helpers
- **test_db_backup.py**, **test_retry_logic.py**, **test_logging_config.py**

`integration/` is an empty package.

## Test Helpers

- **conftest.py** - Shared pytest fixtures
- **mock_imap_client.py** - IMAP client mock implementation

## Running Tests

```bash
# All tests with coverage
uv run pytest --cov --cov-branch --cov-report=xml

# Fast run without coverage
uv run pytest

# Specific file
uv run pytest tests/test_classifier_taxonomy.py

# Specific test
uv run pytest tests/test_classifier_taxonomy.py::test_function_name

# Verbose output
uv run pytest -v
```

## Key Libraries

- `pytest` - Test framework
- `pytest-mock` - Mocking support
- `pytest-cov` - Coverage reporting

## Conventions

- Use fixtures from `conftest.py` for common setup
- Mock external services (IMAP, Gmail API, MLX models)
- Test edge cases and error conditions
- CI runs on Python 3.13
