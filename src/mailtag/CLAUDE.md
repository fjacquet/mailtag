# src/mailtag/

Core package for email classification and organization.

## Key Modules

### Classification Engine

- **classifier.py** - `Classifier` class implementing AMSC (Adaptive Multi-Signal Classification)
  - `classify_email()` - Main entry point, tries 5 signals in priority order
  - `_get_category_from_validated_db()` - Signal 1: Validated mappings (100% confidence)
  - `_get_category_from_labels()` - Signal 2: Server-side labels (95%)
  - `_get_category_from_history()` - Signal 3: Historical patterns (90%+)
  - `_get_category_from_domain()` - Signal 4: Domain rules (90%)
  - `_get_category_from_ai()` - Signal 5: AI fallback with JSON confidence scoring
  - `export_metrics()` / `log_metrics_summary()` - Classification analytics

### Database Layer

- **database.py** - `ClassificationDatabase` class managing 3 JSON databases
  - `update_suggestion()` - Record AI suggestions
  - `promote_to_validated()` - Move to validated DB
  - `get_category_by_domain()` / `store_domain_classification()` - Domain rules
  - All lookups use lowercase-normalized emails/domains

### Email Providers

- **providers.py** - `EmailProvider` abstract base class
  - `connect()` - Context manager for connection lifecycle
  - `get_emails()` - Fetch emails with filters
  - `move_email()` - Move single email

- **imap_service.py** - `ImapService` implementation
  - `get_email_headers()` - Headers-only fetch for Pass 1
  - `get_full_emails()` - Full body fetch for Pass 3
  - `batch_move_emails()` - Efficient bulk operations
  - `get_folder_hierarchy()` - Cached folder structure

- **gmail_service.py** - `GmailService` implementation
  - OAuth-based authentication
  - Label management via Gmail API

### Supporting Modules

- **config.py** - Configuration dataclasses with env var substitution
- **models.py** - `Email` Pydantic model
- **metrics.py** - Performance metrics collection
- **retry.py** - Exponential backoff retry logic
- **folder_analyzer.py** - IMAP folder hierarchy analysis
- **filter_generator.py** - Email filter rule generation
- **gmail_auth.py** - OAuth flow for Gmail

## Design Patterns

- Provider pattern for email backends
- Context managers for connections
- Batch operations over individual calls
- Lowercase normalization for all lookups
