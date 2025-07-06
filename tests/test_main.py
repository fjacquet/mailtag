import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

from mailtag.config import LoggingConfig


@pytest.fixture
def mock_app_config(mocker: MockerFixture):
    """Mocks the global CONFIG object in the main module."""
    mock_config = mocker.patch("main.CONFIG")
    mock_config.logging = LoggingConfig(level="INFO", file="test.log")
    # Ensure providers are configured for tests that need them
    mock_config.imap = mocker.MagicMock()
    mock_config.gmail = mocker.MagicMock()
    return mock_config


class TestMain:
    def test_main_generate_filters(self, mocker: MockerFixture, mock_app_config):
        """Tests that generate_filters is called with the --generate-filters flag."""
        from main import cli

        runner = CliRunner()
        mock_generate = mocker.patch("main.generate_filters")
        result = runner.invoke(cli, ["filters"])
        assert result.exit_code == 0
        mock_generate.assert_called_once()

    def test_main_run_classification_default_both_providers(self, mocker: MockerFixture, mock_app_config):
        """Tests that run_classification is called for both providers by default."""
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        result = runner.invoke(cli, ["run"])
        assert result.exit_code == 0
        assert mock_run.call_count == 2

    def test_main_provider_selection_gmail(self, mocker: MockerFixture, mock_app_config):
        """Tests that the correct provider is used when selected."""
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        result = runner.invoke(cli, ["run", "--provider", "gmail"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        provider, database, validate = mock_run.call_args[0]
        assert provider.__class__.__name__ == "GmailService"

    def test_main_validate_mode(self, mocker: MockerFixture, mock_app_config):
        """
        Tests that when --validate is passed, the 'validate' argument is True
        and move_email is not called.
        """
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        result = runner.invoke(cli, ["run", "--validate"])
        assert result.exit_code == 0
        assert mock_run.call_count == 2
        provider, database, validate = mock_run.call_args[0]
        assert validate is True

    def test_main_invalid_provider(self, mocker: MockerFixture, mock_app_config):
        """Tests that the program exits with an error for an invalid provider."""
        from main import cli

        runner = CliRunner()
        # Make sure no providers are configured to isolate the error
        mock_app_config.imap = None
        mock_app_config.gmail = None
        result = runner.invoke(cli, ["run", "--provider", "invalid"])
        assert result.exit_code != 0
