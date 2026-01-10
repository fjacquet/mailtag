"""Utilities for data validation and normalization."""

import json
import re
from email.header import decode_header
from pathlib import Path

from loguru import logger


def normalize_email(email: str) -> str:
    """
    Normalize an email address.

    - Strip angle brackets
    - Decode RFC 2047 encoded headers
    - Convert to lowercase
    - Strip whitespace

    Args:
        email: Raw email address string

    Returns:
        Normalized email address
    """
    if not email:
        return ""

    email = email.strip()

    # Extract email from "Name <email>" format first
    match = re.search(r"<([^>]+)>", email)
    if match:
        email = match.group(1)
    else:
        # Strip angle brackets if present at start/end
        email = re.sub(r"^<|>$", "", email)

    # Handle RFC 2047 encoded headers (e.g., =?utf-8?b?...?=)
    if "=?" in email and "?=" in email:
        try:
            decoded_parts = decode_header(email)
            decoded_email = ""
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    decoded_email += part.decode(charset or "utf-8", errors="replace")
                else:
                    decoded_email += part
            email = decoded_email
        except (UnicodeDecodeError, LookupError, ValueError, AttributeError) as e:
            logger.debug(f"Failed to decode RFC 2047 email header: {e}")

    return email.lower().strip()


def normalize_domain(domain: str) -> str:
    """
    Normalize a domain name.

    - Strip trailing characters (>, whitespace)
    - Convert to lowercase
    - Validate basic format

    Args:
        domain: Raw domain string

    Returns:
        Normalized domain
    """
    if not domain:
        return ""

    # Strip common artifacts
    domain = re.sub(r"[>\s]+$", "", domain.strip())
    domain = re.sub(r"^[<\s]+", "", domain)

    return domain.lower().strip()


def validate_domain_format(domain: str) -> bool:
    """
    Check if a domain has valid format.

    Args:
        domain: Domain string to validate

    Returns:
        True if valid format
    """
    if not domain:
        return False

    # Basic domain pattern
    pattern = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
    return bool(re.match(pattern, domain.lower()))


def validate_domain_classifications(db_path: Path) -> list[str]:
    """
    Check domain_classifications.json for issues.

    Args:
        db_path: Path to domain_classifications.json

    Returns:
        List of issue descriptions
    """
    issues = []

    if not db_path.exists():
        issues.append(f"File not found: {db_path}")
        return issues

    try:
        with open(db_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        issues.append(f"Invalid JSON: {e}")
        return issues

    for domain, category in data.items():
        # Check for malformed domains
        if domain != normalize_domain(domain):
            issues.append(f"Malformed domain: '{domain}' should be '{normalize_domain(domain)}'")

        # Check for invalid format
        normalized = normalize_domain(domain)
        if normalized and not validate_domain_format(normalized):
            issues.append(f"Invalid domain format: '{domain}'")

        # Check for empty category
        if not category or not category.strip():
            issues.append(f"Empty category for domain: '{domain}'")

    return issues


def validate_sender_classifications(db_path: Path) -> list[str]:
    """
    Check sender_classification_db.json for issues.

    Args:
        db_path: Path to sender_classification_db.json

    Returns:
        List of issue descriptions
    """
    issues = []

    if not db_path.exists():
        issues.append(f"File not found: {db_path}")
        return issues

    try:
        with open(db_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        issues.append(f"Invalid JSON: {e}")
        return issues

    for sender, categories in data.items():
        # Check for malformed sender addresses
        normalized = normalize_email(sender)
        if sender != normalized:
            issues.append(f"Sender needs normalization: '{sender}' -> '{normalized}'")

        # Check for invalid category data
        if not isinstance(categories, dict):
            issues.append(f"Invalid categories for sender '{sender}': expected dict")
            continue

        for category, count in categories.items():
            if not isinstance(count, int) or count < 1:
                issues.append(f"Invalid count for '{sender}' -> '{category}': {count}")

    return issues


def fix_domain_classifications(db_path: Path) -> int:
    """
    Fix issues in domain_classifications.json.

    Args:
        db_path: Path to domain_classifications.json

    Returns:
        Number of entries fixed
    """
    if not db_path.exists():
        return 0

    with open(db_path) as f:
        data = json.load(f)

    fixed_count = 0
    fixed_data = {}

    for domain, category in data.items():
        normalized = normalize_domain(domain)
        if normalized != domain:
            logger.info(f"Fixed domain: '{domain}' -> '{normalized}'")
            fixed_count += 1

        # Skip if normalized domain already exists (dedup)
        if normalized in fixed_data:
            logger.warning(f"Duplicate domain after normalization: '{domain}' -> '{normalized}'")
            continue

        fixed_data[normalized] = category

    if fixed_count > 0:
        with open(db_path, "w") as f:
            json.dump(fixed_data, f, indent=2)
        logger.info(f"Fixed {fixed_count} domain entries")

    return fixed_count


def prune_low_confidence_senders(db_path: Path, min_count: int = 3) -> int:
    """
    Remove sender entries with occurrence count below threshold.

    Args:
        db_path: Path to sender_classification_db.json
        min_count: Minimum total occurrences to keep

    Returns:
        Number of entries removed
    """
    if not db_path.exists():
        return 0

    with open(db_path) as f:
        data = json.load(f)

    original_count = len(data)
    pruned_data = {}

    for sender, categories in data.items():
        total_count = sum(categories.values())
        if total_count >= min_count:
            pruned_data[sender] = categories
        else:
            logger.debug(f"Pruned sender '{sender}' with count {total_count}")

    pruned_count = original_count - len(pruned_data)

    if pruned_count > 0:
        with open(db_path, "w") as f:
            json.dump(pruned_data, f, indent=2)
        logger.info(f"Pruned {pruned_count} low-confidence sender entries (threshold: {min_count})")

    return pruned_count


def get_database_stats(db_dir: Path) -> dict:
    """
    Get statistics about all databases.

    Args:
        db_dir: Path to the database directory

    Returns:
        Dictionary with database statistics
    """
    stats = {}

    # Sender classification DB
    sender_db_path = db_dir / "sender_classification_db.json"
    if sender_db_path.exists():
        with open(sender_db_path) as f:
            data = json.load(f)

        total_occurrences = sum(sum(cats.values()) for cats in data.values())
        high_confidence = sum(1 for cats in data.values() if sum(cats.values()) >= 10)

        stats["sender_db"] = {
            "entries": len(data),
            "total_occurrences": total_occurrences,
            "high_confidence_entries": high_confidence,
            "size_bytes": sender_db_path.stat().st_size,
        }

    # Domain classification DB
    domain_db_path = db_dir / "domain_classifications.json"
    if domain_db_path.exists():
        with open(domain_db_path) as f:
            data = json.load(f)

        unique_categories = set(data.values())

        stats["domain_db"] = {
            "entries": len(data),
            "unique_categories": len(unique_categories),
            "size_bytes": domain_db_path.stat().st_size,
        }

    # Validated classification DB
    validated_db_path = db_dir / "validated_classification_db.json"
    if validated_db_path.exists():
        with open(validated_db_path) as f:
            data = json.load(f)

        stats["validated_db"] = {
            "entries": len(data),
            "size_bytes": validated_db_path.stat().st_size,
        }

    return stats
