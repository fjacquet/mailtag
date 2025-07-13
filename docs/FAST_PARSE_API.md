# IMAP Fast Parse API Reference

This document provides a detailed reference for the public API of the Fast Parse feature in the Mailtag project.

## Overview

The Fast Parse API consists of several key methods in the `ImapService` class that enable efficient email classification and processing. This document outlines the public methods, their parameters, return values, and usage examples.

## ImapService Class

The `ImapService` class is the primary interface for interacting with IMAP servers and implementing the Fast Parse functionality.

### Constructor

```python
def __init__(
    self,
    host: str,
    username: str,
    password: str,
    port: int = 993,
    use_ssl: bool = True,
    fast_parse_config: Optional[FastParseConfig] = None
):
```

**Parameters:**

- `host` (str): IMAP server hostname
- `username` (str): IMAP account username
- `password` (str): IMAP account password
- `port` (int, optional): IMAP server port, defaults to 993
- `use_ssl` (bool, optional): Whether to use SSL for the connection, defaults to True
- `fast_parse_config` (FastParseConfig, optional): Configuration for Fast Parse, defaults to None

**Example:**

```python
from mailtag.imap_service import ImapService
from mailtag.config import FastParseConfig

# Create with default Fast Parse configuration
imap_service = ImapService(
    host="imap.example.com",
    username="user@example.com",
    password="password123",
    port=993,
    use_ssl=True
)

# Create with custom Fast Parse configuration
fast_parse_config = FastParseConfig(
    batch_size=50,
    inbox_folder="INBOX",
    junk_folder="Junk",
    folder_cache_ttl=3600
)

imap_service = ImapService(
    host="imap.example.com",
    username="user@example.com",
    password="password123",
    fast_parse_config=fast_parse_config
)
```

### Connection Methods

#### connect

```python
def connect(self) -> bool:
```

Establishes a connection to the IMAP server.

**Returns:**

- `bool`: True if connection was successful, False otherwise

**Example:**

```python
if imap_service.connect():
    print("Connected to IMAP server")
else:
    print("Failed to connect to IMAP server")
```

#### disconnect

```python
def disconnect(self) -> None:
```

Disconnects from the IMAP server.

**Example:**

```python
imap_service.disconnect()
```

#### is_connected

```python
def is_connected(self) -> bool:
```

Checks if the service is currently connected to the IMAP server.

**Returns:**

- `bool`: True if connected, False otherwise

**Example:**

```python
if not imap_service.is_connected():
    imap_service.connect()
```

### Folder Management Methods

#### select_folder

```python
def select_folder(self, folder_name: str) -> bool:
```

Selects a folder in the IMAP account.

**Parameters:**

- `folder_name` (str): Name of the folder to select

**Returns:**

- `bool`: True if folder was successfully selected, False otherwise

**Example:**

```python
if imap_service.select_folder("INBOX"):
    print("INBOX selected")
else:
    print("Failed to select INBOX")
```

#### create_folder

```python
def create_folder(self, folder_name: str) -> bool:
```

Creates a new folder in the IMAP account.

**Parameters:**

- `folder_name` (str): Name of the folder to create

**Returns:**

- `bool`: True if folder was successfully created, False otherwise

**Example:**

```python
if imap_service.create_folder("Archive/2025"):
    print("Folder created")
else:
    print("Failed to create folder")
```

#### get_folder_hierarchy

```python
def get_folder_hierarchy(self, force_refresh: bool = False) -> dict[str, Any]:
```

Retrieves the folder hierarchy from the IMAP server.

**Parameters:**

- `force_refresh` (bool, optional): If True, forces a refresh of the cached hierarchy, defaults to False

**Returns:**

- `dict[str, Any]`: Dictionary representing the folder hierarchy

**Example:**

```python
folders = imap_service.get_folder_hierarchy()
for folder_name, folder_info in folders.items():
    print(f"Folder: {folder_name}, Attributes: {folder_info['attributes']}")
```

### Email Retrieval Methods

#### get_all_uids

```python
def get_all_uids(self) -> list[str]:
```

Retrieves all UIDs in the currently selected folder.

**Returns:**

- `list[str]`: List of email UIDs in the current folder

**Example:**

```python
imap_service.select_folder("INBOX")
uids = imap_service.get_all_uids()
print(f"Found {len(uids)} emails in INBOX")
```

#### get_email_headers

```python
def get_email_headers(self, uids: list[str | int]) -> dict[str, dict[str, str]]:
```

Fetches 'From' and 'Subject' headers for a batch of email UIDs.

**Parameters:**

- `uids` (list[str | int]): List of UIDs to fetch headers for

**Returns:**

- `dict[str, dict[str, str]]`: Dictionary mapping UID to header information

**Example:**

```python
uids = imap_service.get_all_uids()[:10]  # Get first 10 UIDs
headers = imap_service.get_email_headers(uids)

for uid, header_data in headers.items():
    print(f"UID: {uid}")
    print(f"  From: {header_data['sender_name']} <{header_data['sender_address']}>")
    print(f"  Subject: {header_data['subject']}")
```

