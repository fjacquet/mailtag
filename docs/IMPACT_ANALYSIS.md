# Impact Analysis: Email Automation Service

This document outlines the expected impact of implementing the new Email Automation Service feature, which introduces direct IMAP and Gmail API integration.

## **Executive Summary**

The proposed "Email Automation Service" represents a **fundamental shift** in the project's architecture. The core impact is the replacement of the current `MailService`, which is a **macOS-specific, client-side solution** (using AppleScript to control Mail.app), with a new, **platform-independent, server-side solution** that communicates directly with email servers via the IMAP protocol and the Gmail API.

This is a significant but well-contained refactoring. The core business logic (`Classifier`, `Database`) is well-decoupled and will require minimal changes. The primary effort will be concentrated in the email-fetching and configuration layers.

---

### **Detailed Impact Analysis by Component**

#### 1. `src/mailtag/mail_service.py`

- **Current State:** Interacts with the local Apple Mail application using `osascript`. This is the biggest bottleneck to cross-platform, server-side execution.
- **Impact:** **Major Overhaul / Complete Replacement.**
- **Required Changes:**
  - The existing `MailService` class will be deprecated or completely replaced.
  - A new, more abstract structure is recommended. We should create a base class or interface (e.g., `EmailProvider`) that defines a standard set of methods (`connect`, `get_emails`, `get_body`, `move_email`, etc.).
  - Two new classes will implement this interface:
    - `ImapService`: Will use Python's `imaplib` to connect to any standard IMAP server.
    - `GmailService`: Will use the `google-api-python-client` to interact with the Gmail API.
  - This approach keeps the rest of the application agnostic to the chosen email provider.

#### 2. `src/main.py`

- **Current State:** Orchestrates the workflow: `MailService` -> `Classifier` -> `Database`.
- **Impact:** **High.**
- **Required Changes:**
  - The main execution logic in `run_classification` will need to be updated to instantiate the correct service (`ImapService` or `GmailService`) based on the user's configuration.
  - Argument parsing (`argparse`) will need to be extended to allow the user to specify which email provider to use (e.g., `--provider=imap` or `--provider=gmail`).
  - The error handling will need to be updated to catch new, network-related exceptions from `imaplib` or the Google API client.

#### 3. `src/mailtag/config.py` and `config.toml`

- **Current State:** Manages general, logging, and pre-classification settings.
- **Impact:** **High.**
- **Required Changes:**

  - The `AppConfig` dataclass in `config.py` must be expanded to include new configuration sections.
  - New dataclasses like `ImapConfig` and `GmailConfig` will be needed.
  - The `config.toml` file will need new sections to store the required credentials:

    ```toml
    [imap]
    host = "imap.example.com"
    user = "user@example.com"
    password = "${IMAP_PASSWORD}" # Recommend using env variables

    [gmail]
    credentials_file = "credentials.json"
    token_file = "token.json"
    ```

  - The `load_config` function will need to be updated to parse these new sections.

#### 4. `src/mailtag/models.py`

- **Current State:** Defines the `Email` model with `msg_id: int`.
- **Impact:** **Medium.**
- **Required Changes:**
  - Both IMAP UIDs and Gmail API message IDs are strings, not integers. The `msg_id` field should be changed from `int` to `str` to accommodate both protocols. This is a simple but important change that will ripple through any code that uses this model.

#### 5. `src/mailtag/classifier.py`, `src/mailtag/database.py`, `src/mailtag/filter_generator.py`

- **Current State:** These components handle the core logic of classification, data storage, and filter generation.
- **Impact:** **Low to None.**
- **Reasoning:** These modules are well-decoupled. They operate on the `Email` model and the classification database, and are not directly concerned with how the emails are fetched. They should be reusable as-is, with the minor exception of the `msg_id` type change.

#### 6. `tests/`

- **Current State:** Contains tests for the existing components.
- **Impact:** **High.**
- **Required Changes:**
  - `tests/test_mail_service.py` will need to be **completely rewritten**. The current mocks for `subprocess.run` and `osascript` will be irrelevant.
  - New test files will be required:
    - `test_imap_service.py`: To mock `imaplib` and test the IMAP connection, search, and move logic.
    - `test_gmail_service.py`: To mock the Google API client and test the label listing, search, and modification logic.
    - New tests for the updated configuration loading in `test_config.py`.

---

### **New Components to be Created**

1.  **Gmail Authentication Module:** A new file (e.g., `src/mailtag/gmail_auth.py`) will be needed to handle the OAuth 2.0 flow for the Gmail API. This will manage the creation and refreshing of `token.json`.
2.  **IMAP and Gmail Service Modules:** The new `ImapService` and `GmailService` classes will likely live in their own files within the `mailtag` package.
