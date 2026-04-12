# Usage

## Classification

```bash
# Classify all providers (IMAP + Gmail)
python src/main.py run --provider all

# IMAP only
python src/main.py run --provider imap

# Read-only validation (no moves)
python src/main.py run --provider imap --validate

# Gmail only
python src/main.py run --provider gmail
```

## Database Management

```bash
# Show database statistics
python src/main.py db-stats

# Analyze domains for potential rules
python src/main.py analyze-domains --output data/domain_candidates.json

# Clean up old pass3 files
python src/main.py cleanup --consolidate
python src/main.py cleanup --max-age 30
```

## Filter Generation

```bash
# Generate email filter rules
python src/main.py filters
```

## Databases

MailTag uses three JSON databases in `db/`:

| Database | Purpose | Signal |
|----------|---------|--------|
| `validated_classification_db.json` | Manually confirmed mappings | Signal 1 |
| `sender_classification_db.json` | AI suggestions and history | Signal 3 |
| `domain_classifications.json` | Domain-level rules | Signal 4 |

### Automatic Backups

Databases are backed up to `db/backups/` at the start of each classification run. The 10 most recent backups are kept per database.

## Data Files

| File | Purpose |
|------|---------|
| `data/category_embeddings.npz` | Pre-computed embeddings for Signal 5 |
| `data/imap_folders.json` | Cached IMAP folder structure |
| `data/pass3_manual_matching_*.json` | Emails needing manual review |
| `data/non_commercial_domains.txt` | Domains to skip in Pass 2 |