#### get_full_emails

```python
def get_full_emails(self, uids: list[str | int]) -> list[Email]:
```

Fetches full emails for a batch of UIDs.

**Parameters:**

- `uids` (list[str | int]): List of UIDs to fetch full emails for

**Returns:**

- `list[Email]`: List of Email objects with complete content

**Example:**

```python
uids = imap_service.get_all_uids()[:5]  # Get first 5 UIDs
emails = imap_service.get_full_emails(uids)

for email in emails:
    print(f"UID: {email.msg_id}")
    print(f"  From: {email.sender_name} <{email.sender_address}>")
    print(f"  Subject: {email.subject}")
    print(f"  Body length: {len(email.body)} characters")
```

### Email Management Methods

#### batch_move_emails

```python
def batch_move_emails(self, uids: list[str], destination_folder: str) -> bool:
```

Moves a batch of emails to the specified folder.

**Parameters:**

- `uids` (list[str]): List of UIDs to move
- `destination_folder` (str): Destination folder name

**Returns:**

- `bool`: True if all emails were successfully moved, False otherwise

**Example:**

```python
# Move all emails from a specific sender to Archive folder
imap_service.select_folder("INBOX")
uids = imap_service.get_all_uids()
headers = imap_service.get_email_headers(uids)

uids_to_move = [
    uid for uid, header in headers.items()
    if header['sender_address'] == 'newsletter@example.com'
]

if uids_to_move:
    if imap_service.batch_move_emails(uids_to_move, "Archive"):
        print(f"Moved {len(uids_to_move)} emails to Archive")
    else:
        print("Failed to move emails")
```

### Fast Parse Methods

#### run_fast_parse

```python
def run_fast_parse(
    self,
    database: ClassificationDatabase,
    validate: bool = False
) -> tuple[int, int]:
```

Runs the complete Fast Parse process on the INBOX and Junk folders.

**Parameters:**

- `database` (ClassificationDatabase): Database containing sender classifications
- `validate` (bool, optional): If True, runs in validation mode without moving emails, defaults to False

**Returns:**

- `tuple[int, int]`: Tuple containing (number of emails classified in Pass 1, number of emails classified in Pass 2)

**Example:**

```python
from mailtag.database import ClassificationDatabase

# Initialize the classification database
database = ClassificationDatabase("sender_classification_db.json", "validated_classification_db.json")

# Run Fast Parse in validation mode (dry run)
pass1_count, pass2_count = imap_service.run_fast_parse(database, validate=True)
print(f"Pass 1 would classify {pass1_count} emails")
print(f"Pass 2 would classify {pass2_count} emails")

# Run Fast Parse for real
pass1_count, pass2_count = imap_service.run_fast_parse(database)
print(f"Pass 1 classified {pass1_count} emails")
print(f"Pass 2 classified {pass2_count} emails")
```

## FastParseConfig Class

The `FastParseConfig` class provides configuration options for the Fast Parse feature.

```python
class FastParseConfig:
    def __init__(
        self,
        batch_size: int = 100,
        inbox_folder: str = "INBOX",
        junk_folder: str = "Junk",
        folder_cache_ttl: int = 3600
    ):
```

**Parameters:**

- `batch_size` (int, optional): Maximum number of UIDs to process in a single batch, defaults to 100
- `inbox_folder` (str, optional): Name of the inbox folder, defaults to "INBOX"
- `junk_folder` (str, optional): Name of the junk/spam folder, defaults to "Junk"
- `folder_cache_ttl` (int, optional): Time-to-live for folder hierarchy cache in seconds, defaults to 3600 (1 hour)

**Example:**

```python
from mailtag.config import FastParseConfig

# Create custom configuration
config = FastParseConfig(
    batch_size=50,  # Smaller batch size for slower connections
    inbox_folder="INBOX",
    junk_folder="Spam",  # Different name for junk folder
    folder_cache_ttl=1800  # Shorter cache TTL (30 minutes)
)

# Use in ImapService
imap_service = ImapService(
    host="imap.example.com",
    username="user@example.com",
    password="password123",
    fast_parse_config=config
)
```

## Email Class

The `Email` class represents a structured email message.

```python
@dataclass
class Email:
    msg_id: str
    subject: str
    sender_name: str
    sender_address: str
    body: str
    labels: list[str]
```

**Attributes:**

- `msg_id` (str): Message ID or UID
- `subject` (str): Email subject
- `sender_name` (str): Sender's name
- `sender_address` (str): Sender's email address
- `body` (str): Email body content
- `labels` (list[str]): List of labels/categories assigned to the email

## Integration Examples

### Basic Fast Parse Integration

