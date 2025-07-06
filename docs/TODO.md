# TODO List: Email Automation Service

This document outlines the remaining tasks to complete the implementation of the Email Automation Service.

## **Phase 1: Dual Database Classification**

This phase focuses on implementing the new dual database system and updating the classification strategy.

- [ ] **`database.py` - Dual DB Sytem:**
  - [ ] Modify `ClassificationDatabase` to manage both `sender_classification_db.json` and `validated_classification_db.json`.
  - [ ] Add a method to promote a sender's classification from the suggestion DB to the validated DB.
- [ ] **`classifier.py` - Update AMSC Strategy:**
  - [ ] Update the `classify_email` method to prioritize the validated DB over all other signals.
- [ ] **`app.py` - Update Validation Workflow:**
  - [ ] Change the `--validate` flag's behavior to promote a classification to the validated DB.
- [ ] **`tests/` - Update Tests:**
  - [ ] Update all relevant tests to reflect the new dual-database system and the updated AMSC logic.

## **Phase 2: Fast Parse Implementation**

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
