# Impact Analysis: Enhanced Classification Engine

This document outlines the impact of implementing the "Enhanced Classification Engine" and associated refactoring.

## **Executive Summary**

The "Enhanced Classification Engine" is a significant architectural evolution, moving from a single-signal (AI model) to a multi-signal classification strategy. This new approach, named Adaptive Multi-Signal Classification (AMSC), prioritizes data from more reliable sources (email server labels, historical data) before falling back to the AI model. This improves accuracy, reduces cost, and increases reliability.

This refactoring also introduced:
- A `--validate` flag for read-only operation.
- A more efficient data-fetching strategy in the email provider services.
- Robust resource management using `contextlib`.

The impact is concentrated in the classification and data-fetching layers, with significant improvements to testing and configuration.

---

### **Detailed Impact Analysis by Component**

#### 1. `src/mailtag/classifier.py`

- **Previous State:** Relied solely on an AI model for classification.
- **Impact:** **Major Overhaul.**
- **Changes:**
  - Implemented the **Adaptive Multi-Signal Classification (AMSC)** strategy, which uses a three-tiered approach:
    1.  **Server-Side Labels:** Checks for existing labels on the email server.
    2.  **Historical Database:** Queries the local database for high-confidence classifications based on sender history.
    3.  **AI Model Fallback:** Uses the AI model only when the other signals are inconclusive.
  - The `Classifier` class was refactored to orchestrate this new logic.
  - Configuration was updated to support confidence thresholds for the historical and AI classifiers.

#### 2. `src/mailtag/imap_service.py` and `src/mailtag/gmail_service.py`

- **Previous State:** Fetched email metadata and body in separate, inefficient calls. Lacked robust connection management.
- **Impact:** **High.**
- **Changes:**
  - **Efficient Data Fetching:** Services were refactored to fetch all necessary email data (ID, sender, subject, body, labels) in a single, efficient operation.
  - **Preservation of `\Seen` Status:** The IMAP service now uses `BODY.PEEK[]` instead of `BODY[]` to fetch the email body without marking it as read, preserving the original unread status.
  - **`contextlib` for Resource Management:** Both services now use `@contextmanager` to create robust, reusable context managers for handling connections. This ensures that connections are always closed properly, even if errors occur.

#### 3. `src/app.py` (formerly `src/main.py`)

- **Previous State:** Basic orchestration of the classification workflow.
- **Impact:** **High.**
- **Changes:**
  - **`--validate` Flag:** A new command-line argument, `--validate`, was added. When used, the application runs in a read-only mode, performing classification analysis without making any changes to the email server (i.e., not moving emails).
  - The main execution logic was updated to use the new provider connection context managers.

#### 4. `src/mailtag/config.py` and `config.toml`

- **Previous State:** Contained a `[preclassification]` section.
- **Impact:** **Medium.**
- **Changes:**
  - The `[preclassification]` section in `config.toml` was replaced with a more appropriately named `[classifier]` section.
  - New configuration options were added to support the AMSC strategy: `ai_confidence_threshold`, `historical_confidence_threshold`, and `min_count`.

#### 5. `src/mailtag/models.py`

- **Previous State:** The `Email` model was missing fields for body and labels.
- **Impact:** **Medium.**
- **Changes:**
  - The `Email` model was updated to include `body: str` and `labels: list[str]`, allowing all necessary data to be encapsulated in a single object.

#### 6. `tests/`

- **Previous State:** Tests were written for the old, single-signal classifier and inefficient data providers.
- **Impact:** **High.**
- **Changes:**
  - **Complete Test Overhaul:** All relevant test files (`test_classifier.py`, `test_imap_service.py`, `test_gmail_service.py`, `test_app.py`) were significantly updated to reflect the new AMSC logic, the `--validate` flag, and the `contextlib` refactoring.
  - **Global Mock for `litellm`:** A global mock for `litellm.completion` was added to `tests/conftest.py` to prevent tests from hanging due to network calls, stabilizing the entire test suite.

---

### **New Design Principles**

The following principles were added to `docs/DESIGN_PRINCIPLES.md` to reflect the new best practices established during this refactoring:

1.  **Use `contextlib` for Resource Management:** Emphasizes using `contextlib` for clean and reliable handling of resources like network connections.
2.  **Run Non-Regression Tests:** Mandates running the full test suite before finalizing changes to prevent regressions.
