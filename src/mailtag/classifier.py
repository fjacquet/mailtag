from pathlib import Path

import litellm
import yaml
from loguru import logger

from .config import AppConfig
from .database import ClassificationDatabase
from .models import Email


class Classifier:
    """
    Classifies emails using a multi-signal strategy, prioritizing server-side
    labels, then historical data, and finally an AI model.
    """

    def __init__(self, config: AppConfig, database: ClassificationDatabase):
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

    def _get_category_from_ai(self, email: Email) -> str:
        """
        Signal 4: Fallback to the AI model for classification.
        """
        sender = (
            f"{email.sender_name} <{email.sender_address}>" if email.sender_name else email.sender_address
        )
        category_list = "\n".join([f"- {cat}" for cat in self.categories])

        prompt = (
            f"Sujet : {email.subject}\n"
            f"De : {sender}\n"
            f"Corps : {email.body}\n\n"
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
                # It's good practice to include confidence if the model supports it
                extra_body={"options": {"temperature": 0.2, "confidence": True}},
            )
            classification = response.choices[0].message.content.strip()
            # Note: Confidence score handling might vary by model.
            # This is a placeholder for how one might access it.
            # confidence = response.choices[0].get("confidence", 0)

            # if confidence < self.config.classifier.ai_confidence_threshold:
            #     logger.warning(f"AI confidence ({confidence:.2f}) below threshold for '{classification}'.")
            #     self._log_proposal(email, classification)
            #     return "À Classer"

            if classification.startswith("UNCERTAIN"):
                proposal = classification.replace("UNCERTAIN:", "").strip()
                self._log_proposal(email, proposal)
                return "À Classer"

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

        # Signal 4: AI Model (Fallback)
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
