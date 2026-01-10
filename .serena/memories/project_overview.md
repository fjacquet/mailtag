# MailTag Project Overview

## Purpose
MailTag is a Python-based email automation tool that classifies and organizes emails using AI. It supports both IMAP and Gmail providers.

## Tech Stack
- **Language**: Python 3.12+
- **Package Manager**: uv
- **Key Dependencies**:
  - `litellm` - Multi-provider AI interface (Ollama, Gemini, OpenRouter)
  - `pydantic` - Data validation and models
  - `imapclient` - IMAP protocol support
  - `google-api-python-client` - Gmail API
  - `streamlit` - Web UI
  - `fastapi` - Webhook server
  - `click` - CLI interface
  - `loguru` - Structured logging
  - `beautifulsoup4` - HTML parsing

## Architecture

### Multi-Signal Classification Strategy (AMSC)
The classifier (`src/mailtag/classifier.py`) uses 5 signals in priority order:
1. **Validated Database** (100% confidence) - Manually validated sender mappings
2. **Server-Side Labels** (95%) - Existing IMAP folders/Gmail labels
3. **Historical Database** (90%+) - High-confidence sender history
4. **Domain Classification** (90%) - Commercial domain-based rules
5. **AI Model** (configurable 0.85 threshold) - Fallback to LLM

### Three-Pass Processing (IMAP only)
- **Pass 1**: Headers-only fast classification using databases
- **Pass 2**: Domain-based bulk classification
- **Pass 3**: AI classification for remaining emails

### Key Modules
- `src/mailtag/classifier.py` - Core classification engine
- `src/mailtag/database.py` - JSON database management
- `src/mailtag/imap_service.py` - IMAP provider
- `src/mailtag/gmail_service.py` - Gmail provider
- `src/mailtag/providers.py` - Abstract provider interface
- `src/mailtag/config.py` - Configuration dataclasses
- `src/mailtag/utils/` - Domain, text, and task utilities

### Databases (JSON in db/)
- `sender_classification_db.json` - AI suggestions and history
- `validated_classification_db.json` - Validated mappings
- `domain_classifications.json` - Domain-level rules

### Configuration
- `config.toml` - Main config with env var substitution
- `.env` - Environment variables (IMAP_USER, IMAP_PASSWORD, MODEL, etc.)
