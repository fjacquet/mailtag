# Installation

## Prerequisites

- **Python 3.13+**
- **macOS with Apple Silicon** (MLX requires Metal GPU acceleration)

## Setup

```bash
git clone https://github.com/fjacquet/mailtag.git
cd mailtag
uv sync -U --all-extras
```

### Optional: Gmail support

Gmail runs through the **Gmail API** (OAuth, see [Configuration](configuration.md#gmail-api-setup)). The
`gmail` extra installs the Gmail API/OAuth client libraries `GmailApiService` needs:

```bash
uv sync -U --extra gmail
```

### Optional: Documentation tools

```bash
uv sync -U --extra docs
```

## Verify Installation

```bash
python src/main.py --help
```

## MLX Models

Models are downloaded automatically on first use. The defaults are:

| Component | Model | Size |
|-----------|-------|------|
| Embeddings (nomic centroids) | `nomic-ai/nomic-embed-text-v1.5` | ~280MB |
| LLM (Gemma second opinion) | `mlx-community/gemma-4-e4b-it-OptiQ-4bit` | ~2.5GB |
