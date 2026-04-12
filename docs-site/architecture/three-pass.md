# Three-Pass Processing

For IMAP providers, MailTag processes emails in three passes for performance optimization. Each pass progressively uses more expensive operations.

## Overview

```
INBOX (N emails)
    |
    v
[Pass 1: Fast Parse] -- headers only --> classify via Signals 1-3
    |                                     (batch_size: 500)
    | remaining UIDs + cached headers
    v
[Pass 2: Domain]     -- headers only --> classify via domain rules
    |                                     (groups by commercial domain)
    | remaining UIDs
    v
[Pass 3: AI]         -- full body   --> classify via Signals 5-6
                                         (batch embeddings + LLM)
```

## Pass 1: Fast Parse

Processes emails using **only headers** (sender, subject). Uses validated and historical databases for instant classification.

- Processes emails in configurable batches (default: 500)
- Also runs on the Junk folder before INBOX
- Returns unclassified UIDs **and cached headers** to Pass 2

**Performance**: Classifies known senders in microseconds. Typically handles 60-80% of emails.

## Pass 2: Domain Classification

Groups remaining emails by **commercial domain** and applies domain-based rules in bulk.

- Skips non-commercial domains (gmail.com, yahoo.com, etc.)
- Reuses headers from Pass 1 (no duplicate IMAP fetch)
- Generates `data/pass3_manual_matching_*.json` for review

**Performance**: One database lookup per domain, not per email. Handles 10-20% of remaining emails.

## Pass 3: AI Classification

Fetches **full email bodies** and uses AI classification for remaining emails.

- Batch embedding computation via `route_batch()` for Signal 5
- Sequential LLM fallback for Signal 6
- Batch IMAP moves accumulated by category

**Performance**: ~1-2 seconds per LLM call. Typically 5-15% of total emails reach this pass.

## Gmail Processing

Gmail providers use **single-pass processing** with the full AMSC strategy applied per-email, since Gmail API doesn't support the same batch header operations as IMAP.
