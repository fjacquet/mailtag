# TODO List: Email Automation Service

This document outlines the remaining tasks to complete the implementation of the Email Automation Service.

## **Phase 1: Enhanced Classification Engine**

This phase focuses on implementing the new Adaptive Multi-Signal Classification (AMSC) strategy to improve accuracy and provide a validation workflow.

- [x] **`models.py` - Update Data Model:**
  - Add `body` and `labels` fields to the `Email` model to hold all necessary data in a single object.
- [x] **`providers.py` - Refactor Interface:**
  - Remove the redundant `get_email_body` method from the `EmailProvider` abstract base class.
- [x] **`imap_service.py` - Preserve Unread Status & Efficiency:**
  - Refactor `get_emails` to use `BODY.PEEK[]` to fetch the email body and labels without marking messages as read.
  - Consolidate fetching into a single operation.
- [x] **`gmail_service.py` - Preserve Unread Status & Efficiency:**
  - Refactor `get_emails` to fetch the body and labels in a single API call per message.
  - Implement label caching to reduce API calls.
- [x] **`app.py` - Implement Validation Mode:**
  - Add the `--validate` command-line argument.
  - Update the main loop to prevent email modification actions when `--validate` is active.
- [x] **`config.py` & `config.toml` - Add Classifier Settings:**
  - Add a new `[classifier]` section to `config.toml`.
  - Add settings for `ai_confidence_threshold` and `historical_confidence_threshold`.
  - Update `config.py` to load these new settings.
- [x] **`classifier.py` - Implement AMSC Strategy:**
  - Refactor `classify_email` to use the full `Email` object.
  - Implement the prioritized, multi-signal logic.
- [x] **`tests/test_classifier.py` - Test New Logic:**
  - Update tests to cover the new AMSC strategy and its signals.
- [x] **`tests/test_imap_service.py` - Update Provider Tests:**
  - Update tests to mock and test the new `get_emails` implementation.
- [x] **`tests/test_gmail_service.py` - Update Provider Tests:**
  - Update tests to mock and test the new `get_emails` implementation and label caching.
- [x] **`tests/` - Update Application Tests:**
  - Update tests for `app.py` (or `main.py`) to cover the `--validate` argument and its behavior.
- [x] **Quality Checks:**
  - Run `uv run yamlfix .` to fix YAML file formatting.
  - Run `uv run ruff check --fix .` to ensure code quality and style.

## **Phase 2: Maintenance & Optimization**

- [ ] **Improve Test Performance:**
  - Review existing tests and ensure all external services (IMAP, Gmail) are properly mocked to reduce test execution time.

---
*The original TODO items from previous phases have been completed and are archived.*