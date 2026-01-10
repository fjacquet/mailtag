"""Tests for error recovery and resilience.

Tests database corruption recovery, network failure retry logic,
and AI fallback handling.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

import pytest

from mailtag.classifier import Classifier
from mailtag.config import AppConfig, ClassifierConfig, FastParseConfig, GeneralConfig, GmailConfig, ImapConfig, LoggingConfig, MLXConfig
from mailtag.database import ClassificationDatabase
from mailtag.models import Email
from mailtag.utils.db_backup import backup_database, restore_database


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


class TestDatabaseCorruption:
    """Test recovery from corrupted database files."""

    def test_loads_empty_db_when_missing(self, tmp_path):
        """Test database creates empty structure when file is missing."""
        # Arrange - don't create files
        suggestion_db_path = tmp_path / "sender_classification_db.json"
        validated_db_path = tmp_path / "validated_classification_db.json"
        domain_db_path = tmp_path / "domain_classifications.json"

        # Act
        db = ClassificationDatabase(
            suggestion_db_path=suggestion_db_path,
            validated_db_path=validated_db_path,
            domain_db_path=domain_db_path,
        )

        # Assert - creates empty databases
        assert len(db.suggestion_db) == 0
        assert len(db.validated_db) == 0
        assert len(db.domain_db) == 0

    def test_loads_empty_db_when_corrupted(self, tmp_path):
        """Test database handles invalid JSON gracefully."""
        # Arrange - create corrupted file
        suggestion_db_path = tmp_path / "sender_classification_db.json"
        validated_db_path = tmp_path / "validated_classification_db.json"
        domain_db_path = tmp_path / "domain_classifications.json"

        suggestion_db_path.write_text("{ invalid json }")
        validated_db_path.write_text("{}")
        domain_db_path.write_text("{}")

        # Act & Assert - should handle gracefully
        db = ClassificationDatabase(
            suggestion_db_path=suggestion_db_path,
            validated_db_path=validated_db_path,
            domain_db_path=domain_db_path,
        )

        # Database loads as empty when corrupted
        assert len(db.suggestion_db) == 0

    def test_backup_and_restore_workflow(self, tmp_path):
        """Test complete backup and restore workflow."""
        # Arrange - create database with data
        db_path = tmp_path / "sender_classification_db.json"
        test_data = {"test@example.com": {"Finance/Banking": 10, "Other": 1}}
        db_path.write_text(json.dumps(test_data))

        # Act - backup database
        backup_path = backup_database(db_path)

        # Corrupt original
        db_path.write_text("{ corrupted }")

        # Restore from backup
        restore_database(db_path, backup_path)

        # Assert - data restored correctly
        restored_data = json.loads(db_path.read_text())
        assert restored_data == test_data

    def test_backup_rotation_keeps_recent_backups(self, tmp_path):
        """Test backup rotation keeps only recent backups."""
        # Arrange - create db and backup directory
        db_path = tmp_path / "sender_classification_db.json"
        db_path.write_text(json.dumps({}))

        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir()

        # Create 15 old backup files (should keep only 10)
        for i in range(15):
            timestamp = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d_%H%M%S")
            old_backup = backup_dir / f"sender_classification_db_{timestamp}.json"
            old_backup.write_text(json.dumps({}))

        # Act - create new backup (triggers rotation)
        backup_database(db_path)

        # Assert - only keeps 10 most recent
        backups = list(backup_dir.glob("sender_classification_db_*.json"))
        assert len(backups) <= 10


class TestNetworkFailureRecovery:
    """Test recovery from network failures."""

    def test_retry_decorator_retries_on_failure(self):
        """Test retry decorator retries failed operations."""
        from mailtag.retry import retry

        call_count = 0

        @retry(max_retries=3, retry_delay=0.01, retry_backoff=1.0)
        def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        # Act
        result = fails_twice()

        # Assert
        assert result == "success"
        assert call_count == 3  # Initial + 2 retries

    def test_retry_gives_up_after_max_retries(self):
        """Test retry decorator gives up after max retries."""
        from mailtag.retry import retry

        call_count = 0

        @retry(max_retries=2, retry_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Network error")

        # Act & Assert
        with pytest.raises(ConnectionError):
            always_fails()

        assert call_count == 3  # Initial + 2 retries

    def test_retry_callback_called_on_retry(self):
        """Test retry callback is invoked on each retry."""
        from mailtag.retry import retry

        retry_log = []

        def log_retry(exception, attempt):
            retry_log.append((str(exception), attempt))

        @retry(max_retries=2, retry_delay=0.01, on_retry=log_retry)
        def fails_twice():
            if len(retry_log) < 2:
                raise ValueError(f"Attempt {len(retry_log)}")
            return "success"

        # Act
        result = fails_twice()

        # Assert
        assert result == "success"
        assert len(retry_log) == 2
        assert retry_log[0] == ("Attempt 0", 1)
        assert retry_log[1] == ("Attempt 1", 2)


class TestAIFallback:
    """Test AI model failure handling."""

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_ai_error_routes_to_unclassified(
        self, mock_litellm, mock_folder_analyzer_class, test_config, tmp_path
    ):
        """Test AI errors route email to unclassified folder."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Create empty databases
        db_path = tmp_path / "db"
        db_path.mkdir()
        suggestion_db = db_path / "sender_classification_db.json"
        validated_db = db_path / "validated_classification_db.json"
        domain_db = db_path / "domain_classifications.json"

        suggestion_db.write_text(json.dumps({}))
        validated_db.write_text(json.dumps({}))
        domain_db.write_text(json.dumps({}))

        database = ClassificationDatabase(
            suggestion_db_path=suggestion_db,
            validated_db_path=validated_db,
            domain_db_path=domain_db,
        )

        # Mock AI error
        mock_litellm.completion.side_effect = RuntimeError("Model timeout")

        email = Email(
            msg_id="test-123",
            sender_address="unknown@example.com",
            sender_name="Unknown",
            subject="Test",
            body="Test body",
            labels=[],
        )

        # Act
        classifier = Classifier(test_config, database)
        result = classifier.classify_email(email)

        # Assert - falls back to unclassified
        assert result == "À Classer"

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_low_confidence_routes_to_unclassified(
        self, mock_litellm, mock_folder_analyzer_class, test_config, tmp_path
    ):
        """Test low confidence AI results route to unclassified."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer", "Finance/Banking"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Create empty databases
        db_path = tmp_path / "db"
        db_path.mkdir()
        suggestion_db = db_path / "sender_classification_db.json"
        validated_db = db_path / "validated_classification_db.json"
        domain_db = db_path / "domain_classifications.json"

        suggestion_db.write_text(json.dumps({}))
        validated_db.write_text(json.dumps({}))
        domain_db.write_text(json.dumps({}))

        database = ClassificationDatabase(
            suggestion_db_path=suggestion_db,
            validated_db_path=validated_db,
            domain_db_path=domain_db,
        )

        # Mock low confidence AI response
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "category": "Finance/Banking",
            "confidence": 0.7,  # Below threshold of 0.85
            "reasoning": "Unclear content",
        })
        mock_litellm.completion.return_value = mock_response

        email = Email(
            msg_id="test-123",
            sender_address="ambiguous@example.com",
            sender_name="Ambiguous",
            subject="Maybe finance?",
            body="Could be banking related",
            labels=[],
        )

        # Act
        classifier = Classifier(test_config, database)
        result = classifier.classify_email(email)

        # Assert - routes to unclassified due to low confidence
        assert result == "À Classer"

    @patch("mailtag.classifier.FolderAnalyzer")
    @patch("mailtag.classifier.litellm")
    def test_invalid_json_response_routes_to_unclassified(
        self, mock_litellm, mock_folder_analyzer_class, test_config, tmp_path
    ):
        """Test invalid JSON from AI routes to unclassified."""
        # Arrange
        mock_folder_analyzer = Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer_class.return_value = mock_folder_analyzer

        # Create empty databases
        db_path = tmp_path / "db"
        db_path.mkdir()
        suggestion_db = db_path / "sender_classification_db.json"
        validated_db = db_path / "validated_classification_db.json"
        domain_db = db_path / "domain_classifications.json"

        suggestion_db.write_text(json.dumps({}))
        validated_db.write_text(json.dumps({}))
        domain_db.write_text(json.dumps({}))

        database = ClassificationDatabase(
            suggestion_db_path=suggestion_db,
            validated_db_path=validated_db,
            domain_db_path=domain_db,
        )

        # Mock invalid JSON response
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Not valid JSON at all"
        mock_litellm.completion.return_value = mock_response

        email = Email(
            msg_id="test-123",
            sender_address="test@example.com",
            sender_name="Test",
            subject="Test",
            body="Test body",
            labels=[],
        )

        # Act
        classifier = Classifier(test_config, database)
        result = classifier.classify_email(email)

        # Assert - falls back to unclassified
        assert result == "À Classer"
