from unittest.mock import patch, mock_open, MagicMock

import pytest
import yaml
from pathlib import Path

from mailtag.classifier import Classifier
from mailtag.database import ClassificationDatabase
from mailtag.models import Email


@pytest.fixture
def mock_db() -> MagicMock:
    """Fixture for a mocked ClassificationDatabase."""
    db = MagicMock(spec=ClassificationDatabase)
    db.get_classification_count.return_value = 1
    return db


@pytest.fixture
def classifier(mock_db: MagicMock) -> Classifier:
    """Returns a Classifier instance with a mocked database."""
    schema_content = """
    - name: Finances
      sublabels:
        - name: Bloomberg
    - name: À Classer
    """
    # Mock for the schema file
    mock_schema_path = MagicMock(spec=Path)
    mock_schema_path.exists.return_value = True
    mock_schema_path.open.return_value = mock_open(read_data=schema_content).return_value

    # We'll patch the Path constructor to return our mock
    with patch("pathlib.Path", return_value=mock_schema_path):
        with patch("yaml.safe_load", return_value=yaml.safe_load(schema_content)):
            classifier_instance = Classifier(model="test-model", database=mock_db)
            # Now, replace the proposal_file attribute with a separate mock
            classifier_instance.proposal_file = MagicMock(spec=Path)
            yield classifier_instance


def test_classify_and_update_db(classifier: Classifier, mock_db: MagicMock):
    """Tests that a successful classification updates the database."""
    email = Email(
        msg_id=1,
        subject="Test Subject",
        sender_address="sender@example.com",
        sender_name="Sender Name",
    )
    body = "This is a test email body."

    with patch("ollama.generate") as mock_ollama_generate:
        mock_ollama_generate.return_value = {"response": "Finances/Bloomberg"}
        category = classifier.classify_email(email, body)
        assert category == "Finances/Bloomberg"
        mock_db.update.assert_called_once_with(
            "sender@example.com", "Finances/Bloomberg"
        )


def test_classify_email_with_uncertain_match(classifier: Classifier, mock_db: MagicMock):
    """Tests the email classification logic with an uncertain match."""
    email = Email(
        msg_id=1,
        subject="New Bill",
        sender_address="utility@example.com",
        sender_name="Utility Co",
    )
    body = "Your new bill is available."

    with patch("ollama.generate") as mock_ollama_generate:
        mock_ollama_generate.return_value = {
            "response": "UNCERTAIN: Finances/Utilities"
        }
        # Since proposal_file is a Path object, we mock its open method
        with patch.object(classifier.proposal_file, "open", mock_open()) as m:
            category = classifier.classify_email(email, body)
            assert category == "À Classer"
            m.assert_called_once_with("a", encoding="utf-8")
            m().write.assert_called()
            mock_db.update.assert_not_called()


def test_classify_email_with_unknown_category(classifier: Classifier, mock_db: MagicMock):
    """Tests the email classification logic with an unknown category."""
    email = Email(
        msg_id=1,
        subject="Random Stuff",
        sender_address="random@example.com",
        sender_name="Random Sender",
    )
    body = "This email is about something completely new."

    with patch("ollama.generate") as mock_ollama_generate:
        mock_ollama_generate.return_value = {"response": "NewStuff/Personal"}
        with patch.object(classifier.proposal_file, "open", mock_open()) as m:
            category = classifier.classify_email(email, body)
            assert category == "À Classer"
            m.assert_called_once_with("a", encoding="utf-8")
            m().write.assert_called()
            mock_db.update.assert_not_called()

