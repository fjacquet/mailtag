import hashlib
from pathlib import Path

import litellm
import yaml
from loguru import logger

from .config import AppConfig
from .database import ClassificationDatabase
from .folder_analyzer import FolderAnalyzer
from .models import Email
from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached


class Classifier:
    """
    Classifies emails using a multi-signal strategy, prioritizing server-side
    labels, then historical data, and finally an AI model.
    """

    def __init__(self, config: AppConfig, database: ClassificationDatabase):
        self.config = config
        self.proposal_file = Path("proposals.log")
        self.database = database
        self.ai_cache = {}  # Simple in-memory cache for AI responses

        # Use either folder analyzer or static schema based on configuration
        if config.general.use_imap_folders_for_classification:
            self.folder_analyzer = FolderAnalyzer()
            self.categories = self.folder_analyzer.get_all_categories()
            logger.info(f"Using dynamic IMAP folder structure with {len(self.categories)} categories")
        else:
            self.folder_analyzer = None
            self.categories = self._load_categories_from_schema()
            logger.info(f"Using static classification schema with {len(self.categories)} categories")

    def _load_categories_from_schema(self) -> list[str]:
        """Loads classification categories from the YAML file (legacy method)."""
        schema_path = Path("data/classification_schema.yml")
        if not schema_path.exists():
            logger.error(f"Classification schema not found at {schema_path}")
            return []
        with schema_path.open("r", encoding="utf-8") as f:
            schema = yaml.safe_load(f)

        categories = []
        for category in schema:
            if "sublabels" in category and category["sublabels"]:
                for sublabel in category["sublabels"]:
                    categories.append(f"{category['name']}/{sublabel['name']}")
            else:
                categories.append(category["name"])
        return categories

    def _get_category_from_validated_db(self, email: Email) -> str | None:
        """
        Signal 1: Check for a classification from the validated database.
        """
        return self.database.get_dominant_classification(email.sender_address)

    def _get_category_from_labels(self, email: Email) -> str | None:
        """
        Signal 2: Check for an existing server-side label that matches a known category.
        """
        for label in email.labels:
            if label in self.categories:
                logger.debug(f"Found matching server-side label: {label}")
                return label
        return None

    def _get_category_from_history(self, email: Email) -> str | None:
        """
        Signal 3: Check for a high-confidence classification from the sender's history in the suggestion DB.
        """
        sender_classifications = self.database.suggestion_db.get(email.sender_address)
        if not sender_classifications:
            return None

        total_count = sum(sender_classifications.values())
        if total_count < self.config.classifier.min_count:
            return None

        most_common_category = max(sender_classifications, key=sender_classifications.get)
        confidence = sender_classifications[most_common_category] / total_count

        if confidence >= self.config.classifier.historical_confidence_threshold:
            logger.info(
                f"Found high-confidence historical category for {email.sender_address}: "
                f"{most_common_category} ({confidence:.2f} confidence)."
            )
            return most_common_category
        return None

    def _get_category_from_domain(self, email: Email) -> str | None:
        """
        Signal 4: Check for domain-based classification.
        Skip non-commercial domains (gmail.com, yahoo.com, etc.)
        """
        if not email.sender_address:
            return None

        domain = extract_domain(email.sender_address)
        if not domain:
            return None

        # Skip non-commercial domains (personal email providers)
        if is_non_commercial_domain_cached(domain):
            logger.debug(f"Skipping non-commercial domain: {domain}")
            return None

        # Look up domain classification
        category = self.database.get_category_by_domain(domain)
        if category:
            logger.info(
                f"Found domain-based classification for {email.sender_address}: {category} (domain: {domain})"
            )
            return category

        logger.debug(f"No domain classification found for: {domain}")
        return None

    def _get_cache_key(self, email: Email) -> str:
        """Generate a cache key for AI responses based on sender and subject."""
        sender = email.sender_address or "Unknown"
        subject = email.subject or "No Subject"
        # Create a hash of sender + subject for caching
        cache_input = f"{sender.lower()}:{subject.lower()}"
        return hashlib.md5(cache_input.encode()).hexdigest()

    def _truncate_body(self, body: str, max_chars: int = 500) -> str:
        """Truncate email body to reduce prompt size and improve performance."""
        if not body:
            return ""
        if len(body) <= max_chars:
            return body
        return body[:max_chars] + "..."

    def _get_category_from_ai(self, email: Email) -> str:
        """
        Signal 4: Fallback to the AI model for classification.
        """
        sender = (
            f"{email.sender_name} <{email.sender_address}>"
            if email.sender_name
            else email.sender_address or "Unknown"
        )
        logger.debug(f"Using AI classification for email from {sender}")

        # Check cache first
        cache_key = self._get_cache_key(email)
        if cache_key in self.ai_cache:
            logger.debug(f"Using cached AI response for {email.sender_address}")
            return self.ai_cache[cache_key]

        # Truncate email body for better performance
        truncated_body = self._truncate_body(email.body)

        if self.folder_analyzer:
            # Use dynamic folder structure
            leaf_folders = self.folder_analyzer.get_all_categories()
            parent_folders = self.folder_analyzer.get_parent_folders()

            # Create a more concise list for the prompt
            category_list = "\n".join([f"- {cat}" for cat in sorted(leaf_folders)])
            parent_list = "\n".join([f"- {parent}" for parent in sorted(parent_folders)])

            prompt = (
                f"Sujet: {email.subject}\n"
                f"De: {sender}\n"
                f"Corps: {truncated_body}\n\n"
                "Classe dans une catégorie FEUILLE (catégorie de dernier niveau, sans sous-catégories):\n"
                f"{category_list}\n\n"
                "Si la catégorie appropriée n'existe pas, propose un nouveau sous-dossier sous:\n"
                f"{parent_list}\n\n"
                "IMPORTANT: Réponds UNIQUEMENT avec le nom exact d'une catégorie de la liste ci-dessus, ou 'Parent/NewSub'.\n"
                "N'invente PAS de nouvelles catégories qui ne sont pas dans la liste.\n"
                "Ne donne AUCUNE explication, AUCUN texte supplémentaire. Juste le nom de la catégorie.\n"
                "Format: 'CategoryName' ou 'Parent/NewSub'"
            )
        else:
            # Legacy behavior using static schema
            category_list = "\n".join([f"- {cat}" for cat in self.categories])

            prompt = (
                f"Sujet: {email.subject}\n"
                f"De: {sender}\n"
                f"Corps: {truncated_body}\n\n"
                "Classe dans une catégorie de la liste suivante:\n"
                f"{category_list}\n\n"
                "IMPORTANT: Réponds UNIQUEMENT avec le nom exact d'une catégorie de la liste ci-dessus, ou 'Parent/NewSub'.\n"
                "N'invente PAS de nouvelles catégories qui ne sont pas dans la liste.\n"
                "Ne donne AUCUNE explication, AUCUN texte supplémentaire. Juste le nom de la catégorie.\n"
                "Format: 'CategoryName' ou 'Parent/NewSub'"
            )

        try:
            response = litellm.completion(
                model=self.config.general.ollama_model,
                messages=[{"role": "user", "content": prompt}],
                api_base=self.config.general.api_base,
                extra_body={
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": 2048,  # Reduced context window for better performance
                    }
                },
            )
            classification = response.choices[0].message.content.strip()

            # Cache the response
            self.ai_cache[cache_key] = classification

            # Debug logging (reduced verbosity for performance)
            logger.debug(f"AI response: '{classification}' (cached: False)")
            # Only log prompt in trace/debug mode for performance
            logger.trace(f"AI prompt:\n{prompt}")

            # Handle folder-based classification responses
            if self.config.general.use_imap_folders_for_classification and self.folder_analyzer:
                # Handle new subfolder suggestions
                if classification.startswith("Parent/NewSub"):
                    proposed_path = classification.replace("Parent/NewSub", "").strip()
                    logger.debug(f"Processing new folder proposal: '{proposed_path}'")

                    if "/" in proposed_path:
                        parent, subfolder = proposed_path.split("/", 1)
                        logger.debug(f"Parsed parent: '{parent}', subfolder: '{subfolder}'")

                        # Check if parent is a valid folder that can have subfolders
                        if self.folder_analyzer.is_valid_parent_folder(parent):
                            logger.debug(f"Valid parent folder: '{parent}'")
                            self._log_proposal(email, f"{parent}/{subfolder}")
                            return "À Classer"
                        logger.warning(f"Invalid parent folder in proposal: '{parent}'")
                        return "À Classer"

                    # If the format is incorrect or parent not valid
                    logger.warning(f"Invalid new folder proposal: '{classification}'")
                    return "À Classer"
            else:
                # Legacy handling
                if classification.startswith("UNCERTAIN"):
                    proposal = classification.replace("UNCERTAIN:", "").strip()
                    self._log_proposal(email, proposal)
                    return "À Classer"

            # Common handling for both approaches
            if classification not in self.categories:
                self._log_proposal(email, classification)
                return "À Classer"

            return classification
        except Exception as e:
            logger.error(f"Error calling litellm: {e}")
            return "(Model Error)"

    def classify_email(self, email: Email) -> str:
        """
        Classifies an email using the Adaptive Multi-Signal Classification (AMSC) strategy.
        """
        # Signal 1: Validated Database
        category = self._get_category_from_validated_db(email)
        if category:
            logger.info(f"Classified via Validated DB: {category}")
            return category

        # Signal 2: Server-Side Label
        category = self._get_category_from_labels(email)
        if category:
            logger.info(f"Classified via Server Label: {category}")
            self.database.update_suggestion(email.sender_address, category)
            return category

        # Signal 3: Historical Suggestion Database
        category = self._get_category_from_history(email)
        if category:
            logger.info(f"Classified via History: {category}")
            # No need to update DB, it's already the most confident one
            return category

        # Signal 4: Domain-based Classification
        category = self._get_category_from_domain(email)
        if category:
            logger.info(f"Classified via Domain: {category}")
            # Update suggestion DB to learn from domain classification
            self.database.update_suggestion(email.sender_address, category)
            return category

        # Signal 5: AI Model (Fallback)
        logger.debug("No high-confidence signals found, falling back to AI model.")
        category = self._get_category_from_ai(email)
        logger.info(f"Classified via AI Model: {category}")

        if category not in ["À Classer", "(Model Error)"]:
            self.database.update_suggestion(email.sender_address, category)

        return category

    def _log_proposal(self, email: Email, proposal: str):
        """Logs a classification proposal to a file."""
        sender = (
            f"{email.sender_name} <{email.sender_address}>" if email.sender_name else email.sender_address
        )
        with self.proposal_file.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"From: {sender}\n")
            f.write(f"Subject: {email.subject}\n")
            f.write(f"Proposed Category: {proposal}\n")
            f.write(f"Body:\n{email.body}\n\n")
