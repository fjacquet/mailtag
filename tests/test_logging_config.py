from unittest.mock import patch, mock_open
from mailtag.logging_config import setup_logging

def test_setup_logging(tmp_path):
    """Tests the loguru logging configuration."""
    log_file = tmp_path / "test.log"
    with patch("loguru.logger.add") as mock_add:
        setup_logging("INFO", str(log_file))
        assert mock_add.call_count == 2
        # Check the stderr handler
        mock_add.call_args_list[0].kwargs["level"] == "INFO"
        # Check the file handler
        mock_add.call_args_list[1].kwargs["level"] == "INFO"
        mock_add.call_args_list[1].args[0] == str(log_file)
