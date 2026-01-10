"""Integration tests for complete classification workflows.

Tests the full 3-pass classification strategy:
- Pass 1: Headers-only classification (validated/historical DB)
- Pass 2: Domain classification with manual matching files
- Pass 3: AI classification with body fetching
"""

import json
from unittest.mock import MagicMock, Mock, patch

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
from mailtag.metrics import METRICS
from mailtag.models import Email


@pytest.fixture
def test_config(tmp_path):
    """Create test configuration."""
    return AppConfig(
        general=GeneralConfig(
            ollama_model="ollama_chat/qwen3-vl:8b-instruct",
            api_base="http://localhost:11434",
            use_imap_folders_for_classification=True,
        ),
        logging=LoggingConfig(
            level="INFO",
            file=str(tmp_path / "test.log"),
        ),
        classifier=ClassifierConfig(
            historical_confidence_threshold=0.9,
            min_count=10,
            ai_confidence_threshold=0.85,
        ),
        imap=ImapConfig(
            host="imap.example.com",
            user="test@example.com",
            password="password",
        ),
        gmail=GmailConfig(
            credentials_file=str(tmp_path / "credentials.json"),
            token_file=str(tmp_path / "token.json"),
        ),
        fast_parse=FastParseConfig(
            batch_size=100,
            folder_cache_ttl_hours=24,
            unclassified_folder_name="À Classer",
            junk_folder_name="Junk",
        ),
        mlx=MLXConfig(enabled=False),
    )


@pytest.fixture
def mock_database(tmp_path):
    """Create a real database with test data."""
    db_path = tmp_path / "db"
    db_path.mkdir()

    # Create database files
    validated_db_path = db_path / "validated_classification_db.json"
    validated_db_path.write_text(json.dumps({
        "validated@example.com": {"Finance/Banking": 1},
        "newsletter@company.com": {"Updates/Newsletter": 1},
    }))

    suggestion_db_path = db_path / "sender_classification_db.json"
    suggestion_db_path.write_text(json.dumps({
        "historical@example.com": {"Shopping/Online": 15, "Other": 1},
    }))

    domain_db_path = db_path / "domain_classifications.json"
    domain_db_path.write_text(json.dumps({
        "amazon.com": "Shopping/Online",
        "paypal.com": "Finance/Banking",
        "stripe.com": "Finance/Banking",
    }))

    return ClassificationDatabase(
        suggestion_db_path=suggestion_db_path,
        validated_db_path=validated_db_path,
        domain_db_path=domain_db_path,
    )


def create_test_email(
    sender_address: str,
    sender_name: str = "Test Sender",
    subject: str = "Test Subject",
    body: str = "Test body",
    msg_id: str | None = None,
) -> Email:
    """Helper to create test email."""
    return Email(
        msg_id=msg_id or f"msg-{sender_address}",
        sender_address=sender_address,
        sender_name=sender_name,
        subject=subject,
        body=body,
        labels=[],
    )


