# Task Completion Checklist for MailTag

## Before Committing Code

### 1. Run Linting
```bash
uv run ruff check .
```
Fix any issues or use `--fix` for auto-corrections.

### 2. Run Formatting
```bash
uv run ruff format .
```

### 3. Run Tests
```bash
uv run pytest
```
Ensure all tests pass. For comprehensive coverage:
```bash
uv run pytest --cov --cov-branch --cov-report=xml
```

### 4. Check YAML Files (if modified)
```bash
uv run yamllint .
```

## Code Review Considerations
- Avoid over-engineering - only make directly requested changes
- Don't add features beyond what was asked
- Don't create helpers/utilities for one-time operations
- Keep solutions simple and focused
- Avoid backwards-compatibility hacks for unused code

## Security Considerations
- Check for command injection, XSS, SQL injection risks
- Never store credentials in code
- Use environment variables for secrets

## When Modifying Classification Logic
- Test with `--validate` flag first (read-only mode)
- Check metrics after changes:
  ```python
  classifier.log_metrics_summary("INFO")
  classifier.export_metrics(Path("data/metrics"))
  ```

## Final Steps
1. Ensure all tests pass
2. Code is formatted and linted
3. No sensitive data in commits
4. Commit with descriptive message
