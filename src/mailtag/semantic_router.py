"""Semantic Router for embedding-based email classification.

This module provides fast, embedding-based classification that routes
emails to categories based on semantic similarity, without requiring
LLM inference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from mailtag.mlx_provider import MLXEmbedder


class SemanticRouter:
    """Routes text to categories based on embedding similarity.

    Uses pre-computed category embeddings to instantly classify
    emails based on semantic similarity to category centroids.
    """

    def __init__(self, embedder: MLXEmbedder):
        """Initialize the semantic router.

        Args:
            embedder: MLXEmbedder instance for generating embeddings
        """
        self.embedder = embedder
        self.category_embeddings: dict[str, np.ndarray] = {}
        self.categories: list[str] = []
        self._embedding_matrix: np.ndarray | None = None
        logger.info("SemanticRouter initialized")

    def load_embeddings(self, path: Path | str) -> bool:
        """Load pre-computed category embeddings from file.

        Args:
            path: Path to the .npz file containing embeddings

        Returns:
            True if loaded successfully, False otherwise
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"Embeddings file not found: {path}")
            return False

        try:
            data = np.load(path, allow_pickle=True)
            self.category_embeddings = {key: data[key] for key in data.files}
            self.categories = list(self.category_embeddings.keys())
            self._build_embedding_matrix()
            logger.info(f"Loaded embeddings for {len(self.categories)} categories from {path}")
            return True
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to load embeddings from {path}: {e}")
            return False

    def save_embeddings(self, path: Path | str) -> bool:
        """Save category embeddings to file.

        Args:
            path: Path to save the .npz file

        Returns:
            True if saved successfully, False otherwise
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            np.savez(path, **self.category_embeddings)
            logger.info(f"Saved embeddings for {len(self.categories)} categories to {path}")
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to save embeddings to {path}: {e}")
            return False

    def _build_embedding_matrix(self):
        """Build the embedding matrix for efficient similarity computation."""
        if not self.category_embeddings:
            self._embedding_matrix = None
            return

        self._embedding_matrix = np.stack([self.category_embeddings[cat] for cat in self.categories])
        # Normalize for cosine similarity
        norms = np.linalg.norm(self._embedding_matrix, axis=1, keepdims=True)
        self._embedding_matrix = self._embedding_matrix / norms

    def build_from_examples(self, category_examples: dict[str, list[str]]) -> None:
        """Build category embeddings from example texts.

        Args:
            category_examples: Dict mapping category names to lists of example texts
        """
        logger.info(f"Building embeddings for {len(category_examples)} categories...")

        for category, examples in category_examples.items():
            if not examples:
                logger.warning(f"No examples for category '{category}', skipping")
                continue

            # Compute embeddings for all examples
            embeddings = self.embedder.encode_documents(examples)

            # Use centroid (mean) as category embedding
            centroid = embeddings.mean(axis=0)
            self.category_embeddings[category] = centroid

            logger.debug(f"Built embedding for '{category}' from {len(examples)} examples")

        self.categories = list(self.category_embeddings.keys())
        self._build_embedding_matrix()
        logger.info(f"Built embeddings for {len(self.categories)} categories")

    def top_batch(self, texts: list[str]) -> list[tuple[str, float]]:
        """Return the nearest category and its similarity for each text, without threshold."""
        if not self.categories or self._embedding_matrix is None:
            return [("", 0.0)] * len(texts)
        if not texts:
            return []

        query_embeddings = self.embedder.encode(texts, prefix="search_query: ")
        norms = np.linalg.norm(query_embeddings, axis=1, keepdims=True)
        similarities = np.dot(query_embeddings / norms, self._embedding_matrix.T)

        best = np.argmax(similarities, axis=1)
        return [(self.categories[j], float(similarities[i][j])) for i, j in enumerate(best)]

    @property
    def num_categories(self) -> int:
        """Return the number of loaded categories."""
        return len(self.categories)