```python
from mailtag.imap_service import ImapService
from mailtag.database import ClassificationDatabase
from mailtag.config import FastParseConfig

# Initialize the classification database
database = ClassificationDatabase("sender_classification_db.json", "validated_classification_db.json")

# Create ImapService with custom configuration
config = FastParseConfig(
    batch_size=50,
    inbox_folder="INBOX",
    junk_folder="Spam",
    folder_cache_ttl=3600
)

imap_service = ImapService(
    host="imap.example.com",
    username="user@example.com",
    password="password123",
    fast_parse_config=config
)

# Connect to the server
if imap_service.connect():
    try:
        # Run Fast Parse
        pass1_count, pass2_count = imap_service.run_fast_parse(database)
        print(f"Pass 1 classified {pass1_count} emails")
        print(f"Pass 2 classified {pass2_count} emails")
        print(f"Total classified: {pass1_count + pass2_count} emails")
    finally:
        # Always disconnect when done
        imap_service.disconnect()
else:
    print("Failed to connect to IMAP server")
```

### Custom Two-Pass Implementation

```python
from mailtag.imap_service import ImapService
from mailtag.database import ClassificationDatabase

# Initialize services
database = ClassificationDatabase("sender_classification_db.json", "validated_classification_db.json")
imap_service = ImapService(
    host="imap.example.com",
    username="user@example.com",
    password="password123"
)

# Connect to the server
if imap_service.connect():
    try:
        # Select folder
        imap_service.select_folder("INBOX")
        
        # Get all UIDs
        all_uids = imap_service.get_all_uids()
        print(f"Found {len(all_uids)} emails in INBOX")
        
        # Pass 1: Process headers only
        headers = imap_service.get_email_headers(all_uids)
        
        # Classify based on sender
        classified_uids = {}
        unclassified_uids = []
        
        for uid, header_data in headers.items():
            sender_address = header_data["sender_address"]
            classification = database.get_dominant_classification(sender_address)
            
            if classification:
                if classification not in classified_uids:
                    classified_uids[classification] = []
                classified_uids[classification].append(uid)
            else:
                unclassified_uids.append(uid)
        
        # Move classified emails
        for classification, uids in classified_uids.items():
            imap_service.batch_move_emails(uids, classification)
            print(f"Moved {len(uids)} emails to {classification}")
        
        # Pass 2: Process unclassified emails
        if unclassified_uids:
            full_emails = imap_service.get_full_emails(unclassified_uids)
            
            # Process with more advanced classification
            # (This would typically involve AI classification)
            print(f"Processing {len(full_emails)} emails in Pass 2")
            
            # Example: Simple keyword-based classification
            for email in full_emails:
                if "newsletter" in email.subject.lower() or "newsletter" in email.body.lower():
                    imap_service.batch_move_emails([email.msg_id], "Newsletters")
                    print(f"Moved email {email.msg_id} to Newsletters")
    
    finally:
        # Always disconnect when done
        imap_service.disconnect()
else:
    print("Failed to connect to IMAP server")
```

## Error Handling

The Fast Parse API methods include robust error handling. Here's how to handle common errors:

```python
from mailtag.imap_service import ImapService
import imaplib

imap_service = ImapService(
    host="imap.example.com",
    username="user@example.com",
    password="password123"
)

try:
    # Connect to the server
    if not imap_service.connect():
        print("Failed to connect to IMAP server")
        exit(1)
    
    # Select folder
    if not imap_service.select_folder("INBOX"):
        print("Failed to select INBOX")
        exit(1)
    
    # Get UIDs and process
    try:
        uids = imap_service.get_all_uids()
        headers = imap_service.get_email_headers(uids)
        # Process headers...
    except imaplib.IMAP4.error as e:
        if "Too long argument" in str(e):
            print("Error: IMAP command too long. Try using a smaller batch size.")
        else:
            print(f"IMAP error: {e}")
    except ConnectionError as e:
        print(f"Connection error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

finally:
    # Always disconnect when done
    imap_service.disconnect()
```

## Best Practices

1. **Connection Management**
   - Always call `disconnect()` when done with the IMAP service
   - Use a context manager or try/finally block to ensure proper disconnection

2. **Batch Size Management**
   - Start with the default batch size of 100
   - If you encounter "Too long argument" errors, reduce the batch size
   - For very stable connections, you may increase the batch size for better performance

3. **Error Handling**
   - Handle specific IMAP errors like "Too long argument"
   - Implement reconnection logic for transient network issues
   - Use validation mode (`validate=True`) for testing before making actual changes

4. **Performance Optimization**
   - Use `get_email_headers` instead of `get_full_emails` when only header information is needed
   - Process emails in batches to manage memory usage
   - Cache folder hierarchy to reduce IMAP LIST commands

5. **Security**
   - Never hardcode credentials in your code
   - Use environment variables or secure credential storage
   - Consider using application-specific passwords for services that support them

## Conclusion

The Fast Parse API provides a powerful and efficient way to process and classify emails using IMAP. By leveraging the two-pass approach and batching system, it enables handling large volumes of emails while minimizing network traffic and memory usage.
