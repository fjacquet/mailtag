# Technical Specification: Enhanced Email Classification Engine

**Author:** Senior Solution Architect
**Version:** 2.1
**Date:** 2025-07-06

---

## 1. Executive Summary

The initial email classification system, while functional, relied exclusively on an AI model. This led to potential inaccuracies, unnecessary API costs, and a gradual degradation of the `sender_classification_db.json` database.

This document outlines the **Enhanced Classification Engine**, a significant architectural upgrade that introduces two pivotal capabilities:

1.  **Separation of AI Suggestions and Validated Classifications:** The system will now use two distinct databases:
    *   `db/sender_classification_db.json`: Stores raw, unverified suggestions from the AI model.
    *   `db/validated_classification_db.json`: Stores classifications that have been manually validated by the user, serving as the primary source of truth.
2.  **Adaptive Multi-Signal Classification (AMSC) Strategy:** A more sophisticated, prioritized classification logic that synthesizes information from **explicit user validations**, **existing server-side labels**, the **historical sender database**, and the **AI model** to achieve highly accurate and cost-effective classification decisions.

This initiative transforms the classification system from a simple, automated process into a resilient, adaptive, and continuously learning system.

---

## 2. Core Requirements

### Functional Requirements (FR)

- **FR1: Dual Database System:** The application **MUST** use two separate JSON files for managing classifications:
    *   `db/sender_classification_db.json` for AI suggestions.
    *   `db/validated_classification_db.json` for user-validated classifications.
- **FR2: Adaptive Multi-Signal Classification (AMSC):** In standard mode, the application **MUST** use the AMSC strategy to classify emails.
- **FR3: Signal Prioritization:** The AMSC strategy **MUST** prioritize signals in the following order:
    1.  **Validated Database Match:** A direct match from `validated_classification_db.json`.
    2.  **Explicit Server-Side Label Match:** An existing label on the email that matches a defined category.
    3.  **High-Confidence Sender History:** A classification from `sender_classification_db.json` that meets configured confidence thresholds.
    4.  **AI Model Inference:** A classification from the AI model as a fallback.
- **FR4: Confidence Thresholds:** The system **MUST** allow configuration of confidence thresholds for both AI and historical data in `config.toml`.
- **FR5: Preserve Unread Status:** The IMAP service **MUST** fetch email content without marking messages as read, preserving the `\Seen` flag.

### Non-Functional Requirements (NFR)

- **NFR1: Performance:** The new logic **MUST NOT** significantly degrade email processing performance.
- **NFR2: Configurability:** All new features, especially classifier thresholds, **MUST** be configurable in `config.toml`.
- **NFR3: Observability:** All classification decisions and the signal that determined them **MUST** be clearly logged.
- **NFR4: Robust Resource Management:** Network connections **MUST** be managed robustly to prevent resource leaks, even in the case of errors.

---

## 3. Architecture & Design

### 3.1. Dual Database System

- The `ClassificationDatabase` class will be updated to manage both `sender_classification_db.json` and `validated_classification_db.json`.
- The `--validate` flag will now be used to promote a suggestion from the AI database to the validated database.

### 3.2. Enhanced Classifier (`src/mailtag/classifier.py`)

The `Classifier` class implements the AMSC strategy. The `classify_email` method orchestrates the logic:

1.  **Signal 1: Validated Database:**
    - The classifier first checks `validated_classification_db.json` for a matching sender. If found, this classification is used.
2.  **Signal 2: Server-Side Label Awareness:**
    - If no validated classification exists, the system checks for existing server-side labels.
3.  **Signal 3: High-Confidence Sender History:**
    - If no validated classification or server label is found, the `sender_classification_db.json` is queried.
4.  **Signal 4: AI Model Inference (Fallback):**
    - If the first three signals fail, the AI model is called. Its suggestions are saved to `sender_classification_db.json`.

### 3.3. Data Flow Diagram

```mermaid
graph TD
    subgraph Core Processing Loop
        A[Start] --> B{Fetch Email Data};
        B --> C{Mode?};
    end

    C -- Standard --> D[Apply AMSC];
    C -- Validate --> E[Promote AI Suggestion to Validated DB];

    subgraph Adaptive Multi-Signal Classification (AMSC)
        D --> F{Sender in Validated DB?};
        F -- Yes --> G[Classify: Validated];
        F -- No --> H{Has Server Label?};
        H -- Yes --> I[Classify: Server];
        H -- No --> J{High-Confidence History?};
        J -- Yes --> K[Classify: History];
        J -- No --> L[Call AI Model];
        L --> M{AI Confidence > Threshold?};
        M -- Yes --> N[Classify: AI Suggestion];
        M -- No --> O[Classify: Unclassified];
    end

    subgraph Actions
        G --> P[Move/Label Email];
        I --> P;
        K --> P;
        N --> Q[Update AI DB];
        O --> Q;
        Q --> P;
    end

    P --> R[End];
```
