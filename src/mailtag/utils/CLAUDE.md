# src/mailtag/utils/

Utility modules for domain handling, text processing, backups and run orchestration.

## Modules

### domain_utils.py

Domain extraction and non-commercial domain lookup, with caching.

**Key Functions:**

- `extract_domain(email)` - Extract domain from email address
- `normalize_domain(domain)` - Lowercase and clean domain
- `load_non_commercial_domains()` - Load from `data/non_commercial_domains.yaml`
- `is_non_commercial_domain_cached(domain)` - Cached check (gmail.com, yahoo.com, etc. never get a domain rule)

**Caching:**

- Uses module-level `_non_commercial_cache` set
- `_cache_loaded` flag prevents redundant file reads

### text_utils.py

Email body processing.

**Key Functions:**

- `smart_truncate(text, max_chars)` - Intelligent truncation preserving keywords
- `_remove_signatures(text)` - Strip email signatures

### email_parsing.py

Shared parsing for IMAP and Gmail: `parse_sender()`, `decode_payload()`, `extract_body_from_message()`.

### tasks.py

Orchestration of one `run` for one account (IMAP or Gmail).

**Key Functions:**

- `run_classification(provider, validate)` - Main orchestrator
- `_run_fast_parse_on_folder(...)` - Pass 1: rules on headers only; routes matches, returns the UIDs left
- `pending_archive_path(config, default)` - each account keeps its own pending archive file
- `junk_folder(provider)` - the account's junk folder name

**Flow:**

1. Pass 1 applies the `TaxonomyStore` rules to headers of the junk folder, then INBOX
2. Pass 3 fetches full bodies of the rest; `Classifier` uses nomic, then nomic/Gemma agreement, else `5-A revoir`
3. `run_archive` sweeps the action folders

### db_backup.py

Timestamped backups with automatic rotation.

**Key Functions:**

- `backup_database(db_path, backup_dir)` - Create timestamped backup
- `backup_all_databases(db_dir, backup_dir)` - Back up `db/taxonomy/*.json` and `db/pending_archive*.json` into `db/backups/`
- `cleanup_old_backups(backup_dir, keep_count=10)` - Keep the 10 most recent per file

Run at the start of each `run`.
