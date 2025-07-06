import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mailtag.filter_generator import FilterGenerator


@pytest.fixture
def mock_db_path(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked database path."""
    return mocker.MagicMock(spec=Path)


@pytest.fixture
def mock_output_path(mocker: MockerFixture) -> MockerFixture:
    """Fixture for a mocked output path."""
    return mocker.MagicMock(spec=Path)


def test_generate_filters(
    mock_db_path: MockerFixture, mock_output_path: MockerFixture, mocker: MockerFixture
):
    """Tests the filter generation logic."""
    db_content = {
        "sender1@example.com": {"Finances/Bloomberg": 5, "À Classer": 1},
        "sender2@example.com": {"Services/Apple": 10},
        "sender3@example.com": {},
    }
    mock_db_path.exists.return_value = True
    mocker.patch.object(mock_db_path, "open", mocker.mock_open(read_data=json.dumps(db_content)))
    generator = FilterGenerator(db_path=mock_db_path, output_path=mock_output_path)

    m = mocker.patch.object(mock_output_path, "open", mocker.mock_open())
    generator.generate_filters()
    m.assert_called_once_with("w", encoding="utf-8")

    # Get the content that was written to the file
    written_content = m().write.call_args[0][0]

    # Perform some basic checks on the generated XML
    assert "sender1@example.com" in written_content
    assert "Finances/Bloomberg" in written_content
    assert "sender2@example.com" in written_content
    assert "Services/Apple" in written_content
    assert "sender3@example.com" not in written_content


def test_generate_filters_empty_db(
    mock_db_path: MockerFixture, mock_output_path: MockerFixture, mocker: MockerFixture
):
    """Tests filter generation with an empty database."""
    mock_db_path.exists.return_value = False
    generator = FilterGenerator(db_path=mock_db_path, output_path=mock_output_path)

    m = mocker.patch.object(mock_output_path, "open", mocker.mock_open())
    generator.generate_filters()
    m.assert_called_once_with("w", encoding="utf-8")
    written_content = m().write.call_args[0][0]
    assert "<entry>" not in written_content
