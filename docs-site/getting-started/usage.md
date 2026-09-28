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

In taxonomy mode, `run` files INBOX into the action folders, archives old action-folder mail into its category and learns from the mails you filed out of `9-A revoir`. Do not run `serve` in Docker (with `db/` mounted) while a `run` works on the Mac: the rule files' lock does not cross the Docker Desktop VM.

## Taxonomy Setup

One-time preparation of the taxonomy rules from the legacy folders. No step moves an email.

```bash
uv run python scripts/taxonomy_setup.py scan        # read-only header pass over the legacy folders
uv run python scripts/taxonomy_setup.py crosscheck  # Gemma category per sender (resumable)
uv run streamlit run scripts/taxonomy_review.py     # local review page
uv run python scripts/taxonomy_setup.py build       # rules, corpus and the 19 nomic centroids
```

The review page has four stages, picked in the sidebar:

1. **Contested folders** — confirm or correct the category of legacy folders whose senders Gemma often disagrees with. Run `scan` again afterwards.
2. **Scan senders** — senders with at least `sender_min_mails` mails that no validated, learned or domain rule covers.
3. **Senders learned during runs** — confirm or correct senders promoted after two nomic/Gemma agreements.
4. **Rule control** — after `build`, 60 random rule-covered senders; the page shows the share of right rules.

`scripts/eval_embeddings.py chain` replays signals 5-6 on verified mail to choose `nomic_threshold`.

## Legacy Folder Migration

Moves the mail of the legacy folders into the 19 categories, then deletes the emptied folders. Both commands are a dry run unless given `--apply`.

```bash
uv run python scripts/taxonomy_setup.py migrate            # plan only -> data/migration_report.json
uv run python scripts/taxonomy_setup.py migrate --apply    # move the mail
uv run python scripts/taxonomy_setup.py prune              # list the emptied legacy folders
uv run python scripts/taxonomy_setup.py prune --apply      # delete them
```

- Each mail goes to its sender's rule (validated, learned, then domain), else to its folder's audited category, else to `9-A revoir` (where filing it teaches the rule).
- Category, action and system folders (INBOX, Sent, Trash, Spam, Promotions, À Classer…) are never migrated or deleted. `Contacts/<person>` folders are migrated into `Contacts`.
- `migrate --apply` can be re-run: moved mail has left its folder, so a second dry run should show nothing left.
- `prune` deletes only legacy folders that are empty and whose subfolders are all deletable, deepest first.
- Do not run `run` or `serve` during `migrate --apply`.

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
| `data/non_commercial_domains.yaml` | Personal mailbox domains, never a domain rule |

In taxonomy mode:

| File | Purpose |
|------|---------|
| `db/taxonomy/validated.json` | Senders you confirmed (review page, mail filed out of `9-A revoir`) |
| `db/taxonomy/senders.json` | Learned senders and their agreement counts |
| `db/taxonomy/domains.json` | Business domain rules |
| `db/taxonomy/folder_overrides.json` | Folder audit decisions |
| `db/taxonomy/control.json` | Rule control sample |
| `db/pending_archive.json` | Category of each email waiting in an action folder |
| `data/taxonomy_centroids.npz` | The 19 nomic centroids |
| `data/mailbox_scan.json`, `data/sender_crosscheck.json` | Scan and Gemma opinions per sender |
| `data/migration_report.json` | Last `migrate` plan or result |
