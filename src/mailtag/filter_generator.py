import json
from collections import defaultdict
from pathlib import Path
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring


class FilterGenerator:
    """Generates a Gmail filter XML file from the classification database."""

    def __init__(self, db_path: Path, output_path: Path):
        self.db_path = db_path
        self.output_path = output_path
        self.sender_db = self._load_database()
        register_namespace("apps", "http://schemas.google.com/apps/2006")


    def _load_database(self) -> defaultdict:
        """Loads the sender classification database from a JSON file."""
        if not self.db_path.exists():
            return defaultdict(lambda: defaultdict(int))
        with self.db_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            db = defaultdict(lambda: defaultdict(int))
            for sender, cats in data.items():
                db[sender] = defaultdict(int, cats)
            return db

    def generate_filters(self):
        """Generates the mailfilter.xml file."""
        feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")

        for sender, categories in self.sender_db.items():
            if not categories:
                continue

            # Find the most common category for this sender
            most_common_category = max(categories, key=categories.get)

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

        # Pretty print the XML
        xml_str = tostring(feed, "utf-8")
        pretty_xml_str = minidom.parseString(xml_str).toprettyxml(indent="    ")

        with self.output_path.open("w", encoding="utf-8") as f:
            f.write(pretty_xml_str)