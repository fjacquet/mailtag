"""Tests for MLX provider module."""

import sys

import numpy as np
from pytest_mock import MockerFixture


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

    def test_model_lazy_loading(self, mocker: MockerFixture):
        """Test that model is lazy loaded."""
        from mailtag.mlx_provider import MLXEmbedder

        # Create mock SentenceTransformer
        mock_st = mocker.MagicMock()
        mock_model = mocker.MagicMock()
        mock_st.return_value = mock_model

        mocker.patch.dict(sys.modules, {"sentence_transformers": mocker.MagicMock()})
        mocker.patch("sentence_transformers.SentenceTransformer", mock_st)
        embedder = MLXEmbedder()

        # Model not loaded yet - _model is None
        assert embedder._model is None

    def test_encode_single_text(self, mocker: MockerFixture):
        """Test encoding a single text."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()
        mock_model = mocker.MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        embedder._model = mock_model

        result = embedder.encode("test text")

        mock_model.encode.assert_called_once()
        assert isinstance(result, np.ndarray)

    def test_encode_adds_prefix_for_nomic(self, mocker: MockerFixture):
        """Test that nomic models get task prefixes."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder("nomic-ai/nomic-embed-text-v1.5")
        mock_model = mocker.MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        embedder._model = mock_model

        embedder.encode("test", prefix="search_document: ")

        # Check that prefix was added
        call_args = mock_model.encode.call_args
        texts = call_args[0][0]
        assert texts[0].startswith("search_document: ")

    def test_encode_documents(self, mocker: MockerFixture):
        """Test encode_documents uses correct prefix."""
        from mailtag.mlx_provider import MLXEmbedder

        embedder = MLXEmbedder()
        mock_model = mocker.MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        embedder._model = mock_model

        result = embedder.encode_documents(["doc1", "doc2"])

        # Should use search_document prefix
        call_args = mock_model.encode.call_args
        texts = call_args[0][0]
        assert all(t.startswith("search_document: ") for t in texts)
        assert result.shape == (2, 3)


class TestMLXLLM:
    """Test MLXLLM functionality."""

    def test_init_default_model(self):
        """Test initialization with default model."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        assert llm.model_name == "mlx-community/gemma-4-e4b-it-OptiQ-4bit"
        assert llm._model is None

    def test_model_lazy_loading(self):
        """Test that model is lazy loaded."""
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        # Model not loaded yet - _model is None
        assert llm._model is None


class TestMLXLLMClassifyBatch:
    def _fake_mlx(self, mocker):
        fake_mlx_lm = mocker.MagicMock()
        fake_mlx_lm.batch_generate.side_effect = lambda model, tok, prompts, **kw: mocker.MagicMock(
            texts=[f" {i + 1}\n" for i in range(len(prompts))]
        )
        fake_generate = mocker.MagicMock()
        fake_generate.generate_step.return_value = iter([])
        fake_cache = mocker.MagicMock()
        fake_cache.make_prompt_cache.return_value = ["kv"]
        mocker.patch.dict(
            sys.modules,
            {
                "mlx": mocker.MagicMock(),
                "mlx.core": mocker.MagicMock(),
                "mlx_lm": fake_mlx_lm,
                "mlx_lm.generate": fake_generate,
                "mlx_lm.models": mocker.MagicMock(),
                "mlx_lm.models.cache": fake_cache,
                "mlx_lm.sample_utils": mocker.MagicMock(),
            },
        )
        return fake_mlx_lm, fake_generate

    def _llm(self, mocker):
        from mailtag.mlx_provider import MLXLLM

        llm = MLXLLM()
        llm._model = mocker.MagicMock()
        tokenizer = mocker.MagicMock()
        tokenizer.apply_chat_template.return_value = "<bos>PRE<<<EMAIL>>>POST"
        tokenizer.encode.side_effect = lambda text, add_special_tokens=True: list(range(len(text)))
        llm._tokenizer = tokenizer
        return llm

    def test_batches_and_returns_raw_answers(self, mocker):
        fake_mlx_lm, _ = self._fake_mlx(mocker)
        llm = self._llm(mocker)

        answers = llm.classify_batch("STATIC", ["a", "b", "c"], batch_size=2)

        assert answers == ["1", "2", "1"]
        assert fake_mlx_lm.batch_generate.call_count == 2
        first_call = fake_mlx_lm.batch_generate.call_args_list[0]
        assert len(first_call.kwargs["prompt_caches"]) == 2
        assert first_call.kwargs["max_tokens"] == 4

    def test_prefix_computed_once_per_static_prompt(self, mocker):
        _, fake_generate = self._fake_mlx(mocker)
        llm = self._llm(mocker)

        llm.classify_batch("STATIC", ["a"])
        llm.classify_batch("STATIC", ["b"])
        llm.classify_batch("OTHER", ["c"])

        assert fake_generate.generate_step.call_count == 2

    def test_empty_input(self, mocker):
        self._fake_mlx(mocker)
        assert self._llm(mocker).classify_batch("STATIC", []) == []
