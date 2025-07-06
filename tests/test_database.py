import json
from collections import defaultdict
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mailtag.database import ClassificationDatabase


@pytest.fixture
def mock_db_path(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked database path."""
    return mocker.MagicMock(spec=Path)


def test_load_db_file_not_found(mock_db_path: MockerFixture):
    """Tests that an empty db is created when the file doesn't exist."""
    mock_db_path.exists.return_value = False
    db = ClassificationDatabase(db_path=mock_db_path)
    assert db.sender_db == defaultdict(lambda: defaultdict(int))


def test_load_db_with_content(mock_db_path: MockerFixture, mocker: MockerFixture):
    """Tests loading a database with existing content."""
    db_content = {
        "sender@example.com": {"Finances/Bloomberg": 1},
        "another@sender.com": {"À Classer": 5},
    }
    mock_db_path.exists.return_value = True
    mocker.patch.object(mock_db_path, "open", mocker.mock_open(read_data=json.dumps(db_content)))
    db = ClassificationDatabase(db_path=mock_db_path)
    assert db.get_classification_count("sender@example.com", "Finances/Bloomberg") == 1
    assert db.get_classification_count("another@sender.com", "À Classer") == 5


def test_update_db(mock_db_path: MockerFixture, mocker: MockerFixture):
    """Tests updating the database."""
    mock_db_path.exists.return_value = False
    db = ClassificationDatabase(db_path=mock_db_path)

    m = mocker.patch.object(mock_db_path, "open", mocker.mock_open())
    db.update("sender@example.com", "Finances/Bloomberg")
    assert db.get_classification_count("sender@example.com", "Finances/Bloomberg") == 1

    db.update("sender@example.com", "Finances/Bloomberg")
    assert db.get_classification_count("sender@example.com", "Finances/Bloomberg") == 2

    # Check that save was called twice
    assert m.call_count == 2


def test_load_db_corrupted_file(mock_db_path: MockerFixture, mocker: MockerFixture):
    """Tests that an empty db is created when the file is corrupted."""
    mock_db_path.exists.return_value = True
    mocker.patch.object(mock_db_path, "open", mocker.mock_open(read_data="invalid json"))
    db = ClassificationDatabase(db_path=mock_db_path)
    assert db.sender_db == defaultdict(lambda: defaultdict(int))