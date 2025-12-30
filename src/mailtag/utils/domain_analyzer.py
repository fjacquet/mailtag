"""Domain analysis utilities for identifying classification candidates.

This module analyzes Pass 3 manual matching files and email data to identify
commercial domains that could be added to the domain classification database.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger


@dataclass
class DomainCandidate:
    """Candidate domain for classification."""

    domain: str
    email_count: int
    unique_senders: set[str]
    sample_senders: list[str]
    suggested_category: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "domain": self.domain,
            "email_count": self.email_count,
            "unique_senders": len(self.unique_senders),
            "sample_senders": self.sample_senders,
            "suggested_category": self.suggested_category or "REVIEW_NEEDED",
            "confidence": self.confidence,
        }


class DomainAnalyzer:
    """Analyze email data to find domain classification opportunities."""

    def __init__(self, non_commercial_domains_path: Path):
        """Initialize with non-commercial domains to exclude.

        Args:
            non_commercial_domains_path: Path to YAML file with non-commercial domains
        """
        with open(non_commercial_domains_path) as f:
            self.non_commercial = set(yaml.safe_load(f))
        logger.debug(f"Loaded {len(self.non_commercial)} non-commercial domains")

    def analyze_pass3_files(self, data_dir: Path, min_email_count: int = 5) -> list[DomainCandidate]:
        """Analyze all Pass 3 manual matching files.

        Args:
            data_dir: Directory containing pass3_manual_matching_*.json files
            min_email_count: Minimum emails required from domain to be a candidate

        Returns:
            List of DomainCandidate objects sorted by email count
        """
        # Aggregate data from all Pass 3 files
        domain_data = defaultdict(lambda: {"count": 0, "senders": set(), "sender_list": []})

        pass3_files = list(data_dir.glob("pass3_manual_matching_*.json"))
        logger.info(f"Found {len(pass3_files)} Pass 3 files to analyze")

        for filepath in pass3_files:
            logger.debug(f"Processing {filepath.name}")

            try:
                with open(filepath) as f:
                    data = json.load(f)

                for sender, count in data.items():
                    # Extract domain
                    domain = self._extract_domain(sender)
                    if not domain:
                        continue

                    # Skip non-commercial domains
                    if domain in self.non_commercial:
                        logger.trace(f"Skipping non-commercial domain: {domain}")
                        continue

                    domain_data[domain]["count"] += count
                    domain_data[domain]["senders"].add(sender)
                    if sender not in domain_data[domain]["sender_list"]:
                        domain_data[domain]["sender_list"].append(sender)

            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Failed to process {filepath}: {e}")
                continue

        # Convert to candidates
        candidates = []
        for domain, data in domain_data.items():
            if data["count"] >= min_email_count:
                candidate = DomainCandidate(
                    domain=domain,
                    email_count=data["count"],
                    unique_senders=data["senders"],
                    sample_senders=data["sender_list"][:5],  # First 5 senders
                )
                candidates.append(candidate)

        # Sort by email count (descending)
        candidates.sort(key=lambda c: c.email_count, reverse=True)

        logger.info(f"Found {len(candidates)} domain candidates (min {min_email_count} emails)")
        logger.info(f"Total emails in candidates: {sum(c.email_count for c in candidates)}")

        return candidates

    def _extract_domain(self, email: str) -> str | None:
        """Extract domain from email address.

        Args:
            email: Email address

        Returns:
            Domain (lowercase) or None if invalid
        """
        match = re.search(r"@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})$", email.lower())
        return match.group(1) if match else None

    def export_candidates(self, candidates: list[DomainCandidate], output_path: Path) -> None:
        """Export candidates to JSON for manual review.

        Args:
            candidates: List of domain candidates
            output_path: Path to output JSON file
        """
        export_data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_candidates": len(candidates),
                "total_emails": sum(c.email_count for c in candidates),
            },
            "candidates": [c.to_dict() for c in candidates],
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Exported {len(candidates)} candidates to {output_path}")

    def generate_report(self, candidates: list[DomainCandidate], top_n: int = 50) -> str:
        """Generate human-readable report.

        Args:
            candidates: List of domain candidates
            top_n: Number of top candidates to show

        Returns:
            Formatted report string
        """
        lines = [
            "=" * 80,
            "DOMAIN CLASSIFICATION CANDIDATES",
            "=" * 80,
            f"Total candidates: {len(candidates)}",
            f"Total emails: {sum(c.email_count for c in candidates)}",
            "",
            f"Top {top_n} Domains by Email Count:",
            "-" * 80,
            f"{'Domain':<35} {'Emails':>8} {'Senders':>8} Sample",
            "-" * 80,
        ]

        for candidate in candidates[:top_n]:
            sample = candidate.sample_senders[0] if candidate.sample_senders else ""
            lines.append(
                f"{candidate.domain:<35} {candidate.email_count:>8} "
                f"{len(candidate.unique_senders):>8} {sample}"
            )

        lines.extend(
            [
                "-" * 80,
                "",
                "Next Steps:",
                f"1. Review {len(candidates)} candidates in the exported JSON file",
                "2. For each domain, determine appropriate category",
                "3. Add to db/domain_classifications.json using update_domain_db.py",
                "4. Re-run classification to measure impact",
                "",
            ]
        )

        return "\n".join(lines)

    def analyze_existing_domains(self, domain_db_path: Path) -> dict:
        """Analyze existing domain classifications database.

        Args:
            domain_db_path: Path to domain_classifications.json

        Returns:
            Dictionary with analysis statistics
        """
        try:
            with open(domain_db_path) as f:
                domain_db = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load domain DB: {e}")
            return {}

        # Analyze categories
        category_distribution = defaultdict(int)
        for _domain, category in domain_db.items():
            category_distribution[category] += 1

        # Find parent categories
        parent_categories = set()
        for category in domain_db.values():
            if "/" in category:
                parent = category.split("/")[0]
                parent_categories.add(parent)

        stats = {
            "total_domains": len(domain_db),
            "total_categories": len(set(domain_db.values())),
            "parent_categories": sorted(parent_categories),
            "top_categories": dict(
                sorted(category_distribution.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "domains": sorted(domain_db.keys()),
        }

        return stats
