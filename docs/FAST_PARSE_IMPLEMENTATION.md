# IMAP Fast Parse Implementation

This document provides a detailed technical overview of the Fast Parse implementation for the Mailtag project, including its architecture, key components, and implementation details.

## Overview

The Fast Parse system is designed to efficiently process large volumes of emails by implementing a two-pass classification strategy that minimizes the amount of data transferred from the IMAP server. This approach significantly improves performance and reduces resource usage when dealing with large inboxes.

## Architecture

### Two-Pass Classification Strategy

The Fast Parse implementation follows a two-pass approach:

1. **Pass 1: Fast Classification**
   - Fetches only email headers (From and Subject) in batches
   - Checks sender against the classification database
   - Immediately moves emails from known senders to appropriate folders
   - Avoids downloading full email content for emails that can be classified by sender

2. **Pass 2: AI Classification**
   - Processes only emails not classified in Pass 1
   - Fetches full email content (headers and body)
   - Uses AI to analyze and classify the email
   - Updates the classification database with new sender information
   - Moves emails to appropriate folders based on classification

### Key Components

#### ImapService

The `ImapService` class is the core component responsible for IMAP operations:

- Manages connection to the IMAP server
- Implements batching for efficient data retrieval
- Handles folder hierarchy caching
- Provides methods for email header and full content retrieval

#### Batching System

The batching system is implemented to avoid "Too long argument" errors when fetching multiple UIDs:

- Uses a configurable `MAX_BATCH_SIZE` (default: 100)
- Processes UIDs in chunks to stay within IMAP server limits
- Implements the `_batch_fetch` helper method for reusable batching logic

#### Header Processing

The header processing system efficiently extracts and parses email headers:

- `get_email_headers`: Fetches minimal headers (From and Subject) for a batch of UIDs
- `_process_email_headers`: Parses the IMAP response to extract header values
- `_parse_header_value`: Handles various header formats (Header objects, bytes, strings)
- `_parse_sender`: Extracts name and email address from sender string

#### Email Body Processing

The email body processing system handles full email content retrieval:

- `get_full_emails`: Fetches complete email content for a batch of UIDs
- `_process_full_emails`: Parses the full email response
- `_get_body_from_msg`: Extracts the email body, preferring plain text
- `_decode_payload`: Handles different content types and encodings

## Implementation Details

### Batching Implementation

```python
def _batch_fetch(self, uids: list[Union[str, int]], fetch_command: list[bytes], processor: callable) -> dict[Any, Any]:
    """
    Helper method to fetch UIDs in batches and process the results.
    Processes UIDs in chunks of MAX_BATCH_SIZE (default: 100).
    """
    if not self.client:
        raise ConnectionError("Not connected to IMAP server.")

    results = {}
    for i in range(0, len(uids), MAX_BATCH_SIZE):
        batch = uids[i:i + MAX_BATCH_SIZE]
        try:
            response = self.client.fetch(batch, fetch_command)
            batch_results = processor(response)
            results.update(batch_results)
        except Exception as e:
            logger.error(f"Error fetching batch {i // MAX_BATCH_SIZE + 1}: {e}")
            raise
    return results
```

### Header Processing

The system handles various header formats:

```python
def _parse_header_value(self, header_value) -> str:
    """
    Parse and decode header values, handling various types including email.header.Header objects.
    """
    # Handle email.header.Header objects
    if isinstance(header_value, Header):
        try:
            return str(header_value)
        except Exception as e:
            logger.warning(f"Error decoding header: {e}")
            return str(header_value)

    # Handle bytes
    if isinstance(header_value, bytes):
        try:
            return header_value.decode("utf-8", errors="replace")
        except Exception:
            return str(header_value)

    # Handle other types
    return str(header_value)
```

### Email Body Processing

The system extracts email bodies with preference for plain text:

```python
def _get_body_from_msg(self, msg) -> str:
    """
    Reads the body of a specific email message, prioritizing plain text over HTML.
    Handles various character encodings and malformed content.
    """
    plain_text_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            try:
                content_type = part.get_content_type()
                payload = self._decode_payload(part)

                if content_type == "text/plain" and not plain_text_body:
                    plain_text_body = payload
                elif content_type == "text/html" and not html_body:
                    html_body = payload
            except Exception as e:
                logger.warning(f"Error processing email: {e}")

    # Return plain text if available, otherwise try HTML
    if plain_text_body.strip():
        return plain_text_body.strip()

    if html_body:
        try:
            soup = BeautifulSoup(html_body, "html.parser")
            return soup.get_text(separator="\n", strip=True)
        except Exception as e:
            logger.warning(f"Error parsing HTML content: {e}")
            return html_body.strip()

    return ""
```

## Performance Considerations

### Batch Size

- Default batch size is 100 emails per batch
- This value is a balance between reducing round trips and staying within IMAP server limits
- Can be tuned based on server capabilities and performance requirements

### Memory Management

- Processes one batch at a time to limit memory usage
- Cleans up resources after each batch
- Implements proper connection handling and closure

### Error Handling

- Implements graceful degradation on partial failures
- Provides detailed error logging
- Uses try-except blocks to handle specific error cases

## Configuration

The Fast Parse system is configured through the `FastParseConfig` class:

```python
@dataclass
class FastParseConfig:
    batch_size: int = 100
    junk_folder_name: str = "Junk"
    unclassified_folder_name: str = "Unclassified"
    folder_cache_ttl_hours: int = 24
```

## Future Improvements

1. **Configuration Enhancements**
   - Make batch size configurable via `config.toml`
   - Add configuration for retry attempts and delays

2. **Performance Optimizations**
   - Implement concurrent batch processing
   - Add support for streaming large email bodies

3. **Error Handling & Reliability**
   - Add retry mechanism for transient failures
   - Implement circuit breaker pattern for IMAP operations

4. **Monitoring & Metrics**
   - Add performance metrics collection
   - Implement health checks for IMAP connections

## Conclusion

The IMAP Fast Parse implementation significantly improves the performance and resource efficiency of email classification by using a two-pass approach. The batching system ensures that IMAP operations stay within server limits, while the robust header and body processing logic handles various email formats and encodings.
