# tests/

Test suite using pytest with mocking support.

## Test Organization

### Core Module Tests
- **test_classifier.py** - Classification engine tests
- **test_database.py** - JSON database operations
- **test_config.py** - Configuration loading and validation
- **test_main.py** - CLI entry point tests

### Provider Tests
- **test_imap_service.py** - IMAP operations with mock client
- **test_gmail_service.py** - Gmail API operations
- **test_gmail_auth.py** - OAuth flow testing
- **test_missing_google_deps.py** - Graceful handling when Gmail deps missing

### Utility Tests
- **test_text_utils.py** - Text processing functions
- **test_domain_analyzer.py** - Domain analysis utilities
- **test_filter_generator.py** - Email filter generation

### Feature Tests
- **test_ai_confidence.py** - AI confidence scoring
- **test_classification_metrics.py** - Metrics collection
- **test_logging_config.py** - Logging setup

## Test Helpers
- **conftest.py** - Shared pytest fixtures
- **mock_imap_client.py** - IMAP client mock implementation
- **mock_gmail_service.py** - Gmail service mock

## Running Tests

```bash
# All tests with coverage
uv run pytest --cov --cov-branch --cov-report=xml

# Fast run without coverage
uv run pytest

# Specific file
uv run pytest tests/test_classifier.py

# Specific test
uv run pytest tests/test_classifier.py::test_function_name

# Verbose output
uv run pytest -v
```

## Key Libraries
- `pytest` - Test framework
- `pytest-mock` - Mocking support
- `pytest-cov` - Coverage reporting
- `faker` - Mock data generation

## Conventions
- Use fixtures from `conftest.py` for common setup
- Mock external services (IMAP, Gmail API, AI calls)
- Test edge cases and error conditions
- CI runs on Python 3.10 minimum
