# IMAP Fast Parse Batching System

This document provides a detailed technical overview of the batching system implemented in the Fast Parse feature of the Mailtag project.

## Overview

The batching system is a critical component of the Fast Parse implementation that enables efficient processing of large volumes of emails. It addresses the "Too long argument" error that occurs when attempting to fetch too many email UIDs at once from an IMAP server.

## Problem Statement

IMAP servers typically have limits on the maximum command line length they can process. When fetching emails using a large list of UIDs, the command can exceed this limit, resulting in errors like:

```
imaplib.error: command FETCH failed: BAD [b'Too long argument']
```

## Solution: Batch Processing

The solution is to split large UID lists into smaller batches and process them sequentially. This approach:

1. Stays within IMAP server command length limits
2. Reduces memory usage by processing emails in manageable chunks
3. Provides better error isolation (a failure in one batch doesn't affect others)
4. Enables progress tracking and reporting

## Implementation

### Core Batching Helper Method

The batching system is implemented through the `_batch_fetch` helper method in the `ImapService` class:

```python
def _batch_fetch(self, uids: list[Union[str, int]], fetch_command: list[bytes], processor: callable) -> dict[Any, Any]:
    """
    Helper method to fetch UIDs in batches and process the results.
    Processes UIDs in chunks based on the configured batch size.
    """
    if not self.client:
        raise ConnectionError("Not connected to IMAP server.")

    results = {}
    batch_size = self.fast_parse_config.batch_size
    for i in range(0, len(uids), batch_size):
        batch = uids[i:i + batch_size]
        try:
            response = self.client.fetch(batch, fetch_command)
            batch_results = processor(response)
            results.update(batch_results)
        except Exception as e:
            logger.error(f"Error fetching batch {i // batch_size + 1}: {e}")
            raise
    return results
```

This method:

- Takes a list of UIDs, a fetch command, and a processor function
- Splits the UIDs into batches of `MAX_BATCH_SIZE` (default: 100)
- Fetches and processes each batch
- Combines the results into a single dictionary
- Provides error handling for each batch

### Header Fetching with Batching

The `get_email_headers` method uses the batching system to fetch email headers:

```python
def get_email_headers(self, uids: list[str | int]) -> dict[str, dict[str, str]]:
    """
    Fetches 'From' and 'Subject' headers for a batch of email UIDs.
    Returns a dictionary mapping UID to header information.
    """
    if not self.client:
        raise ConnectionError("Not connected to IMAP server.")

    int_uids = [int(uid) if isinstance(uid, str) and uid.isdigit() else uid for uid in uids]
    return self._batch_fetch(
        int_uids, 
        [b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"], 
        self._process_email_headers
    )
```

### Full Email Fetching with Batching

Similarly, the `get_full_emails` method uses batching to fetch complete emails:

```python
def get_full_emails(self, uids: list[str | int]) -> list[Email]:
    """
    Fetches full emails for a batch of UIDs.
    Returns a list of Email objects with complete content.
    """
    if not self.client:
        raise ConnectionError("Not connected to IMAP server.")

    int_uids = [int(uid) if isinstance(uid, str) and uid.isdigit() else uid for uid in uids]
    emails_dict = self._batch_fetch(
        int_uids, 
        [b"RFC822"], 
        self._process_full_emails
    )
    return list(emails_dict.values())
```

## Batch Size Considerations

### Default Value

The current implementation uses a default `MAX_BATCH_SIZE` of 100, which has been found to work well with most IMAP servers. This value represents a balance between:

- Reducing the number of round trips to the server
- Staying within server command length limits
- Managing memory usage efficiently

### Factors Affecting Optimal Batch Size

The optimal batch size depends on several factors:

1. **IMAP Server Limits**: Different servers have different command length limits
2. **Network Latency**: Higher latency benefits from larger batch sizes to reduce round trips
3. **Email Size**: Larger emails may require smaller batch sizes to manage memory
4. **Server Performance**: Less powerful servers may handle smaller batches better

### Tuning Recommendations

For optimal performance, consider the following guidelines:

- Start with the default batch size of 100
- If you encounter "Too long argument" errors, reduce the batch size
- If performance is slow and memory usage is low, consider increasing the batch size
- Monitor network traffic and server response times when tuning

## Error Handling

The batching system includes robust error handling:

1. **Connection Checking**: Verifies IMAP connection before attempting operations
2. **Batch-Level Error Handling**: Catches and logs errors for each batch
3. **UID Type Safety**: Converts string UIDs to integers as required by IMAPClient
4. **Detailed Logging**: Provides information about which batch failed

## Future Improvements

1. **Configurable Batch Size**: Make the batch size configurable via `config.toml`
2. **Adaptive Batching**: Dynamically adjust batch size based on server response
3. **Parallel Processing**: Implement concurrent batch processing for better performance
4. **Retry Mechanism**: Add automatic retries for transient failures
5. **Progress Reporting**: Add detailed progress tracking for large batches

## Conclusion

The batching system is a critical component that enables the Fast Parse feature to efficiently process large volumes of emails while staying within IMAP server limits. By processing emails in manageable chunks, it provides better performance, error isolation, and resource management.
