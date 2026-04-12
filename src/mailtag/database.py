import json
import re
import threading
from collections import defaultdict
from pathlib import Path

from loguru import logger

from .utils.domain_utils import extract_domain, normalize_domain


def _normalize_email(email: str) -> str:
    """Normalize an email address for consistent storage.

    - Strip angle brackets
    - Convert to lowercase
    - Strip whitespace
    """
    if not email:
        return ""
    # Strip angle brackets
    email = re.sub(r"^<|>$", "", email.strip())
    # Extract email from "Name <email>" format
    match = re.search(r"<([^>]+)>", email)
    if match:
        email = match.group(1)
    return email.lower().strip()


class ClassificationDatabase:
    """Manages the sender classification database."""

    def __init__(self, suggestion_db_path: Path, validated_db_path: Path, domain_db_path: Path | None = None):
        self.suggestion_db_path = suggestion_db_path
        self.validated_db_path = validated_db_path
        self.domain_db_path = domain_db_path or suggestion_db_path.parent / "domain_classifications.json"
        self.suggestion_db = self._load(self.suggestion_db_path)
        self.validated_db = self._load(self.validated_db_path)
        self.domain_db = self._load_domain_db()

        # Deferred write support
        self._lock = threading.RLock()
        self._suggestion_dirty = False
        self._domain_dirty = False

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

    def _save_suggestion_db(self) -> None:
        """Saves the suggestion database to a JSON file."""
        with self.suggestion_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.suggestion_db, f, indent=2, ensure_ascii=False)

    def _save_validated_db(self) -> None:
        """Saves the validated database to a JSON file."""
        with self.validated_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.validated_db, f, indent=2, ensure_ascii=False)

    def _save_domain_db(self) -> None:
        """Saves the domain classification database to a JSON file."""
        with self.domain_db_path.open("w", encoding="utf-8") as f:
            json.dump(self.domain_db, f, indent=2, ensure_ascii=False)

    def update_suggestion(self, sender_address: str, category: str) -> None:
        """Updates the occurrence count for a sender-category pair in the suggestion database.

        Write is deferred — call flush() to persist.
        """
        normalized = _normalize_email(sender_address)
        with self._lock:
            self.suggestion_db[normalized][category] += 1
            self._suggestion_dirty = True

    def promote_to_validated(self, sender_address: str, category: str) -> None:
        """Promotes a classification from the suggestion DB to the validated DB."""
        normalized = _normalize_email(sender_address)
        with self._lock:
            # Remove from suggestion DB
            if normalized in self.suggestion_db:
                del self.suggestion_db[normalized]
                self._save_suggestion_db()
            # Add to validated DB
            self.validated_db[normalized] = {category: 1}
            self._save_validated_db()

    def get_classification_count(self, sender_address: str, category: str) -> int:
        """Gets the classification count for a sender-category pair from the suggestion DB."""
        normalized = _normalize_email(sender_address)
        return self.suggestion_db[normalized][category]

    def get_dominant_classification(self, sender_address: str) -> str | None:
        """Gets the category with the highest count for a given sender."""
        normalized = _normalize_email(sender_address)
        # Check validated DB first
        if normalized in self.validated_db:
            return list(self.validated_db[normalized].keys())[0]
        # Then check suggestion DB
        if normalized in self.suggestion_db:
            classifications = self.suggestion_db[normalized]
            if classifications:
                return max(classifications, key=classifications.get)
        return None

    def get_sender_classifications(self, sender_address: str) -> dict[str, int]:
        """Get all classifications for a sender from the suggestion database.

        Args:
            sender_address: Email address of the sender

        Returns:
            Dictionary mapping categories to occurrence counts
            Returns empty dict if sender not found
        """
        normalized = _normalize_email(sender_address)
        return dict(self.suggestion_db.get(normalized, {}))

    # Domain-based classification methods

    def get_category_by_domain(self, domain: str) -> str | None:
        """Gets the category for a domain from the domain classification database.

        Args:
            domain: Domain to look up (e.g., 'todoist.com')

        Returns:
            Category if domain is found, None otherwise
        """
        normalized_domain = normalize_domain(domain)
        return self.domain_db.get(normalized_domain)

    def store_domain_classification(self, domain: str, category: str) -> None:
        """Stores a domain classification in the database.

        Write is deferred — call flush() to persist.

        Args:
            domain: Domain to classify (e.g., 'todoist.com')
            category: Category to assign (e.g., 'Services/Professional/Todoist')
        """
        normalized_domain = normalize_domain(domain)
        with self._lock:
            self.domain_db[normalized_domain] = category
            self._domain_dirty = True
        logger.debug(f"Stored domain classification: {normalized_domain} -> {category}")

    def get_all_domain_mappings(self) -> dict[str, str]:
        """Gets all domain -> category mappings.

        Returns:
            Dictionary of domain -> category mappings
        """
        return self.domain_db.copy()

    def update_domain_classification(self, domain: str, category: str) -> None:
        """Updates an existing domain classification.

        Args:
            domain: Domain to update
            category: New category to assign
        """
        self.store_domain_classification(domain, category)

    def get_category_by_email(self, email_address: str) -> str | None:
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

    def flush(self) -> None:
        """Persist all dirty databases to disk (thread-safe)."""
        with self._lock:
            if self._suggestion_dirty:
                self._save_suggestion_db()
                self._suggestion_dirty = False
                logger.debug("Flushed suggestion database")
            if self._domain_dirty:
                self._save_domain_db()
                self._domain_dirty = False
                logger.debug("Flushed domain database")

    def remove_domain_classification(self, domain: str) -> bool:
        """Removes a domain classification.

        Args:
            domain: Domain to remove

        Returns:
            True if domain was removed, False if not found
        """
        normalized_domain = normalize_domain(domain)
        with self._lock:
            if normalized_domain in self.domain_db:
                del self.domain_db[normalized_domain]
                self._save_domain_db()
                logger.debug(f"Removed domain classification: {normalized_domain}")
                return True
            return False
