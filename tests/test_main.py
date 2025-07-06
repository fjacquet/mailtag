import pytest
from pytest_mock import MockerFixture

from mailtag.config import LoggingConfig


@pytest.fixture
def mock_app_config(mocker: MockerFixture):
    """Mocks the global CONFIG object in the app module."""
    mock_config = mocker.patch("app.CONFIG")
    mock_config.logging = LoggingConfig(level="INFO", file="test.log")
    # Ensure providers are configured for tests that need them
    mock_config.imap = mocker.MagicMock()
    mock_config.gmail = mocker.MagicMock()
    return mock_config


class TestMain:
    def test_main_generate_filters(self, mocker: MockerFixture, mock_app_config):
        """Tests that generate_filters is called with the --generate-filters flag."""
        from app import main

        mocker.patch("sys.argv", ["src/main.py", "--generate-filters"])
        mock_generate = mocker.patch("app.generate_filters")
        main()
        mock_generate.assert_called_once()

    def test_main_run_classification_default_both_providers(self, mocker: MockerFixture, mock_app_config):
        """Tests that run_classification is called for both providers by default."""
        from app import main

        mocker.patch("sys.argv", ["src/main.py"])
        mock_run = mocker.patch("app.run_classification")
        main()
        assert mock_run.call_count == 2

    def test_main_provider_selection_gmail(self, mocker: MockerFixture, mock_app_config):
        """Tests that the correct provider is used when selected."""
        from app import main

        mocker.patch("sys.argv", ["src/main.py", "--provider", "gmail"])
        mock_run = mocker.patch("app.run_classification")
        main()
        mock_run.assert_called_once()
        args, provider, database = mock_run.call_args[0]
        assert provider.__class__.__name__ == "GmailService"

    def test_main_validate_mode(self, mocker: MockerFixture, mock_app_config):
        """
        Tests that when --validate is passed, the 'validate' argument is True
        and the database's promote_to_validated method is called.
        """
        from app import main

        mocker.patch("sys.argv", ["src/main.py", "--validate", "sender@example.com"])
        mock_db = mocker.patch("app.ClassificationDatabase")
        mock_db.return_value.get_dominant_classification.return_value = "Suggestion/Category"
        main()
        mock_db.return_value.promote_to_validated.assert_called_once_with(
            "sender@example.com", "Suggestion/Category"
        )

    def test_main_invalid_provider(self, mocker: MockerFixture, mock_app_config):
        """Tests that the program exits with an error for an invalid provider."""
        from app import main

        # Make sure no providers are configured to isolate the error
        mock_app_config.imap = None
        mock_app_config.gmail = None
        mocker.patch("sys.argv", ["src/main.py", "--provider", "invalid"])
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 2
