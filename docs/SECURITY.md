# Security Documentation

This document outlines security measures, best practices, and recommendations for MailTag.

## Overview

MailTag is a single-user email classification tool that handles sensitive credentials and email data. This document describes the security measures in place and recommended practices.

## Authentication & Credentials

### Credential Storage

**IMAP Credentials**:

- Stored in `config.toml` with environment variable substitution
- Use `.env` file for sensitive credentials (never commit to git)
- Password should use environment variable: `${IMAP_PASSWORD}`

**Gmail OAuth**:

- Uses OAuth 2.0 flow with refresh tokens
- Tokens stored in `token.json` (automatically managed)
- Credentials file downloaded from Google Cloud Console

**Recommended File Permissions**:

```bash
# Restrict access to configuration and credentials
chmod 600 config.toml
chmod 600 .env
chmod 600 data/gmail/token.json
chmod 600 data/gmail/credentials.json
```

### Configuration Validation

MailTag validates configuration on startup (as of v0.2.0):

- **Email Format**: Validates IMAP user email format
- **Password**: Rejects empty passwords
- **API URLs**: Validates URL format for API endpoints
- **Thresholds**: Ensures confidence thresholds are in valid range (0-1)

**No Fallback Config**: Application will fail fast with clear errors if configuration is invalid, preventing silent failures with insecure defaults.

## Data Security

### Database Files

All classification databases are JSON files stored in `db/`:

- `sender_classification_db.json` - AI suggestions and historical patterns
- `validated_classification_db.json` - Manually validated classifications
- `domain_classifications.json` - Domain-level rules

**Automatic Backups**:

- Created in `db/backups/` at start of each run
- Rotates to keep 10 most recent backups
- Enables recovery from accidental corruption

**No Sensitive Email Content**:

- Databases store only sender addresses and categories
- No email bodies, subjects, or personal content stored
- Email parsing utilities handle temporary data in memory only

### Email Processing

**Pass 1 (Headers Only)**:

- Fetches only sender and subject headers
- No body content retrieved for validated senders
- Minimizes data exposure for known senders

**Pass 3 (AI Classification)**:

- Email bodies sent to AI model (Ollama/Gemini/OpenRouter)
- Body content truncated to 1500 characters maximum
- Signatures automatically removed before AI processing

**Local AI Option**:

- Use Ollama for completely local AI processing
- No data leaves your machine
- Full privacy for email content

## Network Security

### Retry Logic

Network operations use exponential backoff retry with:

- Configurable max retries (default: 3)
- Exponential backoff (default: 2.0x multiplier)
- Random jitter to prevent thundering herd

**Prevents**:

- Accidental DDoS of your own mail server
- Connection exhaustion from rapid retries
- Predictable retry patterns

### IMAP/Gmail Connections

**IMAP**:

- SSL/TLS encryption required (port 993)
- Connections use context managers for automatic cleanup
- Idle connections properly closed

**Gmail**:

- OAuth 2.0 with refresh tokens
- HTTPS only for API calls
- Automatic token refresh handled securely

## Code Security

### Input Validation

**Email Parsing**:

- Handles malformed email headers gracefully
- Decodes RFC 2047 encoded headers safely
- Fallback encodings prevent crashes on invalid UTF-8

**File Operations**:

- All file paths use Path objects (prevents path traversal)
- Database loading handles corrupted JSON gracefully
- Automatic fallback to empty database on corruption

### Error Handling

**Current Status** (as of 2026-01-10):

- ✅ Config validation with early failure
- ✅ Database corruption recovery
- ✅ Network retry logic
- ⚠️ **TODO**: Replace broad `except Exception` handlers with specific exception types (see below)

### Logging

**Security Considerations**:

- Uses `loguru` for structured logging
- No credential logging (passwords never appear in logs)
- Email addresses logged for classification tracking (review if PII concerns)
- Log files stored in `logs/` directory

**Recommendations**:

- Review log retention policy for PII compliance
- Consider hashing email addresses in logs if required
- Rotate logs regularly (configure in logging setup)

## AI Model Security

### API Keys

**Environment Variables**:

- `GEMINI_API_KEY` - For Google Gemini
- `OPENROUTER_API_KEY` - For OpenRouter
- `OLLAMA_API_URL` - For Ollama (usually localhost)

**Never**:

