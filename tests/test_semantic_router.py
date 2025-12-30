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
        embedder.encode_documents.return_value = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        embedder.encode_query.return_value = np.array([0.9, 0.1, 0.0])
        return embedder

    def test_init_default_threshold(self, mock_embedder):
        """Test initialization with default threshold."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        assert router.score_threshold == 0.75
        assert router.categories == []
        assert router._embedding_matrix is None

    def test_init_custom_threshold(self, mock_embedder):
        """Test initialization with custom threshold."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder, score_threshold=0.9)
        assert router.score_threshold == 0.9

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

    def test_route_finds_best_match(self, mock_embedder):
        """Test that routing finds the best matching category."""
        from mailtag.semantic_router import SemanticRouter

        # Setup embedder to return specific embeddings
        mock_embedder.encode_documents.return_value = np.array([
            [1.0, 0.0, 0.0],  # Commerce
            [0.0, 1.0, 0.0],  # Finance
            [0.0, 0.0, 1.0],  # Travel
        ])
        # Query embedding is close to Commerce
        mock_embedder.encode_query.return_value = np.array([0.95, 0.05, 0.0])

        router = SemanticRouter(mock_embedder, score_threshold=0.5)
        router.build_from_examples({
            "Commerce": ["shopping"],
            "Finance": ["banking"],
            "Travel": ["flights"],
        })

        category, score = router.route("shopping related query")

        assert category == "Commerce"
        assert score > 0.5

    def test_route_below_threshold_returns_empty(self, mock_embedder):
        """Test that routing below threshold returns empty."""
        from mailtag.semantic_router import SemanticRouter

        # Setup embedder with orthogonal embeddings
        mock_embedder.encode_documents.return_value = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ])
        # Query embedding is not close to any category
        mock_embedder.encode_query.return_value = np.array([0.3, 0.3, 0.9])

        router = SemanticRouter(mock_embedder, score_threshold=0.75)
        router.build_from_examples({
            "Cat1": ["example1"],
            "Cat2": ["example2"],
        })

        category, score = router.route("unrelated query")

        assert category == ""
        assert score < 0.75

    def test_route_no_categories_returns_empty(self, mock_embedder):
        """Test routing with no categories loaded."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)

        category, score = router.route("any query")

        assert category == ""
        assert score == 0.0

    def test_route_with_alternatives(self, mock_embedder):
        """Test getting top-k alternatives."""
        from mailtag.semantic_router import SemanticRouter

        # Setup embeddings
        mock_embedder.encode_documents.return_value = np.array([
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
        ])
        mock_embedder.encode_query.return_value = np.array([0.95, 0.05, 0.0])

        router = SemanticRouter(mock_embedder)
        router.build_from_examples({
            "Cat1": ["ex1"],
            "Cat2": ["ex2"],
            "Cat3": ["ex3"],
        })

        alternatives = router.route_with_alternatives("query", top_k=2)

        assert len(alternatives) == 2
        assert all(isinstance(alt, tuple) for alt in alternatives)
        assert all(len(alt) == 2 for alt in alternatives)
        # Results should be sorted by score descending
        assert alternatives[0][1] >= alternatives[1][1]

    def test_add_category(self, mock_embedder):
        """Test adding a new category."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        router.build_from_examples({"Existing": ["example"]})

        assert "Existing" in router.categories
        assert "NewCat" not in router.categories

        mock_embedder.encode_documents.return_value = np.array([[0.5, 0.5, 0.0]])
        router.add_category("NewCat", ["new example"])

        assert "NewCat" in router.categories
        assert router.num_categories == 2

    def test_add_category_empty_examples_ignored(self, mock_embedder):
        """Test that adding category with empty examples is ignored."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        initial_count = router.num_categories

        router.add_category("Empty", [])

        assert router.num_categories == initial_count

    def test_remove_category(self, mock_embedder):
        """Test removing a category."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        router.build_from_examples({
            "Cat1": ["ex1"],
            "Cat2": ["ex2"],
        })

        assert "Cat1" in router.categories
        result = router.remove_category("Cat1")

        assert result is True
        assert "Cat1" not in router.categories
        assert router.num_categories == 1

    def test_remove_nonexistent_category(self, mock_embedder):
        """Test removing a non-existent category."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        result = router.remove_category("NonExistent")

        assert result is False

    def test_save_and_load_embeddings(self, mock_embedder):
        """Test saving and loading embeddings."""
        from mailtag.semantic_router import SemanticRouter

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "embeddings.npz"

            # Build and save
            router1 = SemanticRouter(mock_embedder)
            router1.build_from_examples({
                "Cat1": ["ex1"],
                "Cat2": ["ex2"],
            })
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

        router.build_from_examples({
            "Cat1": ["ex1"],
            "Cat2": ["ex2"],
            "Cat3": ["ex3"],
        })
        assert router.num_categories == 3

    def test_get_category_info(self, mock_embedder):
        """Test getting category info."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        router.build_from_examples({
            "Cat1": ["ex1"],
            "Cat2": ["ex2"],
        })

        info = router.get_category_info()

        assert "Cat1" in info
        assert "Cat2" in info
        assert "embedding_dim" in info["Cat1"]
        assert info["Cat1"]["embedding_dim"] == 3

    def test_build_from_validated_db(self, mock_embedder):
        """Test building from validated database."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)

        validated_db = {
            "user@amazon.com": "Commerce/Amazon",
            "orders@amazon.com": "Commerce/Amazon",
            "info@bank.com": "Finance/Banking",
            "single@test.com": "OneEmail",  # Only 1 example
        }

        router.build_from_validated_db(validated_db, min_examples=1)

        assert "Commerce/Amazon" in router.categories
        assert "Finance/Banking" in router.categories
        assert "OneEmail" in router.categories

    def test_build_from_validated_db_min_examples(self, mock_embedder):
        """Test that min_examples filter works."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)

        validated_db = {
            "user@amazon.com": "Commerce/Amazon",
            "orders@amazon.com": "Commerce/Amazon",
            "single@test.com": "OneEmail",  # Only 1 example
        }

        router.build_from_validated_db(validated_db, min_examples=2)

        assert "Commerce/Amazon" in router.categories
        assert "OneEmail" not in router.categories  # Filtered out


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
        mock_embedder.encode_documents.return_value = np.array([
            [3.0, 4.0, 0.0],  # Norm = 5
            [0.0, 2.0, 0.0],  # Norm = 2
        ])

        router = SemanticRouter(mock_embedder)
        router.build_from_examples({
            "Cat1": ["ex1"],
            "Cat2": ["ex2"],
        })

        # Check that rows are normalized
        norms = np.linalg.norm(router._embedding_matrix, axis=1)
        np.testing.assert_array_almost_equal(norms, [1.0, 1.0])

    def test_empty_embeddings_no_matrix(self, mock_embedder):
        """Test that empty embeddings result in no matrix."""
        from mailtag.semantic_router import SemanticRouter

        router = SemanticRouter(mock_embedder)
        router._build_embedding_matrix()

        assert router._embedding_matrix is None
