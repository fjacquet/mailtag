# src/mailtag/

Core package: classifies emails into 19 categories and files them.

## Key Modules

### Classification

- **classifier.py** - `Classifier(config, read_only=False)`
  - `classify_email()` / `classify_emails_batch()` - one category per email; rules first, then nomic, then Gemma
  - `_rule_category()` - validated sender, learned sender, domains (own addresses never match)
  - `_nomic_top()` - nearest centroid and its score
  - `_llm_categories()` - Gemma answers by category number
  - `_classify_uncertain_detailed()` - nomic at `nomic_threshold`, else nomic/Gemma agreement, else `5-A revoir`
- **taxonomy.py** - the 19 categories, PARA folders (`category_folder`), action folders, `map_folder`, `to_category`, Gemma and nomic prompt builders
- **taxonomy_store.py** - `TaxonomyStore`: validated and learned senders, validated and computed domains, folder overrides; `category_for()`, `record_agreement()`, `set_validated()`, `set_validated_domain()`, `save()` (flock, replays operations)
- **semantic_router.py** - `SemanticRouter`: nomic centroids (`top_batch()`, `load_embeddings()`, `save_embeddings()`, `build_from_examples()`)
- **mlx_provider.py** - `MLXEmbedder` (nomic) and `MLXLLM` (Gemma, `classify_batch()`), lazy loaded

### Routing and archive

- **action_rules.py** - `choose_action()`: action folder for a classified email (pure)
- **routing.py** - `route_to_action_folders()`: batch moves, one `PendingArchive` entry per mail with a Message-ID
- **pending_archive.py** - `PendingArchive`: category of each mail waiting in an action folder (no file lock)
- **archive.py** - `run_archive()`: end-of-run sweep (archive read mail, learn from `5-A revoir`, drop orphan entries)

### Providers

- **imap_service.py** - `ImapService`
  - `get_email_headers()` - headers only, Pass 1
  - `get_full_emails()` - full bodies, Pass 3
  - `batch_move_emails()` / `select_folder()`
- **gmail_api.py** - `GmailApiService(ImapService)` and `GmailLabelClient` (IMAPClient subset over the Gmail API)
- **gmail_auth.py** - OAuth flow for Gmail

### Taxonomy preparation and maintenance (used by `scripts/taxonomy_setup.py`)

- **mailbox_scan.py** - read-only scan of the legacy folders
- **sender_crosscheck.py** - Gemma opinion per sender
- **taxonomy_build.py** - learned rules, domain rules, review queue, centroids
- **migration.py** - legacy folder migration, prune, PARA reorganize
- **review_refile.py** - bulk review of `5-A revoir`: groups, suggestions, refile

### Supporting Modules

- **config.py** - Configuration dataclasses with env var substitution (`logging`, `imap`, `gmail`, `fast_parse`, `mlx`, `taxonomy`, `webhook`)
- **models.py** - `Email` Pydantic model
- **retry.py** - Exponential backoff retry logic
- **logging_config.py** - loguru setup
- **api/** - FastAPI webhook (`serve`): `create_app()`, routes `classify`, `health`, schemas, API key middleware

## Design Patterns

- Rules before models: cheapest step first
- Context managers for connections
- Batch operations over individual calls
- Lowercase normalization for all lookups
- Read-only mode (`--validate`) moves nothing and writes nothing
