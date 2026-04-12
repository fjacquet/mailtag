"""Tests for MLX provider module."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestMLXEmbedder:
    """Test MLXEmbedder functionality."""

    def test_init_default_model(self):
        """Test initialization with default model."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()
        assert embedder.model_name == "nomic-ai/nomic-embed-text-v1.5"
        assert embedder._model is None  # Lazy loaded

    def test_init_custom_model(self):
        """Test initialization with custom model."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder("custom-model/name")
        assert embedder.model_name == "custom-model/name"

    def test_model_lazy_loading(self):
        """Test that model is lazy loaded."""
        from mailtag.mlx_provider import MLXEmbedder

        # Create mock SentenceTransformer
        mock_st = MagicMock()
        mock_model = MagicMock()
        mock_st.return_value = mock_model

        with patch.dict(sys.modules, {"sentence_transformers": MagicMock()}):
            with patch("sentence_transformers.SentenceTransformer", mock_st):
                embedder = MLXEmbedder()

                # Model not loaded yet - _model is None
                assert embedder._model is None

    def test_encode_single_text(self):
        """Test encoding a single text."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        embedder._model = mock_model

        result = embedder.encode("test text")

        mock_model.encode.assert_called_once()
        assert isinstance(result, np.ndarray)

    def test_encode_adds_prefix_for_nomic(self):
        """Test that nomic models get task prefixes."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder("nomic-ai/nomic-embed-text-v1.5")
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        embedder._model = mock_model

        embedder.encode("test", prefix="search_document: ")

        # Check that prefix was added
        call_args = mock_model.encode.call_args
        texts = call_args[0][0]
        assert texts[0].startswith("search_document: ")

    def test_encode_query(self):
        """Test encode_query uses correct prefix."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        embedder._model = mock_model

        result = embedder.encode_query("what is this?")

        # Should use search_query prefix
        call_args = mock_model.encode.call_args
        texts = call_args[0][0]
        assert texts[0].startswith("search_query: ")
        assert result.shape == (3,)  # Single embedding

    def test_encode_documents(self):
        """Test encode_documents uses correct prefix."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        embedder._model = mock_model

        result = embedder.encode_documents(["doc1", "doc2"])

        # Should use search_document prefix
        call_args = mock_model.encode.call_args
        texts = call_args[0][0]
        assert all(t.startswith("search_document: ") for t in texts)
        assert result.shape == (2, 3)

    def test_similarity_computation(self):
        """Test cosine similarity computation."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()

        # Create test embeddings
        query = np.array([1.0, 0.0, 0.0])
        docs = np.array(
            [
                [1.0, 0.0, 0.0],  # Same as query
                [0.0, 1.0, 0.0],  # Orthogonal
                [0.707, 0.707, 0.0],  # 45 degrees
            ]
        )

        similarities = embedder.similarity(query, docs)

        assert len(similarities) == 3
        assert similarities[0] == pytest.approx(1.0, rel=1e-3)  # Same vector
        assert similarities[1] == pytest.approx(0.0, rel=1e-3)  # Orthogonal
        assert similarities[2] == pytest.approx(0.707, rel=1e-2)  # 45 degrees


