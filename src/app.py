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
from mailtag.gmail_service import GmailService
from mailtag.imap_service import ImapService
from mailtag.logging_config import setup_logging

PROVIDER_CLASSES = {
    "imap": ImapService,
    "gmail": GmailService,
}


def run_classification(args, provider):
    """Runs the email classification process."""
    try:
        db_path = Path("db/sender_classification_db.json")
        database = ClassificationDatabase(db_path)
        classifier = Classifier(CONFIG, database)
    except FileNotFoundError as e:
        logger.critical(e)
        return

    provider.connect()

    emails = provider.get_emails(
        subject=args.subject,
        sender=args.sender,
        status=args.status,
    )

    if not emails:
        logger.info("No emails found matching the criteria.")
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
            if category != "Unclassified":
                provider.move_email(email, args.destination)
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
        choices=["imap", "gmail", "all"],
        default="all",
        help="The email provider to use.",
    )
    parser.add_argument(
        "--destination",
        type=str,
        default="Processed",
        help="The destination folder/label for moving emails.",
    )
    parser.add_argument(
        "--subject",
        type=str,
        help="Filter emails by subject (case-insensitive).",
    )
    parser.add_argument(
        "--sender",
        type=str,
        help="Filter emails by sender (case-insensitive).",
    )
    parser.add_argument(
        "--status",
        choices=["SEEN", "UNSEEN"],
        help="Filter emails by status (SEEN or UNSEEN).",
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
        providers_to_run = []
        if args.provider == "all":
            if CONFIG.imap:
                providers_to_run.append(ImapService(CONFIG.imap))
            if CONFIG.gmail:
                providers_to_run.append(GmailService(CONFIG.gmail))
        else:
            provider_class = PROVIDER_CLASSES.get(args.provider)
            if not provider_class:
                raise ValueError(f"Invalid provider: {args.provider}")

            if args.provider == "imap" and CONFIG.imap:
                providers_to_run.append(provider_class(CONFIG.imap))
            elif args.provider == "gmail" and CONFIG.gmail:
                providers_to_run.append(provider_class(CONFIG.gmail))

        if not providers_to_run:
            logger.warning(
                "No providers configured or selected. Check your config.toml."
            )
            return

        for provider in providers_to_run:
            logger.info(f"Running classification for provider: {type(provider).__name__}")
            run_classification(args, provider)
