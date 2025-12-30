#!/usr/bin/env python3
"""Helper script to batch update domain classifications.

This script reads a reviewed domain candidates JSON file (from analyze-domains command)
and adds the entries with categories to the domain_classifications.json database.
"""

import json
import sys
from pathlib import Path


def update_domain_db(candidates_file: Path, domain_db_file: Path) -> tuple[int, int]:
    """Update domain DB with reviewed candidates.

    Args:
        candidates_file: Path to reviewed candidates JSON
        domain_db_file: Path to domain_classifications.json

    Returns:
        Tuple of (added count, skipped count)
    """
    # Load candidates with manual categories added
    try:
        with open(candidates_file) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error loading candidates file: {e}")
        return 0, 0

    # Load existing domain DB
    try:
        with open(domain_db_file) as f:
            domain_db = json.load(f)
    except (OSError, json.JSONDecodeError):
        print("Warning: Could not load existing DB, creating new one")
        domain_db = {}

    # Add new entries
    added = 0
    skipped = 0

    for candidate in data.get("candidates", []):
        domain = candidate.get("domain", "").strip()
        category = candidate.get("suggested_category", "").strip()

        if not domain:
            skipped += 1
            continue

        # Skip if no category or placeholder
        if not category or category in ["REVIEW_NEEDED", ""]:
            skipped += 1
            continue

        # Add to DB (or update if exists)
        if domain in domain_db:
            print(f"Updated: {domain} → {category} (was: {domain_db[domain]})")
        else:
            print(f"Added: {domain} → {category}")
            added += 1

        domain_db[domain] = category

    # Save updated DB (sorted for readability)
    with open(domain_db_file, "w") as f:
        json.dump(dict(sorted(domain_db.items())), f, indent=2)

    return added, skipped


def main():
    """Main entry point."""
    # Default paths
    candidates_file = Path("data/domain_candidates.json")
    domain_db_file = Path("db/domain_classifications.json")

    # Override from command line if provided
    if len(sys.argv) > 1:
        candidates_file = Path(sys.argv[1])
    if len(sys.argv) > 2:
        domain_db_file = Path(sys.argv[2])

    print(f"Candidates file: {candidates_file}")
    print(f"Domain DB file: {domain_db_file}")
    print()

    if not candidates_file.exists():
        print(f"Error: Candidates file not found: {candidates_file}")
        print("Run: python src/main.py analyze-domains")
        sys.exit(1)

    # Update database
    added, skipped = update_domain_db(candidates_file, domain_db_file)

    print()
    print("=" * 60)
    print(f"Added {added} new domain classifications")
    print(f"Skipped {skipped} entries (no category assigned)")

    # Show updated stats
    with open(domain_db_file) as f:
        domain_db = json.load(f)
    print(f"Total domains in DB: {len(domain_db)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
