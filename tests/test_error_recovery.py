"""Tests for error recovery and resilience.

Tests database corruption recovery, network failure retry logic,
and AI fallback handling.
"""

import json
from datetime import datetime, timedelta

import pytest
from pytest_mock import MockerFixture

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
from mailtag.utils.db_backup import backup_database, cleanup_old_backups, restore_database


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

        # Restore from backup (args: source backup, destination db)
        restore_database(backup_path, db_path)

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

        # Act - create new backup then run rotation
        backup_database(db_path)
        cleanup_old_backups(backup_dir, keep_count=10)

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
    """Test AI model failure handling via MLX LLM."""

    def _make_db(self, tmp_path):
        """Helper to create empty databases."""
        db_path = tmp_path / "db"
        db_path.mkdir()
        suggestion_db = db_path / "sender_classification_db.json"
        validated_db = db_path / "validated_classification_db.json"
        domain_db = db_path / "domain_classifications.json"

        suggestion_db.write_text(json.dumps({}))
        validated_db.write_text(json.dumps({}))
        domain_db.write_text(json.dumps({}))

        return ClassificationDatabase(
            suggestion_db_path=suggestion_db,
            validated_db_path=validated_db,
            domain_db_path=domain_db,
        )

    def test_ai_error_routes_to_unclassified(self, mocker: MockerFixture, test_config, tmp_path):
        """Test AI errors route email to (Model Error)."""
        mock_folder_analyzer = mocker.Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer.get_parent_folders.return_value = []
        mocker.patch("mailtag.classifier.FolderAnalyzer", return_value=mock_folder_analyzer)

        database = self._make_db(tmp_path)

        email = Email(
            msg_id="test-123",
            sender_address="unknown@example.com",
            sender_name="Unknown",
            subject="Test",
            body="Test body",
            labels=[],
        )

        classifier = Classifier(test_config, database)

        # Mock MLX components: semantic router (no match) + LLM (error)
        mock_router = mocker.Mock()
        mock_router.num_categories = 0
        classifier._semantic_router = mock_router
        mock_llm = mocker.Mock()
        mock_llm.classify.side_effect = RuntimeError("Model timeout")
        classifier._mlx_llm = mock_llm
        classifier._mlx_initialized = True

        result = classifier.classify_email(email)
        assert result == "(Model Error)"

    def test_low_confidence_routes_to_unclassified(self, mocker: MockerFixture, test_config, tmp_path):
        """Test low confidence AI results route to À Classer."""
        mock_folder_analyzer = mocker.Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer", "Finance/Banking"]
        mock_folder_analyzer.get_parent_folders.return_value = ["Finance"]
        mock_folder_analyzer.is_valid_parent_folder.return_value = False
        mocker.patch("mailtag.classifier.FolderAnalyzer", return_value=mock_folder_analyzer)

        database = self._make_db(tmp_path)

        email = Email(
            msg_id="test-123",
            sender_address="ambiguous@example.com",
            sender_name="Ambiguous",
            subject="Maybe finance?",
            body="Could be banking related",
            labels=[],
        )

        classifier = Classifier(test_config, database)

        # Mock MLX components: semantic router (no match) + LLM (low confidence)
        mock_router = mocker.Mock()
        mock_router.num_categories = 0
        classifier._semantic_router = mock_router
        mock_llm = mocker.Mock()
        mock_llm.classify.return_value = ("Finance/Banking", 0.7, "Unclear content")
        classifier._mlx_llm = mock_llm
        classifier._mlx_initialized = True

        result = classifier.classify_email(email)
        assert result == "À Classer"

    def test_invalid_json_response_routes_to_unclassified(self, mocker: MockerFixture, test_config, tmp_path):
        """Test invalid JSON from AI routes to À Classer."""
        mock_folder_analyzer = mocker.Mock()
        mock_folder_analyzer.get_all_categories.return_value = ["À Classer"]
        mock_folder_analyzer.get_parent_folders.return_value = []
        mocker.patch("mailtag.classifier.FolderAnalyzer", return_value=mock_folder_analyzer)

        database = self._make_db(tmp_path)

        email = Email(
            msg_id="test-123",
            sender_address="test@example.com",
            sender_name="Test",
            subject="Test",
            body="Test body",
            labels=[],
        )

        classifier = Classifier(test_config, database)

        # Mock MLX components: semantic router (no match) + LLM (invalid JSON)
        mock_router = mocker.Mock()
        mock_router.num_categories = 0
        classifier._semantic_router = mock_router
        mock_llm = mocker.Mock()
        mock_llm.classify.return_value = ("", 0.5, "JSON parsing failed")
        classifier._mlx_llm = mock_llm
        classifier._mlx_initialized = True

        result = classifier.classify_email(email)
        assert result == "À Classer"
