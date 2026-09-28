# Configuration

MailTag uses two configuration sources:

## config.toml

Main configuration file with all settings:

```toml
[general]
ollama_model = "ollama_chat/qwen3-vl:8b-instruct"
api_base = "http://localhost:11434"
use_imap_folders_for_classification = true

[classifier]
historical_confidence_threshold = 0.9
min_count = 5
ai_confidence_threshold = 0.85

[imap]
host = "imap.example.com"
user = "${IMAP_USER}"
password = "${IMAP_PASSWORD}"

[gmail]
credentials_file = "credentials.json"
token_file = "token.json"

[gmail_imap]
host = "imap.gmail.com"
user = "${GMAIL_IMAP_USER}"
password = "${GMAIL_IMAP_PASSWORD}"
use_gmail_extensions = true
junk_folder_name = "[Gmail]/Spam"
pending_archive_file = "db/pending_archive_gmail.json"
folder_cache_file = "data/gmail_folders.json"

[fast_parse]
batch_size = 500
folder_cache_ttl_hours = 24
unclassified_folder_name = "A Classer"
junk_folder_name = "Spam"

[mlx]
enabled = true
embedding_model = "nomic-ai/nomic-embed-text-v1.5"
llm_model = "mlx-community/gemma-4-e4b-it-OptiQ-4bit"
llm_confidence = 0.85
llm_max_tokens = 128
llm_temperature = 0.2

[taxonomy]
enabled = true
nomic_threshold = 0.90
llm_batch_size = 8
archive_after_days = 7
taxonomy_db_dir = "db/taxonomy"
centroids_file = "data/taxonomy_centroids.npz"
learn_min_agreements = 2
domain_min_purity = 0.90
sender_min_mails = 2
own_addresses = ["you@example.com"]

[logging]
level = "INFO"
file = "mailtag.log"
```

### `[taxonomy]`

| Key | Meaning |
|-----|---------|
| `enabled` | `true`: 19 categories and action folders; `false`: legacy folder classification |
| `nomic_threshold` | nomic alone classifies at or above this score; below, nomic and Gemma must agree |
| `llm_batch_size` | emails per Gemma call |
| `archive_after_days` | days before a seen, unflagged email leaves its action folder for its category |
| `taxonomy_db_dir` | validated, learned and domain rules, folder audit (`db/taxonomy/`) |
| `centroids_file` | the 19 nomic centroids built from verified mail |
| `learn_min_agreements` | nomic/Gemma agreements before a sender becomes a rule |
| `domain_min_purity` | share of a domain's mail in one category needed for a domain rule |
| `sender_min_mails` | mails needed before a folder/Gemma agreement becomes a sender rule; also the review page's minimum |
| `own_addresses` | your own addresses: never a rule, never learned from, skipped by `scan` |

### `[gmail_imap]`

Gmail runs as a **second IMAP account** (not the Gmail API): with 2-Step Verification on, an app password is
enough, since IMAP is always on for Gmail. Absent section, or missing/unsubstituted credentials: no Gmail
account, and no error at load — the Infomaniak account keeps running.

| Key | Meaning |
|-----|---------|
| `host` | IMAP host, `imap.gmail.com` by default |
| `user`, `password` | from `.env` (`GMAIL_IMAP_USER`, `GMAIL_IMAP_PASSWORD`) |
| `use_gmail_extensions` | `true` by default |
| `junk_folder_name` | Gmail's Spam folder, `"[Gmail]/Spam"` by default |
| `pending_archive_file` | this account's own pending-archive file, so its sweep never sees the other account's mails as orphans |
| `folder_cache_file` | this account's own folder cache; it is never refreshed into `data/imap_folders.json` (Infomaniak's) |

## .env

Secrets and environment-specific values:

```bash
IMAP_USER=your-email@example.com
IMAP_PASSWORD=your-app-password

# Gmail as a second IMAP account
GMAIL_IMAP_USER=your-email@gmail.com
GMAIL_IMAP_PASSWORD=your-google-app-password

# Optional: cloud AI provider (overrides MLX for Signal 6)
# MODEL=gemini/gemini-2.5-flash
# GEMINI_API_KEY=your-key
```

## Gmail IMAP Setup

The CLI no longer uses the Gmail API/OAuth path (`GmailService` stays in the codebase, unused by `run`).
Gmail talks IMAP, always on since January 2025:

1. Turn on 2-Step Verification on your Google account
2. Create an app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Set `GMAIL_IMAP_USER` and `GMAIL_IMAP_PASSWORD` in `.env`

Gmail labels act as IMAP folders: moving a mail removes the source label and adds the target label, and
the mail stays in "All Mail". Only new mail is classified — no `scan`, `migrate` or `prune` for Gmail, and
old labels are never touched.

## Dynamic vs Static Classification

Controlled by `general.use_imap_folders_for_classification`:

- **Dynamic (default)**: Uses live IMAP folder structure as categories, refreshed at startup
- **Static**: Uses fixed categories from `data/classification_schema.yml`
