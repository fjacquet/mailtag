# MailTag

MailTag is a Python script that classifies emails from Apple Mail using a local AI model (via Ollama). It is designed to be extensible, allowing you to define your own classification schema and improve the classification over time.

## How It Works

The `src/main.py` script performs the following steps:

1.  **Loads Configuration**: It reads the `config.toml` file to get the necessary settings.
2.  **Finds the Mail Database**: It locates the `Envelope Index` SQLite database used by Apple Mail.
3.  **Copies the Database**: To avoid locking issues, it creates a temporary copy of the database.
4.  **Fetches Emails**: It queries the database to get all emails from the inbox.
5.  **Indexes Email Files**: It builds an index of all `.emlx` files to quickly find the content of each email.
6.  **Classifies Emails**: For each email, it:
    - Finds the corresponding `.emlx` file.
    - Extracts the body of the email.
    - Uses the configured Ollama model to classify the email into a category.
7.  **Updates Database**: It updates the `sender_classification_db.json` file with the classification for each sender.
8.  **Logs Proposals**: If the classifier is uncertain about a classification, it logs a proposal to the `proposals.log` file.
9.  **Outputs the Results**: It prints the subject, sender, and predicted category for each email.

## Prerequisites

- macOS with Apple Mail
- Python 3.12+
- Ollama with the model specified in `config.toml` pulled (e.g., `ollama pull gemma3`)
- Full Disk Access for the terminal running the script

## Usage

### Command-Line Interface

1.  Install the dependencies:
    ```bash
    uv pip install -e ".[dev]"
    ```
2.  Run the classification script:
    ```bash
    python src/main.py
    ```
3.  Generate the mail filters:
    ```bash
    python src/main.py --generate-filters
    ```

### Web Interface

1.  Install the dependencies (if you haven't already):
    ```bash
    uv pip install -e ".[dev]"
    ```
2.  Run the Streamlit app:
    ```bash
    streamlit run src/streamlit_app.py
    ```

## Configuration

The application is configured via the `config.toml` file. The following settings are available:

- `general.mail_dir`: The path to the Mail directory.
- `general.ollama_model`: The name of the Ollama model to use for classification.
- `general.temp_db_prefix`: The prefix for the temporary database file.
- `logging.level`: The logging level (e.g., `INFO`, `DEBUG`).
- `logging.file`: The path to the log file.

## Data Files

The `data` directory contains the following files:

- `classification_schema.yml`: Defines the classification schema used by the classifier. You can edit this file to add, remove, or change the categories.
- `mailfilter.xml`: A Gmail-compatible XML file that can be generated from the classification schema.

## Database

The `db` directory contains the following files:

- `sender_classification_db.json`: A JSON file that stores the classification count for each sender. This file is used to track the accuracy of the classifier and can be used to generate mail filters.

## Logging

The `logs` directory contains the following files:

- `mailtag.log`: The main log file for the application.
- `proposals.log`: A log file that contains classification proposals from the classifier. You can use this file to identify new categories and improve the classification schema.