class TestPass1HeadersOnlyClassification:
    """Test Pass 1: Headers-only classification using validated/historical DB."""

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass1_uses_validated_db(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 1 uses validated database for instant classification."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email("validated@example.com", subject="Bank statement"),
            create_test_email("newsletter@company.com", subject="Weekly news"),
        ]

        # Act
        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        # Assert
        assert results == ["Finance/Banking", "Updates/Newsletter"]
        assert METRICS.classification_metrics.signal_hits["validated_db"] == 2

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass1_uses_historical_db(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 1 uses historical database for high-confidence senders."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Shopping/Online"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email("historical@example.com", subject="Order confirmation")

        # Act
        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        # Assert
        assert result == "Shopping/Online"
        assert METRICS.classification_metrics.signal_hits["historical_db"] == 1
        # Confidence should be 15/16 ≈ 0.9375
        confidence = METRICS.classification_metrics.confidence_scores["historical_db"][0]
        assert 0.93 < confidence < 0.95

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass1_does_not_fetch_body(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 1 classification happens without body content."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Email with empty body (simulating header-only fetch)
        email = create_test_email("validated@example.com", subject="Test", body="")

        # Act
        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        # Assert - should still classify successfully
        assert result == "Finance/Banking"


class TestPass2DomainClassification:
    """Test Pass 2: Domain-based classification with manual matching."""

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass2_uses_domain_db(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 2 applies domain classification rules."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Shopping/Online", "Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email("promo@amazon.com", subject="Holiday deals"),
            create_test_email("alert@paypal.com", subject="Payment received"),
            create_test_email("billing@stripe.com", subject="Invoice"),
        ]

        # Act
        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        # Assert
        assert results == ["Shopping/Online", "Finance/Banking", "Finance/Banking"]
        assert METRICS.classification_metrics.signal_hits["domain_db"] == 3

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass2_groups_by_domain(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 2 groups emails from same domain."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Shopping/Online"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Multiple emails from same domain
        emails = [
            create_test_email(f"sender{i}@amazon.com", subject=f"Email {i}")
            for i in range(5)
        ]

        # Act
        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        # Assert - all classified the same way
        assert all(result == "Shopping/Online" for result in results)
        assert METRICS.classification_metrics.signal_hits["domain_db"] == 5

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass2_skips_non_commercial_domains(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 2 skips non-commercial domains like gmail.com."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email("user@gmail.com", subject="Personal email")

        # Act
        classifier = Classifier(test_config, mock_database)

        # Mock AI to avoid actual API call
        with patch.object(classifier, "_get_category_from_ai", return_value=("À Classer", 0.5)):
            classifier.classify_email(email)

        # Assert - should skip domain classification and use AI
        assert METRICS.classification_metrics.signal_hits.get("domain_db", 0) == 0


class TestPass3AIClassification:
    """Test Pass 3: AI classification with full body fetching."""

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_pass3_uses_ai_for_unknown_senders(
        self, mock_litellm, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test Pass 3 fetches body and uses AI for unknown senders."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Investment", "À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Mock AI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "category": "Finance/Investment",
            "confidence": 0.92,
            "reasoning": "Investment newsletter content",
        })
        mock_litellm.completion.return_value = mock_response

        email = create_test_email(
            "unknown@example.com",
            subject="Investment opportunity",
            body="Full email body with investment details",
        )

        # Act
        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        # Assert
        assert result == "Finance/Investment"
        assert METRICS.classification_metrics.signal_hits["ai_model"] == 1

        # Verify AI was called with body content
        mock_litellm.completion.assert_called_once()
        call_args = mock_litellm.completion.call_args[1]
        assert "Investment opportunity" in call_args["messages"][0]["content"]
        assert "investment details" in call_args["messages"][0]["content"]

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_pass3_low_confidence_routes_to_classifier(
        self, mock_litellm, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test Pass 3 routes low confidence (<0.85) to 'À Classer'."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Mock low confidence AI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "category": "Finance/Investment",
            "confidence": 0.70,  # Below threshold
            "reasoning": "Unclear content",
        })
        mock_litellm.completion.return_value = mock_response

        email = create_test_email("unknown@example.com", subject="Ambiguous content")

        # Act
        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        # Assert
        assert result == "À Classer"

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_pass3_ai_error_routes_to_classifier(
        self, mock_litellm, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test Pass 3 handles AI errors gracefully."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Mock AI error
        mock_litellm.completion.side_effect = RuntimeError("Model timeout")

        email = create_test_email("unknown@example.com", subject="Test")

        # Act
        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        # Assert
        assert result == "À Classer"


class TestFullWorkflowIntegration:
    """Test complete multi-pass workflow integration."""

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_full_workflow_all_passes(
        self, mock_litellm, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test full workflow processes emails through all three passes."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = [
            "Finance/Banking",
            "Shopping/Online",
            "À Classer",
        ]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Mock AI response for unknown senders
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "category": "À Classer",
            "confidence": 0.9,
            "reasoning": "Generic content",
        })
        mock_litellm.completion.return_value = mock_response

        # Mix of emails requiring different passes
        emails = [
            create_test_email("validated@example.com"),  # Pass 1: Validated DB
            create_test_email("historical@example.com"),  # Pass 1: Historical DB
            create_test_email("promo@amazon.com"),  # Pass 2: Domain DB
            create_test_email("unknown@example.com"),  # Pass 3: AI
        ]

        # Act
        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        # Assert
        assert results[0] == "Finance/Banking"  # Validated
        assert results[1] == "Shopping/Online"  # Historical
        assert results[2] == "Shopping/Online"  # Domain
        assert results[3] == "À Classer"  # AI

        # Verify signal distribution
        metrics = METRICS.classification_metrics
        assert metrics.signal_hits["validated_db"] == 1
        assert metrics.signal_hits["historical_db"] == 1
        assert metrics.signal_hits["domain_db"] == 1
        assert metrics.signal_hits["ai_model"] == 1

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_workflow_metrics_tracking(
        self, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test metrics are tracked correctly across all passes."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking", "Shopping/Online"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email("validated@example.com"),
            create_test_email("historical@example.com"),
            create_test_email("promo@amazon.com"),
        ]

        # Act
        classifier = Classifier(test_config, mock_database)
        for email in emails:
            classifier.classify_email(email)

        metrics = METRICS.classification_metrics

        # Assert
        assert metrics.total_classifications == 3
        assert sum(metrics.signal_hits.values()) == 3

        # Check category distribution
        assert metrics.category_counts["Finance/Banking"] == 1
        assert metrics.category_counts["Shopping/Online"] == 2

        # Verify confidence scores recorded
        assert len(metrics.confidence_scores["validated_db"]) == 1
        assert len(metrics.confidence_scores["historical_db"]) == 1
        assert len(metrics.confidence_scores["domain_db"]) == 1
