"""MLX-based AI providers for Apple Silicon optimized classification.

This module provides two main classes:
- MLXEmbedder: Generates text embeddings using sentence-transformers
- MLXLLM: Generates text using mlx-lm for classification fallback
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

    def encode_query(self, query: str) -> np.ndarray:
        """Encode a query text (for searching against documents).

        Args:
            query: The query text to encode

        Returns:
            Numpy array of shape (embedding_dim,)
        """
        return self.encode(query, prefix="search_query: ")[0]

    def encode_documents(self, documents: list[str]) -> np.ndarray:
        """Encode document texts (for building an index).

        Args:
            documents: List of document texts to encode

        Returns:
            Numpy array of shape (n_documents, embedding_dim)
        """
        return self.encode(documents, prefix="search_document: ")

    def similarity(self, query_embedding: np.ndarray, doc_embeddings: np.ndarray) -> np.ndarray:
        """Compute cosine similarity between query and document embeddings.

        Args:
            query_embedding: Query embedding of shape (embedding_dim,)
            doc_embeddings: Document embeddings of shape (n_docs, embedding_dim)

        Returns:
            Similarity scores of shape (n_docs,)
        """
        # Normalize embeddings
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        doc_norms = doc_embeddings / np.linalg.norm(doc_embeddings, axis=1, keepdims=True)

        # Compute cosine similarity
        similarities = np.dot(doc_norms, query_norm)
        return similarities


class MLXLLM:
    """Generates text using mlx-lm for classification fallback.

    Uses quantized models from mlx-community for efficient inference
    on Apple Silicon.
    """

    def __init__(
        self,
        model_name: str = "mlx-community/gemma-4-e4b-it-OptiQ-4bit",
        max_tokens: int = 256,
        temperature: float = 0.2,
    ):
        """Initialize the LLM with the specified model.

        Args:
            model_name: MLX model name from mlx-community
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (lower = more deterministic)
        """
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._model = None
        self._tokenizer = None
        self._generate_fn = None
        self._sampler = None
        logger.info(f"MLXLLM initialized with model: {model_name}")

    def _load_model(self):
        """Lazy load the model, tokenizer, sampler, and generate function."""
        if self._model is None:
            logger.info(f"Loading LLM model: {self.model_name}")
            from mlx_lm import generate as mlx_generate
            from mlx_lm import load
            from mlx_lm.sample_utils import make_sampler

            self._model, self._tokenizer = load(self.model_name)
            self._generate_fn = mlx_generate
            self._sampler = make_sampler(temp=self.temperature)
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

    def generate(self, prompt: str, max_tokens: int | None = None, temperature: float | None = None) -> str:
        """Generate text completion for the given prompt.

        Args:
            prompt: The input prompt
            max_tokens: Override default max tokens
            temperature: Override default temperature

        Returns:
            Generated text response
        """
        max_tokens = max_tokens or self.max_tokens
        temperature = temperature or self.temperature

        # Apply chat template if available
        if hasattr(self.tokenizer, "apply_chat_template"):
            messages = [{"role": "user", "content": prompt}]
            # Disable thinking mode to get direct JSON output
            try:
                formatted_prompt = self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )
            except TypeError:
                # Fallback for tokenizers that don't support enable_thinking
                formatted_prompt = self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
        else:
            formatted_prompt = prompt

        # Use cached sampler if temperature matches, otherwise create new one
        if self._sampler is not None and temperature == self.temperature:
            sampler = self._sampler
        else:
            from mlx_lm.sample_utils import make_sampler

            sampler = make_sampler(temp=temperature)

        generate_fn = self._generate_fn
        if generate_fn is None:
            from mlx_lm import generate as generate_fn

        try:
            response = generate_fn(
                self.model,
                self.tokenizer,
                prompt=formatted_prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                kv_bits=8,
                verbose=False,
            )
        except (TypeError, NotImplementedError):
            # Fallback: kv_bits not supported by mlx-lm version or model architecture
            logger.debug("KV cache quantization not available, falling back without kv_bits")
            response = generate_fn(
                self.model,
                self.tokenizer,
                prompt=formatted_prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                verbose=False,
            )

        return response.strip()

    def classify(self, prompt: str) -> tuple[str, float, str]:
        """Generate a classification response and parse it.

        Args:
            prompt: The classification prompt (should request JSON output)

        Returns:
            Tuple of (category, confidence, reason)
        """
        import json
        import re

        response = self.generate(prompt)

        # Strip thinking blocks from response (Gemma 4: <|channel>thought...<channel|>)
        response = re.sub(r"<\|channel>thought.*?<channel\|>", "", response, count=1, flags=re.DOTALL)

        # Try to parse JSON response (allow nested braces)
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
                category = result.get("category", "").strip()
                confidence = float(result.get("confidence", 0.0))
                reason = result.get("reason", "")

                # Validate confidence range
                confidence = max(0.0, min(1.0, confidence))

                return category, confidence, reason
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        # Fallback: return raw response as category with low confidence
        logger.warning(f"Failed to parse JSON from LLM response: {response[:100]}...")
        return response.strip(), 0.5, "JSON parsing failed"


def get_embedder(model_name: str | None = None) -> MLXEmbedder:
    """Factory function to get an MLXEmbedder instance.

    Args:
        model_name: Optional model name override

    Returns:
        MLXEmbedder instance
    """
    if model_name:
        return MLXEmbedder(model_name)
    return MLXEmbedder()


def get_llm(
    model_name: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.2,
) -> MLXLLM:
    """Factory function to get an MLXLLM instance.

    Args:
        model_name: Optional model name override
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature

    Returns:
        MLXLLM instance
    """
    if model_name:
        return MLXLLM(model_name, max_tokens, temperature)
    return MLXLLM(max_tokens=max_tokens, temperature=temperature)
