from unittest.mock import patch, mock_open, MagicMock

import pytest
import yaml
from pathlib import Path
from collections import defaultdict

from mailtag.classifier import Classifier
from mailtag.database import ClassificationDatabase
from mailtag.models import Email
from mailtag.config import AppConfig, GeneralConfig, LoggingConfig, PreclassificationConfig


@pytest.fixture
def mock_db() -> MagicMock:
    """Fixture for a mocked ClassificationDatabase."""
    db = MagicMock(spec=ClassificationDatabase)
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
        preclassification=PreclassificationConfig(
            enabled=True, min_count=3, confidence_threshold=0.8
        ),
    )


@pytest.fixture
def classifier(config: AppConfig, mock_db: MagicMock) -> Classifier:
    """Returns a Classifier instance with a mocked database."""
    schema_content = """
    - name: Finances
      sublabels:
        - name: Bloomberg
    - name: À Classer
    """
    with patch("pathlib.Path") as mock_path_constructor:
        mock_path_instance = mock_path_constructor.return_value
        mock_path_instance.exists.return_value = True
        mock_path_instance.open.return_value = mock_open(
            read_data=schema_content
        ).return_value

        with patch("yaml.safe_load", return_value=yaml.safe_load(schema_content)):
            classifier_instance = Classifier(config=config, database=mock_db)
            classifier_instance.proposal_file = MagicMock(spec=Path)
            yield classifier_instance


def test_preclassification_success(classifier: Classifier, mock_db: MagicMock):
    """Tests that pre-classification is used when confidence is high."""
    sender = "confident@example.com"
    mock_db.sender_db[sender] = defaultdict(int, {"Finances/Bloomberg": 4, "À Classer": 1})
    
    email = Email(msg_id=1, subject="Confident", sender_address=sender, sender_name="")
    body = "This should be pre-classified."

    with patch("litellm.completion") as mock_completion:
        category = classifier.classify_email(email, body)
        assert category == "Finances/Bloomberg"
        mock_completion.assert_not_called()


def test_preclassification_failure_low_confidence(classifier: Classifier, mock_db: MagicMock):
    """Tests that LLM is called when pre-classification confidence is low."""
    sender = "unsure@example.com"
    mock_db.sender_db[sender] = defaultdict(int, {"Finances/Bloomberg": 2, "À Classer": 2})

    email = Email(msg_id=1, subject="Unsure", sender_address=sender, sender_name="")
    body = "This should not be pre-classified."

    with patch("litellm.completion") as mock_completion:
        mock_choice = MagicMock()
        mock_choice.message.content = "Finances/Bloomberg"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response
        
        category = classifier.classify_email(email, body)
        assert category == "Finances/Bloomberg"
        mock_completion.assert_called_once()
        mock_db.update.assert_called_once_with(sender, "Finances/Bloomberg")

def test_preclassification_failure_min_count(classifier: Classifier, mock_db: MagicMock):
    """Tests that LLM is called when the sender has too few classifications."""
    sender = "new@example.com"
    mock_db.sender_db[sender] = defaultdict(int, {"Finances/Bloomberg": 1})

    email = Email(msg_id=1, subject="New", sender_address=sender, sender_name="")
    body = "This should not be pre-classified."

    with patch("litellm.completion") as mock_completion:
        mock_choice = MagicMock()
        mock_choice.message.content = "Finances/Bloomberg"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response
        
        category = classifier.classify_email(email, body)
        assert category == "Finances/Bloomberg"
        mock_completion.assert_called_once()
        mock_db.update.assert_called_once_with(sender, "Finances/Bloomberg")

def test_uncertain_classification(classifier: Classifier):
    """Tests that 'À Classer' is returned for uncertain classifications."""
    email = Email(msg_id=1, subject="Uncertain", sender_address="test@example.com", sender_name="")
    body = "This is an uncertain email."

    with patch("litellm.completion") as mock_completion:
        mock_choice = MagicMock()
        mock_choice.message.content = "UNCERTAIN: New Category"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        category = classifier.classify_email(email, body)
        assert category == "À Classer"
        classifier.proposal_file.open.assert_called_once_with("a", encoding="utf-8")

def test_new_category_proposal(classifier: Classifier):
    """Tests that 'À Classer' is returned when a new category is proposed."""
    email = Email(msg_id=1, subject="New Cat", sender_address="test@example.com", sender_name="")
    body = "This email suggests a new category."

    with patch("litellm.completion") as mock_completion:
        mock_choice = MagicMock()
        mock_choice.message.content = "New/Category"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        category = classifier.classify_email(email, body)
        assert category == "À Classer"
        classifier.proposal_file.open.assert_called_once_with("a", encoding="utf-8")

def test_model_error(classifier: Classifier):
    """Tests that '(Model Error)' is returned when the LLM call fails."""
    email = Email(msg_id=1, subject="Error", sender_address="test@example.com", sender_name="")
    body = "This email will cause an error."

    with patch("litellm.completion") as mock_completion:
        mock_completion.side_effect = Exception("Test error")

        category = classifier.classify_email(email, body)
        assert category == "(Model Error)"