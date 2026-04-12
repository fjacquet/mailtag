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
| Embeddings (Signal 5) | `nomic-ai/nomic-embed-text-v1.5` | ~280MB |
| LLM (Signal 6) | `mlx-community/gemma-4-e4b-it-OptiQ-4bit` | ~2.5GB |
