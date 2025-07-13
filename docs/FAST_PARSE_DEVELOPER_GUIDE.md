# IMAP Fast Parse Developer Guide

This document provides guidance for developers working with the Fast Parse feature in the Mailtag project. It includes information on extending functionality, troubleshooting common issues, and best practices for development.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Extending Fast Parse](#extending-fast-parse)
3. [Testing Guide](#testing-guide)
4. [Troubleshooting](#troubleshooting)
5. [Code Style and Conventions](#code-style-and-conventions)
6. [Development Workflow](#development-workflow)

## Architecture Overview

The Fast Parse feature is built on a modular architecture that separates concerns and follows functional programming principles as outlined in `docs/LAYOUT.md`. Here's a high-level overview:

### Key Components

1. **ImapService**: Core class that handles IMAP interactions, including connection management, folder operations, and email fetching.

2. **FastParseConfig**: Configuration class that controls batch sizes, folder names, and caching behavior.

3. **ClassificationDatabase**: Manages the dual-database system for sender classifications.

4. **Email Processing Pipeline**:
   - Header fetching and parsing
   - Body extraction and decoding
   - Classification logic
   - Email movement operations

### Data Flow

1. Connect to IMAP server
2. Select folder (INBOX or Junk)
3. Fetch all UIDs in the folder
4. Pass 1: Fetch and process headers in batches
5. Classify emails based on sender information
6. Move classified emails to appropriate folders
7. Pass 2: Fetch and process full content for unclassified emails
8. Apply more sophisticated classification
9. Move newly classified emails to appropriate folders

## Extending Fast Parse

### Adding New Classification Methods

To add a new classification method to the Fast Parse system:

1. **Update the ClassificationDatabase**:

```python
def get_classification_by_new_method(self, email_data: dict) -> Optional[str]:
    """
    Classify an email using a new method.
    """
    # Implement your classification logic here
    return classification_result
```

2. **Integrate with the Two-Pass System**:

```python
# In _run_fast_parse_on_folder or a similar orchestration function
for uid, header_data in headers.items():
    # Existing classification logic
    classification = database.get_dominant_classification(sender_address)
    
    # Add your new classification method
    if not classification:
        classification = database.get_classification_by_new_method(header_data)
        
    if classification:
        emails_to_move[classification].append(uid)
    else:
        uids_to_process_pass2.append(uid)
```

### Adding Support for New Email Formats

To handle new email formats or content types:

1. **Update the `_get_body_from_msg` Method**:

```python
def _get_body_from_msg(self, msg) -> str:
    # Existing code for plain text and HTML
    
    # Add support for new content type
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            
            # Handle new content type
            if content_type == "application/your-format":
                payload = self._decode_payload(part)
                return self._process_your_format(payload)
```

2. **Add a Processing Method for the New Format**:

```python
def _process_your_format(self, content: str) -> str:
    """
    Process content in your custom format.
    """
    # Implement processing logic
    return processed_content
```

### Customizing the Batching System

To customize the batching system for specific needs:

1. **Make Batch Size Dynamic**:

```python
def _get_optimal_batch_size(self, uids: list) -> int:
    """
    Calculate optimal batch size based on various factors.
    """
    # Consider factors like:
    # - Total number of UIDs
    # - Average email size (if known)
    # - Server capabilities
    # - Network conditions
    
    if len(uids) > 1000:
        return 50  # Smaller batches for large mailboxes
    return 100  # Default batch size
```

2. **Update the Batching Method**:

```python
def _batch_fetch(self, uids: list[Union[str, int]], fetch_command: list[bytes], processor: callable) -> dict[Any, Any]:
    results = {}
    
    # Get dynamic batch size
    batch_size = self._get_optimal_batch_size(uids)
    
    for i in range(0, len(uids), batch_size):
        batch = uids[i:i + batch_size]
        # Process batch as before
```

### Adding Concurrency

To implement concurrent batch processing:

1. **Add Dependencies**:

```python
import concurrent.futures
from typing import List, Dict, Any, Union, Callable
```

2. **Implement Concurrent Batch Processing**:

```python
def _concurrent_batch_fetch(
    self, 
    uids: list[Union[str, int]], 
    fetch_command: list[bytes], 
    processor: callable,
    max_workers: int = 4
) -> dict[Any, Any]:
    """
    Fetch UIDs in batches concurrently and process the results.
    """
    if not self.client:
        raise ConnectionError("Not connected to IMAP server.")

    # Split UIDs into batches
    batches = []
    for i in range(0, len(uids), self.fast_parse_config.batch_size):
        batches.append(uids[i:i + self.fast_parse_config.batch_size])
    
    results = {}
    
    # Process batches concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(self._process_single_batch, batch, fetch_command, processor): batch
            for batch in batches
        }
        
        for future in concurrent.futures.as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                batch_results = future.result()
                results.update(batch_results)
            except Exception as e:
                logger.error(f"Error processing batch {batch}: {e}")
    
    return results

def _process_single_batch(
    self, 
    batch: list[Union[str, int]], 
    fetch_command: list[bytes], 
    processor: callable
) -> dict[Any, Any]:
    """
    Process a single batch of UIDs.
    """
    try:
        # Create a new IMAP connection for this thread
        client = IMAPClient(self.host, port=self.port, use_ssl=self.use_ssl)
        client.login(self.username, self.password)
        client.select_folder(self.current_folder)
        
        # Fetch and process the batch
        response = client.fetch(batch, fetch_command)
        batch_results = processor(response)
        
        # Clean up
        client.logout()
        
        return batch_results
    except Exception as e:
        logger.error(f"Error in batch processing: {e}")
        raise
```

## Testing Guide

### Unit Testing

The Fast Parse feature includes unit tests for its components. Here's how to add new tests:

1. **Create Test Files**:

```python
# tests/test_imap_service.py
import unittest
from unittest.mock import Mock, patch
from mailtag.imap_service import ImapService

class TestImapService(unittest.TestCase):
    def setUp(self):
        self.imap_service = ImapService(
            host="test.example.com",
            username="test",
            password="password"
        )
        # Mock the IMAP client
        self.imap_service.client = Mock()
    
    def test_get_email_headers(self):
        # Mock the fetch response
        mock_response = {
            1: {
                b"BODY[HEADER.FIELDS (FROM SUBJECT)]": b"From: test@example.com\r\nSubject: Test Email\r\n\r\n"
            }
        }
        self.imap_service.client.fetch.return_value = mock_response
        
        # Call the method
        result = self.imap_service.get_email_headers([1])
        
        # Verify the result
        self.assertEqual(len(result), 1)
        self.assertEqual(result["1"]["sender_address"], "test@example.com")
        self.assertEqual(result["1"]["subject"], "Test Email")
```

2. **Run Tests**:

```bash
# Run all tests
python -m unittest discover

# Run specific test file
python -m unittest tests.test_imap_service

# Run specific test case
python -m unittest tests.test_imap_service.TestImapService.test_get_email_headers
```

### Integration Testing

For integration testing with a real IMAP server:

1. **Set Up a Test Environment**:

```python
# tests/integration/test_imap_integration.py
import unittest
import os
from mailtag.imap_service import ImapService
from mailtag.database import ClassificationDatabase

class TestImapIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Get credentials from environment variables
        cls.host = os.environ.get("TEST_IMAP_HOST")
        cls.username = os.environ.get("TEST_IMAP_USERNAME")
        cls.password = os.environ.get("TEST_IMAP_PASSWORD")
        
        if not all([cls.host, cls.username, cls.password]):
            raise ValueError("Test IMAP credentials not set in environment variables")
        
        # Initialize services
        cls.imap_service = ImapService(
            host=cls.host,
            username=cls.username,
            password=cls.password
        )
        cls.database = ClassificationDatabase("test_sender_db.json", "test_validated_db.json")
    
    def setUp(self):
        # Connect before each test
        self.imap_service.connect()
    
    def tearDown(self):
        # Disconnect after each test
        self.imap_service.disconnect()
    
    def test_run_fast_parse(self):
        # Run in validation mode to avoid moving emails
        pass1_count, pass2_count = self.imap_service.run_fast_parse(self.database, validate=True)
        
        # Verify results
        self.assertIsInstance(pass1_count, int)
        self.assertIsInstance(pass2_count, int)
```

2. **Run Integration Tests**:

```bash
# Set environment variables
export TEST_IMAP_HOST="imap.example.com"
export TEST_IMAP_USERNAME="test@example.com"
export TEST_IMAP_PASSWORD="password"

# Run integration tests
python -m unittest tests.integration.test_imap_integration
```

## Troubleshooting

### Common Issues and Solutions

#### 1. "Too long argument" Error

**Symptoms**:
- Error message: `imaplib.error: command FETCH failed: BAD [b'Too long argument']`
- Occurs when fetching large batches of emails

**Solutions**:
- Reduce the batch size in `FastParseConfig`
- Check if the UIDs are being properly batched
- Verify that the `_batch_fetch` method is being used correctly

#### 2. Connection Timeouts

**Symptoms**:
- Error message: `socket.timeout: timed out`
- Connection drops during long operations

**Solutions**:
- Implement connection refresh logic
- Add retry mechanism for operations
- Check network stability and firewall settings

```python
def _with_connection_retry(self, operation, max_retries=3):
    """
    Execute an operation with connection retry logic.
    """
    retries = 0
    while retries < max_retries:
        try:
            return operation()
        except (socket.timeout, ConnectionError) as e:
            retries += 1
            logger.warning(f"Connection error (attempt {retries}/{max_retries}): {e}")
            
            if retries < max_retries:
                # Reconnect and try again
                self.disconnect()
                time.sleep(2 ** retries)  # Exponential backoff
                self.connect()
            else:
                raise
```

#### 3. Memory Issues

**Symptoms**:
- High memory usage
- Process crashes with `MemoryError`

**Solutions**:
- Process emails in smaller batches
- Implement streaming for large emails
- Add explicit garbage collection

```python
import gc

def _process_large_mailbox(self, uids):
    """
    Process a large mailbox with memory management.
    """
    results = {}
    
    for i in range(0, len(uids), self.fast_parse_config.batch_size):
        batch = uids[i:i + self.fast_parse_config.batch_size]
        
        # Process batch
        batch_results = self._process_batch(batch)
        results.update(batch_results)
        
        # Force garbage collection after each batch
        gc.collect()
        
        # Log progress
        logger.info(f"Processed {i + len(batch)}/{len(uids)} emails")
    
    return results
```

#### 4. Character Encoding Issues

**Symptoms**:
- `UnicodeDecodeError` when processing emails
- Garbled text in email content

**Solutions**:
- Use more robust decoding in `_decode_payload`
- Add support for additional character encodings
- Implement fallback decoding strategies

#### 5. HTML Parsing Failures

**Symptoms**:
- Error messages from BeautifulSoup
- Missing or incomplete content from HTML emails

**Solutions**:
- Update BeautifulSoup parser options
- Add better error handling for HTML parsing
- Consider alternative HTML parsing libraries

### Debugging Techniques

#### 1. Enable Detailed Logging

```python
import logging
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="DEBUG")
logger.add("fast_parse_debug.log", level="DEBUG", rotation="10 MB")

# Add detailed logging in key methods
def get_email_headers(self, uids: list[str | int]) -> dict[str, dict[str, str]]:
    logger.debug(f"Fetching headers for {len(uids)} UIDs")
    # ...
    logger.debug(f"Headers fetched successfully: {len(results)} results")
    return results
```

#### 2. Use IMAP Debug Mode

```python
# Enable IMAP debug mode
import imaplib
imaplib.Debug = 4  # Set to desired debug level (1-5)

# Or in ImapService
def connect(self):
    self.client = IMAPClient(self.host, port=self.port, use_ssl=self.use_ssl)
    self.client._imap.debug = 4  # Enable debug output
    # ...
```

#### 3. Create Test Scripts

Create standalone test scripts to isolate and debug specific functionality:

```python
# debug_imap_connection.py
from mailtag.imap_service import ImapService
import sys

def test_connection(host, username, password):
    service = ImapService(host, username, password)
    
    print(f"Connecting to {host}...")
    connected = service.connect()
    print(f"Connected: {connected}")
    
    if connected:
        print("Listing folders:")
        folders = service.get_folder_hierarchy(force_refresh=True)
        for name, info in folders.items():
            print(f"- {name} ({info['attributes']})")
        
        service.disconnect()
        print("Disconnected")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python debug_imap_connection.py host username password")
        sys.exit(1)
    
    test_connection(sys.argv[1], sys.argv[2], sys.argv[3])
```

## Code Style and Conventions

The Fast Parse feature follows the coding conventions outlined in `docs/LAYOUT.md`, with an emphasis on functional programming principles:

### 1. Pure Functions

Prefer pure functions that don't have side effects and return the same output for the same input:

```python
# Good: Pure function
def parse_sender(sender_string: str) -> tuple[str, str]:
    """Parse sender string into name and email address."""
    name, address = email.utils.parseaddr(sender_string)
    return name, address

# Avoid: Impure function with side effects
def process_sender(self, sender_string: str) -> None:
    """Process sender with side effects."""
    name, address = email.utils.parseaddr(sender_string)
    self.sender_name = name  # Side effect: modifies object state
    self.sender_address = address
```

### 2. Type Hints

Use comprehensive type hints for all functions and methods:

```python
from typing import Dict, List, Optional, Union, Any, Callable

def get_email_headers(self, uids: list[Union[str, int]]) -> Dict[str, Dict[str, str]]:
    """
    Fetches 'From' and 'Subject' headers for a batch of email UIDs.
    Returns a dictionary mapping UID to header information.
    """
    # Implementation...
```

### 3. Error Handling

Use the `returns` library for functional error handling:

```python
from returns.result import Result, Success, Failure

def parse_header_safely(header_value: Any) -> Result[str, Exception]:
    """
    Parse header value with functional error handling.
    """
    try:
        if isinstance(header_value, Header):
            return Success(str(header_value))
        elif isinstance(header_value, bytes):
            return Success(header_value.decode("utf-8", errors="replace"))
        else:
            return Success(str(header_value))
    except Exception as e:
        return Failure(e)
```

### 4. Documentation

Follow these documentation conventions:

- Use docstrings for all functions, classes, and methods
- Include parameter and return type descriptions
- Document exceptions that may be raised
- Add examples for complex functions

```python
def batch_move_emails(self, uids: list[str], destination_folder: str) -> bool:
    """
    Moves a batch of emails to the specified folder.
    
    Args:
        uids: List of UIDs to move
        destination_folder: Destination folder name
    
    Returns:
        bool: True if all emails were successfully moved, False otherwise
    
    Raises:
        ConnectionError: If not connected to IMAP server
        ValueError: If destination folder doesn't exist
    
    Example:
        >>> imap_service.batch_move_emails(["123", "124"], "Archive")
        True
    """
    # Implementation...
```

## Development Workflow

### 1. Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/username/mailtag.git
cd mailtag

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -e .  # Install in development mode
```

### 2. Development Cycle

1. **Make Changes**: Implement new features or fix bugs in the Fast Parse system
2. **Write Tests**: Add unit tests and integration tests for your changes
3. **Run Tests**: Verify that all tests pass
4. **Update Documentation**: Keep documentation in sync with code changes
5. **Code Review**: Submit your changes for review

### 3. Recommended Tools

- **Code Formatting**: Use `black` and `isort` to maintain consistent code style
- **Type Checking**: Use `mypy` to verify type hints
- **Testing**: Use `pytest` for running tests
- **Linting**: Use `flake8` to catch common issues

```bash
# Format code
black mailtag/
isort mailtag/

# Type checking
mypy mailtag/

# Linting
flake8 mailtag/

# Run tests
pytest
```

### 4. Continuous Integration

Set up CI workflows to automatically run tests and checks on code changes:

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.10'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r requirements-dev.txt
    - name: Lint with flake8
      run: flake8 mailtag/
    - name: Type check with mypy
      run: mypy mailtag/
    - name: Test with pytest
      run: pytest
```

## Conclusion

This developer guide provides a comprehensive reference for working with the Fast Parse feature in the Mailtag project. By following these guidelines, you can effectively extend, test, and troubleshoot the system while maintaining code quality and consistency.

For additional information, refer to the following documents:
- `FAST_PARSE_IMPLEMENTATION.md`: Overview of the Fast Parse implementation
- `FAST_PARSE_BATCHING.md`: Details on the batching system
- `FAST_PARSE_HEADER_PROCESSING.md`: Information on header parsing
- `FAST_PARSE_BODY_PROCESSING.md`: Details on email body extraction
- `FAST_PARSE_PERFORMANCE.md`: Performance considerations and tuning
- `FAST_PARSE_API.md`: API reference and usage examples
