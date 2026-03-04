# IMAP Fast Parse Body Processing

This document provides a detailed technical overview of the email body processing system implemented in the Fast Parse feature of the Mailtag project.

## Overview

The email body processing system is responsible for extracting and decoding email content from IMAP responses during the second pass of the Fast Parse implementation. It handles various content types, character encodings, and multipart messages to provide clean, readable text content for classification.

## Key Components

### Full Email Fetching

The `get_full_emails` method fetches complete emails for a batch of UIDs:

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

This method:

- Converts string UIDs to integers as required by IMAPClient
- Uses the `RFC822` command to fetch the complete email content
- Leverages the batching system to handle large UID lists
- Uses a dedicated processor function to parse the IMAP response
- Returns a list of structured `Email` objects

### Full Email Processing

The `_process_full_emails` method parses the complete email content:

```python
def _process_full_emails(self, response: dict[int, dict[bytes, bytes]]) -> dict[str, Email]:
    """
    Process full emails from IMAP response.
    Converts the raw IMAP response into structured Email objects.
    """
    emails = {}
    for msg_id, data in response.items():
        if b"RFC822" not in data:
            logger.warning(f"Missing RFC822 data in response for message {msg_id}")
            continue

        try:
            email_data = data[b"RFC822"]
            msg = email.message_from_bytes(email_data)
            
            # Extract headers
            from_header = self._parse_header_value(msg.get("From", ""))
            sender_name, sender_address = self._parse_sender(from_header)
            subject = self._parse_header_value(msg.get("Subject", ""))
            
            # Extract body
            body = self._get_body_from_msg(msg)
            
            # Create Email object
            emails[str(msg_id)] = Email(
                msg_id=str(msg_id),
                subject=subject,
                sender_name=sender_name,
                sender_address=sender_address,
                body=body,
                labels=[]  # Labels are typically not available in IMAP
            )
        except Exception as e:
            logger.error(f"Error processing email {msg_id}: {e}")
    
    return emails
```

This method:

- Iterates through each message in the IMAP response
- Uses `email.message_from_bytes` to parse the raw email data
- Extracts headers using the same methods as the header processing system
- Extracts the email body using a dedicated method
- Creates structured `Email` objects with all the necessary information
- Provides robust error handling for each email

### Body Extraction

The `_get_body_from_msg` method extracts the email body, prioritizing plain text over HTML:

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
                logger.warning(f"Error processing email part: {e}")
    else:
        try:
            plain_text_body = self._decode_payload(msg)
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
            # If we can't parse the HTML, return it as is
            return html_body.strip()

    return ""
```

This method:

- Handles both multipart and single-part messages
- Prioritizes plain text content over HTML
- Uses a dedicated method to decode payloads with proper character encoding
- Falls back to HTML content if plain text is not available
- Uses BeautifulSoup to extract text from HTML content
- Provides robust error handling for various content types

### Payload Decoding

The `_decode_payload` method handles the decoding of email part payloads:

```python
def _decode_payload(self, part) -> str:
    """
    Decode email part payload with proper character encoding handling.
    """
    try:
        payload = part.get_payload(decode=True)
        if not payload:
            return ""

        # Try to get charset from the part
        charset = part.get_content_charset() or "utf-8"

        # Common charsets to try if the specified one fails
        charsets = [charset, "utf-8", "latin-1", "iso-8859-1", "windows-1252"]

        for cs in charsets:
            try:
                return payload.decode(cs, errors="strict")
            except (UnicodeDecodeError, LookupError):
                continue

        # If all else fails, use replace to handle errors
        return payload.decode("utf-8", errors="replace")

    except Exception as e:
        logger.warning(f"Error decoding email part: {e}")
        return "[Error decoding content]"
```

This method:

- Gets the decoded payload using `get_payload(decode=True)`
- Attempts to determine the character encoding from the email part
- Tries multiple common character encodings if the specified one fails
- Falls back to UTF-8 with replacement for invalid characters
- Provides a meaningful error message if decoding fails completely

## Challenges and Solutions

### Challenge 1: Multipart Messages

**Problem**: Emails often contain multiple parts with different content types.

**Solution**: The `_get_body_from_msg` method walks through all parts of a multipart message:

```python
if msg.is_multipart():
    for part in msg.walk():
        try:
            content_type = part.get_content_type()
            payload = self._decode_payload(part)
            # Process based on content type...
        except Exception as e:
            logger.warning(f"Error processing email part: {e}")
```

### Challenge 2: Character Encoding

**Problem**: Email bodies can use various character encodings, leading to decoding errors.

**Solution**: The `_decode_payload` method tries multiple common encodings and falls back to replacement for invalid characters:

```python
charsets = [charset, "utf-8", "latin-1", "iso-8859-1", "windows-1252"]

for cs in charsets:
    try:
        return payload.decode(cs, errors="strict")
    except (UnicodeDecodeError, LookupError):
        continue

# If all else fails, use replace to handle errors
return payload.decode("utf-8", errors="replace")
```

### Challenge 3: HTML Content

**Problem**: Some emails only provide content in HTML format.

**Solution**: The system uses BeautifulSoup to extract readable text from HTML content:

```python
if html_body:
    try:
        soup = BeautifulSoup(html_body, "html.parser")
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        logger.warning(f"Error parsing HTML content: {e}")
        # If we can't parse the HTML, return it as is
        return html_body.strip()
```

## Performance Considerations

### Content Type Prioritization

The system prioritizes plain text over HTML for better performance:

- Plain text requires less processing
- HTML parsing with BeautifulSoup can be resource-intensive
- This approach ensures the most efficient processing path is taken when possible

### Memory Efficiency

The system is designed to be memory efficient by:

- Processing one email at a time
- Avoiding unnecessary data duplication
- Using streaming parsers where possible

## Error Handling

The body processing system includes robust error handling:

- Part-level error handling to prevent a single part failure from affecting the entire email
- Graceful fallbacks for decoding errors
- Detailed logging of processing errors
- Default values for missing or unparseable content

## Future Improvements

1. **Enhanced Content Extraction**
   - Add support for additional content types (e.g., PDF attachments)
   - Implement more sophisticated HTML parsing

2. **Performance Optimizations**
   - Use more efficient HTML parsing libraries
   - Implement caching for frequently accessed content

3. **Error Recovery**
   - Add retry logic for transient parsing failures
   - Implement more detailed error reporting

## Conclusion

The email body processing system is a critical component of the Fast Parse implementation that enables efficient extraction and decoding of email content. By handling various content types and character encodings while providing robust error handling, it contributes significantly to the overall reliability and effectiveness of the Fast Parse feature.
