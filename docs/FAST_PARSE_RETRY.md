# IMAP Fast Parse Retry Mechanism

This document provides a detailed technical overview of the retry mechanism implemented in the Fast Parse feature of the Mailtag project.

## Overview

The retry mechanism is designed to handle transient failures that can occur during IMAP operations, such as network interruptions, server timeouts, or temporary server unavailability. By automatically retrying failed operations with exponential backoff, the system becomes more resilient and can recover from temporary issues without manual intervention.

## Problem Statement

IMAP operations can fail due to various transient issues:

1. Network connectivity problems
2. Server timeouts
3. Temporary server overload
4. Connection resets
5. Temporary authentication issues

Without a retry mechanism, these transient failures would cause the entire operation to fail, requiring manual intervention or resulting in incomplete data processing.

## Solution: Retry with Exponential Backoff

The solution is to implement a retry mechanism with exponential backoff that:

1. Automatically retries failed operations
2. Increases the delay between retries exponentially
3. Adds random jitter to prevent thundering herd problems
4. Limits the maximum number of retry attempts
5. Provides detailed logging of retry attempts

## Implementation

### Configuration

The retry mechanism is configurable through the `FastParseConfig` class and the `config.toml` file:

```toml
[fast_parse]
# Maximum number of retry attempts for transient failures.
max_retries = 3
# Initial delay between retries in seconds.
retry_delay = 1.0
# Multiplier for exponential backoff between retries.
retry_backoff = 2.0
# Random jitter factor to add to retry delays (0.0-1.0).
retry_jitter = 0.1
```

These configuration options allow fine-tuning of the retry behavior:

- `max_retries`: Maximum number of retry attempts before giving up
- `retry_delay`: Initial delay between retries in seconds
- `retry_backoff`: Multiplier for exponential backoff (e.g., 2.0 means each retry waits twice as long as the previous one)
- `retry_jitter`: Random jitter factor to add to delay (0.0-1.0) to prevent synchronized retries

### Retry Decorator

The retry mechanism is implemented as a decorator in `retry.py` that can be applied to any method that might experience transient failures:

```python
@retry(exceptions=(ConnectionError, TimeoutError, IOError))
def some_method(self, ...):
    # Method implementation
```

The decorator handles:

1. Catching specified exceptions
2. Calculating the next retry delay with exponential backoff and jitter
3. Logging retry attempts
4. Re-raising the exception after max retries are exhausted

### Applied to IMAP Operations

The retry decorator is applied to key IMAP operations in the `ImapService` class:

1. **Connection Operations**:
   - `_connect_with_retry`: Establishes connection to the IMAP server

2. **Folder Operations**:
   - `_list_folders_with_retry`: Lists folders from the IMAP server
   - `_create_folder_with_retry`: Creates new folders

3. **Email Operations**:
   - `_batch_fetch`: Core method for fetching email data in batches
   - `_move_emails_with_retry`: Moves emails between folders

## Usage Example

The retry mechanism works transparently to the caller. For example, when fetching email headers:

```python
with imap_service.connect() as imap:
    headers = imap.get_email_headers(uids)
```

If a transient failure occurs during this operation, the retry mechanism will:

1. Log the failure
2. Wait for the calculated delay
3. Retry the operation
4. Either succeed or continue retrying until max_retries is reached

## Benefits

1. **Improved Reliability**: The system can recover from transient failures automatically
2. **Reduced Manual Intervention**: Fewer operations fail completely, reducing the need for manual restarts
3. **Better Resource Utilization**: Exponential backoff prevents overwhelming the server during issues
4. **Detailed Logging**: Each retry attempt is logged for monitoring and debugging
5. **Configurable Behavior**: Retry parameters can be tuned for different environments

## Limitations

1. **Permanent Failures**: The retry mechanism cannot recover from permanent failures (e.g., authentication errors, invalid commands)
2. **Stateful Operations**: Care must be taken when retrying operations that modify state
3. **Timeout Handling**: Long-running operations might still time out at a higher level

## Future Improvements

1. **Circuit Breaker Pattern**: Implement a circuit breaker to prevent retries when the server is known to be down
2. **Retry Metrics**: Collect metrics on retry attempts and success rates
3. **Adaptive Retry**: Dynamically adjust retry parameters based on observed failure patterns
4. **Operation-Specific Retry Policies**: Different retry policies for different types of operations
