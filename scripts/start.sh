#!/bin/bash

# This script provides a convenient way to start the MailTag application.

# --- Configuration ---
VENV_DIR=".venv"

# --- Functions ---

function check_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Virtual environment not found. Please run 'uv pip install -e ".[dev]"' first."
        exit 1
    fi
}

# --- Main Logic ---

check_venv

case "$1" in
    --ui)
        ./scripts/streamlit.sh
        ;;
    --webhook)
        ./scripts/webhook.sh
        ;;
    *)
        ./scripts/cli.sh "$@"
        ;;
esac