"""Tests for AI confidence scoring functionality."""

from unittest.mock import Mock, patch

import pytest

from mailtag.classifier import Classifier
from mailtag.config import (
    AppConfig,
    ClassifierConfig,
    FastParseConfig,
    GeneralConfig,
    GmailConfig,
    ImapConfig,
    LoggingConfig,
    MLXConfig,
)
from mailtag.database import ClassificationDatabase
from mailtag.models import Email


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
            use_imap_folders_for_classification=True,
        ),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85, historical_confidence_threshold=0.9, min_count=10
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        imap=ImapConfig(host="test", user="test", password="test"),
        gmail=GmailConfig(credentials_file="test.json", token_file="test.json"),
        fast_parse=FastParseConfig(
            batch_size=100,
            folder_cache_ttl_hours=24,
            unclassified_folder_name="Unclassified",
            junk_folder_name="Junk",
        ),
        mlx=MLXConfig(enabled=False),  # Disable MLX for unit tests
    )


@pytest.fixture
def mock_database():
    """Create a mock classification database."""
    db = Mock(spec=ClassificationDatabase)
    db.suggestion_db = {}
    db.get_dominant_classification = Mock(return_value=None)
    db.update_suggestion = Mock()
    db.get_category_by_domain = Mock(return_value=None)
    return db


@pytest.fixture
def mock_folder_analyzer():
    """Create a mock folder analyzer."""
    analyzer = Mock()
    analyzer.get_all_categories = Mock(
        return_value=["Finance/Banking", "Services/Professional", "Shopping/Online"]
    )
    analyzer.get_parent_folders = Mock(return_value=["Finance", "Services", "Shopping"])
    analyzer.is_valid_parent_folder = Mock(return_value=True)
    return analyzer


@pytest.fixture
def classifier(mock_config, mock_database, mock_folder_analyzer):
    """Create a classifier instance with mocked dependencies."""
    with patch("mailtag.classifier.FolderAnalyzer", return_value=mock_folder_analyzer):
        clf = Classifier(mock_config, mock_database)
        clf.folder_analyzer = mock_folder_analyzer
        clf.categories = ["Finance/Banking", "Services/Professional", "Shopping/Online"]
    return clf


@pytest.fixture
def sample_email():
    """Create a sample email for testing."""
    return Email(
        msg_id="test-123",
        sender_address="test@example.com",
        sender_name="Test Sender",
        subject="Test Subject",
        body="Test email body content",
        labels=[],
    )


class TestAIJsonResponseParsing:
    """Test AI JSON response parsing."""

    def test_parse_valid_json_response(self, classifier):
        """Test parsing a valid JSON response."""
        json_response = '{"category": "Finance/Banking", "confidence": 0.95, "reason": "Invoice email"}'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == "Finance/Banking"
        assert confidence == 0.95
        assert reason == "Invoice email"

    def test_parse_json_with_markdown_code_block(self, classifier):
        """Test parsing JSON wrapped in markdown code blocks."""
        json_response = '```json\n{"category": "Shopping/Online", "confidence": 0.88, "reason": "Order confirmation"}\n```'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == "Shopping/Online"
        assert confidence == 0.88
        assert reason == "Order confirmation"

    def test_parse_json_with_extra_text(self, classifier):
        """Test parsing JSON with extra text around it."""
        json_response = 'Here is my classification: {"category": "Services/Professional", "confidence": 0.92, "reason": "LinkedIn"} hope this helps'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == "Services/Professional"
        assert confidence == 0.92
        assert reason == "LinkedIn"

    def test_parse_json_missing_fields(self, classifier):
        """Test parsing JSON with missing optional fields."""
        json_response = '{"category": "Finance/Banking", "confidence": 0.75}'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == "Finance/Banking"
        assert confidence == 0.75
        assert reason == ""

    def test_parse_json_confidence_out_of_range_high(self, classifier):
        """Test parsing JSON with confidence > 1.0."""
        json_response = '{"category": "Finance/Banking", "confidence": 1.5, "reason": "Test"}'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == "Finance/Banking"
        assert confidence == 1.0  # Clamped to 1.0
        assert reason == "Test"

    def test_parse_json_confidence_out_of_range_low(self, classifier):
        """Test parsing JSON with confidence < 0.0."""
        json_response = '{"category": "Finance/Banking", "confidence": -0.5, "reason": "Test"}'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == "Finance/Banking"
        assert confidence == 0.0  # Clamped to 0.0
        assert reason == "Test"

    def test_parse_invalid_json(self, classifier):
        """Test parsing invalid JSON."""
        json_response = '{"category": "Finance/Banking", "confidence": invalid}'
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == ""
        assert confidence == 0.0
        assert reason == ""

    def test_parse_non_json_text(self, classifier):
        """Test parsing plain text (no JSON)."""
        json_response = "Finance/Banking"
        category, confidence, reason = classifier._parse_ai_json_response(json_response)

        assert category == ""
        assert confidence == 0.0
        assert reason == ""


class TestLegacyResponseParsing:
    """Test legacy (non-JSON) response parsing."""

    def test_parse_simple_category(self, classifier):
        """Test parsing simple category string."""
        response = "Finance/Banking"
        category = classifier._parse_legacy_ai_response(response)

        assert category == "Finance/Banking"

    def test_parse_uncertain_response(self, classifier):
        """Test parsing UNCERTAIN response."""
        response = "UNCERTAIN: Finance/Banking"
        category = classifier._parse_legacy_ai_response(response)

        assert category == ""

    def test_parse_new_folder_proposal(self, classifier):
        """Test parsing Parent/NewSub format."""
        response = "Parent/NewSub Finance/NewFolder"
        category = classifier._parse_legacy_ai_response(response)

        assert category == ""

    def test_parse_whitespace(self, classifier):
        """Test parsing with whitespace."""
        response = "  Finance/Banking  "
        category = classifier._parse_legacy_ai_response(response)

        assert category == "Finance/Banking"


