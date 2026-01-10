# Suggested Commands for MailTag Development

## Environment Setup
```bash
# Install dependencies (includes dev tools)
uv pip install -e ".[dev]"

# Install with Gmail support
uv pip install -e ".[gmail]"

# Sync dependencies (updates to latest compatible versions)
uv sync -U
```

## Testing
```bash
# Run all tests with coverage
uv run pytest --cov --cov-branch --cov-report=xml

# Run tests without coverage (faster)
uv run pytest

# Run specific test file
uv run pytest tests/test_database.py

# Run specific test function
uv run pytest tests/test_database.py::test_function_name
```

## Linting and Formatting
```bash
# Check code with ruff linter
uv run ruff check .

# Auto-fix linting issues
uv run ruff check . --fix

# Check formatting
uv run ruff format --check .

# Auto-format code
uv run ruff format .

# Check YAML files
uv run yamllint .

# Auto-fix YAML files
uv run yamlfix .
```

## Running the Application
```bash
# Run classification on all providers
python src/main.py run --provider all

# Run on specific provider
python src/main.py run --provider imap
python src/main.py run --provider gmail

# Validation mode (read-only, no email moves)
python src/main.py run --provider all --validate

# Generate email filters
python src/main.py filters

# Analyze Pass 3 files for domain candidates
python src/main.py analyze-domains --output data/domain_candidates.json --min-emails 5 --top 50

# Update domain database from reviewed candidates
python scripts/update_domain_db.py

# Streamlit UI
streamlit run src/streamlit_app.py

# FastAPI webhook server
python src/webhook.py
```

## AI Model Configuration
```bash
# Ollama (local, free) - start server with optimized settings
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q4_0 OLLAMA_NUM_CTX=8192 ollama serve

# In .env:
MODEL=ollama_chat/qwen3-vl:8b-instruct
OLLAMA_API_URL=http://localhost:11434

# Gemini (cloud):
MODEL=gemini/gemini-2.5-flash
GEMINI_API_KEY=your-api-key

# OpenRouter (multi-provider):
MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY=your-key
API_BASE=https://openrouter.ai/api/v1
```

## Utility Commands (macOS/Darwin)
```bash
# Git operations
git status
git log --oneline -10
git diff

# File search
find . -name "*.py" -not -path "./.venv/*"
grep -r "pattern" src/

# Process management
ps aux | grep python
```
