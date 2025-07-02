import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from mailtag.logging_config import setup_logging


@patch("logging.getLogger")
def test_setup_logging_basic(mock_get_logger: MagicMock):
    """Tests basic logging configuration (console only)."""
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger

    setup_logging("INFO", None)

    mock_get_logger.assert_called_once()
    mock_logger.setLevel.assert_called_once_with(logging.INFO)
    assert mock_logger.addHandler.call_count == 1


@patch("logging.getLogger")
def test_setup_logging_with_file(mock_get_logger: MagicMock, tmp_path: Path):
    """Tests logging configuration with a file."""
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger
    log_file = tmp_path / "test.log"

    setup_logging("DEBUG", str(log_file))

    mock_get_logger.assert_called_once()
    mock_logger.setLevel.assert_called_once_with(logging.DEBUG)
    assert mock_logger.addHandler.call_count == 2
    assert log_file.exists()


@patch("logging.getLogger")
def test_setup_logging_invalid_level(mock_get_logger: MagicMock):
    """Tests that an invalid logging level defaults to INFO."""
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger

    setup_logging("INVALID_LEVEL", None)

    mock_get_logger.assert_called_once()
    mock_logger.setLevel.assert_called_once_with(logging.INFO)
