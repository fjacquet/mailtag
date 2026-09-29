# Usage

## Classification

```bash
# Classify all providers (IMAP + Gmail)
python src/main.py run --provider all

# IMAP only
python src/main.py run --provider imap

# Read-only validation (no moves)
python src/main.py run --provider imap --validate

# Gmail only (through the Gmail API)
python src/main.py run --provider gmail
```

In taxonomy mode, `run` files INBOX into the action folders, archives old action-folder mail into its category and learns from the mails you filed out of `5-A revoir`. Do not run `serve` in Docker (with `db/` mounted) while a `run` works on the Mac: the rule files' lock does not cross the Docker Desktop VM.

Gmail runs through the **Gmail API** (OAuth, see [Configuration](configuration.md#gmail-api-setup)): the
`db/taxonomy/` rules and centroids are shared with Infomaniak, but each account keeps its own pending
archive, junk label and folder cache — Gmail's label listing never replaces `data/imap_folders.json`. On
Gmail, "moving" a mail out of `INBOX` removes the `INBOX` label (the mail stays in "All Mail"); `Promotions`
reuses Gmail's own Promotions tab (`CATEGORY_PROMOTIONS`) instead of a label; labels for other action
folders and categories are created on demand — see the [folder ↔ label mapping](../architecture/classification.md#gmail).
Gmail is new-mail only: there is no `scan`, `migrate` or `prune` for it, and its old labels are never
touched. Run `--validate` first: the OAuth app is in "Testing" mode, so the token expires after 7 days.

## Taxonomy Setup

One-time preparation of the taxonomy rules from the legacy folders. No step moves an email.

```bash
uv run python scripts/taxonomy_setup.py scan        # read-only header pass over the legacy folders
uv run python scripts/taxonomy_setup.py crosscheck  # Gemma category per sender (resumable)
uv run streamlit run scripts/taxonomy_review.py     # local review page
uv run python scripts/taxonomy_setup.py build       # rules, corpus and the 19 nomic centroids
```

The review page has five stages, picked in the sidebar:

1. **Contested folders** — confirm or correct the category of legacy folders whose senders Gemma often disagrees with. Run `scan` again afterwards.
2. **Scan senders** — senders with at least `sender_min_mails` mails that no validated, learned or domain rule covers.
3. **Senders learned during runs** — confirm or correct senders promoted after two nomic/Gemma agreements.
4. **Rule control** — after `build`, 60 random rule-covered senders; the page shows the share of right rules.
5. **Mails en revue** — after `review-scan`, decide a category per domain or per sender for the mail waiting in `5-A revoir`; see [Bulk Review of 5-A revoir](#bulk-review-of-5-a-revoir) below.

Stage 5's source files (`data/review_scan_*.json`) are independent of `scan`/`crosscheck`, so it is available even before you run them.

`scripts/eval_embeddings.py chain` replays signals 5-6 on verified mail to choose `nomic_threshold`.

## Legacy Folder Migration

Moves the mail of the legacy folders into the 19 categories, then deletes the emptied folders. Both commands are a dry run unless given `--apply`.

```bash
uv run python scripts/taxonomy_setup.py migrate            # plan only -> data/migration_report.json
uv run python scripts/taxonomy_setup.py migrate --apply    # move the mail
uv run python scripts/taxonomy_setup.py prune              # list the emptied legacy folders
uv run python scripts/taxonomy_setup.py prune --apply      # delete them
```

- Each mail goes to its sender's rule (validated, learned, then domain), else to its folder's audited category, else to `5-A revoir` (where filing it teaches the rule).
- Category, action and system folders (INBOX, Sent, Trash, Spam, Promotions, À Classer…) are never migrated or deleted. `Contacts/<person>` folders are migrated into `Contacts`.
- `migrate --apply` can be re-run: moved mail has left its folder, so a second dry run should show nothing left.
- `prune` deletes only legacy folders that are empty and whose subfolders are all deletable, deepest first.
- Do not run `run` or `serve` during `migrate --apply`.

## PARA Folders and Standard Promotions

```bash
uv run python scripts/taxonomy_setup.py reorganize            # list renames and merges
uv run python scripts/taxonomy_setup.py reorganize --apply    # apply them
```

Renames each flat category folder into its PARA folder (`Santé` → `Domaines/Santé`, `Achats` → `Archive/Achats`, `Veille & Newsletters pro` → `Ressources/Veille & Newsletters pro`) with IMAP RENAME (no mail is copied), renames `9-A revoir` to `5-A revoir`, and merges `5-Promos` into the standard `Promotions` folder. When both an old and a new folder exist, their mail is merged instead of overwritten. It also merges duplicate system folders created by mail clients into the ones Infomaniak's webmail uses: `Archives` → `Archive`, `Junk` → `Spam`, `Deleted Messages` → `Trash`, `Sent Messages` → `Sent` (set your mail client to use these folders, or it may recreate the others). Re-running it does nothing once done.

## Bulk Review of 5-A revoir

Deciding thousands of mails in `5-A revoir` one by one does not scale, especially after a first Gmail run. Instead decide a category per **domain** (all its senders, present and future) or per **sender**, then move every mail a rule now covers in one command. Dry run unless `--apply`.

```bash
uv run python scripts/taxonomy_setup.py review-scan --provider imap|gmail    # read-only, writes data/review_scan_<provider>.json
uv run streamlit run scripts/taxonomy_review.py                              # stage 5: "Mails en revue"
uv run python scripts/taxonomy_setup.py refile-review --provider imap|gmail          # report only
uv run python scripts/taxonomy_setup.py refile-review --provider imap|gmail --apply  # move the mail
```

- `review-scan` reads `5-A revoir`, skips mail a rule already covers and the owner's own addresses, groups the rest by domain (or by sender for a personal domain such as `gmail.com`), and asks Gemma for a suggested category per group. Re-running it keeps suggestions already computed.
- On stage 5, each row shows the group's mail count, its top senders, a few subjects and Gemma's suggestion. `Confirmer` accepts the suggestion; a category button picks one of the 19 directly; `Par expéditeur` (domain rows only) splits the row into one per sender for this session; `Passer` skips it, like the other stages. A domain decision goes to `db/taxonomy/validated_domains.json`, a sender decision to `db/taxonomy/validated.json` — same file, same rule, as any other validated sender.
- `refile-review` moves each covered mail to its category folder and drops its `pending_archive` entry, so a later archive sweep does not relearn it as a sender rule. Mail with no rule stays in `5-A revoir` for manual review.
- Blocked while `migrate`/`prune` would be (taxonomy rules must exist first). Do not run `run` or `serve` during `refile-review --apply`.

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
| `db/taxonomy/validated.json` | Senders you confirmed (review page, mail filed out of `5-A revoir`) |
| `db/taxonomy/senders.json` | Learned senders and their agreement counts |
| `db/taxonomy/domains.json` | Business domain rules computed by `build` |
| `db/taxonomy/validated_domains.json` | Domains you decided (bulk review); `build` never replaces it |
| `db/taxonomy/folder_overrides.json` | Folder audit decisions |
| `db/taxonomy/control.json` | Rule control sample |
| `db/pending_archive.json` | Category of each email waiting in an action folder (Infomaniak) |
| `db/pending_archive_gmail.json` | Same, for the Gmail IMAP account |
| `data/gmail_folders.json` | Cached Gmail (label) folder structure |
| `data/taxonomy_centroids.npz` | The 19 nomic centroids |
| `data/mailbox_scan.json`, `data/sender_crosscheck.json` | Scan and Gemma opinions per sender |
| `data/migration_report.json` | Last `migrate` plan or result |
| `data/review_scan_imap.json`, `data/review_scan_gmail.json` | Last `review-scan` per account: groups and Gemma suggestions |
