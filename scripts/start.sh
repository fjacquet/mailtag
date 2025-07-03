#!/bin/bash

# This script provides a convenient way to start the MailTag application.

# --- Configuration ---
VENV_DIR=".venv"
SRC_DIR="src"

# --- Functions ---

function check_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Virtual environment not found. Please run 'uv pip install -e ".[dev]"' first."
        exit 1
    fi
}

function start_streamlit() {
    echo "Starting Streamlit web interface..."
    streamlit run "$SRC_DIR/streamlit_app.py"
}

function start_cli() {
    echo "Starting command-line interface..."
    python "$SRC_DIR/main.py" "$@"
}

# --- Main Logic ---

check_venv

if [ "$1" == "--ui" ]; then
    start_streamlit
else
    start_cli "$@"
fi
