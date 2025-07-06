import pytest
from pytest_mock import MockerFixture


@pytest.mark.usefixtures("mocker")
class TestMain:
    def test_main_generate_filters(self, mocker: MockerFixture):
        """Tests that generate_filters is called with the --generate-filters flag."""
        from app import main
        mocker.patch("sys.argv", ["src/main.py", "--generate-filters"])
        mock_generate = mocker.patch("app.generate_filters")
        main()
        mock_generate.assert_called_once()

    def test_main_run_classification_default_both_providers(self, mocker: MockerFixture):
        """Tests that run_classification is called for both providers by default."""
        from app import main
        mock_config = mocker.patch("app.CONFIG")
        mock_config.imap = mocker.MagicMock()
        mock_config.gmail = mocker.MagicMock()

        mocker.patch("sys.argv", ["src/main.py"])
        mock_run = mocker.patch("app.run_classification")
        
        main()
        
        assert mock_run.call_count == 2

    def test_main_run_classification_default_one_provider(self, mocker: MockerFixture):
        """Tests that run_classification is called for one provider if only one is configured."""
        from app import main
        mock_config = mocker.patch("app.CONFIG")
        mock_config.imap = mocker.MagicMock()
        mock_config.gmail = None

        mocker.patch("sys.argv", ["src/main.py"])
        mock_run = mocker.patch("app.run_classification")
        main()
        mock_run.assert_called_once()

    def test_main_provider_selection_gmail(self, mocker: MockerFixture):
        """Tests that the correct provider is used when selected."""
        from app import main
        mock_config = mocker.patch("app.CONFIG")
        mock_config.imap = mocker.MagicMock()
        mock_config.gmail = mocker.MagicMock()
        
        mocker.patch("sys.argv", ["src/main.py", "--provider", "gmail"])
        mock_run = mocker.patch("app.run_classification")
        main()
        mock_run.assert_called_once()
        _, provider = mock_run.call_args[0]
        assert provider.__class__.__name__ == "GmailService"


    def test_main_provider_selection_imap(self, mocker: MockerFixture):
        """Tests that the correct provider is used when selected."""
        from app import main
        mock_config = mocker.patch("app.CONFIG")
        mock_config.imap = mocker.MagicMock()
        mock_config.gmail = mocker.MagicMock()

        mocker.patch("sys.argv", ["src/main.py", "--provider", "imap"])
        mock_run = mocker.patch("app.run_classification")
        main()
        mock_run.assert_called_once()
        _, provider = mock_run.call_args[0]
        assert provider.__class__.__name__ == "ImapService"


    def test_main_filter_arguments(self, mocker: MockerFixture):
        """Tests that filter arguments are correctly passed."""
        from app import main
        mock_config = mocker.patch("app.CONFIG")
        mock_config.imap = mocker.MagicMock()
        mock_config.gmail = None

        mocker.patch("sys.argv", ["src/main.py", "--subject", "Test", "--sender", "test@test.com", "--status", "UNSEEN"])
        mock_run = mocker.patch("app.run_classification")
        main()
        mock_run.assert_called_once()
        args, _ = mock_run.call_args[0]
        assert args.subject == "Test"
        assert args.sender == "test@test.com"
        assert args.status == "UNSEEN"

    def test_main_invalid_provider(self, mocker: MockerFixture):
        """Tests that the program exits with an error for an invalid provider."""
        from app import main
        mocker.patch("sys.argv", ["src/main.py", "--provider", "invalid"])
        with pytest.raises(SystemExit):
            main()