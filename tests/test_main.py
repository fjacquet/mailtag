from unittest.mock import patch, MagicMock
import pytest
from src.main import main

@patch("src.main.setup_logging")
@patch("src.main.run_classification")
def test_main_run_classification_default(mock_run, mock_logging):
    """Tests that run_classification is called by default."""
    with patch("sys.argv", ["src/main.py"]):
        main()
        mock_run.assert_called_once()

@patch("src.main.setup_logging")
@patch("src.main.generate_filters")
def test_main_generate_filters(mock_generate, mock_logging):
    """Tests that generate_filters is called with the --generate-filters flag."""
    with patch("sys.argv", ["src/main.py", "--generate-filters"]):
        main()
        mock_generate.assert_called_once()

@patch("src.main.setup_logging")
@patch("src.main.run_classification")
def test_main_provider_selection(mock_run, mock_logging):
    """Tests that the provider is correctly selected."""
    with patch("sys.argv", ["src/main.py", "--provider", "gmail"]):
        main()
        # We can't directly assert the provider object, but we can check the args
        args = mock_run.call_args[0][0]
        assert args.provider == "gmail"

@patch("src.main.setup_logging")
@patch("src.main.run_classification")
def test_main_filter_arguments(mock_run, mock_logging):
    """Tests that filter arguments are correctly passed."""
    with patch("sys.argv", ["src/main.py", "--subject", "Test", "--sender", "test@test.com", "--status", "UNSEEN"]):
        main()
        args = mock_run.call_args[0][0]
        assert args.subject == "Test"
        assert args.sender == "test@test.com"
        assert args.status == "UNSEEN"
