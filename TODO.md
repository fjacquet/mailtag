# TODO List: Email Automation Service Implementation

This file outlines the remaining tasks to complete the implementation of the Email Automation Service.

## **Phase 1: Core Service Implementation**

- [x] **`ImapService` - Robust Body Parsing:**
  - Enhance `get_email_body` to correctly parse various multipart email structures (e.g., `text/html`, attachments) and prioritize `text/plain`.
- [x] **`ImapService` - Error Handling:**
  - Add specific error handling for `mail.select()` failing (e.g., mailbox not found).
  - Handle `mail.fetch()` and `mail.copy()` errors gracefully.
- [x] **`GmailService` - Pagination:**
  - Implement pagination in `get_emails` to handle more than one page of results from the Gmail API. The `nextPageToken` from the API response should be used.
- [x] **`GmailService` - Label Management:**
  - Add a helper function to get a label's ID from its name, as the `move_email` function currently expects a label ID.
- [x] **`gmail_auth.py` - Full OAuth 2.0 Flow:**
  - Complete the implementation of `get_gmail_service` to handle the full OAuth 2.0 flow.
  - Add user-friendly instructions for when `credentials.json` is not found.

## **Phase 2: Feature Enhancement & CLI**

- [x] **`main.py` - Advanced CLI Arguments:**
  - Add command-line arguments for specifying search criteria (e.g., `--subject`, `--from`, `--status`).
  - Add an argument for the destination folder/label for moving emails.
- [x] **`main.py` - Dynamic Provider Selection:**
  - Refactor `main()` to be cleaner when selecting and initializing the email provider.
- [x] **Configuration - Secure Password Handling:**
  - Implement the logic to load the IMAP password from an environment variable (`${IMAP_PASSWORD}`) as recommended in the configuration.

## **Phase 3: Testing & Documentation**

- [x] **`tests/test_imap_service.py` - Edge Cases:**
  - Add tests for multipart emails.
  - Add tests for IMAP-specific errors (e.g., invalid credentials, mailbox not found).
- [x] **`tests/test_gmail_service.py` - Edge Cases:**
  - Add tests for pagination.
  - Add tests for API errors (e.g., invalid credentials, label not found).
- [x] **`tests/test_main.py` - CLI Testing:**
  - Add tests for the new command-line arguments.
- [x] **Documentation - `README.md`:**
  - Add a new section to `README.md` explaining how to configure and use the new service.
  - Include instructions for enabling IMAP and generating Gmail API credentials.
