import json
from collections import defaultdict
from pathlib import Path

from loguru import logger


class ClassificationDatabase:
    """Manages the sender classification database."""

    def __init__(self, suggestion_db_path: Path, validated_db_path: Path):
        self.suggestion_db_path = suggestion_db_path
        self.validated_db_path = validated_db_path
        self.suggestion_db = self._load(self.suggestion_db_path)
        self.validated_db = self._load(self.validated_db_path)

    def _load(self, db_path: Path) -> defaultdict:
        """Loads a database from a JSON file."""
        if not db_path.exists():
            return defaultdict(lambda: defaultdict(int))
        try:
            with db_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                db = defaultdict(lambda: defaultdict(int))
                for sender, cats in data.items():
                    db[sender] = defaultdict(int, cats)
                return db
        except (json.JSONDecodeError, FileNotFoundError):
            logger.error(f"Could not read or parse db file at {db_path}")
            return defaultdict(lambda: defaultdict(int))

    def _save_suggestion_db(self):
        """Saves the suggestion database to a JSON file."""
        with self.suggestion_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.suggestion_db, f, indent=2, ensure_ascii=False)

    def _save_validated_db(self):
        """Saves the validated database to a JSON file."""
        with self.validated_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.validated_db, f, indent=2, ensure_ascii=False)

    def update_suggestion(self, sender_address: str, category: str):
        """Updates the occurrence count for a sender-category pair in the suggestion database."""
        self.suggestion_db[sender_address][category] += 1
        self._save_suggestion_db()

    def promote_to_validated(self, sender_address: str, category: str):
        """Promotes a classification from the suggestion DB to the validated DB."""
        # Remove from suggestion DB
        if sender_address in self.suggestion_db:
            del self.suggestion_db[sender_address]
            self._save_suggestion_db()
        # Add to validated DB
        self.validated_db[sender_address] = {category: 1}
        self._save_validated_db()

    def get_classification_count(self, sender_address: str, category: str) -> int:
        """Gets the classification count for a sender-category pair from the suggestion DB."""
        return self.suggestion_db[sender_address][category]

    def get_dominant_classification(self, sender_address: str) -> str | None:
        """Gets the category with the highest count for a given sender."""
        # Check validated DB first
        if sender_address in self.validated_db:
            return list(self.validated_db[sender_address].keys())[0]
        # Then check suggestion DB
        if sender_address in self.suggestion_db:
            classifications = self.suggestion_db[sender_address]
            if classifications:
                return max(classifications, key=classifications.get)
        return None
