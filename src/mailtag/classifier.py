import logging
import yaml
from pathlib import Path

import ollama

from .models import Email
from .database import ClassificationDatabase


class Classifier:
    """Classifies emails using an AI model."""

    def __init__(self, model: str, database: ClassificationDatabase):
        self.model = model
        self.proposal_file = Path("proposals.log")
        self.categories = self._load_categories()
        self.database = database

    def _load_categories(self) -> list[str]:
        """Loads classification categories from the YAML file."""
        schema_path = Path("data/classification_schema.yml")
        if not schema_path.exists():
            logging.error(f"Classification schema not found at {schema_path}")
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

    def classify_email(self, email: Email, body: str) -> str:
        """Classifies an email using Ollama and updates the sender database."""
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
            "Réponds uniquement avec le nom complet de la catégorie (ex: Finances/Bloomberg).\n"
            "Si aucune catégorie ne correspond parfaitement, réponds avec 'UNCERTAIN' suivi de la catégorie la plus proche ou d'une nouvelle suggestion de catégorie."
        )
        try:
            response = ollama.generate(model=self.model, prompt=prompt)
            classification = response["response"].strip()

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
            logging.error(f"Error calling Ollama: {e}")
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
