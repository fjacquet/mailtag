from unittest.mock import patch, mock_open, MagicMock
import json
from pathlib import Path
import pytest
from collections import defaultdict

from mailtag.database import ClassificationDatabase


@pytest.fixture
def mock_db_path() -> MagicMock:
    """Fixture for a mocked database path."""
    return MagicMock(spec=Path)


def test_load_db_file_not_found(mock_db_path: MagicMock):
    """Tests that an empty db is created when the file doesn't exist."""
    mock_db_path.exists.return_value = False
    db = ClassificationDatabase(db_path=mock_db_path)
    assert db.sender_db == defaultdict(lambda: defaultdict(int))


def test_load_db_with_content(mock_db_path: MagicMock):
    """Tests loading a database with existing content."""
    db_content = {
        "sender@example.com": {"Finances/Bloomberg": 1},
        "another@sender.com": {"À Classer": 5},
    }
    mock_db_path.exists.return_value = True
    with patch.object(mock_db_path, "open", mock_open(read_data=json.dumps(db_content))):
        db = ClassificationDatabase(db_path=mock_db_path)
        assert db.get_classification_count("sender@example.com", "Finances/Bloomberg") == 1
        assert db.get_classification_count("another@sender.com", "À Classer") == 5


def test_update_db(mock_db_path: MagicMock):
    """Tests updating the database."""
    mock_db_path.exists.return_value = False
    db = ClassificationDatabase(db_path=mock_db_path)

    with patch.object(mock_db_path, "open", mock_open()) as m:
        db.update("sender@example.com", "Finances/Bloomberg")
        assert db.get_classification_count("sender@example.com", "Finances/Bloomberg") == 1

        db.update("sender@example.com", "Finances/Bloomberg")
        assert db.get_classification_count("sender@example.com", "Finances/Bloomberg") == 2

        # Check that save was called twice
        assert m.call_count == 2

def test_load_db_corrupted_file(mock_db_path: MagicMock):
    """Tests that an empty db is created when the file is corrupted."""
    mock_db_path.exists.return_value = True
    with patch.object(mock_db_path, "open", mock_open(read_data="invalid json")):
        db = ClassificationDatabase(db_path=mock_db_path)
        assert db.sender_db == defaultdict(lambda: defaultdict(int))