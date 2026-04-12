# MLX Provider

The MLX provider enables on-device AI inference on Apple Silicon via the MLX framework.

## Components

### MLXEmbedder

Generates text embeddings via `sentence-transformers` for the Semantic Router (Signal 5).

- Default model: `nomic-ai/nomic-embed-text-v1.5`
- Supports task-specific prefixes (`search_query:`, `search_document:`)
- Batch encoding for efficient multi-email processing
- Cosine similarity computation for category matching

### MLXLLM

Text generation via `mlx-lm` for classification fallback (Signal 6).

- Default model: `mlx-community/gemma-4-e4b-it-OptiQ-4bit`
- Uses `apply_chat_template` with `enable_thinking=False` for Gemma 4
- Strips residual `<|channel>thought...<channel|>` blocks as safety net
- KV cache quantization (`kv_bits=8`) with graceful fallback
- Cached sampler and generate function for reduced per-call overhead

## Lazy Loading

Both classes use lazy loading -- models are only downloaded and loaded on first use:

```python
embedder = MLXEmbedder()  # No model loaded yet
embedder.encode("text")    # Model loaded here on first call
```

## Configuration

Models are configured in `config.toml`:

```toml
[mlx]
enabled = true
embedding_model = "nomic-ai/nomic-embed-text-v1.5"
llm_model = "mlx-community/gemma-4-e4b-it-OptiQ-4bit"
llm_confidence = 0.85
llm_max_tokens = 128
llm_temperature = 0.2
```

## Performance Optimizations

- **Prompt prefix caching**: Static category list (~600-900 tokens) is built once and reused
- **Batch embeddings**: `route_batch()` encodes all pending emails in a single call
- **Cached sampler**: Reused across calls when temperature matches
- **KV cache quantization**: Reduces memory usage (when supported by model architecture)
