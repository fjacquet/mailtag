from pathlib import Path
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from .database import ClassificationDatabase


class FilterGenerator:
    """Generates a Gmail filter XML file from the classification database."""

    def __init__(self, database: ClassificationDatabase, output_path: Path):
        self.database = database
        self.output_path = output_path
        register_namespace("apps", "http://schemas.google.com/apps/2006")

    def generate_filters(self):
        """Generates the mailfilter.xml file."""
        feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")

        # Collect all unique senders from both suggestion and validated databases
        all_senders = set(self.database.suggestion_db.keys()).union(self.database.validated_db.keys())

        # Collect all unique senders and their dominant categories
        sender_categories = []
        for sender in all_senders:
            most_common_category = self.database.get_dominant_classification(sender)
            if most_common_category:
                sender_categories.append((most_common_category, sender))

        # Sort by category (label)
        sender_categories.sort(key=lambda x: x[0])

        for most_common_category, sender in sender_categories:

            entry = SubElement(feed, "entry")
            SubElement(entry, "category", term="filter")
            title = SubElement(entry, "title")
            title.text = f"MailTag - {most_common_category}"

            SubElement(
                entry,
                "{http://schemas.google.com/apps/2006}property",
                name="from",
                value=sender,
            )
            SubElement(
                entry,
                "{http://schemas.google.com/apps/2006}property",
                name="label",
                value=most_common_category,
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
                name="shouldMarkAsRead",
                value="true",
            )
            SubElement(
                entry,
                "{http://schemas.google.com/apps/2006}property",
                name="shouldNeverSpam",
                value="true",
            )
            SubElement(
                entry,
                "{http://schemas.google.com/apps/2006}property",
                name="hasTheWord",
                value="has:unread",
            )

        # Pretty print the XML
        xml_str = tostring(feed, "utf-8")
        pretty_xml_str = minidom.parseString(xml_str).toprettyxml(indent="    ")

        with self.output_path.open("w", encoding="utf-8") as f:
            f.write(pretty_xml_str)
