# Mailtag

Mailtag is a Python script that classifies emails from Apple Mail using a local AI model (via Ollama).

## How it works

The `src/main.py` script performs the following steps:

1.  **Finds the Mail database**: It locates the `Envelope Index` SQLite database used by Apple Mail.
2.  **Copies the database**: To avoid locking issues, it creates a temporary copy of the database.
3.  **Fetches emails**: It queries the database to get all emails from the inbox.
4.  **Indexes email files**: It builds an index of all `.emlx` files to quickly find the content of each email.
5.  **Classifies emails**: For each email, it:
    *   Finds the corresponding `.emlx` file.
    *   Extracts the body of the email.
    *   Uses the Ollama-served `gemma3` model to classify the email into a category (e.g., "work", "personal", "invoices").
6.  **Outputs the results**: It prints the subject, sender, and predicted category for each email.

## Prerequisites

*   macOS with Apple Mail
*   Python 3.12+
*   Ollama with the `gemma3` model pulled (`ollama pull gemma3`)
*   Full Disk Access for the terminal running the script

## Usage

1.  Install the dependencies:
    ```bash
    uv pip install -e ".[dev]"
    ```
2.  Run the script:
    ```bash
    python src/main.py
    ```
