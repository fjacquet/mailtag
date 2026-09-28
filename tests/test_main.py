import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

from mailtag.config import (
    ClassifierConfig,
    FastParseConfig,
    GeneralConfig,
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
    mock_config.general = GeneralConfig(
        ollama_model="test-model",
        api_base="http://localhost:11434",
        use_imap_folders_for_classification=False,
    )
    mock_config.classifier = ClassifierConfig(
        ai_confidence_threshold=0.7,
        historical_confidence_threshold=0.9,
        min_count=3,
    )
    mock_config.fast_parse = FastParseConfig(
        batch_size=100,
        folder_cache_ttl_hours=24,
        unclassified_folder_name="Unclassified",
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
        # Mock the provider classes to avoid actual IMAP/Gmail connections
        mocker.patch("main.ImapService")
        mocker.patch("main.GmailApiService")
        # Mock refresh_imap_folders to avoid actual server calls
        mocker.patch("main.refresh_imap_folders")

        result = runner.invoke(cli, ["run"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        assert mock_run.call_count == 2

    def test_main_provider_selection_gmail(self, mocker: MockerFixture, mock_app_config):
        """--provider gmail builds a GmailApiService from CONFIG.gmail, no folder refresh."""
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        mock_gmail_service = mocker.patch("main.GmailApiService")
        mock_refresh = mocker.patch("main.refresh_imap_folders")

        result = runner.invoke(cli, ["run", "--provider", "gmail"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        mock_gmail_service.assert_called_once_with(mock_app_config.gmail, mock_app_config.fast_parse)
        mock_refresh.assert_not_called()
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
        mocker.patch("main.refresh_imap_folders")

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
        mocker.patch("main.refresh_imap_folders")

        result = runner.invoke(cli, ["run", "--provider", "gmail"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        mock_run.assert_not_called()

    def test_main_validate_mode(self, mocker: MockerFixture, mock_app_config):
        """
        Tests that when --validate is passed, the 'validate' argument is True
        and move_email is not called.
        """
        from main import cli

        runner = CliRunner()
        mock_run = mocker.patch("main.run_classification")
        # Mock the provider classes to avoid actual IMAP/Gmail connections
        mocker.patch("main.ImapService")
        mocker.patch("main.GmailApiService")
        # Mock refresh_imap_folders to avoid actual server calls
        mocker.patch("main.refresh_imap_folders")

        result = runner.invoke(cli, ["run", "--validate"])
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        assert mock_run.call_count == 2
        # Check that validate=True was passed
        for call in mock_run.call_args_list:
            args, kwargs = call
            assert args[2] is True  # validate argument

    def test_main_invalid_provider(self, mocker: MockerFixture, mock_app_config):
        """Tests that the program exits with an error for an invalid provider."""
        from main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--provider", "invalid"])
        assert result.exit_code != 0


@pytest.mark.parametrize("validate", [True, False])
def test_validate_opens_database_read_only(mocker: MockerFixture, validate):
    from main import start_classification_run

    mocker.patch("mailtag.utils.db_backup.backup_all_databases")
    mocker.patch("mailtag.utils.db_backup.cleanup_old_backups")
    config = mocker.patch("main.CONFIG")
    config.imap = None
    database = mocker.patch("main.ClassificationDatabase")

    start_classification_run("imap", validate)

    assert database.call_args.kwargs["read_only"] is validate
