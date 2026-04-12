# Design Principles

## Cost-Ordered Classification

Signals are ordered from cheapest to most expensive:

1. **Dictionary lookups** (Signals 1-4): O(1) hash table lookups, microseconds
2. **Embedding similarity** (Signal 5): One matrix multiplication, milliseconds
3. **LLM inference** (Signal 6): Full model forward pass, 1-2 seconds

This ensures the fastest path is always tried first.

## Batch Over Individual

Operations are batched wherever possible:

- IMAP header fetches in configurable batch sizes
- Embedding computation via `route_batch()` for all pending emails
- IMAP moves accumulated by category, then executed in bulk
- Database writes deferred with dirty flags, flushed at pass boundaries

## Fail Safe

Every classification failure has a safe fallback:

- Low confidence results route to "A Classer" (unclassified folder)
- Model errors route to "(Model Error)"
- Database corruption loads empty databases
- Network failures use configurable retry with exponential backoff

## Thread Safety

All shared state uses proper locking:

- `threading.RLock` on database mutations
- Thread-safe lazy initialization for MLX components
- Deep copy pattern for metrics reads
- `Event`-based shutdown for IMAP daemon

## Normalize Everything

All lookups use normalized keys:

- Email addresses: lowercase, angle brackets stripped
- Domains: lowercase, normalized
- IMAP folders: case-sensitive with forward slash delimiter