class TestConfidenceThreshold:
    """Test confidence threshold enforcement."""

    def test_high_confidence_accepted(self, classifier, sample_email):
        """Test that high confidence classifications are accepted."""
        # Mock MLX components
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.95, "Invoice")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "Finance/Banking"

    def test_low_confidence_rejected(self, classifier, sample_email):
        """Test that low confidence classifications are rejected."""
        # Mock MLX components
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.50, "Not sure")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "À Classer"

    def test_threshold_boundary(self, classifier, sample_email):
        """Test classification at threshold boundary (0.85)."""
        # Mock MLX components - exactly at threshold should be accepted
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.85, "Test")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "Finance/Banking"

    def test_just_below_threshold(self, classifier, sample_email):
        """Test classification just below threshold."""
        # Mock MLX components
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.84, "Test")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "À Classer"


class TestInvalidCategoryHandling:
    """Test handling of invalid category suggestions."""

    def test_invalid_category_high_confidence(self, classifier, sample_email):
        """Test that invalid categories are rejected even with high confidence."""
        # Mock MLX components with invalid category
        mock_llm = Mock()
        mock_llm.classify.return_value = ("InvalidCategory", 0.99, "Test")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "À Classer"

    def test_new_folder_proposal_valid_parent(
        self, classifier, sample_email, mock_folder_analyzer
    ):
        """Test new folder proposal with valid parent."""
        # Mock MLX components with new folder proposal
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/NewFolder", 0.90, "New category")
        classifier._mlx_llm = mock_llm
        mock_folder_analyzer.is_valid_parent_folder.return_value = True

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        # Should be logged as proposal and return "À Classer"
        assert result == "À Classer"

    def test_new_folder_proposal_invalid_parent(
        self, classifier, sample_email, mock_folder_analyzer
    ):
        """Test new folder proposal with invalid parent."""
        # Mock MLX components with invalid parent proposal
        mock_llm = Mock()
        mock_llm.classify.return_value = ("InvalidParent/NewFolder", 0.90, "Test")
        classifier._mlx_llm = mock_llm
        mock_folder_analyzer.is_valid_parent_folder.return_value = False

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "À Classer"


class TestCaching:
    """Test AI response caching."""

    def test_cache_hit(self, classifier, sample_email):
        """Test that cached responses are used."""
        # Mock MLX components
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.95, "Test")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            # First call - should call LLM
            result1 = classifier._get_category_from_ai(sample_email)
            assert result1 == "Finance/Banking"
            assert mock_llm.classify.call_count == 1

            # Second call with same email - should use cache
            result2 = classifier._get_category_from_ai(sample_email)
            assert result2 == "Finance/Banking"
            assert mock_llm.classify.call_count == 1  # No additional call

    def test_cache_key_includes_subject(self, classifier):
        """Test that cache key includes subject (different subjects = different cache entries)."""
        # Mock MLX components
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.95, "Test")
        classifier._mlx_llm = mock_llm

        email1 = Email(
            msg_id="1",
            sender_address="test@example.com",
            sender_name="Test",
            subject="Subject 1",
            body="Body",
        )

        email2 = Email(
            msg_id="2",
            sender_address="test@example.com",
            sender_name="Test",
            subject="Subject 2",  # Different subject
            body="Body",
        )

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            classifier._get_category_from_ai(email1)
            classifier._get_category_from_ai(email2)

        # Should be 2 LLM calls (different cache keys)
        assert mock_llm.classify.call_count == 2


class TestMLXEdgeCases:
    """Test edge cases with MLX LLM responses."""

    def test_valid_category_response(self, classifier, sample_email):
        """Test that valid category responses work correctly."""
        # Mock MLX components with valid category
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.95, "Test reason")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "Finance/Banking"

    def test_empty_category_response(self, classifier, sample_email):
        """Test that empty category responses are handled."""
        # Mock MLX components with empty category
        mock_llm = Mock()
        mock_llm.classify.return_value = ("", 0.95, "No match found")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "À Classer"

    def test_low_confidence_with_valid_category(self, classifier, sample_email):
        """Test that low confidence classifications route to À Classer."""
        # Mock MLX components with low confidence
        mock_llm = Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.40, "Not confident")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "À Classer"


class TestErrorHandling:
    """Test error handling in AI classification."""

    def test_llm_exception(self, classifier, sample_email):
        """Test handling of LLM exceptions."""
        # Mock MLX components that raise an exception
        mock_llm = Mock()
        mock_llm.classify.side_effect = Exception("LLM Error")
        classifier._mlx_llm = mock_llm

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "(Model Error)"

    def test_mlx_not_initialized(self, classifier, sample_email):
        """Test handling when MLX components are not initialized."""
        # Set _mlx_llm to None - _init_mlx_components returns True but _mlx_llm is None
        classifier._mlx_llm = None

        with patch.object(classifier, "_init_mlx_components", return_value=True):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "(Model Error)"

    def test_mlx_disabled_returns_error(self, classifier, sample_email):
        """Test that disabled MLX returns model error."""
        # When MLX is disabled and can't initialize, it should return error
        with patch.object(classifier, "_init_mlx_components", return_value=False):
            result = classifier._get_category_from_ai(sample_email)

        assert result == "(Model Error)"
