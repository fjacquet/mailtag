# Data Management Guide

This guide covers the data management utilities for maintaining MailTag's databases and data files.

## Overview

MailTag generates and maintains several data files during operation:

| Directory | Contents |
|-----------|----------|
| `db/` | Classification databases (JSON) |
| `db/backups/` | Automatic database backups |
| `data/` | Runtime data files (pass3 outputs, folder cache) |

## CLI Commands

### Database Statistics

View statistics and health check for all databases:

```bash
python src/main.py db-stats
```

**Output includes:**

- Number of entries in each database
- High-confidence sender entries (10+ occurrences)
- Unique categories in domain database
- File sizes

### Data Cleanup

Remove old pass3 files and validate databases:

```bash
# Remove pass3 files older than 30 days (default)
python src/main.py cleanup

# Custom age threshold
python src/main.py cleanup --max-age 14

# Also consolidate duplicate files from same day
python src/main.py cleanup --consolidate

# Preview without deleting (dry run)
python src/main.py cleanup --dry-run
```

**What gets cleaned:**

- `pass3_manual_matching_*.json` files older than threshold
- Duplicate files from same day (keeps first and last)

### Prune Low-Confidence Entries

Remove sender entries with few occurrences:

```bash
# Remove entries with less than 3 occurrences (default)
python src/main.py prune-db

# Custom threshold
python src/main.py prune-db --min-count 5

# Preview without modifying
python src/main.py prune-db --dry-run
```

**Why prune?**

- Single-occurrence entries provide low classification signal
- Reduces database size and lookup time
- Improves signal-to-noise ratio

## Database Files

### sender_classification_db.json

Historical AI classification suggestions per sender.

```json
{
  "newsletter@example.com": {
    "Marketing/Newsletters": 15,
    "Promotions": 2
  }
}
```

- Key: Normalized sender email (lowercase)
- Value: Category counts from AI suggestions
- Used by Signal 3 (Historical Database) when count >= 10

### validated_classification_db.json

Manually validated sender-to-category mappings.

```json
{
  "support@company.com": "Services/Support"
}
```

- Key: Normalized sender email
- Value: Definitive category
- Used by Signal 1 (highest priority, 100% confidence)

### domain_classifications.json

Domain-level classification rules for commercial senders.

```json
{
  "amazon.com": "Shopping/Amazon",
  "github.com": "Tech/Development"
}
```

- Key: Normalized domain (lowercase)
- Value: Category
- Used by Signal 4 (90% confidence)
- Skips non-commercial domains (gmail.com, yahoo.com, etc.)

## Automatic Backups

Databases are automatically backed up:

1. **When**: Once at the start of each classification run
2. **Where**: `db/backups/`
3. **Format**: `{database_name}_{YYYYMMDD}_{HHMMSS}.json`
4. **Retention**: Keeps 10 most recent backups per database

### Manual Backup

```python
from mailtag.utils.db_backup import backup_all_databases

backup_all_databases(Path("db"))
```

### Restore from Backup

```python
from mailtag.utils.db_backup import restore_database

restore_database(
    backup_path=Path("db/backups/sender_classification_db_20251230_120000.json"),
    db_path=Path("db/sender_classification_db.json")
)
```

### List Backups

```python
from mailtag.utils.db_backup import list_backups

backups = list_backups(Path("db/backups"))
for b in backups:
    print(f"{b['name']}: {b['size_bytes']} bytes, created {b['created']}")
```

## Data Validation

### Validate Databases

Check for data quality issues:

```python
from mailtag.utils.data_validation import (
    validate_domain_classifications,
    validate_sender_classifications
)

# Check domain database
issues = validate_domain_classifications(Path("db/domain_classifications.json"))
for issue in issues:
    print(f"Issue: {issue}")

# Check sender database
issues = validate_sender_classifications(Path("db/sender_classification_db.json"))
```

**Detects:**

- Malformed domains (trailing `>`, invalid format)
- Empty categories
- Sender addresses needing normalization
- Invalid category data types

### Fix Common Issues

```python
from mailtag.utils.data_validation import fix_domain_classifications

# Auto-fix malformed domains
fixed = fix_domain_classifications(Path("db/domain_classifications.json"))
print(f"Fixed {fixed} domains")
```

## Email Normalization

All emails and domains are normalized before storage:

```python
from mailtag.utils.data_validation import normalize_email, normalize_domain

# Email normalization
normalize_email("<John.Doe@EXAMPLE.COM>")  # → "john.doe@example.com"
normalize_email("Name <user@host.com>")     # → "user@host.com"

# Domain normalization
normalize_domain("Example.COM>")  # → "example.com"
```

**Normalization rules:**

- Strip angle brackets `< >`
- Decode RFC 2047 encoded headers
- Convert to lowercase
- Strip whitespace

## Pass3 Files

Pass3 files contain emails that need manual classification review.

### File Format

```json
{
  "timestamp": "2025-12-30T12:00:00",
  "emails_for_manual_matching": [
    {
      "msg_id": "...",
      "sender": "unknown@domain.com",
      "subject": "...",
      "suggested_category": "À Classer"
    }
  ]
}
```

### Cleanup Strategy

1. **Age-based**: Remove files older than 30 days
2. **Consolidation**: When multiple files exist for same day, keep only first and last

### Statistics

```python
from mailtag.utils.data_cleanup import get_pass3_file_stats

stats = get_pass3_file_stats(Path("data"))
print(f"Total files: {stats['total_files']}")
print(f"Date range: {stats['oldest_date']} to {stats['newest_date']}")
print(f"Files per day: {stats['files_by_date']}")
```

## Best Practices

1. **Run cleanup weekly**: `python src/main.py cleanup`
2. **Check db-stats periodically**: Monitor database growth
3. **Prune after initial setup**: Remove single-occurrence entries once you have enough data
4. **Review backups**: Ensure backups are being created
5. **Validate after manual edits**: Run validation if you edit databases manually

## Troubleshooting

### "File not found" errors

If `validated_classification_db.json` is missing:

```bash
echo "{}" > db/validated_classification_db.json
```

### Malformed domain entries

Run the fix command:

```python
from mailtag.utils.data_validation import fix_domain_classifications
fix_domain_classifications(Path("db/domain_classifications.json"))
```

### Pass3 files accumulating

Enable regular cleanup:

```bash
# Add to crontab or scheduled task
python src/main.py cleanup --max-age 30
```

### Restore corrupted database

```python
from mailtag.utils.db_backup import list_backups, restore_database

# Find recent backup
backups = list_backups(Path("db/backups"))
latest = backups[-1]  # Most recent

# Restore
restore_database(latest['path'], Path("db/sender_classification_db.json"))
```
