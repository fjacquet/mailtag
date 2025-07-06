This is a well-structured and clear technical specification. As an expert developer, I can suggest several improvements to enhance its robustness, clarity, and future-proofing.

-----

# Technical Specification: Enhanced Email Classification Engine

**Author:** Senior Solution Architect
**Version:** 1.1 (Improved)
**Date:** 2025-07-06

-----

## 1\. Executive Summary

The existing email classification system suffers from an unacceptable error rate in its AI-driven categorization, leading to the gradual degradation of the `sender_classification_db.json` database. This, in turn, diminishes the accuracy of pre-classification and creates a negative feedback loop due to the absence of a robust mechanism for classification validation and user-driven learning.

This document outlines the **Enhanced Classification Engine**, a critical upgrade that introduces two pivotal capabilities:

1. **Validation Mode (`--validate`):** A new, read-only operational mode designed for safe, offline population and pre-validation of the `sender_classification_db.json`. This mode enables thorough review and correction of AI-suggested classifications before any system actions are taken, transforming the database into a reliable source of truth.
2. **Adaptive Multi-Signal Classification (AMSC) Strategy:** A sophisticated, prioritized classification logic for the standard operational mode. This strategy intelligently synthesizes information from **existing server-side labels/folders**, the **user-validated historical sender database**, and the **AI model** to achieve highly accurate and reliable classification decisions.

This initiative is set to transform the classification system from a brittle, automated process into a resilient, adaptive, and continuously learning system that inherently improves with user interaction and feedback.

-----

## 2\. Core Requirements

### Functional Requirements (FR)

* **FR1: Validation Mode Activation:** The application **MUST** introduce a new, mutually exclusive command-line argument: `--validate`.
* **FR2: Database Population (Validation Mode):** When executed with the `--validate` flag, the application **MUST** process emails, determine their classification based on all available signals (excluding actions), and update the `sender_classification_db.json` accordingly.
* **FR3: Read-Only Operation (Validation Mode):** When in `--validate` mode, the application **MUST NOT** perform any modifying actions on the email server (e.g., moving emails, applying labels, deleting messages, marking as read/unread). This ensures idempotency and safety.
* **FR4: Adaptive Multi-Signal Classification (Standard Mode):** When run in standard mode (without `--validate`), the application **MUST** employ the Adaptive Multi-Signal Classification Strategy to determine an email's category.
* **FR5: Signal Prioritization:** The Adaptive Multi-Signal Classification Strategy **MUST** prioritize classification signals in the following definitive order:
    1. **Explicit Server-Side Label/Folder Match:** A direct and unambiguous match between an email's current server-side label/folder and a defined category. This reflects explicit user classification.
    2. **High-Confidence Sender History:** A classification derived from the `sender_classification_db.json` where the entry exhibits a configurable high-confidence threshold (e.g., based on multiple past identical classifications or a manual validation flag).
    3. **AI Model Inference:** The classification suggested by the configured `litellm` model, acting as a fallback for novel or ambiguous cases.
* **FR6: Confidence Threshold Configuration:** The system **MUST** allow configuration of confidence thresholds for both AI model inferences and historical sender data within `config.toml` to fine-tune the classification strategy.
* **FR7: Classification Ambiguity Handling:** The system **SHOULD** provide a mechanism (e.g., logging, special classification category) to flag emails where the Multi-Signal Classification Strategy yields ambiguous or conflicting results, requiring manual review.

### Non-Functional Requirements (NFR)

* **NFR1: Performance Preservation:** The introduction of the new classification logic **MUST NOT** degrade the overall email processing pipeline performance by more than 10% under typical load. Benchmarking will be required.
* **NFR2: Configurability:** The `config.toml` **MUST** be updated to allow granular enabling/disabling, configuration of signal weights (if introduced later), and threshold settings for all new features.
* **NFR3: Observability & Auditability:** All classification decisions, including the signal that led to the final classification, any overrides, and ambiguity flags, **MUST** be comprehensively logged at an appropriate verbosity level to ensure transparency, traceability, and aid in debugging and post-hoc analysis.
* **NFR4: Extensibility:** The classification engine design **SHOULD** allow for the future integration of additional classification signals (e.g., email content analysis, time-based rules) with minimal architectural changes.
* **NFR5: Data Integrity:** The `sender_classification_db.json` database **MUST** maintain its integrity and consistency under all operational modes. Automated backups of this database **SHOULD** be considered.

