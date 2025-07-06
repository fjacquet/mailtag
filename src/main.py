#!/usr/bin/env python3

"""
Main entry point for the mailtag email classification script.
"""

import argparse
from pathlib import Path

from loguru import logger

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.filter_generator import FilterGenerator
from mailtag.logging_config import setup_logging
from mailtag.providers import EmailProvider
from mailtag.imap_service import ImapService
from mailtag.gmail_service import GmailService


def run_classification(provider: EmailProvider):
    """Runs the email classification process."""
    try:
        db_path = Path("db/sender_classification_db.json")
        database = ClassificationDatabase(db_path)
        classifier = Classifier(CONFIG, database)
    except FileNotFoundError as e:
        logger.critical(e)
        return

    provider.connect()
    emails = provider.get_emails()
    if not emails:
        logger.info("No emails found in the inbox.")
        return

    logger.info(f"Found {len(emails)} emails. Starting analysis...")

    for email in emails:
        try:
            body = provider.get_email_body(email)
            category = classifier.classify_email(email, body)
            logger.info(
                'Email "%s" from %s -> Category: %s',
                email.subject,
                email.sender_address,
                category,
            )
        except Exception as e:
            logger.error(f"Could not process email {email.msg_id}: {e}")

    logger.info("Analysis complete.")


def generate_filters():
    """Generates the mailfilter.xml file."""
    db_path = Path("db/sender_classification_db.json")
    output_path = Path("data/mailfilter.xml")
    generator = FilterGenerator(db_path, output_path)
    generator.generate_filters()
    logger.info(f"Filters generated at {output_path}")


def main():
    """Main function to run the email classification script."""
    setup_logging(CONFIG.logging.level, CONFIG.logging.file)

    parser = argparse.ArgumentParser(description="MailTag: Email Classification Tool")
    parser.add_argument(
        "--provider",
        choices=["imap", "gmail"],
        default="imap",
        help="The email provider to use.",
    )
    parser.add_argument(
        "--generate-filters",
        action="store_true",
        help="Generate the mailfilter.xml file from the database.",
    )
    args = parser.parse_args()

    if args.generate_filters:
        generate_filters()
    else:
        if args.provider == "imap":
            provider = ImapService(CONFIG.imap)
        elif args.provider == "gmail":
            provider = GmailService(CONFIG.gmail)
        else:
            raise ValueError(f"Invalid provider: {args.provider}")
        run_classification(provider)


if __name__ == "__main__":
    main()