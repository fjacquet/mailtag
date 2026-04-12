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

## Metrics

Classification metrics are tracked per signal:

- Hit rates and miss rates
- Confidence score distributions
- Processing times
- Error counts

Export via `classifier.export_metrics()` or log with `classifier.log_metrics_summary()`.