-----

## 3\. Proposed Architecture & Design

### 3.1. Component: Command-Line Interface (`main.py`)

The `main.py` entry point will be updated to recognize the new, mutually exclusive argument:

* **`--validate`**: (boolean, default: `False`) When present, activates Validation Mode. This flag will control the application's main loop, specifically by preventing any email server modification actions (e.g., `move_email`, `apply_label`).

**Consideration:** A clear error message should be provided if `--validate` is used with other action-triggering flags (if any exist or are introduced).

### 3.2. Component: Enhanced Classifier (`src/mailtag/classifier.py`)

The `Classifier` class will undergo significant refactoring to implement the Adaptive Multi-Signal Classification Strategy. The `classify_email` method will be redesigned to orchestrate the new logic, potentially abstracting each signal into its own method or dedicated class for modularity.

#### 3.2.1. Signal 1: Server-Side Label/Folder Awareness (`src/mailtag/providers.py`)

* The `EmailProvider` interface (and its `ImapService` and `GmailService` implementations) **MUST** be extended to reliably fetch the existing label(s) or folder(s) for each email being processed.
* The `Email` data model in `src/mailtag/models.py` **MUST** be updated to include a field (`current_labels` or `current_folder`) to store this information.
* The `Classifier` will query the email's current labels/folders and compare them against a predefined mapping of categories (`data/classification_schema.yml`).
* **Decision Logic:** If a direct, unambiguous match is found (e.g., email is in a folder named "Travel" and "Travel" is a defined category), this classification is considered definitive and overrides all other signals. This classification will be used to update `sender_classification_db.json`, establishing a powerful feedback loop from user's manual organization.

#### 3.2.2. Signal 2: High-Confidence Sender History (`db/sender_classification_db.json`)

* This existing logic will be integrated as the second priority. It will only be invoked if no definitive server-side label match is found.
* **Enhancement:** The `sender_classification_db.json` schema **MAY** be extended to include a `confidence_score` or `validation_status` (e.g., `validated_by_user`, `ai_suggested`) for each entry. Only entries exceeding a configurable `historical_confidence_threshold` will be considered "high-confidence." This allows manual corrections in Validation Mode to increase confidence in specific entries.
* **Decision Logic:** If a sender has a high-confidence entry in the database, that classification is used.

#### 3.2.3. Signal 3: AI Model Inference (Fallback)

* The `litellm` API call will serve as the final fallback for classification, invoked only if the first two signals do not yield a definitive result.
* Its role is explicitly shifted from the primary classifier to a "suggestion engine" for new, ambiguous, or unclassified senders.
* **Enhancement:** The AI model's output **SHOULD** ideally include a confidence score. This score, if available, **MUST** be logged, and can be used in `config.toml` to define an `ai_confidence_threshold` below which the AI's suggestion is considered too weak to act upon, potentially leading to an "unclassified" or "review\_required" state.

### 3.3. Data Flow Diagram (Updated for Clarity and Detail)