class TestMLXLLM:
    """Test MLXLLM functionality."""

    def test_init_default_model(self):
        """Test initialization with default model."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        assert llm.model_name == "mlx-community/gemma-4-e4b-it-OptiQ-4bit"
        assert llm.max_tokens == 256
        assert llm.temperature == 0.2
        assert llm._model is None

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM(
            model_name="custom/model",
            max_tokens=512,
            temperature=0.5,
        )
        assert llm.model_name == "custom/model"
        assert llm.max_tokens == 512
        assert llm.temperature == 0.5

    def test_model_lazy_loading(self):
        """Test that model is lazy loaded."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        # Model not loaded yet - _model is None
        assert llm._model is None

    def test_generate_basic(self):
        """Test basic text generation."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "formatted prompt"
        llm._model = mock_model
        llm._tokenizer = mock_tokenizer

        # Patch mlx_lm.generate and mlx_lm.sample_utils.make_sampler at module level
        mock_generate = MagicMock(return_value="  Generated response  ")
        mock_make_sampler = MagicMock(return_value=MagicMock())
        mock_sample_utils = MagicMock(make_sampler=mock_make_sampler)
        mock_mlx_lm = MagicMock(generate=mock_generate, sample_utils=mock_sample_utils)
        with patch.dict(
            sys.modules,
            {"mlx_lm": mock_mlx_lm, "mlx_lm.sample_utils": mock_sample_utils},
        ):
            result = llm.generate("Test prompt")

        assert result == "Generated response"  # Stripped

    def test_classify_json_response(self):
        """Test classification with JSON response."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "formatted prompt"
        llm._model = mock_model
        llm._tokenizer = mock_tokenizer

        json_response = '{"category": "Commerce/Amazon", "confidence": 0.95, "reason": "test"}'
        mock_generate = MagicMock(return_value=json_response)
        mock_make_sampler = MagicMock(return_value=MagicMock())
        mock_sample_utils = MagicMock(make_sampler=mock_make_sampler)
        mock_mlx_lm = MagicMock(generate=mock_generate, sample_utils=mock_sample_utils)
        with patch.dict(
            sys.modules,
            {"mlx_lm": mock_mlx_lm, "mlx_lm.sample_utils": mock_sample_utils},
        ):
            category, confidence, reason = llm.classify("Test prompt")

        assert category == "Commerce/Amazon"
        assert confidence == 0.95
        assert reason == "test"

    def test_classify_json_in_text(self):
        """Test classification with JSON embedded in text."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "formatted prompt"
        llm._model = mock_model
        llm._tokenizer = mock_tokenizer

        response = 'I classify this as {"category": "Finance", "confidence": 0.8, "reason": "invoice"}'
        mock_generate = MagicMock(return_value=response)
        mock_make_sampler = MagicMock(return_value=MagicMock())
        mock_sample_utils = MagicMock(make_sampler=mock_make_sampler)
        mock_mlx_lm = MagicMock(generate=mock_generate, sample_utils=mock_sample_utils)
        with patch.dict(
            sys.modules,
            {"mlx_lm": mock_mlx_lm, "mlx_lm.sample_utils": mock_sample_utils},
        ):
            category, confidence, reason = llm.classify("Test prompt")

        assert category == "Finance"
        assert confidence == 0.8

    def test_classify_invalid_json(self):
        """Test classification with invalid JSON response."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "formatted prompt"
        llm._model = mock_model
        llm._tokenizer = mock_tokenizer

        mock_generate = MagicMock(return_value="Commerce/Amazon")
        mock_make_sampler = MagicMock(return_value=MagicMock())
        mock_sample_utils = MagicMock(make_sampler=mock_make_sampler)
        mock_mlx_lm = MagicMock(generate=mock_generate, sample_utils=mock_sample_utils)
        with patch.dict(
            sys.modules,
            {"mlx_lm": mock_mlx_lm, "mlx_lm.sample_utils": mock_sample_utils},
        ):
            category, confidence, reason = llm.classify("Test prompt")

        # Fallback: raw response as category with low confidence
        assert category == "Commerce/Amazon"
        assert confidence == 0.5
        assert reason == "JSON parsing failed"

    def test_classify_confidence_clamping(self):
        """Test that confidence is clamped to [0, 1]."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "formatted prompt"
        llm._model = mock_model
        llm._tokenizer = mock_tokenizer

        mock_generate = MagicMock(return_value='{"category": "Test", "confidence": 1.5, "reason": ""}')
        mock_make_sampler = MagicMock(return_value=MagicMock())
        mock_sample_utils = MagicMock(make_sampler=mock_make_sampler)
        mock_mlx_lm = MagicMock(generate=mock_generate, sample_utils=mock_sample_utils)
        with patch.dict(
            sys.modules,
            {"mlx_lm": mock_mlx_lm, "mlx_lm.sample_utils": mock_sample_utils},
        ):
            _, confidence, _ = llm.classify("Test prompt")

        assert confidence == 1.0  # Clamped to max


class TestFactoryFunctions:
    """Test factory functions."""

    def test_get_embedder_default(self):
        """Test get_embedder with default model."""
        from mailtag.mlx_provider import get_embedder

        embedder = get_embedder()
        assert embedder.model_name == "nomic-ai/nomic-embed-text-v1.5"

    def test_get_embedder_custom(self):
        """Test get_embedder with custom model."""
        from mailtag.mlx_provider import get_embedder

        embedder = get_embedder("custom-model")
        assert embedder.model_name == "custom-model"

    def test_get_llm_default(self):
        """Test get_llm with default parameters."""
        from mailtag.mlx_provider import get_llm

        llm = get_llm()
        assert llm.max_tokens == 256
        assert llm.temperature == 0.2

    def test_get_llm_custom(self):
        """Test get_llm with custom parameters."""
        from mailtag.mlx_provider import get_llm

        llm = get_llm(
            model_name="custom/model",
            max_tokens=512,
            temperature=0.7,
        )
        assert llm.model_name == "custom/model"
        assert llm.max_tokens == 512
        assert llm.temperature == 0.7
