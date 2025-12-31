from collections import defaultdict
from pathlib import Path

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


@pytest.fixture
def mock_db(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked ClassificationDatabase."""
    db = mocker.MagicMock(spec=ClassificationDatabase)
    db.suggestion_db = defaultdict(lambda: defaultdict(int))
    db.validated_db = defaultdict(lambda: defaultdict(int))
    # Mock the get_dominant_classification to check the validated_db
    db.get_dominant_classification.side_effect = (
        lambda sender: list(db.validated_db.get(sender, {}).keys())[0] if sender in db.validated_db else None
    )
    # Default: no domain classification
    db.get_category_by_domain.return_value = None
    return db


@pytest.fixture
def config() -> AppConfig:
    """Returns a default AppConfig for testing."""
    return AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
            use_imap_folders_for_classification=False,  # Use schema-based categories
        ),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7,
            historical_confidence_threshold=0.9,
            min_count=3,
        ),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(
            batch_size=10,
            folder_cache_ttl_hours=24,
            unclassified_folder_name="Unclassified",
            junk_folder_name="Junk",
        ),
        mlx=MLXConfig(enabled=False),  # Disable MLX for unit tests
    )


@pytest.fixture
def classifier(config: AppConfig, mock_db: MockerFixture, mocker: MockerFixture) -> Classifier:
    """Returns a Classifier instance with a mocked database."""
    # Initialize the classifier
    classifier_instance = Classifier(config=config, database=mock_db)

    # Directly set the categories for testing
    classifier_instance.categories = [
        "Finances/Bloomberg",
        "Services/Skylum",
        "À Classer",
    ]

    # Mock the proposal file to prevent actual file writes
    classifier_instance.proposal_file = mocker.MagicMock(spec=Path)
    return classifier_instance


# --- AMSC Strategy Tests ---


def test_signal_1_validated_db_match(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if an email sender is in the validated DB, it is used for classification immediately.
    """
    sender = "validated@example.com"
    mock_db.validated_db[sender] = {"Validated/Category": 1}
    email = Email(
        msg_id="1",
        subject="Test",
        sender_address=sender,
        sender_name="Test",
        body="Test body",
        labels=["Inbox"],
    )
    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai")

    category = classifier.classify_email(email)

    assert category == "Validated/Category"
    mock_db.update_suggestion.assert_not_called()
    mock_ai.assert_not_called()


def test_signal_2_server_label_match(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if an email has a server-side label matching a category,
    it is used for classification.
    """
    email = Email(
        msg_id="1",
        subject="Test",
        sender_address="test@example.com",
        sender_name="Test",
        body="Test body",
        labels=["Services/Skylum", "Inbox"],
    )
    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai")

    category = classifier.classify_email(email)

    assert category == "Services/Skylum"
    mock_db.update_suggestion.assert_called_once_with("test@example.com", "Services/Skylum")
    mock_ai.assert_not_called()


def test_signal_3_historical_match(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if no server label matches, but a high-confidence historical
    category exists, it is used.
    """
    sender = "history@example.com"
    mock_db.suggestion_db[sender] = defaultdict(int, {"Finance/Bloomberg": 10, "À Classer": 1})
    email = Email(
        msg_id="1",
        subject="History Test",
        sender_address=sender,
        sender_name="History",
        body="Test body",
        labels=["Inbox"],  # No matching server label
    )
    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai")

    category = classifier.classify_email(email)

    assert category == "Finance/Bloomberg"
    mock_db.update_suggestion.assert_not_called()
    mock_ai.assert_not_called()


def test_signal_4_ai_fallback(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if no other signals match, the AI model is used as a fallback.
    """
    sender = "ai@example.com"
    email = Email(
        msg_id="1",
        subject="AI Test",
        sender_address=sender,
        sender_name="AI",
        body="Test body",
        labels=["Inbox"],  # No matching server label
    )
    # No historical data for this sender

    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai", return_value="Finance/Bloomberg")

    category = classifier.classify_email(email)

    assert category == "Finance/Bloomberg"
    mock_ai.assert_called_once_with(email)
    mock_db.update_suggestion.assert_called_once_with(sender, "Finance/Bloomberg")
