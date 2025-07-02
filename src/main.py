#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Main entry point for the mailtag email classification script.
"""

import logging

from mailtag.classifier import Classifier
from mailtag.config import MAIL_DIR, OLLAMA_MODEL
from mailtag.mail_service import MailService


def main():
    """Main function to run the email classification script."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    try:
        mail_service = MailService(MAIL_DIR)
        classifier = Classifier(OLLAMA_MODEL)
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