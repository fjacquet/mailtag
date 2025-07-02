#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Main entry point for the mailtag email classification script.
"""

import logging
from pathlib import Path

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.logging_config import setup_logging
from mailtag.mail_service import MailService


def main():
    """Main function to run the email classification script."""
    setup_logging(CONFIG.logging.level, CONFIG.logging.file)

    try:
        db_path = Path("db/sender_classification_db.json")
        database = ClassificationDatabase(db_path)
        mail_service = MailService(CONFIG.general.mail_dir)
        classifier = Classifier(CONFIG.general.ollama_model, database)
    except FileNotFoundError as e:
        logging.critical(e)
        return

    emails = mail_service.get_inbox_emails()
    if not emails:
        logging.info("No emails found in the inbox.")
        return

    logging.info(f"Found {len(emails)} emails. Starting analysis...")

    for email in emails:
        body = mail_service.get_email_body(email)
        category = classifier.classify_email(email, body)
        logging.info(
            'Email "%s" from %s -> Category: %s',
            email.subject,
            email.sender_address,
            category,
        )

    logging.info("Analysis complete.")


if __name__ == "__main__":
    main()
