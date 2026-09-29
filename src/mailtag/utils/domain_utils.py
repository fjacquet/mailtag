"""Domain utilities for email classification."""

from pathlib import Path

import yaml
from loguru import logger


def extract_domain(email_address: str) -> str:
    """Extract domain from email address.

    Args:
        email_address: Email address like 'user@example.com'

    Returns:
        Domain part like 'example.com'

    Examples:
        >>> extract_domain('service@ifolor.ch')
        'ifolor.ch'
        >>> extract_domain('noreply@todoist.com')
        'todoist.com'
    """
    if not email_address or "@" not in email_address:
        return ""

    # Extract domain part after @
    domain = email_address.split("@")[-1].strip()
    return normalize_domain(domain)


def normalize_domain(domain: str) -> str:
    """Normalize domain to lowercase and strip whitespace.

    Args:
        domain: Domain like 'EXAMPLE.COM' or ' example.com '

    Returns:
        Normalized domain like 'example.com'
    """
    if not domain:
        return ""

    return domain.lower().strip()


def load_non_commercial_domains() -> set[str]:
    """Load non-commercial domains from YAML configuration.

    Returns:
        Set of non-commercial domain names
    """
    config_path = Path(__file__).parent.parent.parent.parent / "data" / "non_commercial_domains.yaml"

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        domains = config.get("non_commercial_domains", [])
        normalized_domains = {normalize_domain(domain) for domain in domains}

        logger.debug(f"Loaded {len(normalized_domains)} non-commercial domains")
        return normalized_domains

    except FileNotFoundError:
        logger.warning(f"Non-commercial domains file not found: {config_path}")
        return set()
    except (OSError, PermissionError) as e:
        logger.error(f"Error loading non-commercial domains: {e}")
        return set()


# Cache for non-commercial domains to avoid repeated file reads
_non_commercial_cache: set[str] = set()
_cache_loaded = False


def _get_cached_non_commercial_domains() -> set[str]:
    """Get cached non-commercial domains, loading if necessary."""
    global _non_commercial_cache, _cache_loaded

    if not _cache_loaded:
        _non_commercial_cache = load_non_commercial_domains()
        _cache_loaded = True

    return _non_commercial_cache


def is_non_commercial_domain_cached(domain: str) -> bool:
    """Check if domain is non-commercial using cached data.

    Args:
        domain: Domain to check

    Returns:
        True if domain is a personal email provider
    """
    if not domain:
        return False

    normalized = normalize_domain(domain)
    non_commercial = _get_cached_non_commercial_domains()

    return normalized in non_commercial
