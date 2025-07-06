
# Technical Specification: Enhanced Classification Engine

This document outlines the technical details of the Enhanced Classification Engine and associated refactoring.

## 1. **Core Libraries**

- **IMAP Client:** `imapclient` is used for its robust, high-level API for IMAP communications.
- **Gmail API Client:** `google-api-python-client`, `google-auth-httplib2`, and `google-auth-oauthlib` are used for interacting with the Gmail API.
- **AI Model:** `litellm` is used as a consistent interface to interact with various LLM providers.
- **Resource Management:** `contextlib` is used for creating robust context managers for network connections.

## 2. **Adaptive Multi-Signal Classification (AMSC)**

The core of the new engine is the AMSC strategy, which follows a prioritized sequence to classify emails.

1.  **Pre-computation (Server-Side Labels):**
    - The system first checks if the email on the server already has a classification label (e.g., `Dossier/Client A`).
    - If a valid label exists, this classification is used, and no further processing is done.
    - **Technical Detail:** This is implemented by fetching email labels/flags during the initial data fetch.

2.  **Historical Analysis (Database):**
    - If no server-side label is found, the system queries the local `sender_classification_db.json` database.
    - It calculates the historical classification confidence for the email's sender.
    - A classification is accepted if:
        - The confidence level exceeds `historical_confidence_threshold` (from `config.toml`).
        - The sender has appeared at least `min_count` times.
    - **Technical Detail:** This logic is encapsulated within the `Classifier.get_historical_classification` method.

3.  **AI Model Fallback:**
    - If both pre-computation and historical analysis fail to yield a classification, the system falls back to the AI model.
    - The email content (sender, subject, body) is sent to the configured LLM via `litellm`.
    - The AI's classification is only accepted if its confidence score is above `ai_confidence_threshold` (from `config.toml`).
    - **Technical Detail:** This is handled by the `Classifier.get_ai_classification` method.

## 3. **Data Fetching and Processing**

- **Efficient Fetching:** Both `ImapService` and `GmailService` were refactored to fetch all required email attributes (ID, sender, subject, body, labels) in a single, optimized API call.
- **Preserving `\Seen` Status (IMAP):**
    - To avoid unintentionally marking emails as read, the `ImapService` uses the `BODY.PEEK[]` directive instead of `BODY[]`.
    - This fetches the email content without altering the `\Seen` flag on the server, preserving the user's read/unread status.

## 4. **Resource Management with `contextlib`**

- **Problem:** Previous implementations risked leaving network connections open if errors occurred.
- **Solution:**
    - Both `ImapService` and `GmailService` now implement a `connect` method decorated with `@contextlib.contextmanager`.
    - This pattern ensures that the connection is automatically and reliably closed (logging out, shutting down) when the `with` block is exited, regardless of whether it completes successfully or raises an exception.
    - **Example Usage in `app.py`:**
      ```python
      with provider.connect() as service:
          # ... perform email operations
      ```

## 5. **Read-Only Validation Mode**

- **`--validate` Flag:** A new command-line argument that runs the application in a read-only "validation" mode.
- **Functionality:**
    - The application performs the entire classification process: fetching emails, running the AMSC logic, and logging the results.
    - However, it **skips the final step** of moving the email or applying any labels on the server.
    - This allows for safe, non-destructive testing of classification rules and AI model performance against a live inbox.
- **Implementation:** The main application loop in `app.py` checks for the `validate` flag before calling any methods that would modify email state (`service.move_email`).
