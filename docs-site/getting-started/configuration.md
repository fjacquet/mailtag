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

[fast_parse]
batch_size = 500
folder_cache_ttl_hours = 24
unclassified_folder_name = "A Classer"
junk_folder_name = "Junk"

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

## .env

Secrets and environment-specific values:

```bash
IMAP_USER=your-email@example.com
IMAP_PASSWORD=your-app-password

# Optional: cloud AI provider (overrides MLX for Signal 6)
# MODEL=gemini/gemini-2.5-flash
# GEMINI_API_KEY=your-key
```

## Gmail OAuth Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Gmail API**
3. Create **OAuth 2.0 Desktop** credentials
4. Download as `credentials.json` in the project root
5. First run will prompt for browser authorization

## Dynamic vs Static Classification

Controlled by `general.use_imap_folders_for_classification`:

- **Dynamic (default)**: Uses live IMAP folder structure as categories, refreshed at startup
- **Static**: Uses fixed categories from `data/classification_schema.yml`
