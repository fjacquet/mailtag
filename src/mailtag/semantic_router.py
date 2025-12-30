"""Semantic Router for embedding-based email classification.

This module provides fast, embedding-based classification that routes
emails to categories based on semantic similarity, without requiring
LLM inference.
"""

from __future__ import annotations

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

    def __init__(
        self,
        embedder: MLXEmbedder,
        score_threshold: float = 0.75,
    ):
        """Initialize the semantic router.

        Args:
            embedder: MLXEmbedder instance for generating embeddings
            score_threshold: Minimum similarity score to accept a route (0.0-1.0)
        """
        self.embedder = embedder
        self.score_threshold = score_threshold
        self.category_embeddings: dict[str, np.ndarray] = {}
        self.categories: list[str] = []
        self._embedding_matrix: np.ndarray | None = None
        logger.info(f"SemanticRouter initialized with threshold: {score_threshold}")

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
        except Exception as e:
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
        except Exception as e:
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

    def build_from_validated_db(self, validated_db: dict[str, str], min_examples: int = 1) -> None:
        """Build category embeddings from validated classification database.

        Args:
            validated_db: Dict mapping sender email to category
            min_examples: Minimum examples required per category
        """
        # Group by category
        category_senders: dict[str, list[str]] = {}
        for sender, category in validated_db.items():
            if category not in category_senders:
                category_senders[category] = []
            category_senders[category].append(sender)

        # Build examples from sender addresses
        category_examples: dict[str, list[str]] = {}
        for category, senders in category_senders.items():
            if len(senders) >= min_examples:
                # Use sender domain and category name as examples
                examples = []
                for sender in senders[:10]:  # Limit to 10 examples per category
                    # Create representative text from sender
                    domain = sender.split("@")[-1] if "@" in sender else sender
                    examples.append(f"Email from {domain} categorized as {category}")
                category_examples[category] = examples

        self.build_from_examples(category_examples)

    def route(self, text: str) -> tuple[str, float]:
        """Route text to the most similar category.

        Args:
            text: Input text to classify

        Returns:
            Tuple of (category, similarity_score)
            Returns ("", 0.0) if no category meets threshold
        """
        if not self.categories or self._embedding_matrix is None:
            logger.warning("No category embeddings loaded, cannot route")
            return "", 0.0

        # Compute query embedding
        query_embedding = self.embedder.encode_query(text)
        query_norm = query_embedding / np.linalg.norm(query_embedding)

        # Compute similarities with all categories
        similarities = np.dot(self._embedding_matrix, query_norm)

        # Find best match
        best_idx = np.argmax(similarities)
        best_score = similarities[best_idx]
        best_category = self.categories[best_idx]

        if best_score >= self.score_threshold:
            logger.debug(f"Routed to '{best_category}' with score {best_score:.3f}")
            return best_category, float(best_score)
        else:
            logger.debug(f"No route found (best: '{best_category}' with score {best_score:.3f})")
            return "", float(best_score)

    def route_with_alternatives(self, text: str, top_k: int = 3) -> list[tuple[str, float]]:
        """Route text and return top-k alternatives.

        Args:
            text: Input text to classify
            top_k: Number of top alternatives to return

        Returns:
            List of (category, score) tuples sorted by score descending
        """
        if not self.categories or self._embedding_matrix is None:
            return []

        query_embedding = self.embedder.encode_query(text)
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        similarities = np.dot(self._embedding_matrix, query_norm)

        # Get top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            results.append((self.categories[idx], float(similarities[idx])))

        return results

    def add_category(self, category: str, examples: list[str]) -> None:
        """Add a new category with examples.

        Args:
            category: Category name
            examples: List of example texts
        """
        if not examples:
            logger.warning(f"No examples provided for category '{category}'")
            return

        embeddings = self.embedder.encode_documents(examples)
        centroid = embeddings.mean(axis=0)
        self.category_embeddings[category] = centroid

        if category not in self.categories:
            self.categories.append(category)

        self._build_embedding_matrix()
        logger.info(f"Added category '{category}' with {len(examples)} examples")

    def remove_category(self, category: str) -> bool:
        """Remove a category.

        Args:
            category: Category name to remove

        Returns:
            True if removed, False if not found
        """
        if category not in self.category_embeddings:
            return False

        del self.category_embeddings[category]
        self.categories.remove(category)
        self._build_embedding_matrix()
        logger.info(f"Removed category '{category}'")
        return True

    @property
    def num_categories(self) -> int:
        """Return the number of loaded categories."""
        return len(self.categories)

    def get_category_info(self) -> dict[str, dict]:
        """Get information about loaded categories.

        Returns:
            Dict with category names and embedding dimensions
        """
        return {
            cat: {"embedding_dim": emb.shape[0]} for cat, emb in self.category_embeddings.items()
        }
