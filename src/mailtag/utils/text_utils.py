"""Text extraction and processing utilities for email classification.

This module provides intelligent text processing functions for email bodies,
including smart truncation, signature removal, and content extraction.
"""

import re
from typing import Tuple


def smart_truncate(body: str, max_chars: int = 1500) -> str:
    """Intelligently truncate email body to preserve important content.

    Strategy:
    1. Remove quoted replies (lines starting with >)
    2. Remove email signatures and disclaimers
    3. Extract first 2-3 paragraphs (likely main message)
    4. Find sentences with high-signal keywords
    5. Combine and truncate to max_chars

    Args:
        body: Email body text
        max_chars: Maximum characters to return

    Returns:
        Truncated email body with important content preserved
    """
    if not body:
        return ""

    if len(body) <= max_chars:
        return body

    # Remove quoted replies (lines starting with >)
    lines = [line for line in body.split("\n") if not line.strip().startswith(">")]
    clean_body = "\n".join(lines)

    # Remove common email signatures
    clean_body = _remove_signatures(clean_body)

    # Extract paragraphs
    paragraphs = [p.strip() for p in clean_body.split("\n\n") if p.strip()]

    # High-signal keywords that indicate important content
    keywords = [
        # Financial
        "invoice",
        "facture",
        "payment",
        "paiement",
        "bill",
        "billing",
        "order",
        "commande",
        "delivery",
        "livraison",
        "receipt",
        "reçu",
        # Account/Security
        "account",
        "compte",
        "password",
        "mot de passe",
        "security",
        "sécurité",
        "alert",
        "alerte",
        "verify",
        "vérifier",
        # Subscription/Renewal
        "subscription",
        "abonnement",
        "renewal",
        "renouvellement",
        "confirm",
        "confirmer",
        "confirmation",
        # Communication
        "meeting",
        "réunion",
        "appointment",
        "rendez-vous",
        "reminder",
        "rappel",
        # Marketing
        "unsubscribe",
        "désabonner",
        "offer",
        "offre",
        "promotion",
    ]

    # Collect important sentences
    important_sentences = []
    for para in paragraphs[:3]:  # First 3 paragraphs
        sentences = re.split(r"[.!?]\s+", para)
        for sentence in sentences:
            if any(kw in sentence.lower() for kw in keywords):
                important_sentences.append(sentence.strip())

    # Build result: first paragraphs + important sentences
    result_parts = paragraphs[:2]  # First 2 paragraphs
    if important_sentences:
        # Add unique important sentences (avoid duplicates)
        unique_important = []
        for sent in important_sentences[:3]:
            if not any(sent in part for part in result_parts):
                unique_important.append(sent)
        if unique_important:
            result_parts.append(" ".join(unique_important))

    result = "\n\n".join(result_parts)

    # Final truncation
    if len(result) > max_chars:
        result = result[:max_chars] + "..."

    return result


def _remove_signatures(body: str) -> str:
    """Remove common email signatures and disclaimers.

    Args:
        body: Email body text

    Returns:
        Email body with signatures removed
    """
    # Signature patterns to remove
    signature_patterns = [
        r"\n--\s*\n.*",  # Standard signature delimiter
        r"\nSent from my .*",
        r"\nGet Outlook for .*",
        r"\n_{10,}.*",  # Underline separators
        r"\n={10,}.*",  # Equal sign separators
        r"\nBest regards,.*",
        r"\nCordialement,.*",
        r"\nRegards,.*",
        r"\nSincerely,.*",
        r"\nThank you,.*",
        r"\nMerci,.*",
    ]

    result = body
    for pattern in signature_patterns:
        result = re.sub(pattern, "", result, flags=re.DOTALL | re.IGNORECASE)

    return result


def extract_urls(body: str) -> list[str]:
    """Extract all URLs from email body.

    Args:
        body: Email body text

    Returns:
        List of URLs found in the email
    """
    url_pattern = r'https?://[^\s<>"\']+'
    return re.findall(url_pattern, body)


def count_links(body: str) -> int:
    """Count number of links in email.

    Args:
        body: Email body text

    Returns:
        Number of URLs found
    """
    return len(extract_urls(body))


def has_unsubscribe_link(body: str) -> bool:
    """Check if email contains unsubscribe link (newsletter indicator).

    Args:
        body: Email body text

    Returns:
        True if unsubscribe link found
    """
    return bool(re.search(r"unsubscribe|désabonner|se désinscrire|opt.out", body, re.IGNORECASE))


def extract_first_n_words(text: str, n: int = 100) -> str:
    """Extract first N words from text.

    Args:
        text: Input text
        n: Number of words to extract

    Returns:
        First N words
    """
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "..."


def clean_whitespace(text: str) -> str:
    """Clean excessive whitespace from text.

    Args:
        text: Input text

    Returns:
        Text with normalized whitespace
    """
    # Replace multiple spaces with single space
    text = re.sub(r" +", " ", text)
    # Replace multiple newlines with double newline (paragraph separator)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing/leading whitespace
    return text.strip()


def extract_subject_keywords(subject: str, max_keywords: int = 5) -> list[str]:
    """Extract important keywords from email subject.

    Args:
        subject: Email subject line
        max_keywords: Maximum keywords to return

    Returns:
        List of important keywords
    """
    # Common stop words to filter out
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "will",
        "with",
        "you",
        "your",
        # French
        "le",
        "la",
        "les",
        "un",
        "une",
        "de",
        "du",
        "des",
        "et",
        "ou",
        "dans",
        "pour",
        "par",
        "sur",
        "avec",
        "est",
        "sont",
        "être",
    }

    # Extract words (alphanumeric sequences)
    words = re.findall(r"\b\w+\b", subject.lower())

    # Filter stop words and short words
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    return keywords[:max_keywords]


def is_likely_automated(body: str, subject: str) -> bool:
    """Detect if email is likely automated (newsletter, notification, etc.).

    Args:
        body: Email body text
        subject: Email subject line

    Returns:
        True if email appears to be automated
    """
    # Check for automated indicators
    indicators = [
        has_unsubscribe_link(body),
        count_links(body) > 5,  # Many links
        re.search(r"this is an automated", body, re.IGNORECASE) is not None,
        re.search(r"do not reply", body, re.IGNORECASE) is not None,
        re.search(r"ne pas répondre", body, re.IGNORECASE) is not None,
        "noreply" in subject.lower(),
        "no-reply" in subject.lower(),
    ]

    # If 2+ indicators, likely automated
    return sum(indicators) >= 2
