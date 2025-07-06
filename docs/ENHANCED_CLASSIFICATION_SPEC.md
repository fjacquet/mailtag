# Technical Specification: Enhanced Email Classification Engine

**Author:** Senior Solution Architect
**Version:** 2.0
**Date:** 2025-07-06

---

## 1. Executive Summary

The initial email classification system, while functional, relied exclusively on an AI model. This led to potential inaccuracies, unnecessary API costs, and a gradual degradation of the `sender_classification_db.json` database.

This document outlines the **Enhanced Classification Engine**, a significant architectural upgrade that introduces two pivotal capabilities:

1.  **Validation Mode (`--validate`):** A new, read-only operational mode for safely pre-validating classifications without modifying the email server. This allows for the creation of a reliable, human-in-the-loop-verified database.
2.  **Adaptive Multi-Signal Classification (AMSC) Strategy:** A more sophisticated, prioritized classification logic that synthesizes information from **existing server-side labels**, the **historical sender database**, and the **AI model** to achieve highly accurate and cost-effective classification decisions.

This initiative transforms the classification system from a simple, automated process into a resilient, adaptive, and continuously learning system.

---

## 2. Core Requirements

### Functional Requirements (FR)

- **FR1: Validation Mode:** The application **MUST** include a `--validate` command-line argument that runs the system in a read-only mode.
- **FR2: Read-Only Operation:** In `--validate` mode, the application **MUST NOT** perform any modifying actions on the email server (e.g., moving emails, applying labels).
- **FR3: Adaptive Multi-Signal Classification (AMSC):** In standard mode, the application **MUST** use the AMSC strategy to classify emails.
- **FR4: Signal Prioritization:** The AMSC strategy **MUST** prioritize signals in the following order:
    1.  **Explicit Server-Side Label Match:** An existing label on the email that matches a defined category.
    2.  **High-Confidence Sender History:** A classification from the local database that meets configured confidence thresholds.
    3.  **AI Model Inference:** A classification from the AI model as a fallback.
- **FR5: Confidence Thresholds:** The system **MUST** allow configuration of confidence thresholds for both AI and historical data in `config.toml`.
- **FR6: Preserve Unread Status:** The IMAP service **MUST** fetch email content without marking messages as read, preserving the `\Seen` flag.

### Non-Functional Requirements (NFR)

- **NFR1: Performance:** The new logic **MUST NOT** significantly degrade email processing performance.
- **NFR2: Configurability:** All new features, especially classifier thresholds, **MUST** be configurable in `config.toml`.
- **NFR3: Observability:** All classification decisions and the signal that determined them **MUST** be clearly logged.
- **NFR4: Robust Resource Management:** Network connections **MUST** be managed robustly to prevent resource leaks, even in the case of errors.

---

## 3. Architecture & Design

### 3.1. Command-Line Interface (`app.py`)

- The entry point recognizes the `--validate` flag to activate read-only mode.
- It orchestrates the main workflow, using `contextlib` to ensure provider connections are managed safely.

### 3.2. Enhanced Classifier (`src/mailtag/classifier.py`)

The `Classifier` class implements the AMSC strategy. The `classify_email` method orchestrates the logic:

1.  **Signal 1: Server-Side Label Awareness:**
    - The `EmailProvider` interface and its implementations (`ImapService`, `GmailService`) were extended to fetch existing labels for each email.
    - The `Email` model in `src/mailtag/models.py` was updated to include a `labels` field.
    - If a fetched label matches a known category, that classification is considered definitive.

2.  **Signal 2: High-Confidence Sender History:**
    - If no server label is found, the `sender_classification_db.json` is queried.
    - A classification is considered high-confidence if the sender's historical data meets the `historical_confidence_threshold` and `min_count` defined in `config.toml`.

3.  **Signal 3: AI Model Inference (Fallback):**
    - If the first two signals fail, the AI model (`litellm`) is called.
    - The AI's suggestion is only accepted if its confidence score exceeds the `ai_confidence_threshold` from `config.toml`.

### 3.3. Provider Services (`imap_service.py`, `gmail_service.py`)

- **Efficient Data Fetching:** Services were refactored to fetch all necessary email data (ID, sender, subject, body, labels) in a single operation.
- **Preserving `\Seen` Status (IMAP):** The `ImapService` now uses `BODY.PEEK[]` to fetch email content without marking it as read.
- **`contextlib` for Resource Management:** Both services use the `@contextmanager` decorator for their `connect` methods, ensuring connections are always closed properly.

### 3.4. Data Flow Diagram

```mermaid
graph TD
    subgraph Core Processing Loop
        A[Start] --> B{Fetch Email Data};
        B --> C{Mode?};
    end

    C -- Standard --> D[Apply AMSC];
    C -- Validate --> E[Apply AMSC (Read-Only)];

    subgraph Adaptive Multi-Signal Classification (AMSC)
        D --> F{Has Server Label?};
        F -- Yes --> G[Classify: Server];
        F -- No --> H{High-Confidence History?};
        H -- Yes --> I[Classify: History];
        H -- No --> J[Call AI Model];
        J --> K{AI Confidence > Threshold?};
        K -- Yes --> L[Classify: AI];
        K -- No --> M[Classify: Unclassified];
    end

    subgraph Actions
        G --> N[Update DB];
        I --> N;
        L --> N;
        M --> N;
        N --> O{Mode?};
        O -- Standard --> P[Move/Label Email];
        O -- Validate --> Q[Log Only];
    end

    P --> R[End];
    Q --> R;

    style P fill:#f9f,stroke:#333,stroke-width:2px;
    style Q fill:#ccf,stroke:#333,stroke-width:2px;
```

---

## 4. Impact Summary

- **`src/app.py`**: Modified to handle the `--validate` flag and use `contextlib` for provider connections.
- **`src/mailtag/classifier.py`**: Major refactoring to implement the AMSC strategy.
- **`src/mailtag/providers.py` & Services**: Enhanced to fetch all data efficiently, preserve the `\Seen` flag, and use `contextlib`.
- **`src/mailtag/models.py`**: The `Email` model was updated to include `body` and `labels`.
- **`config.toml`**: The `[preclassification]` section was replaced with a `[classifier]` section containing new thresholds.
- **`tests/`**: All relevant tests were updated to reflect the new logic. A global mock for `litellm` was added in `conftest.py` to stabilize the test suite.
