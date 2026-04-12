"""Integration tests for complete classification workflows.

Tests the full 3-pass classification strategy:
- Pass 1: Headers-only classification (validated/historical DB)
- Pass 2: Domain classification with manual matching files
- Pass 3: AI classification with body fetching
"""

import json
from unittest.mock import Mock, patch

import pytest
from faker import Faker

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

fake = Faker()


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset global metrics before each test to prevent accumulation."""
    METRICS.reset()


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

    validated_db_path = db_path / "validated_classification_db.json"
    validated_db_path.write_text(
        json.dumps(
            {
                "validated@example.com": {"Finance/Banking": 1},
                "newsletter@company.com": {"Updates/Newsletter": 1},
            }
        )
    )

    suggestion_db_path = db_path / "sender_classification_db.json"
    suggestion_db_path.write_text(
        json.dumps(
            {
                "historical@example.com": {"Shopping/Online": 15, "Other": 1},
            }
        )
    )

    domain_db_path = db_path / "domain_classifications.json"
    domain_db_path.write_text(
        json.dumps(
            {
                "amazon.com": "Shopping/Online",
                "paypal.com": "Finance/Banking",
                "stripe.com": "Finance/Banking",
            }
        )
    )

    return ClassificationDatabase(
        suggestion_db_path=suggestion_db_path,
        validated_db_path=validated_db_path,
        domain_db_path=domain_db_path,
    )


def create_test_email(
    sender_address: str,
    sender_name: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    msg_id: str | None = None,
) -> Email:
    """Create a test email with Faker-generated defaults."""
    return Email(
        msg_id=msg_id or fake.uuid4(),
        sender_address=sender_address,
        sender_name=sender_name or fake.name(),
        subject=subject or fake.sentence(),
        body=body or fake.paragraph(),
        labels=[],
    )


class TestPass1HeadersOnlyClassification:
    """Test Pass 1: Headers-only classification using validated/historical DB."""

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass1_uses_validated_db(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 1 uses validated database for instant classification."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email("validated@example.com", subject=fake.sentence()),
            create_test_email("newsletter@company.com", subject=fake.sentence()),
        ]

        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        assert results == ["Finance/Banking", "Updates/Newsletter"]
        assert METRICS.classification_metrics.signal_hits["validated_db"] == 2

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass1_uses_suggestion_db_for_known_senders(
        self, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test Signal 1 also matches senders in suggestion DB via get_dominant_classification.

        get_dominant_classification() checks both validated and suggestion DBs,
        so senders in the suggestion DB with a dominant category hit Signal 1.
        """
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Shopping/Online"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email("historical@example.com", subject=fake.sentence())

        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        assert result == "Shopping/Online"
        assert METRICS.classification_metrics.signal_hits["validated_db"] == 1

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass1_does_not_fetch_body(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 1 classification works without body content."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email("validated@example.com", subject=fake.sentence(), body="")

        classifier = Classifier(test_config, mock_database)
        result = classifier.classify_email(email)

        assert result == "Finance/Banking"


class TestPass2DomainClassification:
    """Test Pass 2: Domain-based classification with manual matching."""

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass2_uses_domain_db(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 2 applies domain classification rules."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Shopping/Online", "Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email(f"{fake.user_name()}@amazon.com", subject=fake.sentence()),
            create_test_email(f"{fake.user_name()}@paypal.com", subject=fake.sentence()),
            create_test_email(f"{fake.user_name()}@stripe.com", subject=fake.sentence()),
        ]

        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        assert results == ["Shopping/Online", "Finance/Banking", "Finance/Banking"]
        assert METRICS.classification_metrics.signal_hits["domain_db"] == 3

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass2_groups_by_domain(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 2 groups emails from same domain."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Shopping/Online"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email(f"{fake.user_name()}@amazon.com", subject=fake.sentence()) for _ in range(5)
        ]

        classifier = Classifier(test_config, mock_database)
        results = [classifier.classify_email(email) for email in emails]

        assert all(result == "Shopping/Online" for result in results)
        assert METRICS.classification_metrics.signal_hits["domain_db"] == 5

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass2_skips_non_commercial_domains(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 2 skips non-commercial domains like gmail.com."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email(f"{fake.user_name()}@gmail.com", subject=fake.sentence())

        classifier = Classifier(test_config, mock_database)
        with patch.object(classifier, "_get_category_from_ai", return_value="À Classer"):
            classifier.classify_email(email)

        assert METRICS.classification_metrics.signal_hits.get("domain_db", 0) == 0


class TestPass3AIClassification:
    """Test Pass 3: AI classification with full body fetching.

    Since MLX is disabled in test config, we mock _get_category_from_ai directly
    on the classifier instance (not litellm, which is no longer used).
    """

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass3_uses_ai_for_unknown_senders(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test Pass 3 uses AI for unknown senders."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Investment", "À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email(
            f"{fake.user_name()}@{fake.domain_name()}",
            subject=fake.sentence(),
            body=fake.paragraph(nb_sentences=5),
        )

        classifier = Classifier(test_config, mock_database)
        with patch.object(classifier, "_get_category_from_ai", return_value="Finance/Investment"):
            result = classifier.classify_email(email)

        assert result == "Finance/Investment"
        assert METRICS.classification_metrics.signal_hits["mlx_llm"] == 1

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass3_low_confidence_routes_to_unclassified(
        self, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test Pass 3 routes low confidence to 'À Classer'."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email(f"{fake.user_name()}@{fake.domain_name()}", subject=fake.sentence())

        classifier = Classifier(test_config, mock_database)
        with patch.object(classifier, "_get_category_from_ai", return_value="À Classer"):
            result = classifier.classify_email(email)

        assert result == "À Classer"

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_pass3_ai_error_routes_to_model_error(
        self, mock_folder_analyzer_class, test_config, mock_database
    ):
        """Test Pass 3 handles AI unavailability gracefully."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        email = create_test_email(f"{fake.user_name()}@{fake.domain_name()}", subject=fake.sentence())

        # MLX disabled + litellm fails → "(Model Error)"
        classifier = Classifier(test_config, mock_database)
        with patch.object(classifier, "_get_category_from_litellm", return_value="(Model Error)"):
            result = classifier.classify_email(email)

        assert result == "(Model Error)"


class TestFullWorkflowIntegration:
    """Test complete multi-pass workflow integration."""

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_full_workflow_all_passes(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test full workflow processes emails through all passes."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = [
            "Finance/Banking",
            "Shopping/Online",
            "À Classer",
        ]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email("validated@example.com"),  # Signal 1: Validated DB
            create_test_email("historical@example.com"),  # Signal 1: Suggestion DB
            create_test_email(f"{fake.user_name()}@amazon.com"),  # Signal 4: Domain DB
            create_test_email(f"{fake.user_name()}@{fake.domain_name()}"),  # Signal 6: AI
        ]

        classifier = Classifier(test_config, mock_database)
        with patch.object(classifier, "_get_category_from_ai", return_value="À Classer"):
            results = [classifier.classify_email(email) for email in emails]

        assert results[0] == "Finance/Banking"  # Validated DB
        assert results[1] == "Shopping/Online"  # Suggestion DB (via Signal 1)
        assert results[2] == "Shopping/Online"  # Domain DB
        assert results[3] == "À Classer"  # AI

        metrics = METRICS.classification_metrics
        assert metrics.signal_hits["validated_db"] == 2
        assert metrics.signal_hits["domain_db"] == 1
        # "À Classer" results are recorded as errors (key includes sender address)
        uncertain_errors = sum(1 for k in metrics.errors if k.startswith("mlx_llm_uncertain"))
        assert uncertain_errors == 1

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_workflow_metrics_tracking(self, mock_folder_analyzer_class, test_config, mock_database):
        """Test metrics are tracked correctly across all passes."""
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking", "Shopping/Online"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        emails = [
            create_test_email("validated@example.com"),  # Signal 1: validated DB
            create_test_email("historical@example.com"),  # Signal 1: suggestion DB
            create_test_email(f"{fake.user_name()}@amazon.com"),  # Signal 4: domain DB
        ]

        classifier = Classifier(test_config, mock_database)
        for email in emails:
            classifier.classify_email(email)

        metrics = METRICS.classification_metrics

        assert sum(metrics.signal_hits.values()) == 3

        assert metrics.category_distribution["Finance/Banking"] == 1
        assert metrics.category_distribution["Shopping/Online"] == 2

        assert len(metrics.confidence_scores["validated_db"]) == 2
        assert len(metrics.confidence_scores["domain_db"]) == 1
