"""Tests for classification metrics functionality."""

import json
import tempfile
from pathlib import Path
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
)
from mailtag.database import ClassificationDatabase
from mailtag.metrics import METRICS, ClassificationMetrics
from mailtag.models import Email


@pytest.fixture
def classification_metrics():
    """Create a fresh ClassificationMetrics instance."""
    metrics = ClassificationMetrics()
    metrics.reset()
    return metrics


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
    )


@pytest.fixture
def mock_database():
    """Create a mock classification database."""
    db = Mock(spec=ClassificationDatabase)
    db.suggestion_db = {"sender@example.com": {"Finance/Banking": 9, "Shopping/Online": 1}}
    db.get_dominant_classification = Mock(return_value=None)
    db.update_suggestion = Mock()
    db.get_category_by_domain = Mock(return_value=None)
    return db


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


class TestClassificationMetricsRecording:
    """Test classification metrics recording."""

    def test_record_classification_basic(self, classification_metrics):
        """Test basic classification recording."""
        classification_metrics.record_classification(
            email_id="test-1",
            signal="validated_db",
            category="Finance/Banking",
            confidence=1.0,
            processing_time_ms=5.0,
        )

        assert classification_metrics.signal_hits["validated_db"] == 1
        assert classification_metrics.category_distribution["Finance/Banking"] == 1
        assert classification_metrics.confidence_scores["validated_db"] == [1.0]
        assert classification_metrics.processing_times["validated_db"] == [5.0]

    def test_record_multiple_classifications(self, classification_metrics):
        """Test recording multiple classifications."""
        classification_metrics.record_classification("1", "validated_db", "Finance/Banking", 1.0, 5.0)
        classification_metrics.record_classification(
            "2", "historical_db", "Services/Professional", 0.92, 10.0
        )
        classification_metrics.record_classification("3", "ai_model", "Shopping/Online", 0.88, 150.0)

        assert sum(classification_metrics.signal_hits.values()) == 3
        assert classification_metrics.signal_hits["validated_db"] == 1
        assert classification_metrics.signal_hits["historical_db"] == 1
        assert classification_metrics.signal_hits["ai_model"] == 1

    def test_record_classification_without_confidence(self, classification_metrics):
        """Test recording classification without confidence score."""
        classification_metrics.record_classification(
            email_id="test-1",
            signal="domain_db",
            category="Finance/Banking",
            confidence=None,
            processing_time_ms=3.0,
        )

        assert classification_metrics.signal_hits["domain_db"] == 1
        assert "domain_db" not in classification_metrics.confidence_scores

    def test_record_error(self, classification_metrics):
        """Test error recording."""
        classification_metrics.record_error("ai_uncertain", "test@example.com")

        assert classification_metrics.errors["ai_uncertain:test@example.com"] == 1

    def test_record_error_without_context(self, classification_metrics):
        """Test error recording without context."""
        classification_metrics.record_error("ai_model_error")

        assert classification_metrics.errors["ai_model_error"] == 1


class TestSignalHitRates:
    """Test signal hit rate calculations."""

    def test_signal_hit_rates_balanced(self, classification_metrics):
        """Test hit rates with balanced distribution."""
        classification_metrics.record_classification("1", "validated_db", "Cat1")
        classification_metrics.record_classification("2", "historical_db", "Cat2")
        classification_metrics.record_classification("3", "domain_db", "Cat3")
        classification_metrics.record_classification("4", "ai_model", "Cat4")

        rates = classification_metrics.get_signal_hit_rates()

        assert rates["validated_db"] == 25.0
        assert rates["historical_db"] == 25.0
        assert rates["domain_db"] == 25.0
        assert rates["ai_model"] == 25.0

    def test_signal_hit_rates_skewed(self, classification_metrics):
        """Test hit rates with skewed distribution."""
        for i in range(80):
            classification_metrics.record_classification(f"hist-{i}", "historical_db", "Cat1")
        for i in range(15):
            classification_metrics.record_classification(f"domain-{i}", "domain_db", "Cat2")
        for i in range(5):
            classification_metrics.record_classification(f"ai-{i}", "ai_model", "Cat3")

        rates = classification_metrics.get_signal_hit_rates()

        assert rates["historical_db"] == 80.0
        assert rates["domain_db"] == 15.0
        assert rates["ai_model"] == 5.0

    def test_signal_hit_rates_empty(self, classification_metrics):
        """Test hit rates with no data."""
        rates = classification_metrics.get_signal_hit_rates()

        assert rates == {}


class TestMetricsSummary:
    """Test metrics summary generation."""

    def test_summary_structure(self, classification_metrics):
        """Test that summary contains all required fields."""
        classification_metrics.record_classification("1", "validated_db", "Cat1", 1.0, 5.0)

        summary = classification_metrics.get_summary()

        assert "total_classified" in summary
        assert "signal_hit_rates" in summary
        assert "signal_counts" in summary
        assert "top_categories" in summary
        assert "avg_confidence_by_signal" in summary
        assert "min_confidence_by_signal" in summary
        assert "max_confidence_by_signal" in summary
        assert "avg_processing_time_ms" in summary
        assert "errors" in summary
        assert "timestamp" in summary

    def test_summary_confidence_stats(self, classification_metrics):
        """Test confidence statistics in summary."""
        classification_metrics.record_classification("1", "ai_model", "Cat1", 0.85)
        classification_metrics.record_classification("2", "ai_model", "Cat2", 0.95)
        classification_metrics.record_classification("3", "ai_model", "Cat3", 0.75)

        summary = classification_metrics.get_summary()

        assert summary["avg_confidence_by_signal"]["ai_model"] == pytest.approx(0.85, abs=0.01)
        assert summary["min_confidence_by_signal"]["ai_model"] == 0.75
        assert summary["max_confidence_by_signal"]["ai_model"] == 0.95

    def test_summary_top_categories(self, classification_metrics):
        """Test top categories in summary."""
        for i in range(50):
            classification_metrics.record_classification(f"cat1-{i}", "domain_db", "Finance/Banking")
        for i in range(30):
            classification_metrics.record_classification(f"cat2-{i}", "ai_model", "Services/Professional")
        for i in range(20):
            classification_metrics.record_classification(f"cat3-{i}", "historical_db", "Shopping/Online")

        summary = classification_metrics.get_summary()

        assert summary["top_categories"]["Finance/Banking"] == 50
        assert summary["top_categories"]["Services/Professional"] == 30
        assert summary["top_categories"]["Shopping/Online"] == 20