```mermaid
graph TD
    subgraph Core Processing Loop
        A[Start Email Processing] --> B{Fetch Email Metadata & Body};
        B --> C[Extract Sender & Subject];
        C --> D{Determine Operating Mode?};
    end

    D -- Standard Mode --> E[Apply AMSC Strategy];
    D -- Validation Mode --> F[Apply AMSC Strategy (No Actions)];

    subgraph Adaptive Multi-Signal Classification (AMSC)
        E --> G{Email Has Explicit Server Label/Folder Match?};
        G -- Yes --> H[Final Category: Server Label];
        G -- No --> I{Sender in DB with High Confidence?};
        I -- Yes --> J[Final Category: DB History];
        I -- No --> K{Call AI Model (litellm)};
        K --> L[AI Suggests Category & Confidence];
        L --> M{AI Confidence > Threshold?};
        M -- Yes --> N[Final Category: AI Suggestion];
        M -- No --> O[Final Category: Unclassified/Review Required];
    end

    subgraph Actions & Database Update
        H --> P[Update sender_classification_db.json];
        J --> P;
        N --> P;
        O --> P;
        P --> Q{Operating Mode?};
        Q -- Standard Mode --> R[Execute Email Action (Move/Label)];
        Q -- Validation Mode --> S[Log & End (No Action)];
    end

    R --> T[Loop to Next Email];
    S --> T;

    style R fill:#f9f,stroke:#333,stroke-width:2px;
    style S fill:#f9f,stroke:#333,stroke-width:2px;
```

-----

## 4\. Impact Analysis

* **`src/main.py`**: Requires modification to parse the `--validate` CLI argument, manage mutually exclusive flags, and adjust the main processing loop to conditionally execute server actions.
* **`src/mailtag/classifier.py`**: **High Impact.** Requires significant refactoring of the `classify_email` method to implement the prioritized Multi-Signal Classification Strategy. This likely involves new helper methods or classes for each signal.
* **`src/mailtag/providers.py` / `imap_service.py` / `gmail_service.py`**: Requires enhancement to reliably retrieve existing email labels/folders. This will involve updating API calls to the respective email services.
* **`src/mailtag/models.py`**: The `Email` data model **MUST** be updated to include fields for existing label/folder information. Additional fields for classification confidence or source might be beneficial but are optional for v1.1.
* **`db/sender_classification_db.json`**: The integrity and accuracy of this file will be dramatically improved. A schema enhancement to include a `confidence` or `validation_status` field for each entry **IS RECOMMENDED** to fully leverage user validation. This will necessitate a migration strategy if the application is already in use.
* **`config.toml`**: **High Impact.** Will require new sections and parameters for:
  * `[classifier]` with `ai_confidence_threshold`, `historical_confidence_threshold`.
  * Potentially `[features]` with `enable_server_label_signal`.
* **Logging Infrastructure**: Review and enhance existing logging to capture detailed classification decisions (which signal won, confidence scores, etc.).

-----

## 5\. Validation and Rollout Strategy

1. **Phase 1 (Implementation & Unit Testing):** Implement all described changes. Develop comprehensive **unit tests** for each signal's logic, the `classify_email` orchestration, and the command-line argument parsing.
2. **Phase 2 (Pre-production Validation Mode):** Deploy to a staging or pre-production environment. Run the application extensively in `--validate` mode against a representative dataset of emails.
      * **Manual Review:** Develop or use a script to export `sender_classification_db.json` entries for manual review. Focus on identifying and correcting misclassifications made by the AI or historical data. This phase is crucial for building a high-quality, validated `sender_classification_db.json`.
      * **Log Analysis:** Analyze logs generated during this phase to understand how the AMSC strategy is making decisions and identify any unexpected behavior.
3. **Phase 3 (Controlled Activation & A/B Testing - Optional but Recommended):**
      * **Small-Scale Pilot:** Deploy the standard mode to a small group of internal users or a subset of mailboxes.
      * **A/B Comparison (if feasible):** For a short period, potentially run the old and new classification engines in parallel (if architecture permits non-destructive comparison) to quantify improvement before full rollout.
4. **Phase 4 (Full Production Rollout):** Once satisfied with the results from Phase 3, deploy the Enhanced Classification Engine in standard mode to all production mailboxes.
5. **Phase 5 (Continuous Monitoring & Refinement):**
      * Continuously monitor logs for classification accuracy, performance, and any unclassified emails.
      * Establish a feedback loop for users to report misclassifications, which can then be used to update `sender_classification_db.json` (either directly or via another `--validate` run).
      * Iteratively adjust confidence thresholds in `config.toml` based on monitoring and feedback.

-----
