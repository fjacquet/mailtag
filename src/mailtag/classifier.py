from pathlib import Path

import litellm
import yaml
from loguru import logger

from .config import AppConfig
from .database import ClassificationDatabase
from .models import Email


class Classifier:
    """Classifies emails using an AI model."""

    def __init__(
        self, config: AppConfig, database: ClassificationDatabase
    ):
        self.config = config
        self.proposal_file = Path("proposals.log")
        self.categories = self._load_categories()
        self.database = database

    def _load_categories(self) -> list[str]:
        """Loads classification categories from the YAML file."""
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

    def _get_preclassified_category(self, sender_address: str) -> str | None:
        """
        Returns a pre-classified category for a sender if the confidence
        threshold is met.
        """
        if not self.config.preclassification.enabled:
            return None

        sender_classifications = self.database.sender_db.get(sender_address)
        if not sender_classifications:
            return None

        total_count = sum(sender_classifications.values())
        if total_count < self.config.preclassification.min_count:
            return None

        most_common_category = max(
            sender_classifications, key=sender_classifications.get
        )
        confidence = sender_classifications[most_common_category] / total_count

        if confidence >= self.config.preclassification.confidence_threshold:
            logger.info(
                f"Pre-classifying sender {sender_address} as "
                f"{most_common_category} with {confidence:.2f} confidence."
            )
            return most_common_category
        return None

    def classify_email(self, email: Email, body: str) -> str:
        """Classifies an email using litellm."""
        # Try to get a pre-classified category first
        preclassified_category = self._get_preclassified_category(email.sender_address)
        if preclassified_category:
            return preclassified_category

        sender = (
            f"{email.sender_name} <{email.sender_address}>"
            if email.sender_name
            else email.sender_address
        )

        category_list = "\n".join([f"- {cat}" for cat in self.categories])

        prompt = (
            f"Sujet : {email.subject}\n"
            f"De : {sender}\n"
            f"Corps : {body}\n\n"
            "Classe cet e-mail dans l'une des catégories suivantes:\n"
            f"{category_list}\n\n"
            "Réponds uniquement avec le nom complet de la catégorie "
            "(ex: Finances/Bloomberg).\n"
            "Si aucune catégorie ne correspond parfaitement, "
            "réponds avec 'UNCERTAIN' suivi de la catégorie la plus "
            "proche ou d'une nouvelle suggestion de catégorie."
        )
        try:
            response = litellm.completion(
                model=self.config.general.ollama_model,
                messages=[{"role": "user", "content": prompt}],
                api_base=self.config.general.api_base,
            )
            classification = response.choices[0].message.content.strip()

            if classification.startswith("UNCERTAIN"):
                proposal = classification.replace("UNCERTAIN:", "").strip()
                self._log_proposal(email, body, proposal)
                return "À Classer"

            if classification not in self.categories:
                self._log_proposal(email, body, classification)
                return "À Classer"

            # Update database on successful classification
            self.database.update(email.sender_address, classification)
            return classification
        except Exception as e:
            logger.error(f"Error calling litellm: {e}")
            return "(Model Error)"

    def _log_proposal(self, email: Email, body: str, proposal: str):
        """Logs a classification proposal to a file."""
        sender = (
            f"{email.sender_name} <{email.sender_address}>"
            if email.sender_name
            else email.sender_address
        )
        with self.proposal_file.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"From: {sender}\n")
            f.write(f"Subject: {email.subject}\n")
            f.write(f"Proposed Category: {proposal}\n")
            f.write(f"Body:\n{body}\n\n")