# MailTag

AI-powered email classification and organization using on-device inference.

[![CI Tests and Checks](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/fjacquet/mailtag)](https://github.com/fjacquet/mailtag/releases)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/fjacquet/mailtag/blob/main/LICENSE)

## What is MailTag?

MailTag is a Python-based email automation tool that classifies and organizes emails using a **6-signal classification strategy** with MLX-powered local inference on Apple Silicon. It supports both IMAP and Gmail providers.

## Key Features

- **On-device AI** via MLX on Apple Silicon -- no cloud API required
- **6 prioritized classification signals** for accuracy and speed
- **Three-pass IMAP processing** (headers, domains, full body + AI)
- **Batch operations** for efficient email organization
- **Domain-based rules** for commercial email routing
- **Semantic routing** via embedding similarity
- **Automatic database backups** with rotation

## Quick Start

```bash
git clone https://github.com/fjacquet/mailtag.git
cd mailtag
uv sync -U --all-extras
python src/main.py run --provider imap --validate  # Read-only test
```

## Classification Signals

| Signal | Source | Confidence | Speed |
|--------|--------|-----------|-------|
| 1. Validated DB | Manual mappings | 100% | Instant |
| 2. Server Labels | IMAP folders / Gmail labels | 95% | Instant |
| 3. Historical DB | Sender patterns (10+ emails) | 90%+ | Instant |
| 4. Domain Rules | Commercial domain mappings | 90% | Instant |
| 5. Semantic Router | Embedding similarity (nomic-embed) | Configurable | Fast |
| 6. MLX LLM | Gemma 4 E4B local model | 85% threshold | ~1-2s |

Each signal stops evaluation when it classifies an email, ensuring the fastest path is always tried first.
