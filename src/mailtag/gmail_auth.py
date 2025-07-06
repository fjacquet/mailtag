import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def get_gmail_service(credentials_file: str, token_file: str):
    """
    Authenticates with the Gmail API and returns a service object.
    Handles the OAuth 2.0 flow, including token refreshing and user consent.
    """
    creds = None
    if os.path.exists(token_file):
        logger.debug(f"Token file found at '{token_file}'. Loading credentials.")
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Credentials have expired. Refreshing token.")
            creds.refresh(Request())
        else:
            logger.info("No valid credentials found. Starting new user authentication flow.")
            if not os.path.exists(credentials_file):
                logger.error(f"Credentials file not found at '{credentials_file}'.")
                logger.info(
                    "Please follow these steps to get your credentials file:\n"
                    "1. Go to the Google Cloud Console: https://console.cloud.google.com/\n"
                    "2. Create a new project or select an existing one.\n"
                    "3. Enable the Gmail API for your project.\n"
                    "4. Create an OAuth 2.0 Client ID for a 'Desktop app'.\n"
                    "5. Download the JSON file and save it as 'credentials.json' "
                    "in your project's root directory."
                )
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            except FileNotFoundError:
                logger.error(f"Credentials file not found at '{credentials_file}'.")
                logger.info(
                    "Please follow these steps to get your credentials file:\n"
                    "1. Go to the Google Cloud Console: https://console.cloud.google.com/\n"
                    "2. Create a new project or select an existing one.\n"
                    "3. Enable the Gmail API for your project.\n"
                    "4. Create an OAuth 2.0 Client ID for a 'Desktop app'.\n"
                    "5. Download the JSON file and save it as 'credentials.json' "
                    "in your project's root directory."
                )
                return None
            except json.JSONDecodeError:
                logger.error(
                    f"Error decoding the credentials file '{credentials_file}'. "
                    "Make sure it is a valid JSON file."
                )
                return None

        logger.info(f"Saving new credentials to '{token_file}'.")
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("gmail", "v1", credentials=creds)
        logger.info("Successfully built Gmail service.")
        return service
    except Exception as e:
        logger.error(f"Failed to build Gmail service: {e}")
        raise