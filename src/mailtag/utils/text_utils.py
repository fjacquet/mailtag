"""Text extraction and processing utilities for email classification.

This module provides intelligent text processing functions for email bodies,
including smart truncation, signature removal, and content extraction.
"""

import re


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
