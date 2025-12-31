# scripts/

Utility scripts for development, deployment, and database management.

## Shell Scripts

### start.sh
Start the main application.

### run.sh
Run classification with default settings.

### cli.sh
Launch the CLI interface.

### streamlit.sh
Start the Streamlit web UI.
```bash
./scripts/streamlit.sh
# Equivalent to: streamlit run src/streamlit_app.py
```

### webhook.sh
Start the FastAPI webhook server.
```bash
./scripts/webhook.sh
# Equivalent to: python src/webhook.py
```

### test.sh
Run the test suite.
```bash
./scripts/test.sh
# Equivalent to: uv run pytest
```

## Python Scripts

### build_domain_database.py
Build domain classification database from existing data.

### update_domain_db.py
Update domain database from reviewed candidates.

**Usage:**
```bash
# First, generate candidates
python src/main.py analyze-domains --output data/domain_candidates.json

# Review and edit domain_candidates.json

# Then update the database
python scripts/update_domain_db.py
```

### inject_filters.py
Inject email filter rules into email client configuration.

### check_duplicates.py
Check for duplicate entries in databases.

## Running Scripts

```bash
# Shell scripts
chmod +x scripts/*.sh
./scripts/start.sh

# Python scripts
python scripts/update_domain_db.py
```

## Notes
- Shell scripts assume `uv` is available in PATH
- Python scripts should be run from project root
- Check script contents for specific arguments/options
