import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

from loguru import logger

from .utils.domain_utils import extract_domain, normalize_domain


class ClassificationDatabase:
    """Manages the sender classification database."""

    def __init__(
        self, suggestion_db_path: Path, validated_db_path: Path, domain_db_path: Optional[Path] = None
    ):
        self.suggestion_db_path = suggestion_db_path
        self.validated_db_path = validated_db_path
        self.domain_db_path = domain_db_path or suggestion_db_path.parent / "domain_classifications.json"
        self.suggestion_db = self._load(self.suggestion_db_path)
        self.validated_db = self._load(self.validated_db_path)
        self.domain_db = self._load_domain_db()

    def _load(self, db_path: Path) -> defaultdict:
        """Loads a database from a JSON file."""
        if not db_path.exists() or db_path.stat().st_size == 0:
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

    def _load_domain_db(self) -> dict[str, str]:
        """Loads the domain classification database from a JSON file."""
        if not self.domain_db_path.exists() or self.domain_db_path.stat().st_size == 0:
            return {}
        try:
            with self.domain_db_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure all domains are normalized (lowercase)
                normalized_data = {normalize_domain(domain): category for domain, category in data.items()}
                logger.debug(f"Loaded {len(normalized_data)} domain classifications")
                return normalized_data
        except (json.JSONDecodeError, FileNotFoundError):
            logger.error(f"Could not read or parse domain db file at {self.domain_db_path}")
            return {}

    def _save_suggestion_db(self):
        """Saves the suggestion database to a JSON file."""
        with self.suggestion_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.suggestion_db, f, indent=2, ensure_ascii=False)

    def _save_validated_db(self):
        """Saves the validated database to a JSON file."""
        with self.validated_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.validated_db, f, indent=2, ensure_ascii=False)

    def _save_domain_db(self):
        """Saves the domain classification database to a JSON file."""
        with self.domain_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.domain_db, f, indent=2, ensure_ascii=False)

    def update_suggestion(self, sender_address: str, category: str):
        """Updates the occurrence count for a sender-category pair in the suggestion database."""
        self.suggestion_db[sender_address.lower()][category] += 1
        self._save_suggestion_db()

    def promote_to_validated(self, sender_address: str, category: str):
        """Promotes a classification from the suggestion DB to the validated DB."""
        sender_address = sender_address.lower()
        # Remove from suggestion DB
        if sender_address in self.suggestion_db:
            del self.suggestion_db[sender_address]
            self._save_suggestion_db()
        # Add to validated DB
        self.validated_db[sender_address] = {category: 1}
        self._save_validated_db()

    def get_classification_count(self, sender_address: str, category: str) -> int:
        """Gets the classification count for a sender-category pair from the suggestion DB."""
        return self.suggestion_db[sender_address.lower()][category]

    def get_dominant_classification(self, sender_address: str) -> str | None:
        """Gets the category with the highest count for a given sender."""
        sender_address = sender_address.lower()
        # Check validated DB first
        if sender_address in self.validated_db:
            return list(self.validated_db[sender_address].keys())[0]
        # Then check suggestion DB
        if sender_address in self.suggestion_db:
            classifications = self.suggestion_db[sender_address]
            if classifications:
                return max(classifications, key=classifications.get)
        return None

    # Domain-based classification methods

    def get_category_by_domain(self, domain: str) -> Optional[str]:
        """Gets the category for a domain from the domain classification database.

        Args:
            domain: Domain to look up (e.g., 'todoist.com')

        Returns:
            Category if domain is found, None otherwise
        """
        normalized_domain = normalize_domain(domain)
        return self.domain_db.get(normalized_domain)

    def store_domain_classification(self, domain: str, category: str):
        """Stores a domain classification in the database.

        Args:
            domain: Domain to classify (e.g., 'todoist.com')
            category: Category to assign (e.g., 'Services/Professional/Todoist')
        """
        normalized_domain = normalize_domain(domain)
        self.domain_db[normalized_domain] = category
        self._save_domain_db()
        logger.debug(f"Stored domain classification: {normalized_domain} -> {category}")

    def get_all_domain_mappings(self) -> dict[str, str]:
        """Gets all domain -> category mappings.

        Returns:
            Dictionary of domain -> category mappings
        """
        return self.domain_db.copy()

    def update_domain_classification(self, domain: str, category: str):
        """Updates an existing domain classification.

        Args:
            domain: Domain to update
            category: New category to assign
        """
        self.store_domain_classification(domain, category)

    def get_category_by_email(self, email_address: str) -> Optional[str]:
        """Gets the category for an email address based on its domain.

        Args:
            email_address: Email address to classify

        Returns:
            Category if domain is found, None otherwise
        """
        domain = extract_domain(email_address)
        if not domain:
            return None
        return self.get_category_by_domain(domain)

    def has_domain_classification(self, domain: str) -> bool:
        """Checks if a domain has a classification.

        Args:
            domain: Domain to check

        Returns:
            True if domain has a classification
        """
        normalized_domain = normalize_domain(domain)
        return normalized_domain in self.domain_db

    def remove_domain_classification(self, domain: str) -> bool:
        """Removes a domain classification.

        Args:
            domain: Domain to remove

        Returns:
            True if domain was removed, False if not found
        """
        normalized_domain = normalize_domain(domain)
        if normalized_domain in self.domain_db:
            del self.domain_db[normalized_domain]
            self._save_domain_db()
            logger.debug(f"Removed domain classification: {normalized_domain}")
            return True
        return False
