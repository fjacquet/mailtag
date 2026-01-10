"""Shared email parsing utilities for IMAP and Gmail providers.

This module contains common functionality for parsing email headers, bodies,
and handling various encoding formats across different email providers.
"""

import email.header
import email.message
import re
from email.utils import parseaddr

from bs4 import BeautifulSoup
from loguru import logger


def parse_sender(sender_raw) -> tuple[str, str]:
    """Parse sender into (name, address) tuple.

    Handles multiple input formats:
    - email.header.Header objects
    - Bytes with various encodings
    - Plain strings
    - RFC 2047 encoded headers
    - Format: "Sender Name <sender@example.com>"

    Args:
        sender_raw: Raw sender data (Header, bytes, or str)

    Returns:
        Tuple of (name, address) where address is lowercase normalized.
        Returns ("", "") if parsing fails.

    Examples:
        >>> parse_sender("John Doe <john@example.com>")
        ('John Doe', 'john@example.com')
        >>> parse_sender(b"sender@example.com")
        ('', 'sender@example.com')
    """
    # Handle None case
    if sender_raw is None:
        return "", ""

    # Handle email.header.Header objects
    if hasattr(email.header, "Header") and isinstance(sender_raw, email.header.Header):
        sender_raw = str(sender_raw)
    # Handle bytes objects with encoding detection
    elif isinstance(sender_raw, bytes):
        try:
            sender_raw = sender_raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                sender_raw = sender_raw.decode("latin-1")
            except (UnicodeDecodeError, AttributeError):
                logger.warning("Failed to decode sender bytes")
                return "", ""
    # Ensure we have a string
    elif not isinstance(sender_raw, str):
        try:
            sender_raw = str(sender_raw)
        except (ValueError, TypeError, AttributeError):
            logger.warning(f"Failed to convert sender to string: {type(sender_raw)}")
            return "", ""

    # Empty string check
    if not sender_raw or not sender_raw.strip():
        return "", ""

    # Use email.utils.parseaddr for robust parsing
    # This handles RFC 2822 format: "Name" <address> or just address
    name, address = parseaddr(sender_raw)

    # If parseaddr didn't extract an address, try regex as fallback
    if not address and sender_raw:
        match = re.match(r"(.+?)\s*<(.+?)>", sender_raw)
        if match:
            name, address = match.groups()
        else:
            # Assume the whole string is the address
            address = sender_raw

    return name.strip(), address.lower().strip() if address else ""


def decode_payload(payload: bytes, charset: str | None) -> str:
    """Decode email payload with fallback encodings.

    Tries multiple character encodings in order of likelihood to successfully
    decode the payload. This handles emails with incorrect or missing charset
    information.

    Args:
        payload: Raw email payload bytes
        charset: Declared charset from email headers (may be None or incorrect)

    Returns:
        Decoded string content. Uses error replacement as last resort.

    Examples:
        >>> decode_payload(b"Hello", "utf-8")
        'Hello'
        >>> decode_payload(b"\\xff\\xfe", None)  # Invalid UTF-8
        'ÿþ'  # Falls back to latin-1
    """
    if not payload:
        return ""

    # Build list of charsets to try, with declared charset first
    encodings = []
    if charset:
        encodings.append(charset)
    # Common fallback encodings
    encodings.extend(["utf-8", "latin-1", "iso-8859-1", "windows-1252"])

    # Remove duplicates while preserving order
    seen = set()
    encodings = [x for x in encodings if not (x in seen or seen.add(x))]

    # Try each encoding
    for encoding in encodings:
        if not encoding:
            continue
        try:
            return payload.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort: decode with error replacement
    logger.warning("All encodings failed, using UTF-8 with error replacement")
    return payload.decode("utf-8", errors="replace")


def extract_body_from_message(msg: email.message.Message) -> str:
    """Extract plain text body from email.Message object.

    Prioritizes text/plain content over text/html. For HTML-only emails,
    converts HTML to plain text using BeautifulSoup.

    Args:
        msg: email.message.Message object (from IMAP or email.parser)

    Returns:
        Plain text email body, or empty string if no readable content found.

    Examples:
        >>> import email
        >>> msg = email.message_from_string("Content-Type: text/plain\\n\\nHello")
        >>> extract_body_from_message(msg)
        'Hello'
    """
    plain_text_body = ""
    html_body = ""

    if msg.is_multipart():
        # Walk through all parts to find text content
        for part in msg.walk():
            try:
                content_type = part.get_content_type()

                # Skip container types
                if content_type in ("multipart/alternative", "multipart/mixed", "multipart/related"):
                    continue

                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                charset = part.get_content_charset()
                decoded = decode_payload(payload, charset)

                if content_type == "text/plain" and not plain_text_body:
                    plain_text_body = decoded
                elif content_type == "text/html" and not html_body:
                    html_body = decoded

            except (UnicodeDecodeError, LookupError, ValueError, AttributeError, KeyError) as e:
                logger.warning(f"Error processing email part ({content_type}): {e}")
                continue
    else:
        # Single-part message
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset()
                plain_text_body = decode_payload(payload, charset)
        except (UnicodeDecodeError, LookupError, ValueError, AttributeError, KeyError) as e:
            logger.warning(f"Error processing single-part email: {e}")

    # Return plain text if available
    if plain_text_body.strip():
        return plain_text_body.strip()

    # Fall back to HTML, converting to text
    if html_body:
        try:
            soup = BeautifulSoup(html_body, "html.parser")
            return soup.get_text(separator="\n", strip=True)
        except (ValueError, AttributeError, TypeError) as e:
            logger.warning(f"Error parsing HTML content: {e}")
            # Return raw HTML as last resort
            return html_body.strip()

    return ""
