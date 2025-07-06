import json
from collections import defaultdict
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mailtag.database import ClassificationDatabase


@pytest.fixture
def mock_suggestion_db_path(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked suggestion database path."""
    return mocker.MagicMock(spec=Path)


@pytest.fixture
def mock_validated_db_path(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked validated database path."""
    return mocker.MagicMock(spec=Path)


def test_load_db_file_not_found(
    mock_suggestion_db_path: MockerFixture, mock_validated_db_path: MockerFixture
):
    """Tests that an empty db is created when the file doesn't exist."""
    mock_suggestion_db_path.exists.return_value = False
    mock_validated_db_path.exists.return_value = False
    db = ClassificationDatabase(
        suggestion_db_path=mock_suggestion_db_path, validated_db_path=mock_validated_db_path
    )
    assert db.suggestion_db == defaultdict(lambda: defaultdict(int))
    assert db.validated_db == defaultdict(lambda: defaultdict(int))


def test_load_db_with_content(
    mock_suggestion_db_path: MockerFixture, mock_validated_db_path: MockerFixture, mocker: MockerFixture
):
    """Tests loading a database with existing content."""
    suggestion_db_content = {
        "sender@example.com": {"Finance/Bloomberg": 1},
        "another@sender.com": {"À Classer": 5},
    }
    validated_db_content = {"validated@sender.com": {"Validated/Category": 1}}
    mock_suggestion_db_path.exists.return_value = True
    mock_validated_db_path.exists.return_value = True
    mocker.patch.object(
        mock_suggestion_db_path, "open", mocker.mock_open(read_data=json.dumps(suggestion_db_content))
    )
    mocker.patch.object(
        mock_validated_db_path, "open", mocker.mock_open(read_data=json.dumps(validated_db_content))
    )
    db = ClassificationDatabase(
        suggestion_db_path=mock_suggestion_db_path, validated_db_path=mock_validated_db_path
    )
    assert db.get_classification_count("sender@example.com", "Finance/Bloomberg") == 1
    assert db.get_classification_count("another@sender.com", "À Classer") == 5
    assert db.get_dominant_classification("validated@sender.com") == "Validated/Category"


def test_update_suggestion_db(
    mock_suggestion_db_path: MockerFixture,
    mock_validated_db_path: MockerFixture,
    mocker: MockerFixture,
):
    """Tests updating the suggestion database."""
    mock_suggestion_db_path.exists.return_value = False
    mock_validated_db_path.exists.return_value = False
    db = ClassificationDatabase(
        suggestion_db_path=mock_suggestion_db_path, validated_db_path=mock_validated_db_path
    )

    m = mocker.patch.object(mock_suggestion_db_path, "open", mocker.mock_open())
    db.update_suggestion("sender@example.com", "Finance/Bloomberg")
    assert db.get_classification_count("sender@example.com", "Finance/Bloomberg") == 1

    db.update_suggestion("sender@example.com", "Finance/Bloomberg")
    assert db.get_classification_count("sender@example.com", "Finance/Bloomberg") == 2

    # Check that save was called twice
    assert m.call_count == 2


def test_promote_to_validated(
    mock_suggestion_db_path: MockerFixture, mock_validated_db_path: MockerFixture, mocker: MockerFixture
):
    """Tests promoting a classification to the validated database."""
    suggestion_db_content = {"sender@example.com": {"Finance/Bloomberg": 1}}
    mock_suggestion_db_path.exists.return_value = True
    mock_validated_db_path.exists.return_value = False
    mocker.patch.object(
        mock_suggestion_db_path, "open", mocker.mock_open(read_data=json.dumps(suggestion_db_content))
    )
    db = ClassificationDatabase(
        suggestion_db_path=mock_suggestion_db_path, validated_db_path=mock_validated_db_path
    )

    m_suggestion = mocker.patch.object(mock_suggestion_db_path, "open", mocker.mock_open())
    m_validated = mocker.patch.object(mock_validated_db_path, "open", mocker.mock_open())

    db.promote_to_validated("sender@example.com", "Finance/Bloomberg")

    assert "sender@example.com" not in db.suggestion_db
    assert db.validated_db["sender@example.com"] == {"Finance/Bloomberg": 1}
    assert m_suggestion.call_count == 1
    assert m_validated.call_count == 1


def test_get_dominant_classification(
    mock_suggestion_db_path: MockerFixture, mock_validated_db_path: MockerFixture, mocker: MockerFixture
):
    """Tests that the dominant classification is correctly retrieved."""
    suggestion_db_content = {"sender@example.com": {"Suggestion/Category": 5}}
    validated_db_content = {"sender@example.com": {"Validated/Category": 1}}
    mock_suggestion_db_path.exists.return_value = True
    mock_validated_db_path.exists.return_value = True
    mocker.patch.object(
        mock_suggestion_db_path, "open", mocker.mock_open(read_data=json.dumps(suggestion_db_content))
    )
    mocker.patch.object(
        mock_validated_db_path, "open", mocker.mock_open(read_data=json.dumps(validated_db_content))
    )
    db = ClassificationDatabase(
        suggestion_db_path=mock_suggestion_db_path, validated_db_path=mock_validated_db_path
    )

    assert db.get_dominant_classification("sender@example.com") == "Validated/Category"
    assert db.get_dominant_classification("new@sender.com") is None
