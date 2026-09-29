"""MLX-based AI providers for Apple Silicon optimized classification.

This module provides two main classes:
- MLXEmbedder: Generates text embeddings using sentence-transformers
- MLXLLM: answers short prompts in batches (Signal 6)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class MLXEmbedder:
    """Generates embeddings using sentence-transformers with MLX backend.

    Supports models like nomic-ai/nomic-embed-text-v1.5 which are optimized
    for semantic similarity tasks and support long context (8k tokens).
    """

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5"):
        """Initialize the embedder with the specified model.

        Args:
            model_name: HuggingFace model name for embeddings
        """
        self.model_name = model_name
        self._model: SentenceTransformer | None = None
        logger.info(f"MLXEmbedder initialized with model: {model_name}")

    @property
    def model(self) -> SentenceTransformer:
        """Lazy load the embedding model."""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
            logger.info("Embedding model loaded successfully")
        return self._model

    def encode(self, texts: list[str] | str, prefix: str = "search_document: ") -> np.ndarray:
        """Generate embeddings for the given texts.

        Args:
            texts: Single text or list of texts to encode
            prefix: Prefix to add to each text (nomic models use task prefixes)

        Returns:
            Numpy array of embeddings with shape (n_texts, embedding_dim)
        """
        if isinstance(texts, str):
            texts = [texts]

        # Add prefix for nomic models (they use task-specific prefixes)
        if "nomic" in self.model_name.lower():
            texts = [f"{prefix}{text}" for text in texts]

        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings

    def encode_documents(self, documents: list[str]) -> np.ndarray:
        """Encode document texts (for building an index).

        Args:
            documents: List of document texts to encode

        Returns:
            Numpy array of shape (n_documents, embedding_dim)
        """
        return self.encode(documents, prefix="search_document: ")


class MLXLLM:
    """Answers short prompts in batches using mlx-lm (Signal 6).

    Uses quantized models from mlx-community for efficient inference
    on Apple Silicon.
    """

    def __init__(self, model_name: str = "mlx-community/gemma-4-e4b-it-OptiQ-4bit"):
        """Initialize the LLM with the specified model.

        Args:
            model_name: MLX model name from mlx-community
        """
        self.model_name = model_name
        self._model = None
        self._tokenizer = None
        self._prefix_key: str | None = None
        self._prefix_cache = None
        self._prefix_post = ""
        logger.info(f"MLXLLM initialized with model: {model_name}")

    def _load_model(self):
        """Lazy load the model and tokenizer."""
        if self._model is None:
            logger.info(f"Loading LLM model: {self.model_name}")
            from mlx_lm import load

            self._model, self._tokenizer = load(self.model_name)
            logger.info("LLM model loaded successfully")

    @property
    def model(self):
        """Get the loaded model."""
        self._load_model()
        return self._model

    @property
    def tokenizer(self):
        """Get the loaded tokenizer."""
        self._load_model()
        return self._tokenizer

    def classify_batch(
        self, static_prompt: str, email_parts: list[str], batch_size: int = 8, max_tokens: int = 4
    ) -> list[str]:
        """Answer one short prompt per email, reusing the KV cache of the shared static prefix.

        The chat-formatted prompt is `static_prompt + email_part`; the static part is prefilled once
        per distinct value and each email only prefills its own tokens. Emails run in batches.
        """
        import copy

        import mlx.core as mx
        from mlx_lm import batch_generate
        from mlx_lm.generate import generate_step
        from mlx_lm.models.cache import make_prompt_cache
        from mlx_lm.sample_utils import make_sampler

        if not email_parts:
            return []

        if self._prefix_key != static_prompt:
            marker = "<<<EMAIL>>>"
            messages = [{"role": "user", "content": static_prompt + marker}]
            try:
                template = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
                )
            except TypeError:
                template = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            pre, self._prefix_post = template.split(marker)
            cache = make_prompt_cache(self.model)
            for _ in generate_step(
                mx.array(self.tokenizer.encode(pre)), self.model, max_tokens=0, prompt_cache=cache
            ):
                pass
            self._prefix_cache, self._prefix_key = cache, static_prompt

        suffixes = [
            self.tokenizer.encode(part + self._prefix_post, add_special_tokens=False) for part in email_parts
        ]
        sampler = make_sampler(temp=0.0)
        texts: list[str] = []
        for start in range(0, len(suffixes), batch_size):
            chunk = suffixes[start : start + batch_size]
            response = batch_generate(
                self.model,
                self.tokenizer,
                chunk,
                prompt_caches=[copy.deepcopy(self._prefix_cache) for _ in chunk],
                max_tokens=max_tokens,
                sampler=sampler,
            )
            texts.extend(text.strip() for text in response.texts)
        return texts
