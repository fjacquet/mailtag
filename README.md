# MailTag

MailTag is a Python-based email automation tool that classifies and organizes your emails. It supports both IMAP and Gmail, allowing you to connect to your email account, classify emails using a local AI model (via Ollama), and automatically move them to a specified folder or label.

[![CI Tests and Checks](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/mailtag/actions/workflows/ci.yml)

## How It Works

The `src/main.py` script provides a command-line interface to:

1. **Connect to Your Email**: It can connect to an IMAP server or your Gmail account.
2. **Fetch Emails**: It fetches emails from your inbox, with optional filters for subject, sender, and status.
3. **Classify Emails**: For each email, it uses the configured Ollama model to classify it into a category based on your `classification_schema.yml`.
4. **Move Emails**: It moves classified emails to a specified destination folder (for IMAP) or label (for Gmail).
5. **Generate Filters**: It can also generate a `mailfilter.xml` file from your classification database, which can be imported into Gmail.

## Prerequisites

- Python 3.12+
- Ollama with the model specified in `config.toml` pulled (e.g., `ollama pull gemma3`)

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/fjacquet/mailtag.git
    cd mailtag
    ```

2. Install the dependencies:
    ```bash
    uv pip install -e ".[dev]"
    ```

## Configuration

The application is configured via the `config.toml` file.

### General Configuration

- `general.ollama_model`: The name of the Ollama model to use for classification.
- `logging.level`: The logging level (e.g., `INFO`, `DEBUG`).
- `logging.file`: The path to the log file.

### IMAP Configuration

To use the IMAP provider, add an `[imap]` section to your `config.toml`:

```toml
[imap]
host = "your-imap-server.com"
user = "your-email@example.com"
```

You also need to set the `IMAP_PASSWORD` environment variable. You can do this by creating a `.env` file in the project root:

```
IMAP_PASSWORD="your-password"
```

### Gmail Configuration

To use the Gmail provider, you need to enable the Gmail API and get a `credentials.json` file.

1. **Enable the Gmail API**:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/).
   - Create a new project or select an existing one.
   - In the navigation menu, go to **APIs & Services > Library**.
   - Search for "Gmail API" and enable it.

2. **Create OAuth 2.0 Credentials**:
   - Go to **APIs & Services > Credentials**.
   - Click **Create Credentials > OAuth client ID**.
   - Select **Desktop app** as the application type.
   - Click **Create**.
   - Download the JSON file and save it as `credentials.json` in the project root.

Once you have your `credentials.json` file, add a `[gmail]` section to your `config.toml`:

```toml
[gmail]
credentials_file = "credentials.json"
token_file = "token.json"
```

The first time you run the script with the `gmail` provider, you will be prompted to authorize the application. A `token.json` file will be created to store your credentials for future runs.

## Usage

The script is run from the command line.

### Classify and Move Emails

```bash
python src/main.py --provider <imap|gmail> [options]
```

**Arguments:**

- `--provider`: The email provider to use (`imap` or `gmail`).
- `--destination`: The destination folder (for IMAP) or label (for Gmail) to move emails to. Defaults to `Processed`.
- `--subject`: Filter emails by subject (case-insensitive).
- `--sender`: Filter emails by sender (case-insensitive).
- `--status`: Filter emails by status (`SEEN` or `UNSEEN`).

**Example:**

```bash
python src/main.py --provider gmail --destination "My Label" --subject "Invoice"
```

### Generate Filters

To generate a `mailfilter.xml` file from your classification database:

```bash
python src/main.py --generate-filters
```

## Data and Database

- `data/classification_schema.yml`: Defines the categories for email classification.
- `db/sender_classification_db.json`: Stores the classification history for each sender.
