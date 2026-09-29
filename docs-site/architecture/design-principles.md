# Design Principles

## Cost-Ordered Classification

Steps are ordered from cheapest to most expensive:

1. **Rules** (validated and learned senders, domains): dictionary lookups on headers, microseconds
2. **Embedding similarity** (nomic centroids): one matrix multiplication, milliseconds
3. **LLM inference** (Gemma): a model forward pass, 1-2 seconds

This ensures the fastest path is always tried first, and only mail no rule covers is read in full.

## Batch Over Individual

Operations are batched wherever possible:

- IMAP header fetches in configurable batch sizes
- Embedding computation for all pending emails in one call (`top_batch()`)
- Gemma prompts in batches sharing a cached prompt prefix
- IMAP moves accumulated by destination folder, then executed in bulk
- Rule changes recorded as operations and written once per `save()`

## Fail Safe

Every classification failure has a safe fallback:

- Anything unsure or failing (model error, missing MLX) routes to `5-A revoir`, never to a guessed category
- `--validate` moves nothing and writes nothing
- Rules and pending archives are backed up at the start of each `run`
- Network failures use configurable retry with exponential backoff

## Shared State

- `TaxonomyStore.save()` takes an exclusive `flock` on `db/taxonomy/.lock` and replays its operations on top of what other processes wrote
- Thread-safe lazy initialization for MLX components
- `PendingArchive` has no lock: an entry recorded by `serve` during a `run` of the same account can be lost

## Normalize Everything

All lookups use normalized keys:

- Email addresses: lowercase, angle brackets stripped
- Domains: lowercase, normalized
- IMAP folders: case-sensitive with forward slash delimiter
