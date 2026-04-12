# ADR-001: Migration from litellm/Ollama to MLX for On-Device Classification

## Status

Accepted (implemented)

## Date

2025-12-30

## Context

MailTag relied on Ollama (via litellm) for AI classification (Signal 5). This required:

- Running an Ollama server process alongside the application
- Network round-trips to localhost for every classification
- ~4-5 GB RAM for the Ollama process on top of the Python process
- Manual model management (`ollama pull`, `ollama serve`)

Since MailTag is Mac-only (Apple Silicon), we had the option to use MLX for direct in-process inference.

## Decision

Replace litellm/Ollama with a hybrid MLX architecture:

- **Signal 5 (new)**: Semantic Router using `nomic-ai/nomic-embed-text-v1.5` embeddings for instant classification via cosine similarity against pre-computed category embeddings
- **Signal 6**: MLX LLM fallback using quantized models from `mlx-community` via `mlx-lm` for emails the semantic router can't classify

## Consequences

### Positive

- No external server dependency — inference runs in-process
- ~5-6x faster classification via embeddings (Signal 5 is near-instant)
- ~32% less memory vs running a separate Ollama process
- Model management via HuggingFace Hub (auto-download on first use)
- Configuration unified in `config.toml [mlx]` section

### Negative

- Apple Silicon only (no Linux/x86 support) — acceptable since project is Mac-only
- New dependencies: `mlx`, `mlx-lm`, `sentence-transformers`, `numpy`
- Category embeddings must be pre-computed and stored (`data/category_embeddings.npz`)

### Neutral

- Signals 1-4 (validated DB, server labels, historical DB, domain rules) remain unchanged
- Cloud providers (Gemini, OpenRouter) still available via `.env` MODEL variable for the litellm path

## Implementation

- `src/mailtag/mlx_provider.py` — `MLXEmbedder` and `MLXLLM` classes with lazy loading
- `src/mailtag/semantic_router.py` — embedding-based classification
- `src/mailtag/config.py` — `MLXConfig` dataclass
- `scripts/build_category_embeddings.py` — embedding pre-computation
