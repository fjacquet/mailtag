# TODO List: Email Automation Service

This document outlines the remaining tasks to complete the implementation of the Email Automation Service.

## **Phase 1: Architecture Refactoring**

This phase focuses on restructuring the application into three distinct entry points.

- [x] **`main.py` - CLI Entry Point:**
  - [x] Move the CLI logic from `app.py` to `main.py`.
  - [x] Replace `argparse` with `click`.
- [x] **`app.py` - Streamlit UI:**
  - [x] Create a placeholder for the Streamlit application.
- [x] **`webhook.py` - Webhook Entry Point:**
  - [x] Create a placeholder for the webhook endpoint using `fastapi`.

## **Phase 2: Dual Database Classification**

This phase focuses on implementing the new dual database system and updating the classification strategy.

- [x] **`database.py` - Dual DB Sytem:**
  - [x] Modify `ClassificationDatabase` to manage both `sender_classification_db.json` and `validated_classification_db.json`.
- [x] **`classifier.py` - Update AMSC Strategy:**
  - [x] Update the `classify_email` method to prioritize the validated DB over all other signals.
- [x] **`main.py` - Update CLI:**
  - [x] Restore the `--validate` flag to its original "dry run" functionality.
- [x] **`tests/` - Update Tests:**
  - [x] Update all relevant tests to reflect the new architecture and dual-database system.

## **Phase 3: Fast Parse Implementation**

This phase focuses on implementing the two-pass system to dramatically improve performance on IMAP accounts.

- [x] **`config.py` & `config.toml` - Add Fast Parse Settings:**
- [x] **`imap_service.py` - Implement Fast Parse Methods:**
- [x] **`main.py` - Implement Two-Pass Orchestration:**
- [x] **Testing - Update and Add Tests:**
- [x] **Documentation - Update Project Documentation:**

---
*The original TODO items from previous phases have been completed and are archived.*
