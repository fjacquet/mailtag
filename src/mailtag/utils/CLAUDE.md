# src/mailtag/utils/

Utility modules for domain handling, text processing, and task orchestration.

## Modules

### domain_utils.py
Domain extraction and validation utilities with caching.

**Key Functions:**
- `extract_domain(email)` - Extract domain from email address
- `normalize_domain(domain)` - Lowercase and clean domain
- `is_valid_domain(domain)` - Validate domain format
- `is_non_commercial_domain(domain)` - Check if gmail.com, yahoo.com, etc.
- `is_non_commercial_domain_cached(domain)` - Cached version for performance
- `load_non_commercial_domains()` - Load from `data/non_commercial_domains.txt`

**Caching:**
- Uses module-level `_non_commercial_cache` set
- `_cache_loaded` flag prevents redundant file reads

### text_utils.py
Email body processing and analysis.

**Key Functions:**
- `smart_truncate(text, max_chars)` - Intelligent truncation preserving keywords
- `_remove_signatures(text)` - Strip email signatures
- `extract_urls(text)` - Find all URLs in text
- `count_links(text)` - Count hyperlinks
- `has_unsubscribe_link(text)` - Detect newsletter patterns
- `extract_subject_keywords(subject)` - Pull key terms from subject
- `is_likely_automated(email)` - Detect automated/transactional emails
- `clean_whitespace(text)` - Normalize spacing

### tasks.py
Three-pass classification orchestration for IMAP.

**Key Functions:**
- `run_classification(provider, classifier, db, config)` - Main orchestrator
- `_run_fast_parse_on_folder(...)` - Pass 1: Headers-only classification
- `_run_domain_classification_pass(...)` - Pass 2: Domain-based bulk classification
- `_dump_pass3_emails_for_manual_matching(...)` - Generate review files

**Pass Flow:**
1. Pass 1 uses validated/historical DBs on headers only
2. Pass 2 groups by commercial domain, applies domain rules
3. Pass 3 fetches full bodies, uses AI classification

### domain_analyzer.py
Analyze Pass 3 output files to find domain candidates for DB expansion.

**Usage:**
```bash
python src/main.py analyze-domains --output data/domain_candidates.json
```

### data_cleanup.py
Utilities for cleaning up accumulated data files.

**Key Functions:**
- `cleanup_old_pass3_files(data_dir, max_age_days)` - Remove pass3 files older than threshold
- `consolidate_duplicate_pass3_files(data_dir)` - Remove duplicates, keep first/last per day
- `get_pass3_file_stats(data_dir)` - Get statistics about pass3 files

**Usage:**
```bash
python src/main.py cleanup --max-age 30
python src/main.py cleanup --consolidate
```

### db_backup.py
Database backup and restore utilities with automatic rotation.

**Key Functions:**
- `backup_database(db_path, backup_dir)` - Create timestamped backup
- `backup_all_databases(db_dir)` - Backup all JSON databases
- `restore_database(backup_path, db_path)` - Restore from backup
- `cleanup_old_backups(backup_dir, keep_count)` - Remove old backups
- `list_backups(backup_dir)` - List available backups
- `get_backup_stats(backup_dir)` - Get backup statistics

**Automatic Backups:**
- Databases are backed up once at start of each classification run
- Backups stored in `db/backups/` with timestamp suffix
- Keeps 10 most recent backups by default

### data_validation.py
Validation and normalization utilities for data integrity.

**Key Functions:**
- `normalize_email(email)` - Strip brackets, decode RFC 2047, lowercase
- `normalize_domain(domain)` - Strip artifacts, lowercase
- `validate_domain_format(domain)` - Check valid domain pattern
- `validate_domain_classifications(db_path)` - Find issues in domain DB
- `validate_sender_classifications(db_path)` - Find issues in sender DB
- `fix_domain_classifications(db_path)` - Auto-fix malformed domains
- `prune_low_confidence_senders(db_path, min_count)` - Remove low-count entries
- `get_database_stats(db_dir)` - Get statistics for all databases

**Usage:**
```bash
python src/main.py db-stats
python src/main.py prune-db --min-count 3
```

## Testing
Test files in `tests/`:
- `test_text_utils.py`
- `test_domain_analyzer.py`
- `test_data_cleanup.py`
- `test_db_backup.py`
- `test_data_validation.py`