- Commit API keys to git
- Share API keys in issue reports
- Log API keys (automatically excluded by loguru)

### Model Responses

**Validation**:

- AI responses parsed as JSON with validation
- Confidence scores validated (0-1 range)
- Invalid responses route to "À Classer" (unclassified)
- No arbitrary code execution from model responses

**Low Confidence Handling**:

- Responses below threshold (default 0.85) rejected
- Fallback to manual classification folder
- Prevents misclassification from uncertain AI

## Recommendations & Best Practices

### Immediate Actions

1. **Set Secure File Permissions**:

   ```bash
   chmod 600 config.toml .env data/gmail/*.json
   ```

2. **Use Environment Variables**:
   - Never hardcode passwords in config.toml
   - Always use `${IMAP_PASSWORD}` substitution

3. **Review API Key Access**:
   - Use read-only API keys where possible
   - Rotate keys periodically
   - Monitor API usage for anomalies

### Operational Security

1. **Regular Backups**:
   - Database backups are automatic (kept in `db/backups/`)
   - Consider backing up `config.toml` and `.env` separately
   - Test restore procedure periodically

2. **Update Dependencies**:

   ```bash
   uv sync -U  # Update to latest compatible versions
   uv run pip list --outdated  # Check for security updates
   ```

3. **Monitor Logs**:
   - Review `logs/mailtag.log` for unusual patterns
   - Check for authentication failures
   - Monitor AI classification errors

### Development Security

1. **Code Review**:
   - All code changes should be reviewed
   - Pay attention to exception handling
   - Validate input from external sources

2. **Testing**:
   - Run full test suite before deployment: `uv run pytest`
   - Test with invalid/malicious inputs
   - Verify error recovery scenarios

3. **Linting**:
   - Use `uv run ruff check .` to catch security issues
   - Fix all linting errors before deployment
   - Enable strict type checking with mypy

## Known Issues & TODO

### Completed ✅

- [x] **Replace Broad Exception Handlers** (Phase 3.2) - COMPLETED 2026-01-10
  - Replaced 30 broad `except Exception` with specific types
  - Locations: `imap_service.py`, `gmail_service.py`, `classifier.py`, and others
  - Now using operation-specific exception types (network, JSON, file, encoding)

- [x] **Add Thread Safety** (Phase 4) - COMPLETED 2026-01-10
  - Classifier lazy initialization with RLock for MLX components
  - Metrics concurrent access protection with Lock
  - IMAP daemon thread lifecycle with Event-based shutdown

### Low Priority

- [ ] **Consider PII Hashing**: Hash email addresses in logs if PII compliance required
- [ ] **Rate Limiting**: Add rate limiting for AI API calls to prevent accidental spend
- [ ] **Audit Logging**: Separate audit log for classification decisions

## Security Disclosure

If you discover a security vulnerability in MailTag:

1. **Do NOT** open a public GitHub issue
2. Email the maintainer directly with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact assessment
   - Suggested fix (if available)

3. Allow reasonable time for fix before public disclosure

## Compliance

### GDPR Considerations

If processing email addresses from EU users:

- Email addresses are personal data under GDPR
- Stored locally in JSON databases
- Consider implementing data retention policy
- Provide mechanism for data deletion on request

### Data Minimization

MailTag follows data minimization principles:

- Only stores sender addresses and categories
- No email content persisted to disk
- Temporary body content discarded after classification
- AI cache stores only classification results, not email content

## Audit Trail

### Recent Security Improvements

**2026-01-10** - Quality Review & Remediation (Complete):

- ✅ Removed insecure fallback configuration
- ✅ Added comprehensive config validation
- ✅ Fixed dependency injection vulnerabilities
- ✅ Added error recovery tests
- ✅ Documented security practices
- ✅ Replaced 30 broad exception handlers with specific types
- ✅ Added comprehensive thread safety (classifier, metrics, IMAP daemon)
- ✅ Implemented graceful thread lifecycle management

**Previous**:

- Environment variable substitution for credentials
- OAuth 2.0 for Gmail authentication
- SSL/TLS for IMAP connections
- Automatic database backups
- AI confidence scoring with thresholds

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [Gmail API Security](https://developers.google.com/gmail/api/auth/about-auth)
- [IMAP Security](https://tools.ietf.org/html/rfc3501#section-6.2)
