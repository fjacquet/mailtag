# MailTag Code Style and Conventions

## Python Version
- Target: Python 3.12+
- Uses modern features: type hints, union types with `|`, match statements

## Code Formatting (Ruff)
- **Line length**: 110 characters
- **Indent**: 4 spaces
- **Quotes**: Double quotes for strings
- **Import order**: isort-compatible

## Linter Rules
- pycodestyle (E)
- Pyflakes (F)
- flake8-bugbear (B)
- isort (I)
- pyupgrade (UP)

## Naming Conventions
- Underscore-prefixed variables allowed for intentionally unused: `_unused_var`
- Email addresses and domains normalized to lowercase for database operations
- IMAP folder names are case-sensitive, use forward slash delimiter

## Type Hints
- Use modern union syntax: `str | None` instead of `Optional[str]`
- Pydantic models for data validation (see `src/mailtag/models.py`)
- Dataclasses for configuration types

## Logging
- Use `loguru` for all logging
- Structured logging throughout
- Log levels configured in `config.toml`

## Error Handling
- Context managers (`with` statements) for provider connections
- Retry logic with exponential backoff for transient failures
- Custom retry utilities in `src/mailtag/retry.py`

## Design Patterns
- **Provider pattern**: Abstract base class in `providers.py`, implementations in `imap_service.py` and `gmail_service.py`
- **Batch operations**: Preferred over individual operations for IMAP efficiency
- **Configuration**: Environment variable substitution in TOML config

## Language
- AI prompts are in French (in `classifier.py`)
- Code and comments in English

## Documentation
- Don't add docstrings, comments, or type annotations to code you didn't change
- Only add comments where the logic isn't self-evident
