
# Technical Specification: Email Automation Service

This document outlines the technical details for implementing the Email Automation Service.

## **4.1. Core Libraries**

* **IMAP Client:** Implementation will use Python's built-in `imaplib` module for all IMAP-related communications. Secure `IMAP4_SSL` connections are required.
* **Gmail API Client:** Implementation will use the official Google Client Libraries for Python: `google-api-python-client`, `google-auth-httplib2`, and `google-auth-oauthlib`.

## **4.2. Authentication**

* **IMAP:** The IMAP password will be loaded from an `IMAP_PASSWORD` environment variable. The application will use the `python-dotenv` library to load this variable from a `.env` file in the project root. This file should be added to `.gitignore` and never be committed. The system should explicitly recommend using an **App Password** for accounts with 2-Factor Authentication (2FA) enabled.
* **Gmail API (OAuth 2.0):**
  * The application will be registered in the Google Cloud Console to obtain `credentials.json`.
  * The authentication flow will generate a `token.json` file upon first user consent, which will be used for subsequent API calls.
  * The required API scope will be `https://www.googleapis.com/auth/gmail.modify` to allow for reading and modifying messages and labels.

## **4.3. Key Functions & Logic**

The implementation will be modular, with distinct functions for each core task:

| Function | IMAP Implementation (`imaplib`) | Gmail API Implementation (`googleapiclient`) |
| :--- | :--- | :--- |
| **Connect & Login** | `imaplib.IMAP4_SSL(hostname)` followed by `mail.login(user, pass)` | Build a `service` object via the `google-auth-oauthlib` flow. |
| **List Folders/Labels** | `mail.list()` | `service.users().labels().list(userId='me').execute()` |
| **Search Messages** | `mail.select(mailbox)` then `mail.search(None, criteria)` | `service.users().messages().list(userId='me', q=query).execute()` |
| **Fetch Message** | `mail.fetch(uid, '(RFC822)')` | `service.users().messages().get(userId='me', id=msg_id).execute()` |
| **Move/Organize** | `mail.copy(uid, target)` followed by `mail.store(uid, '+FLAGS', '\Deleted')` and `mail.expunge()` | `service.users().messages().modify(userId='me', id=msg_id, body=body).execute()` |

## **4.4. Provider Selection**

The application will support running against the IMAP provider, the Gmail provider, or both. The selection will be made at runtime via a command-line argument.

*   **`--provider`**: A command-line argument to specify which email provider(s) to use.
    *   `--provider imap`: Runs the service only for the configured IMAP account.
    *   `--provider gmail`: Runs the service only for the configured Gmail account.
    *   `--provider all`: Runs the service for both IMAP and Gmail accounts.
    *   If the argument is not provided, it will default to `all`.
