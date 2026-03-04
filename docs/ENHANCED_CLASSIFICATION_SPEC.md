# Technical Specification: Enhanced Email Classification Engine

**Author:** Senior Solution Architect
**Version:** 4.0
**Date:** 2025-07-06

---

## 1. Executive Summary

The initial email classification system, while functional, relied exclusively on an AI model. This led to potential inaccuracies, unnecessary API costs, and a gradual degradation of the `sender_classification_db.json` database.

This document outlines the **Enhanced Classification Engine**, a significant architectural upgrade that introduces three distinct entry points and a more robust classification strategy:

1. **Three Entry Points:**
    * **CLI (`main.py`):** A command-line interface for running the classification process, powered by `click`.
    * **Streamlit UI (`app.py`):** A web-based user interface for interacting with the classification system.
    * **Webhook (`webhook.py`):** A webhook endpoint for triggering classification from external services.
2. **Separation of AI Suggestions and Validated Classifications:** The system will now use two distinct databases:
    * `db/sender_classification_db.json`: Stores raw, unverified suggestions from the AI model.
    * `db/validated_classification_db.json`: Stores classifications that have been manually validated by the user, serving as the primary source of truth.
3. **Adaptive Multi-Signal Classification (AMSC) Strategy:** A more sophisticated, prioritized classification logic that synthesizes information from **explicit user validations**, **existing server-side labels**, the **historical sender database**, and the **AI model** to achieve highly accurate and cost-effective classification decisions.
4. **Fast Parse Implementation:** A two-pass system for IMAP accounts that dramatically improves performance by quickly handling known senders and deferring more resource-intensive AI analysis.

This initiative transforms the classification system from a simple, automated process into a resilient, adaptive, and continuously learning system with multiple ways to interact with it.

---

## 2. Core Requirements

### Functional Requirements (FR)

* **FR1: Three Entry Points:** The application **MUST** provide three distinct entry points: a CLI, a Streamlit UI, and a webhook.
* **FR2: Dual Database System:** The application **MUST** use two separate JSON files for managing classifications.
* **FR3: Adaptive Multi-Signal Classification (AMSC):** The application **MUST** use the AMSC strategy to classify emails.
* **FR4: Signal Prioritization:** The AMSC strategy **MUST** prioritize signals in the following order:
    1. **Validated Database Match:** A direct match from `validated_classification_db.json`.
    2. **Explicit Server-Side Label Match:** An existing label on the email that matches a defined category.
    3. **High-Confidence Sender History:** A classification from `sender_classification_db.json` that meets configured confidence thresholds.
    4. **AI Model Inference:** A classification from the AI model as a fallback.
* **FR5: Dry Run Mode:** The CLI **MUST** include a `--validate` flag that runs the system in a read-only "dry run" mode.
* **FR6: Fast Parse:** The IMAP provider **MUST** use a two-pass system to improve performance.

### Non-Functional Requirements (NFR)

* **NFR1: Performance:** The new logic **MUST NOT** significantly degrade email processing performance.
* **NFR2: Configurability:** All new features, especially classifier thresholds, **MUST** be configurable in `config.toml`.
* **NFR3: Observability:** All classification decisions and the signal that determined them **MUST** be clearly logged.
* **NFR4: Robust Resource Management:** Network connections **MUST** be managed robustly to prevent resource leaks, even in the case of errors.

---

## 3. Architecture & Design

### 3.1. Entry Points

* **`main.py` (CLI):** Uses `click` to provide a user-friendly command-line interface for running the classification process and generating filters.
* **`app.py` (Streamlit):** Provides a web-based UI for a more interactive experience.
* **`webhook.py` (Webhook):** Uses `fastapi` to provide a webhook endpoint for programmatic integration.

### 3.2. Dual Database System

* The `ClassificationDatabase` class manages both `sender_classification_db.json` and `validated_classification_db.json`.
* The `validated_classification_db.json` is intended to be manually edited by the user to ensure accuracy.

### 3.3. Enhanced Classifier (`src/mailtag/classifier.py`)

The `Classifier` class implements the AMSC strategy, with the same signal prioritization as defined in the requirements.

### 3.4. Fast Parse (`src/mailtag/imap_service.py`)

The `ImapService` implements a two-pass system for fetching and classifying emails to improve performance.
