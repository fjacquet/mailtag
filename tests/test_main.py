import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

from mailtag.config import (
    FastParseConfig,
    GmailConfig,
    ImapConfig,
    LoggingConfig,
    MLXConfig,
)


@pytest.fixture
def mock_app_config(mocker: MockerFixture, tmp_path):
    """Mocks the global CONFIG object in the main module."""
    mock_config = mocker.patch("main.CONFIG")
    mock_config.logging = LoggingConfig(level="INFO", file=str(tmp_path / "test.log"))
    mock_config.fast_parse = FastParseConfig(
        batch_size=100,
        junk_folder_name="Junk",
    )
    mock_config.imap = ImapConfig(
        host="imap.test.com",
        user="test@test.com",
        password="testpass",
    )
    mock_config.gmail = GmailConfig(
        credentials_file="creds.json",
        token_file="token.json",
    )
    mock_config.mlx = MLXConfig(enabled=False)
    return mock_config


class TestMain:
    def test_main_run_classification_default_both_providers(self, mocker: MockerFixture, mock_app_config):
        """Tests that run_classification is called for both providers by default."""
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        # Mock the provider classes to avoid actual IMAP/Gmail connections
        mocker.patch("main.ImapService")
        mocker.patch("main.GmailApiService")

        result = runner.invoke(cli, ["run"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        assert mock_run.call_count == 2

    def test_main_provider_selection_gmail(self, mocker: MockerFixture, mock_app_config):
        """--provider gmail builds a GmailApiService from CONFIG.gmail."""
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        mock_gmail_service = mocker.patch("main.GmailApiService")

        result = runner.invoke(cli, ["run", "--provider", "gmail"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        mock_gmail_service.assert_called_once_with(mock_app_config.gmail, mock_app_config.fast_parse)
        mock_run.assert_called_once()

    def test_main_provider_all_without_gmail_runs_infomaniak_only(
        self, mocker: MockerFixture, mock_app_config
    ):
        """No CONFIG.gmail: --provider all runs Infomaniak only, no error."""
        from main import cli

        mock_app_config.gmail = None
        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        mocker.patch("main.ImapService")
        mocker.patch("main.GmailApiService")

        result = runner.invoke(cli, ["run", "--provider", "all"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        mock_run.assert_called_once()

    def test_main_provider_gmail_without_gmail_config_runs_nothing(
        self, mocker: MockerFixture, mock_app_config
    ):
        """No CONFIG.gmail: --provider gmail runs nothing, no error."""
        from main import cli

        mock_app_config.gmail = None
        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        mocker.patch("main.ImapService")
        mocker.patch("main.GmailApiService")

        result = runner.invoke(cli, ["run", "--provider", "gmail"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        mock_run.assert_not_called()

    def test_main_validate_mode(self, mocker: MockerFixture, mock_app_config):
        """
        Tests that when --validate is passed, the 'validate' argument is True
        and no email is moved.
        """
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        # Mock the provider classes to avoid actual IMAP/Gmail connections
        mocker.patch("main.ImapService")
        mocker.patch("main.GmailApiService")

        result = runner.invoke(cli, ["run", "--validate"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        assert mock_run.call_count == 2
        # Check that validate=True was passed
        for call in mock_run.call_args_list:
            args, kwargs = call
            assert args[1] is True  # validate argument

    def test_main_invalid_provider(self, mocker: MockerFixture, mock_app_config):
        """Tests that the program exits with an error for an invalid provider."""
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--provider", "invalid"])
        assert result.exit_code != 0


@pytest.mark.parametrize("validate", [True, False])
def test_run_passes_validate_to_each_provider(mocker: MockerFixture, validate):
    from main import start_classification_run

    mocker.patch("mailtag.utils.db_backup.backup_all_databases")
    mocker.patch("mailtag.utils.db_backup.cleanup_old_backups")
    config = mocker.patch("main.CONFIG")
    config.gmail = None
    mocker.patch("main.ImapService")
    run = mocker.patch("main.run_classification")

    start_classification_run("imap", validate)

    assert run.call_args.args[1] is validate


@pytest.mark.parametrize("validate", [True, False])
def test_backups_only_on_real_runs(mocker: MockerFixture, validate):
    from main import start_classification_run

    backup = mocker.patch("mailtag.utils.db_backup.backup_all_databases")
    cleanup = mocker.patch("mailtag.utils.db_backup.cleanup_old_backups")
    config = mocker.patch("main.CONFIG")
    config.gmail = None
    mocker.patch("main.ImapService")
    mocker.patch("main.run_classification")

    start_classification_run("imap", validate)

    assert backup.call_count == cleanup.call_count == (0 if validate else 1)


def test_only_run_and_serve_remain():
    from main import cli

    assert sorted(cli.commands) == ["run", "serve"]
