from pytest_mock import MockerFixture

from mailtag.gmail_auth import get_gmail_service


class TestGmailAuth:
    def test_get_gmail_service_with_token(self, mocker: MockerFixture):
        """Tests that the service is built correctly when a valid token exists."""
        mocker.patch("mailtag.gmail_auth.os.path.exists", return_value=True)
        mock_creds = mocker.patch("mailtag.gmail_auth.Credentials.from_authorized_user_file")
        mock_creds.return_value.valid = True
        mock_creds.return_value.expired = False
        mock_creds.return_value.refresh_token = True
        mock_build = mocker.patch("mailtag.gmail_auth.build")

        get_gmail_service("creds.json", "token.json")

        mock_creds.assert_called_once_with("token.json", ["https://www.googleapis.com/auth/gmail.modify"])
        mock_build.assert_called_once()

    def test_get_gmail_service_no_token(self, mocker: MockerFixture):
        """Tests the OAuth flow when no token exists."""
        mocker.patch("mailtag.gmail_auth.os.path.exists", side_effect=[False, True])
        mock_flow = mocker.patch("mailtag.gmail_auth.InstalledAppFlow.from_client_secrets_file")
        mock_build = mocker.patch("mailtag.gmail_auth.build")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        mock_flow_instance = mock_flow.return_value
        mock_creds = mock_flow_instance.run_local_server.return_value

        get_gmail_service("creds.json", "token.json")

        mock_flow.assert_called_once_with("creds.json", ["https://www.googleapis.com/auth/gmail.modify"])
        mock_flow_instance.run_local_server.assert_called_once_with(port=0)
        mock_open.assert_called_once_with("token.json", "w")
        mock_creds.to_json.assert_called_once()
        mock_build.assert_called_once()

    def test_get_gmail_service_no_credentials(self, mocker: MockerFixture):
        """Tests that None is returned when the credentials file is missing."""
        mocker.patch("mailtag.gmail_auth.os.path.exists", side_effect=[False, False])
        service = get_gmail_service("creds.json", "token.json")
        assert service is None

    def test_get_gmail_service_refresh_token(self, mocker: MockerFixture):
        """Tests that an expired token is refreshed."""
        mocker.patch("mailtag.gmail_auth.os.path.exists", return_value=True)
        mock_creds_from_file = mocker.patch("mailtag.gmail_auth.Credentials.from_authorized_user_file")
        mock_creds_instance = mock_creds_from_file.return_value
        mock_creds_instance.valid = False
        mock_creds_instance.expired = True
        mock_creds_instance.refresh_token = True

        mock_build = mocker.patch("mailtag.gmail_auth.build")
        mocker.patch("mailtag.gmail_auth.Request")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        get_gmail_service("creds.json", "token.json")

        mock_creds_from_file.assert_called_once_with(
            "token.json", ["https://www.googleapis.com/auth/gmail.modify"]
        )
        mock_creds_instance.refresh.assert_called_once()
        mock_open.assert_called_once_with("token.json", "w")
        mock_creds_instance.to_json.assert_called_once()
        mock_build.assert_called_once()
