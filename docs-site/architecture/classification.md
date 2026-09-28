# Classification Strategy (AMSC)

MailTag uses an **Adaptive Multi-Signal Classification** strategy with 6 prioritized signals. Each signal can definitively classify an email, stopping further evaluation.

## Signal Priority

```
Email arrives
    |
    v
[Signal 1: Validated DB] --match--> Done (100% confidence)
    |
    v
[Signal 2: Server Labels] --match--> Done (95% confidence)
    |
    v
[Signal 3: Historical DB] --match--> Done (90%+ confidence)
    |
    v
[Signal 4: Domain Rules]  --match--> Done (90% confidence)
    |
    v
[Signal 5: Semantic Router] --match--> Done (configurable threshold)
    |
    v
[Signal 6: MLX LLM]       --match--> Done (0.85 threshold)
    |
    v
Route to "A Classer" (unclassified)
```

## Signal Details

### Signal 1: Validated Database

Manually confirmed sender-to-category mappings stored in `validated_classification_db.json`. These are promoted from Signal 3 after manual review.

### Signal 2: Server-Side Labels

Existing IMAP folder structure or Gmail labels that match known categories. The classifier checks if the email's current labels match any category in the folder hierarchy.

### Signal 3: Historical Database

Sender classification history from `sender_classification_db.json`. Requires configurable thresholds:

- `historical_confidence_threshold`: Minimum confidence (default: 0.9)
- `min_count`: Minimum occurrence count (default: 5)

### Signal 4: Domain Classification

Commercial domain-based rules from `domain_classifications.json`. Non-commercial domains (gmail.com, yahoo.com, etc.) are skipped to avoid false matches.

### Signal 5: Semantic Router

MLX embedding-based classification using `nomic-embed-text-v1.5`. Computes cosine similarity between email content and pre-computed category embeddings.

- Supports batch processing via `route_batch()` for efficiency
- Category embeddings stored in `data/category_embeddings.npz`

### Signal 6: MLX LLM

Fallback to local Gemma 4 E4B model. Returns structured JSON:

```json
{"category": "Finance/Banking", "confidence": 0.92, "reason": "Invoice from bank"}
```

- Classifications below `ai_confidence_threshold` (0.85) route to "A Classer"
- Model errors route to "(Model Error)"
- Uses `enable_thinking=False` to prevent thinking tokens from consuming the budget

## Taxonomy Mode

With `[taxonomy] enabled = true` (the default since 2026-09-28), MailTag files mail into **19 business-sector categories** instead of the 611 legacy IMAP folders, and new mail first lands in an **action folder**.

### Categories

Banque & Placements, Assurances & Retraite, Impôts & Administration, Énergie & Télécom, Santé, Famille & École, Logement & Maison, Achats, Colis & Livraisons, Transports & Mobilité, Voyages & Loisirs, Médias & Divertissement, Veille & Newsletters pro, Éditeurs IT & Cloud, Outils & Services en ligne, Sécurité & Comptes, Carrière & Formation, Associations & Communauté, Contacts.

### Signal chain

```
Email arrives
    |
    v
[1. Validated sender]   db/taxonomy/validated.json  --match--> category
    |
    v
[3. Learned sender]     db/taxonomy/senders.json    --match--> category (after 2 nomic/Gemma agreements)
    |
    v
[4. Business domain]    db/taxonomy/domains.json    --match--> category (personal mailboxes excluded)
    |
    v
[5. nomic, 19 centroids] score >= nomic_threshold    --match--> category
    |
    v
[6. Gemma agrees with nomic's top choice]            --match--> category (the sender earns one agreement)
    |
    v
"9-A revoir"
```

Signal 2 (server labels) is not used. The owner's own addresses (`own_addresses`) never become a rule and are never learned from.

### Action folders

A classified email goes to an action folder; its category is remembered in `db/pending_archive.json`:

| Folder | When |
|--------|------|
| `2-A payer` | money category (bank, energy, insurance, taxes) and a bill-like subject |
| `1-A traiter` | sent by a person |
| `5-Promos` | bulk mail with an unsubscribe link and a promo subject |
| `3-A lire` | newsletters, media |
| `4-Pour info` | everything else |
| `9-A revoir` | no signal decided |

Emails that are seen, unflagged and older than `archive_after_days` move from their action folder into their category. When you file a mail out of `9-A revoir` into a category, its sender becomes a validated rule.

### Where the rules come from

The rules were learned once from the legacy folders (`scripts/taxonomy_setup.py`, see [Usage](../getting-started/usage.md#taxonomy-setup)): a read-only scan of every folder, a Gemma opinion per sender, a folder audit and a sender review in a local Streamlit page, then `build`. On a random control sample, the learned and domain rules were right for 59 of 60 senders.

## Metrics

Classification metrics are tracked per signal:

- Hit rates and miss rates
- Confidence score distributions
- Processing times
- Error counts

Export via `classifier.export_metrics()` or log with `classifier.log_metrics_summary()`.
