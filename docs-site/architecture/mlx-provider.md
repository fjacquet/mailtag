# MLX Provider

The MLX provider enables on-device AI inference on Apple Silicon via the MLX framework.

## Components

### MLXEmbedder

Generates text embeddings via `sentence-transformers` for the Semantic Router (nomic centroids).

- Default model: `nomic-ai/nomic-embed-text-v1.5`
- Supports task-specific prefixes (`search_query:`, `search_document:`)
- Batch encoding for efficient multi-email processing
- Cosine similarity against the category centroids is done by `SemanticRouter`

### MLXLLM

Answers short prompts in batches via `mlx-lm` (Gemma, by category number).

- Default model: `mlx-community/gemma-4-e4b-it-OptiQ-4bit`
- Uses `apply_chat_template` with `enable_thinking=False` for Gemma 4

## Lazy Loading

Both classes use lazy loading -- models are only downloaded and loaded on first use:

```python
embedder = MLXEmbedder()  # No model loaded yet
embedder.encode("text")  # Model loaded here on first call
```

## Configuration

Models are configured in `config.toml`:

```toml
[mlx]
enabled = true
embedding_model = "nomic-ai/nomic-embed-text-v1.5"
llm_model = "mlx-community/gemma-4-e4b-it-OptiQ-4bit"
```

## Performance Optimizations

- **Prompt prefix caching**: Static category list (~600-900 tokens) is built once and reused
- **Batch embeddings**: `top_batch()` encodes all pending emails in a single call
