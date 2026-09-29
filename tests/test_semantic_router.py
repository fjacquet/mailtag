"""Tests for SemanticRouter module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


class TestSemanticRouter:
    """Test SemanticRouter functionality."""

    @pytest.fixture
    def mock_embedder(self):
        """Create a mock embedder."""
        embedder = MagicMock()
        embedder.encode_documents.return_value = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        return embedder

    def test_init_defaults(self, mock_embedder):
        """Test initialization defaults."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        assert router.categories == []
        assert router._embedding_matrix is None

    def test_build_from_examples(self, mock_embedder):
        """Test building embeddings from examples."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)

        examples = {
            "Commerce": ["shopping email", "order confirmation"],
            "Finance": ["invoice", "payment"],
            "Travel": ["flight booking", "hotel reservation"],
        }

        router.build_from_examples(examples)

        assert len(router.categories) == 3
        assert "Commerce" in router.categories
        assert "Finance" in router.categories
        assert "Travel" in router.categories
        assert router._embedding_matrix is not None

    def test_build_from_examples_empty_skipped(self, mock_embedder):
        """Test that empty categories are skipped."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)

        examples = {
            "Valid": ["example1", "example2"],
            "Empty": [],  # Should be skipped
        }

        router.build_from_examples(examples)

        assert len(router.categories) == 1
        assert "Valid" in router.categories
        assert "Empty" not in router.categories

    def test_save_and_load_embeddings(self, mock_embedder):
        """Test saving and loading embeddings."""
        from mailtag.semantic_router import SemanticRouter

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "embeddings.npz"

            # Build and save
            router1 = SemanticRouter(mock_embedder)
            router1.build_from_examples(
                {
                    "Cat1": ["ex1"],
                    "Cat2": ["ex2"],
                }
            )
            save_result = router1.save_embeddings(filepath)

            assert save_result is True
            assert filepath.exists()

            # Load in new router
            router2 = SemanticRouter(mock_embedder)
            load_result = router2.load_embeddings(filepath)

            assert load_result is True
            assert router2.num_categories == router1.num_categories
            assert set(router2.categories) == set(router1.categories)

    def test_load_nonexistent_file(self, mock_embedder):
        """Test loading from non-existent file."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        result = router.load_embeddings(Path("/nonexistent/path.npz"))

        assert result is False
        assert router.num_categories == 0

    def test_num_categories_property(self, mock_embedder):
        """Test num_categories property."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        assert router.num_categories == 0

        router.build_from_examples(
            {
                "Cat1": ["ex1"],
                "Cat2": ["ex2"],
                "Cat3": ["ex3"],
            }
        )
        assert router.num_categories == 3


class TestSemanticRouterEmbeddingMatrix:
    """Test embedding matrix operations."""

    @pytest.fixture
    def mock_embedder(self):
        """Create a mock embedder."""
        embedder = MagicMock()
        return embedder

    def test_embedding_matrix_normalized(self, mock_embedder):
        """Test that embedding matrix is normalized."""
        from mailtag.semantic_router import SemanticRouter

        # Return non-normalized embeddings
        mock_embedder.encode_documents.return_value = np.array(
            [
                [3.0, 4.0, 0.0],  # Norm = 5
                [0.0, 2.0, 0.0],  # Norm = 2
            ]
        )

        router = SemanticRouter(mock_embedder)
        router.build_from_examples(
            {
                "Cat1": ["ex1"],
                "Cat2": ["ex2"],
            }
        )

        # Check that rows are normalized
        norms = np.linalg.norm(router._embedding_matrix, axis=1)
        np.testing.assert_array_almost_equal(norms, [1.0, 1.0])

    def test_empty_embeddings_no_matrix(self, mock_embedder):
        """Test that empty embeddings result in no matrix."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        router._build_embedding_matrix()

        assert router._embedding_matrix is None


def test_top_batch_returns_nearest_category(mocker):
    import numpy as np

    from mailtag.semantic_router import SemanticRouter

    embedder = mocker.MagicMock()
    embedder.encode.return_value = np.array([[1.0, 0.0], [0.6, 0.8]])
    router = SemanticRouter(embedder)
    router.category_embeddings = {"A": np.array([1.0, 0.0]), "B": np.array([0.0, 1.0])}
    router.categories = ["A", "B"]
    router._build_embedding_matrix()

    top = router.top_batch(["x", "y"])

    assert [c for c, _ in top] == ["A", "B"]
    assert top[1][1] == pytest.approx(0.8)


def test_top_batch_without_centroids(mocker):
    from mailtag.semantic_router import SemanticRouter

    assert SemanticRouter(mocker.MagicMock()).top_batch(["x"]) == [("", 0.0)]
