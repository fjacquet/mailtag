import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def get_gmail_service(credentials_file: str, token_file: str):
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    if not os.path.exists(credentials_file):
        logger.error(f"Credentials file not found at '{credentials_file}'.")
        logger.info(
            "Please follow these steps to get your credentials file:\n"
            "1. Go to the Google Cloud Console: https://console.cloud.google.com/\n"
            "2. Create a new project or select an existing one.\n"
            "3. Enable the Gmail API for your project.\n"
            "4. Create an OAuth 2.0 Client ID for a 'Desktop app'.\n"
            "5. Download the JSON file and save it as 'credentials.json' in your project's root directory."
        )
        return None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.path.exists(credentials_file):
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            logger.error(f"Credentials file not found at '{credentials_file}'.")
            logger.info(
                "Please follow these steps to get your credentials file:\n"
                "1. Go to the Google Cloud Console: https://console.cloud.google.com/\n"
                "2. Create a new project or select an existing one.\n"
                "3. Enable the Gmail API for your project.\n"
                "4. Create an OAuth 2.0 Client ID for a 'Desktop app'.\n"
                "5. Download the JSON file and save it as 'credentials.json' in your project's root directory."
            )
            return None
        # Save the credentials for the next run
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Gmail service: {e}")
        raise
