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
credentials_file = "secrets/credentials.json"
token_file = "secrets/token.json"
pending_archive_file = "db/pending_archive_gmail.json"
folder_cache_file = "data/gmail_labels.json"
junk_folder_name = "SPAM"
use_gmail_extensions = false

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

### `[gmail]`

Gmail runs through the **Gmail API** (OAuth), not IMAP: `credentials_file` and `token_file` point to the
OAuth desktop client (`secrets/credentials.json`) and the saved user token (`secrets/token.json`).

| Key | Meaning |
|-----|---------|
| `credentials_file` | OAuth desktop client secret, downloaded from Google Cloud Console |
| `token_file` | saved user token; created on first run, refreshed automatically |
| `pending_archive_file` | this account's own pending-archive file, so its sweep never sees Infomaniak's mails as orphans |
| `folder_cache_file` | this account's own label cache; it is never refreshed into `data/imap_folders.json` (Infomaniak's) |
| `junk_folder_name` | Gmail's system Spam label, `"SPAM"` |
| `use_gmail_extensions` | unused by the API path (kept for parity with `ImapConfig`); `false` |

## .env

Secrets and environment-specific values:

```bash
IMAP_USER=your-email@example.com
IMAP_PASSWORD=your-app-password

# Gmail through the API: no environment variables needed, only secrets/credentials.json and secrets/token.json (below)

# Optional: cloud AI provider (overrides MLX for Signal 6)
# MODEL=gemini/gemini-2.5-flash
# GEMINI_API_KEY=your-key
```

## Gmail API Setup

Gmail talks through the **Gmail API** (OAuth), not IMAP — `GmailApiService` (`src/mailtag/gmail_api.py`)
is the provider `run --provider gmail` uses; `GmailService` stays in the codebase, unused:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project, enable the Gmail API and
   create an OAuth 2.0 Client ID for a **Desktop app**
2. Download the JSON file and save it as `secrets/credentials.json` (the `secrets/` directory is git-ignored)
3. Run `python src/main.py run --provider gmail --validate` once: it opens a browser for consent and saves
   `secrets/token.json`

While the OAuth app is in "Testing" (the default until you publish it), the token expires after **7 days**
and the browser flow runs again. Never commit anything in `secrets/`.

Gmail labels act as folders: moving a mail out of `INBOX` removes the `INBOX` label (Gmail's own "archive"),
and the mail stays in "All Mail". `Promotions` reuses Gmail's own Promotions tab (`CATEGORY_PROMOTIONS`)
instead of a label — see the [classification architecture](../architecture/classification.md#gmail) for the
full folder ↔ label mapping. Only new mail is classified — no `scan`, `migrate` or `prune` for Gmail, and
old labels are never touched.

## Dynamic vs Static Classification

Controlled by `general.use_imap_folders_for_classification`:

- **Dynamic (default)**: Uses live IMAP folder structure as categories, refreshed at startup
- **Static**: Uses fixed categories from `data/classification_schema.yml`
