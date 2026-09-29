# MailTag

AI-powered email classification and organization using on-device inference.

[![CI Tests and Checks](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/fjacquet/mailtag)](https://github.com/fjacquet/mailtag/releases)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/fjacquet/mailtag/blob/main/LICENSE)

## What is MailTag?

MailTag is a Python-based email automation tool that classifies and organizes emails into a **19-category business taxonomy** with MLX-powered local inference on Apple Silicon. It supports both IMAP and Gmail providers.

## Key Features

- **On-device AI** via MLX on Apple Silicon -- no cloud API required
- **Rules first, models second**: validated and learned senders, then domain rules, then embeddings and a local LLM
- **Action folders** (`1-A traiter`, `2-A payer`, `3-A lire`, `4-Pour info`, `Promotions`, `5-A revoir`) and PARA category folders
- **Learning from your decisions**: filing a mail out of `5-A revoir` teaches MailTag its sender
- **Batch operations** for efficient email organization
- **Webhook API** for external integrations
- **Automatic backups** of the rules with rotation

## Quick Start

```bash
git clone https://github.com/fjacquet/mailtag.git
cd mailtag
uv sync -U --all-extras
python src/main.py run --provider imap --validate  # Read-only test
```

Then read the [User Guide](user-guide.md) for day-to-day use.

## Classification Chain

| Step | Source | Speed |
|------|--------|-------|
| 1. Validated sender | Senders you confirmed | Instant |
| 2. Learned sender | Sender after 2 nomic/Gemma agreements | Instant |
| 3. Domain rules | Validated domains, then computed commercial domains | Instant |
| 4. Nomic centroids | Embedding similarity, score at least `nomic_threshold` | Fast |
| 5. Nomic and Gemma agree | Local Gemma 4 E4B answers by category number | ~1-2s |
| 6. `5-A revoir` | Nothing decided | Instant |

The first match wins, so the fastest path is always tried first. See [Classification Strategy](architecture/classification.md).
