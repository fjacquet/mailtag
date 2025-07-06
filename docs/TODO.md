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

## **Phase 3: Fast Parse Implementation**

This phase focuses on implementing the two-pass system to dramatically improve performance on IMAP accounts.

- [ ] **`config.py` & `config.toml` - Add Fast Parse Settings:**
  - [ ] Add `fast_parse_batch_size` to control the number of emails fetched in Pass 1.
  - [ ] Add `folder_cache_ttl_hours` for the IMAP folder hierarchy cache.
  - [ ] Add `unclassified_folder_name` for AI fallback.
- [ ] **`imap_service.py` - Implement Fast Parse Methods:**
  - [ ] Implement `get_folder_hierarchy()` to fetch and cache the folder list in `data/imap_folders.json`.
  - [ ] Implement `get_email_senders(uids: list[str])` to fetch only the `From` header for a batch of emails.
  - [ ] Implement `get_full_emails(uids: list[str])` for Pass 2 processing.
  - [ ] Deprecate the existing `get_emails()` method.
- [ ] **`app.py` - Implement Two-Pass Orchestration:**
  - [ ] Rework the main application logic to manage the two-pass system.
  - [ ] Implement Pass 1: Batch fetch UIDs, get senders, check against the database, and move matches.
  - [ ] Implement Pass 2: Process remaining UIDs with the full AI classification logic.
  - [ ] Implement the fallback strategy to move unclassified emails to the folder specified in `unclassified_folder_name`.
- [ ] **Testing - Update and Add Tests:**
  - [ ] Add unit tests for the new `imap_service.py` methods (`get_folder_hierarchy`, `get_email_senders`, etc.).
  - [ ] Add integration tests for the full two-pass orchestration in `app.py`.
  - [ ] Test the cache logic (creation, expiration, error handling).
  - [ ] Test the AI fallback logic.
- [ ] **Documentation - Update Project Documentation:**
  - [ ] Update `README.md` to explain the new Fast Parse feature and its configuration.
  - [ ] Ensure `TECHNICAL_SPECIFICATION.md` reflects the new architecture.

---
*The original TODO items from previous phases have been completed and are archived.*
