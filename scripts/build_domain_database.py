#!/usr/bin/env python3
"""Build initial domain classification database from existing sender classifications."""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Add src to path to import mailtag modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mailtag.utils.domain_utils import extract_domain, is_non_commercial_domain_cached


def analyze_existing_classifications(db_path: Path) -> dict[str, Counter]:
    """Analyze existing sender classifications to extract domain patterns.

    Args:
        db_path: Path to sender classification database

    Returns:
        Dictionary mapping domains to category counters
    """
    if not db_path.exists():
        logger.warning(f"Database file not found: {db_path}")
        return {}

    try:
        with open(db_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading database: {e}")
        return {}

    domain_categories = defaultdict(Counter)

    for sender_email, categories in data.items():
        domain = extract_domain(sender_email)
        if not domain:
            continue

        # Skip non-commercial domains (gmail.com, yahoo.com, etc.)
        if is_non_commercial_domain_cached(domain):
            logger.debug(f"Skipping non-commercial domain: {domain}")
            continue

        # Handle both dict and simple category formats
        if isinstance(categories, dict):
            for category, count in categories.items():
                domain_categories[domain][category] += count
        else:
            # Assume it's a single category string
            domain_categories[domain][categories] += 1

    return domain_categories


def build_domain_mappings(
    domain_categories: dict[str, Counter], min_confidence: float = 0.8
) -> dict[str, str]:
    """Build domain -> category mappings from analyzed data.

    Args:
        domain_categories: Domain to category counter mapping
        min_confidence: Minimum confidence threshold (0.0 to 1.0)

    Returns:
        Dictionary of domain -> category mappings
    """
    domain_mappings = {}

    for domain, category_counts in domain_categories.items():
        if not category_counts:
            continue

        total_count = sum(category_counts.values())
        most_common_category, most_common_count = category_counts.most_common(1)[0]

        confidence = most_common_count / total_count

        if confidence >= min_confidence:
            domain_mappings[domain] = most_common_category
            logger.info(f"Domain mapping: {domain} -> {most_common_category} (confidence: {confidence:.2f})")
        else:
            logger.debug(f"Skipping {domain} due to low confidence: {confidence:.2f}")

    return domain_mappings


def save_domain_database(domain_mappings: dict[str, str], output_path: Path):
    """Save domain mappings to JSON file.

    Args:
        domain_mappings: Domain to category mappings
        output_path: Output file path
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(domain_mappings, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(domain_mappings)} domain mappings to {output_path}")


def print_statistics(domain_categories: dict[str, Counter], domain_mappings: dict[str, str]):
    """Print analysis statistics.

    Args:
        domain_categories: Domain to category counter mapping
        domain_mappings: Final domain mappings
    """
    total_domains = len(domain_categories)
    mapped_domains = len(domain_mappings)

    print("\n=== Domain Analysis Statistics ===")
    print(f"Total domains analyzed: {total_domains}")
    print(f"Domains with high-confidence mappings: {mapped_domains}")
    print(f"Coverage: {mapped_domains / total_domains * 100:.1f}%" if total_domains > 0 else "Coverage: 0%")

    if mapped_domains > 0:
        print("\n=== Top 10 Domain Mappings ===")
        for i, (domain, category) in enumerate(list(domain_mappings.items())[:10], 1):
            print(f"{i:2d}. {domain:25} -> {category}")

    # Show domains with conflicts (low confidence)
    conflicted_domains = []
    for domain, category_counts in domain_categories.items():
        if domain not in domain_mappings and len(category_counts) > 1:
            total = sum(category_counts.values())
            top_category, top_count = category_counts.most_common(1)[0]
            confidence = top_count / total
            conflicted_domains.append((domain, confidence, category_counts))

    if conflicted_domains:
        print("\n=== Domains with Classification Conflicts ===")
        conflicted_domains.sort(key=lambda x: x[1], reverse=True)
        for domain, confidence, counts in conflicted_domains[:5]:
            print(f"{domain:25} (confidence: {confidence:.2f}) -> {dict(counts)}")


def main():
    """Main function to build domain database."""
    project_root = Path(__file__).parent.parent

    # Input databases
    suggestion_db_path = project_root / "db" / "sender_classification_db.json"
    validated_db_path = project_root / "db" / "validated_sender_db.json"

    # Output database
    domain_db_path = project_root / "db" / "domain_classifications.json"

    logger.info("Building domain classification database...")

    # Analyze both suggestion and validated databases
    all_domain_categories = defaultdict(Counter)

    for db_path in [suggestion_db_path, validated_db_path]:
        if db_path.exists():
            logger.info(f"Analyzing {db_path}")
            domain_categories = analyze_existing_classifications(db_path)

            # Merge results
            for domain, category_counts in domain_categories.items():
                for category, count in category_counts.items():
                    all_domain_categories[domain][category] += count

    if not all_domain_categories:
        logger.warning("No domain classifications found. Creating empty domain database.")
        save_domain_database({}, domain_db_path)
        return

    # Build domain mappings with high confidence threshold
    domain_mappings = build_domain_mappings(all_domain_categories, min_confidence=0.8)

    # Save to database
    save_domain_database(domain_mappings, domain_db_path)

    # Print statistics
    print_statistics(all_domain_categories, domain_mappings)

    logger.success(f"Domain database built successfully: {domain_db_path}")


if __name__ == "__main__":
    main()
