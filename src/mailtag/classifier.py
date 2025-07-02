import logging

import ollama

from .models import Email


class Classifier:
    """Classifies emails using an AI model."""

    def __init__(self, model: str):
        self.model = model

    def classify_email(self, email: Email, body: str) -> str:
        """Classifies an email using Ollama."""
        sender = (
            f"{email.sender_name} <{email.sender_address}>"
            if email.sender_name
            else email.sender_address
        )
        prompt = (
            f"Sujet : {email.subject}\n"
            f"De : {sender}\n"
            f"Corps : {body}\n\n"
            "Indique la catégorie générale de cet e-mail "
            "(ex: travail, personnel, factures...). "
            "Réponds uniquement par le ou les noms de catégories appropriées."
        )
        try:
            response = ollama.generate(model=self.model, prompt=prompt)
            return response["response"].strip()
        except Exception as e:
            logging.error(f"Error calling Ollama: {e}")
            return "(Model Error)"

