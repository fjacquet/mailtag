from pytest_mock import MockerFixture

from mailtag.logging_config import setup_logging


def test_setup_logging(tmp_path, mocker: MockerFixture):
    """Tests the loguru logging configuration."""
    log_file = tmp_path / "test.log"
    mock_add = mocker.patch("loguru.logger.add")
    setup_logging("INFO", str(log_file))
    assert mock_add.call_count == 2
    # Check the stderr handler
    assert mock_add.call_args_list[0].kwargs["level"] == "INFO"
    # Check the file handler
    assert mock_add.call_args_list[1].kwargs["level"] == "INFO"
    assert mock_add.call_args_list[1].args[0] == str(log_file)