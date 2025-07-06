import json
from collections import defaultdict
from pathlib import Path

from loguru import logger


class ClassificationDatabase:
    """Manages the sender classification database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.sender_db = self._load()

    def _load(self) -> defaultdict:
        """Loads the database from a JSON file."""
        if not self.db_path.exists():
            return defaultdict(lambda: defaultdict(int))
        try:
            with self.db_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                db = defaultdict(lambda: defaultdict(int))
                for sender, cats in data.items():
                    db[sender] = defaultdict(int, cats)
                return db
        except (json.JSONDecodeError, FileNotFoundError):
            logger.error(f"Could not read or parse db file at {self.db_path}")
            return defaultdict(lambda: defaultdict(int))

    def _save(self):
        """Saves the database to a JSON file."""
        with self.db_path.open("w", encoding="utf-8") as f:
            json.dump(self.sender_db, f, indent=2, ensure_ascii=False)

    def update(self, sender_address: str, category: str):
        """Updates the occurrence count for a sender-category pair."""
        self.sender_db[sender_address][category] += 1
        self._save()

    def get_classification_count(self, sender_address: str, category: str) -> int:
        """Gets the classification count for a sender-category pair."""
        return self.sender_db[sender_address][category]

    def get_dominant_classification(self, sender_address: str) -> str | None:
        """Gets the category with the highest count for a given sender."""
        if sender_address in self.sender_db:
            classifications = self.sender_db[sender_address]
            if classifications:
                return max(classifications, key=classifications.get)
        return None
