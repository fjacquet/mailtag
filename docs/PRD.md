# MailTag — Product Requirements Document

## Vision

MailTag automatically classifies and organizes emails into folder hierarchies using on-device AI, eliminating the need for manual email sorting while keeping all data local.

## Target User

Individual power user with a large email volume across multiple accounts (IMAP + Gmail), running macOS on Apple Silicon.

## Problem Statement

Email inboxes accumulate thousands of unorganized messages. Manual sorting is tedious and unsustainable. Server-side rules are brittle (exact-match only) and don't adapt to new senders. Cloud AI solutions raise privacy concerns.

## Solution

A local classification engine that:

1. Learns from user-validated classifications to build a sender→category database
2. Uses 6 progressively expensive signals to classify each email, stopping at the first confident match
3. Runs entirely on-device using MLX for AI inference (no cloud APIs required)
4. Moves classified emails to the appropriate IMAP folder or Gmail label

## Core Requirements

### Classification Engine

| Req | Description | Priority |
|-----|-------------|----------|
| CR-1 | 6-signal hierarchical classification (validated DB → server labels → history → domain → semantic → LLM) | Must |
| CR-2 | Each signal stops evaluation on confident match | Must |
| CR-3 | AI returns structured JSON with category, confidence, and reasoning | Must |
| CR-4 | Below-threshold AI classifications route to "À Classer" for manual review | Must |
| CR-5 | Prompts and categories support French | Must |
| CR-6 | Classification metrics tracked per signal (hit rates, confidence, timing) | Should |

### Email Providers

| Req | Description | Priority |
|-----|-------------|----------|
| EP-1 | IMAP provider with batch operations and folder hierarchy support | Must |
| EP-2 | Gmail provider with OAuth authentication and label management | Must |
| EP-3 | 3-pass IMAP processing: headers → domains → full body + AI | Must |
| EP-4 | Provider abstraction via `EmailProvider` base class | Must |

### Data Management

| Req | Description | Priority |
|-----|-------------|----------|
| DM-1 | Three JSON databases: validated, historical (suggestions), domain rules | Must |
| DM-2 | Automatic database backups with rotation (10 most recent) | Must |
| DM-3 | Lowercase normalization for all email/domain lookups | Must |
| DM-4 | Domain analysis tools to identify candidates for domain DB expansion | Should |
| DM-5 | Pass3 file cleanup and consolidation utilities | Should |

### AI / MLX

| Req | Description | Priority |
|-----|-------------|----------|
| AI-1 | On-device embedding generation for semantic classification (Signal 5) | Must |
| AI-2 | On-device LLM inference for classification fallback (Signal 6) | Must |
| AI-3 | Lazy model loading (only load when needed) | Must |
| AI-4 | Configurable model selection via `config.toml` (no code changes to switch models) | Must |
| AI-5 | Support for thinking-mode models (Gemma 4) with automatic suppression | Must |
| AI-6 | Pre-computed category embeddings stored in `.npz` format | Should |

### Configuration

| Req | Description | Priority |
|-----|-------------|----------|
| CF-1 | `config.toml` as main config with env var substitution for secrets | Must |
| CF-2 | `.env` for secrets (IMAP password, API keys) | Must |
| CF-3 | Dynamic classification mode using live IMAP folder structure | Must |
| CF-4 | Static classification mode via YAML schema (legacy) | Should |
| CF-5 | Fail-fast on invalid configuration with clear error messages | Must |

## Non-Functional Requirements

| Req | Description | Priority |
|-----|-------------|----------|
| NF-1 | Runs on macOS with Apple Silicon (MLX requirement) | Must |
| NF-2 | Python 3.13+ | Must |
| NF-3 | Thread-safe concurrent email processing | Must |
| NF-4 | No external server dependencies for core classification (Ollama not required) | Must |
| NF-5 | Cloud AI providers available as optional alternative via `.env` | Should |

## Out of Scope

- Web UI for classification management (Streamlit UI exists but is not a core deliverable)
- Multi-user or server deployment
- Non-macOS platforms
- Real-time email monitoring (batch processing only)