class TestMetricsExport:
    """Test metrics export functionality."""

    def test_export_to_json(self, classification_metrics):
        """Test JSON export."""
        classification_metrics.record_classification("1", "validated_db", "Cat1", 1.0, 5.0)
        classification_metrics.record_classification("2", "ai_model", "Cat2", 0.88, 150.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "metrics.json"
            classification_metrics.export_to_json(filepath)

            assert filepath.exists()

            with open(filepath) as f:
                data = json.load(f)

            assert data["total_classified"] == 2
            assert "validated_db" in data["signal_counts"]
            assert "ai_model" in data["signal_counts"]

    def test_export_creates_directory(self, classification_metrics):
        """Test that export creates parent directories if needed."""
        classification_metrics.record_classification("1", "validated_db", "Cat1")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "nested" / "dir" / "metrics.json"
            classification_metrics.export_to_json(filepath)

            assert filepath.exists()


class TestMetricsReset:
    """Test metrics reset functionality."""

    def test_reset_clears_all_data(self, classification_metrics):
        """Test that reset clears all collected data."""
        classification_metrics.record_classification("1", "validated_db", "Cat1", 1.0, 5.0)
        classification_metrics.record_classification("2", "ai_model", "Cat2", 0.88, 150.0)
        classification_metrics.record_error("test_error", "context")

        classification_metrics.reset()

        assert len(classification_metrics.signal_hits) == 0
        assert len(classification_metrics.category_distribution) == 0
        assert len(classification_metrics.confidence_scores) == 0
        assert len(classification_metrics.errors) == 0
        assert len(classification_metrics.processing_times) == 0


class TestClassifierMetricsIntegration:
    """Test integration of metrics with Classifier."""

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_classifier_tracks_validated_db(
        self, mock_folder_analyzer_class, mock_config, mock_database, sample_email
    ):
        """Test that classifier tracks validated DB classifications."""
        # Setup
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer.get_parent_folders.return_value = ["Finance"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        mock_database.get_dominant_classification.return_value = "Finance/Banking"

        # Reset global metrics
        METRICS.classification_metrics.reset()

        # Create classifier and classify
        classifier = Classifier(mock_config, mock_database)
        result = classifier.classify_email(sample_email)

        assert result == "Finance/Banking"
        assert METRICS.classification_metrics.signal_hits["validated_db"] == 1
        assert METRICS.classification_metrics.category_distribution["Finance/Banking"] == 1

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_classifier_tracks_historical_db(
        self, mock_folder_analyzer_class, mock_config, mock_database, sample_email
    ):
        """Test that classifier tracks historical DB classifications."""
        # Setup
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer.get_parent_folders.return_value = ["Finance"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        mock_database.get_dominant_classification.return_value = None
        mock_database.suggestion_db = {"test@example.com": {"Finance/Banking": 10, "Other": 1}}

        # Reset global metrics
        METRICS.classification_metrics.reset()

        # Create classifier and classify
        classifier = Classifier(mock_config, mock_database)
        result = classifier.classify_email(sample_email)

        assert result == "Finance/Banking"
        assert METRICS.classification_metrics.signal_hits["historical_db"] == 1

        # Check confidence was calculated correctly (10/11 ≈ 0.909)
        confidence = METRICS.classification_metrics.confidence_scores["historical_db"][0]
        assert confidence == pytest.approx(10 / 11, abs=0.001)

    @patch("mailtag.classifier.FolderAnalyzer")
    def test_classifier_export_metrics(self, mock_folder_analyzer_class, mock_config, mock_database):
        """Test classifier metrics export."""
        # Setup
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        METRICS.classification_metrics.reset()

        classifier = Classifier(mock_config, mock_database)

        # Add some metrics
        METRICS.classification_metrics.record_classification("1", "validated_db", "Cat1", 1.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = classifier.export_metrics(Path(tmpdir))

            assert filepath.exists()
            assert "classification_metrics_" in filepath.name
            assert filepath.suffix == ".json"


class TestMetricsLogging:
    """Test metrics logging functionality."""

    def test_log_summary_with_data(self, classification_metrics, caplog):
        """Test that log summary outputs correctly formatted data."""
        classification_metrics.record_classification("1", "validated_db", "Finance/Banking", 1.0, 5.0)
        classification_metrics.record_classification("2", "ai_model", "Services/Professional", 0.88, 150.0)

        import logging

        caplog.set_level(logging.INFO)

        classification_metrics.log_summary("INFO")

        # Check that summary was logged
        assert "CLASSIFICATION METRICS SUMMARY" in caplog.text
        assert "Total emails classified: 2" in caplog.text
        assert "Signal Hit Rates:" in caplog.text
        assert "validated_db" in caplog.text
        assert "ai_model" in caplog.text

    def test_log_summary_empty(self, classification_metrics, caplog):
        """Test logging with no data."""
        import logging

        caplog.set_level(logging.INFO)

        classification_metrics.log_summary("INFO")

        assert "Total emails classified: 0" in caplog.text
