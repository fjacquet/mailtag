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

## Testing
Test files in `tests/`:
- `test_text_utils.py`
- `test_domain_analyzer.py`
