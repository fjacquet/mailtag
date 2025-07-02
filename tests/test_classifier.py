from unittest.mock import patch

import pytest

from mailtag.classifier import Classifier
from mailtag.models import Email


@pytest.fixture
def classifier() -> Classifier:
    """Returns a Classifier instance."""
    return Classifier(model="test-model")


def test_classify_email(classifier: Classifier):
    """Tests the email classification logic."""
    email = Email(
        msg_id=1,
        subject="Test Subject",
        sender_address="sender@example.com",
        sender_name="Sender Name",
    )
    body = "This is a test email body."

    with patch("ollama.generate") as mock_ollama_generate:
        mock_ollama_generate.return_value = {"response": "Test Category"}
        category = classifier.classify_email(email, body)
        assert category == "Test Category"
        mock_ollama_generate.assert_called_once()
