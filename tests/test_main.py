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
        args, provider = mock_run.call_args[0]
        assert provider.__class__.__name__ == "GmailService"

    def test_main_validate_mode(self, mocker: MockerFixture, mock_app_config):
        """
        Tests that when --validate is passed, the 'validate' argument is True
        and move_email is not called.
        """
        from app import run_classification  # Import the real function to test its behavior

        # Mock components inside run_classification
        mocker.patch("app.ClassificationDatabase")
        mock_classifier = mocker.patch("app.Classifier")
        mock_provider = mocker.MagicMock()
        mock_provider.connect.return_value.__enter__.return_value = mock_provider
        mock_provider.get_emails.return_value = [mocker.MagicMock(msg_id="1")]
        mock_classifier.return_value.classify_email.return_value = "TestCategory"

        # Create a mock for argparse
        mock_args = mocker.MagicMock()
        mock_args.validate = True  # Simulate the --validate flag
        mock_args.subject = None
        mock_args.sender = None
        mock_args.status = None
        mock_args.destination = "Processed"

        # Call the real function with mocked args
        run_classification(mock_args, mock_provider)

        # Assert that the classification logic ran
        mock_provider.connect.assert_called_once()
        mock_provider.get_emails.assert_called_once()
        mock_classifier.return_value.classify_email.assert_called_once()

        # CRITICAL: Assert that move_email was NOT called in validate mode
        mock_provider.move_email.assert_not_called()

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
