# Impact Analysis: Enhanced Classification Engine

This document outlines the impact of implementing the "Enhanced Classification Engine" and associated refactoring.

## **Executive Summary**

The "Enhanced Classification Engine" is a significant architectural evolution, moving from a single-signal (AI model) to a multi-signal classification strategy. This new approach, named Adaptive Multi-Signal Classification (AMSC), prioritizes data from more reliable sources (validated classifications, email server labels, historical data) before falling back to the AI model. This improves accuracy, reduces cost, and increases reliability.

This refactoring also introduced:
- A three-entry-point architecture (CLI, Streamlit, Webhook).
- A dual-database system for AI suggestions and validated classifications.
- The use of `click` for a more modern CLI.
- A two-pass "Fast Parse" system for IMAP to improve performance.

The impact is concentrated in the application's entry points and the classification and data-fetching layers, with significant improvements to testing and configuration.

---

### **Detailed Impact Analysis by Component**

#### 1. `src/main.py` (CLI)

- **Previous State:** The CLI logic was in `src/app.py` and used `argparse`.
- **Impact:** **High.**
- **Changes:**
  - The CLI logic has been moved to `src/main.py`.
  - `argparse` has been replaced with `click` for a more modern and user-friendly CLI.

#### 2. `src/app.py` (Streamlit)

- **Previous State:** This file contained the CLI logic.
- **Impact:** **High.**
- **Changes:**
  - This file is now a placeholder for a Streamlit web application.

#### 3. `src/webhook.py` (Webhook)

- **Previous State:** This file did not exist.
- **Impact:** **High.**
- **Changes:**
  - This new file is a placeholder for a webhook endpoint using `fastapi`.

#### 4. `src/mailtag/database.py`

- **Previous State:** Managed a single `sender_classification_db.json`.
- **Impact:** **High.**
- **Changes:**
  - The `ClassificationDatabase` class now manages two files: `sender_classification_db.json` (for AI suggestions) and `validated_classification_db.json` (for user-approved classifications).

#### 5. `src/mailtag/classifier.py`

- **Previous State:** Relied on a single database.
- **Impact:** **Major Overhaul.**
- **Changes:**
  - The AMSC strategy now prioritizes the `validated_classification_db.json` over all other signals.
  - The classifier now interacts with both databases.

#### 6. `src/mailtag/imap_service.py`

- **Previous State:** Used a single-pass approach to fetch emails.
- **Impact:** **High.**
- **Changes:**
  - Implemented a two-pass "Fast Parse" system to improve performance.
  - Added methods to fetch only email headers and to fetch full emails for the second pass.
