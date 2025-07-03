#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Main entry point for the mailtag email classification script.
"""

import logging
import argparse
from pathlib import Path

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.logging_config import setup_logging
from mailtag.mail_service import MailService
from mailtag.filter_generator import FilterGenerator


def run_classification():
    """Runs the email classification process."""
    try:
        db_path = Path("db/sender_classification_db.json")
        database = ClassificationDatabase(db_path)
        mail_service = MailService()
        classifier = Classifier(CONFIG, database)
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


def generate_filters():
    """Generates the mailfilter.xml file."""
    db_path = Path("db/sender_classification_db.json")
    output_path = Path("data/mailfilter.xml")
    generator = FilterGenerator(db_path, output_path)
    generator.generate_filters()
    logging.info(f"Filters generated at {output_path}")


def main():
    """Main function to run the email classification script."""
    setup_logging(CONFIG.logging.level, CONFIG.logging.file)

    parser = argparse.ArgumentParser(description="MailTag: Email Classification Tool")
    parser.add_argument(
        "--generate-filters",
        action="store_true",
        help="Generate the mailfilter.xml file from the database.",
    )
    args = parser.parse_args()

    if args.generate_filters:
        generate_filters()
    else:
        run_classification()


if __name__ == "__main__":
    main()
