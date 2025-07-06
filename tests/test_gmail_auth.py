from unittest.mock import patch, mock_open
import pytest
from mailtag.gmail_auth import get_gmail_service

@patch("os.path.exists")
@patch("google.oauth2.credentials.Credentials.from_authorized_user_file")
@patch("googleapiclient.discovery.build")
def test_get_gmail_service_with_token(mock_build, mock_from_file, mock_exists):
    """Tests that the service is built correctly when a valid token exists."""
    mock_exists.return_value = True
    get_gmail_service("creds.json", "token.json")
    mock_from_file.assert_called_once_with("token.json", ["https://www.googleapis.com/auth/gmail.modify"])
    mock_build.assert_called_once()

@patch("os.path.exists")
@patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file")
@patch("googleapiclient.discovery.build")
def test_get_gmail_service_no_token(mock_build, mock_flow, mock_exists):
    """Tests the OAuth flow when no token exists."""
    mock_exists.side_effect = [False, True] # No token, but creds exist
    mock_flow_instance = mock_flow.return_value
    mock_creds = mock_flow_instance.run_local_server.return_value
    
    with patch("builtins.open", mock_open()) as mock_file:
        get_gmail_service("creds.json", "token.json")
        mock_flow.assert_called_once_with("creds.json", ["https://www.googleapis.com/auth/gmail.modify"])
        mock_flow_instance.run_local_server.assert_called_once()
        mock_file.assert_called_once_with("token.json", "w")
        mock_build.assert_called_once()

@patch("os.path.exists")
def test_get_gmail_service_no_credentials(mock_exists):
    """Tests that None is returned when the credentials file is missing."""
    mock_exists.return_value = False
    service = get_gmail_service("creds.json", "token.json")
    assert service is None
