# ADR-002: Switch MLX LLM from Mistral 7B to Gemma 4 E4B

## Status

Accepted (implemented)

## Date

2026-04-12

## Context

The MLX LLM fallback (Signal 6) used `mlx-community/Mistral-7B-Instruct-v0.3-4bit` (7B params, 4-bit quantized). While functional, we evaluated whether newer models could improve:

- Structured JSON output reliability (`{category, confidence, reason}`)
- French language classification quality (prompts are in French)
- Inference speed on Apple Silicon
- Memory efficiency

Google released Gemma 4 (April 2026) with E4B, 26B MoE, and 31B dense variants, all Apache 2.0 licensed with 140+ language support.

## Decision

Switch to `mlx-community/gemma-4-e4b-it-OptiQ-4bit` (Gemma 4 E4B, 4-bit quantized).

### Why E4B over other Gemma 4 variants

| Variant | Active Params | RAM (4-bit) | Fit |
|---------|---------------|-------------|-----|
| E2B | ~2B | ~2 GB | Too small for classification quality |
| **E4B** | **~4B** | **~4 GB** | **Best balance: similar RAM to Mistral 7B, native JSON** |
| 26B MoE | ~3.8B active | ~18 GB | Overkill for email classification |
| 31B Dense | 31B | ~20 GB | Too large for this use case |

## Consequences

### Positive

- Native structured JSON + function-calling support (fewer parsing failures)
- Stronger multilingual/French performance (82% MMLU multilingual)
- Similar or lower RAM footprint (~4 GB vs ~4-5 GB for Mistral 7B)
- Faster inference (fewer effective parameters)

### Negative

- Gemma 4 defaults to "thinking mode" (`<|channel>thought...`), which consumed the entire token budget before producing JSON output

### Thinking mode fix

Two-part solution based on [official Gemma 4 documentation](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4):

1. **Prevention**: Pass `enable_thinking=False` to `tokenizer.apply_chat_template()` — prevents the `<|think|>` system token from being included
2. **Safety net**: Strip residual `<|channel>thought...<channel|>` blocks from responses before JSON parsing

### Other changes

- `llm_max_tokens` reduced from 256 → 128 (JSON classification is <80 tokens; halves generation time)
- Config loader refactored: `_dataclass_from_dict()` eliminates duplicated defaults between `config.toml`, `MLXConfig` dataclass, and `MLXLLM.__init__`

## Implementation

- `config.toml [mlx]` — `llm_model` updated
- `src/mailtag/config.py` — dataclass default updated, loader refactored
- `src/mailtag/mlx_provider.py` — `enable_thinking=False`, response stripping, updated default
- `tests/test_mlx_provider.py` — default model assertion updated
