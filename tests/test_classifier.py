from collections import defaultdict
from pathlib import Path

import pytest
import yaml
from pytest_mock import MockerFixture

from mailtag.classifier import Classifier
from mailtag.config import (
    AppConfig,
    ClassifierConfig,
    GeneralConfig,
    GmailConfig,
    ImapConfig,
    LoggingConfig,
)
from mailtag.database import ClassificationDatabase
from mailtag.models import Email


@pytest.fixture
def mock_db(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked ClassificationDatabase."""
    db = mocker.MagicMock(spec=ClassificationDatabase)
    db.sender_db = defaultdict(lambda: defaultdict(int))
    return db


@pytest.fixture
def config() -> AppConfig:
    """Returns a default AppConfig for testing."""
    return AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
        ),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7,
            historical_confidence_threshold=0.9,
            min_count=3,
        ),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
    )


@pytest.fixture
def classifier(config: AppConfig, mock_db: MockerFixture, mocker: MockerFixture) -> Classifier:
    """Returns a Classifier instance with a mocked database."""
    schema_content = """
    - name: Finances
      sublabels:
        - name: Bloomberg
    - name: Services
      sublabels:
        - name: Skylum
    - name: À Classer
    """
    # Mock Path object to control file operations
    mock_path_constructor = mocker.patch("pathlib.Path")
    mock_path_instance = mock_path_constructor.return_value
    mock_path_instance.exists.return_value = True
    # Create a mock file object for the context manager
    mock_file = mocker.mock_open(read_data=schema_content)
    mock_path_instance.open.return_value = mock_file.return_value

    # Mock yaml.safe_load to return the parsed schema
    mocker.patch("yaml.safe_load", return_value=yaml.safe_load(schema_content))

    # Initialize the classifier
    classifier_instance = Classifier(config=config, database=mock_db)
    # Mock the proposal file to prevent actual file writes
    classifier_instance.proposal_file = mocker.MagicMock(spec=Path)
    return classifier_instance


# --- AMSC Strategy Tests ---


def test_signal_1_server_label_match(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if an email has a server-side label matching a category,
    it is used for classification immediately.
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
    mock_db.update.assert_called_once_with("test@example.com", "Services/Skylum")
    mock_ai.assert_not_called()


def test_signal_2_historical_match(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if no server label matches, but a high-confidence historical
    category exists, it is used.
    """
    sender = "history@example.com"
    mock_db.sender_db[sender] = defaultdict(int, {"Finances/Bloomberg": 10, "À Classer": 1})
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

    assert category == "Finances/Bloomberg"
    mock_db.update.assert_not_called()  # DB is not updated when using historical data
    mock_ai.assert_not_called()


def test_signal_3_ai_fallback(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
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

    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai", return_value="Finances/Bloomberg")

    category = classifier.classify_email(email)

    assert category == "Finances/Bloomberg"
    mock_ai.assert_called_once_with(email)
    mock_db.update.assert_called_once_with(sender, "Finances/Bloomberg")


def test_no_signals_match(classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture):
    """
    Tests that if no signals match and the AI returns 'À Classer',
    the database is not updated.
    """
    sender = "unclassified@example.com"
    email = Email(
        msg_id="1",
        subject="Unclassified Test",
        sender_address=sender,
        sender_name="Unclassified",
        body="Test body",
        labels=["Inbox"],
    )
    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai", return_value="À Classer")

    category = classifier.classify_email(email)

    assert category == "À Classer"
    mock_ai.assert_called_once_with(email)
    mock_db.update.assert_not_called()


def test_historical_match_below_threshold(
    classifier: Classifier, mock_db: MockerFixture, mocker: MockerFixture
):
    """
    Tests that the AI is used if historical data exists but is below the
    confidence threshold.
    """
    sender = "low-confidence@example.com"
    # Confidence is 2/3 = 0.66, which is below the 0.9 threshold
    mock_db.sender_db[sender] = defaultdict(int, {"Finances/Bloomberg": 2, "Services/Skylum": 1})
    email = Email(
        msg_id="1",
        subject="Low Confidence",
        sender_address=sender,
        sender_name="LowCo",
        body="Test body",
        labels=["Inbox"],
    )
    mock_ai = mocker.patch.object(classifier, "_get_category_from_ai", return_value="Services/Skylum")

    category = classifier.classify_email(email)

    assert category == "Services/Skylum"
    mock_ai.assert_called_once_with(email)
    mock_db.update.assert_called_once_with(sender, "Services/Skylum")
