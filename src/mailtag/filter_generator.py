from collections import defaultdict
from pathlib import Path
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from loguru import logger

from .database import ClassificationDatabase
from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached


class FilterGenerator:
    """Generates a Gmail filter XML file from the classification database.

    Supports domain consolidation to reduce filter count by using wildcard
    patterns like *@domain.com for commercial domains with multiple senders.
    """

    def __init__(
        self,
        database: ClassificationDatabase,
        output_path: Path,
        consolidate_domains: bool = True,
        consolidation_threshold: int = 2,
    ):
        """Initialize the filter generator.

        Args:
            database: The classification database to generate filters from.
            output_path: Path to write the mailfilter.xml file.
            consolidate_domains: If True, consolidate multiple senders from same
                commercial domain into a single wildcard filter.
            consolidation_threshold: Minimum number of senders from a domain
                before consolidating (default: 2).
        """
        self.database = database
        self.output_path = output_path
        self.consolidate_domains = consolidate_domains
        self.consolidation_threshold = consolidation_threshold
        register_namespace("apps", "http://schemas.google.com/apps/2006")

    def _collect_sender_categories(self) -> list[tuple[str, str]]:
        """Collect all unique senders and their dominant categories.

        Returns:
            List of (category, sender) tuples.
        """
        all_senders = set(self.database.suggestion_db.keys()).union(self.database.validated_db.keys())

        sender_categories = []
        for sender in all_senders:
            most_common_category = self.database.get_dominant_classification(sender)
            if most_common_category:
                sender_categories.append((most_common_category, sender))

        return sender_categories

    def _consolidate_by_domain(self, sender_categories: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Consolidate senders by domain where appropriate.

        Groups senders by (domain, category) and replaces groups with wildcard
        patterns for commercial domains that meet the threshold.

        Args:
            sender_categories: List of (category, sender) tuples.

        Returns:
            Consolidated list of (category, filter_value) tuples.
        """
        # Group by (domain, category)
        domain_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        individual_entries: list[tuple[str, str]] = []

        for category, sender in sender_categories:
            domain = extract_domain(sender)

            if not domain:
                # No domain extracted, keep as individual entry
                individual_entries.append((category, sender))
                continue

            if is_non_commercial_domain_cached(domain):
                # Non-commercial domains (gmail, hotmail, etc.) should not be
                # consolidated as they represent different individuals
                individual_entries.append((category, sender))
                continue

            domain_groups[(domain, category)].append(sender)

        # Process domain groups
        consolidated_entries: list[tuple[str, str]] = []
        consolidated_count = 0
        original_count = 0

        for (domain, category), senders in domain_groups.items():
            original_count += len(senders)

            if len(senders) >= self.consolidation_threshold:
                # Consolidate to wildcard pattern
                wildcard = f"*@{domain}"
                consolidated_entries.append((category, wildcard))
                consolidated_count += 1
                logger.debug(
                    f"Consolidated {len(senders)} senders from @{domain} "
                    f"into wildcard filter for '{category}'"
                )
            else:
                # Keep individual entries
                for sender in senders:
                    consolidated_entries.append((category, sender))

        # Combine all entries
        all_entries = individual_entries + consolidated_entries

        # Log consolidation stats
        individual_count = len(individual_entries)
        final_count = len(all_entries)
        if consolidated_count > 0:
            logger.info(
                f"Domain consolidation: {original_count + individual_count} -> "
                f"{final_count} filters ({consolidated_count} wildcard patterns created)"
            )

        return all_entries

    def _create_filter_entry(self, feed: Element, category: str, filter_value: str) -> None:
        """Create a single filter entry in the XML feed.

        Args:
            feed: The XML feed element to add the entry to.
            category: The label/category for the filter.
            filter_value: The from value (email or wildcard pattern).
        """
        entry = SubElement(feed, "entry")
        SubElement(entry, "category", term="filter")
        title = SubElement(entry, "title")
        title.text = f"MailTag - {category}"

        SubElement(
            entry,
            "{http://schemas.google.com/apps/2006}property",
            name="from",
            value=filter_value,
        )
        SubElement(
            entry,
            "{http://schemas.google.com/apps/2006}property",
            name="label",
            value=category,
        )
        SubElement(
            entry,
            "{http://schemas.google.com/apps/2006}property",
            name="shouldArchive",
            value="true",
        )
        SubElement(
            entry,
            "{http://schemas.google.com/apps/2006}property",
            name="shouldNeverSpam",
            value="true",
        )

    def generate_filters(self) -> int:
        """Generates the mailfilter.xml file.

        Returns:
            Number of filter entries generated.
        """
        feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")

        # Collect sender categories
        sender_categories = self._collect_sender_categories()
        original_count = len(sender_categories)

        # Apply domain consolidation if enabled
        if self.consolidate_domains:
            filter_entries = self._consolidate_by_domain(sender_categories)
        else:
            filter_entries = sender_categories

        # Sort by category (label) for consistent output
        filter_entries.sort(key=lambda x: x[0])

        # Create XML entries
        for category, filter_value in filter_entries:
            self._create_filter_entry(feed, category, filter_value)

        # Pretty print the XML
        xml_str = tostring(feed, "utf-8")
        pretty_xml_str = minidom.parseString(xml_str).toprettyxml(indent="    ")  # nosec B318

        with self.output_path.open("w", encoding="utf-8") as f:
            f.write(pretty_xml_str)

        final_count = len(filter_entries)
        logger.info(
            f"Generated {final_count} Gmail filters "
            f"(from {original_count} sender entries) -> {self.output_path}"
        )

        return final_count
