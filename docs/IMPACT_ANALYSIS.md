# Impact Analysis: Enhanced Classification Engine

This document outlines the impact of implementing the "Enhanced Classification Engine" and associated refactoring.

## **Executive Summary**

The "Enhanced Classification Engine" is a significant architectural evolution, moving from a single-signal (AI model) to a multi-signal classification strategy. This new approach, named Adaptive Multi-Signal Classification (AMSC), prioritizes data from more reliable sources (validated classifications, email server labels, historical data) before falling back to the AI model. This improves accuracy, reduces cost, and increases reliability.

This refactoring also introduced:
- A dual-database system for AI suggestions and validated classifications.
- A workflow to promote AI suggestions to validated classifications.

The impact is concentrated in the classification and data-fetching layers, with significant improvements to testing and configuration.

---

### **Detailed Impact Analysis by Component**

#### 1. `src/mailtag/database.py`

- **Previous State:** Managed a single `sender_classification_db.json`.
- **Impact:** **High.**
- **Changes:**
  - The `ClassificationDatabase` class will be updated to manage two files: `sender_classification_db.json` (for AI suggestions) and `validated_classification_db.json` (for user-approved classifications).
  - New methods will be required to move a classification from the suggestion database to the validated database.

#### 2. `src/mailtag/classifier.py`

- **Previous State:** Relied on a single database.
- **Impact:** **Major Overhaul.**
- **Changes:**
  - The AMSC strategy will be updated to prioritize the `validated_classification_db.json` over all other signals.
  - The classifier will need to interact with both databases.

#### 3. `src/app.py` (formerly `src/main.py`)

- **Previous State:** The `--validate` flag was for read-only analysis.
- **Impact:** **High.**
- **Changes:**
  - The `--validate` flag will now be used to trigger the promotion of an AI suggestion to the validated database. This changes its purpose from a pure read-only flag to a write action on the local database.
