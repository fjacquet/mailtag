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


def run_classification(args, provider_instance):
    """Runs the email classification process using a given provider instance."""
    try:
        db_path = Path("db/sender_classification_db.json")
        database = ClassificationDatabase(db_path)
        classifier = Classifier(CONFIG, database)

        with provider_instance.connect() as provider:
            # Fast Parse Implementation for IMAP
            if isinstance(provider, ImapService):
                # Pass 1: Fast classification based on known senders
                logger.info("Starting Pass 1: Fast classification...")
                provider.mail.select("inbox")
                all_uids = provider.mail.uid('search', None, "ALL")[1][0].split()
                
                uids_to_process_pass2 = []
                
                for i in range(0, len(all_uids), CONFIG.fast_parse.batch_size):
                    batch_uids = all_uids[i:i+CONFIG.fast_parse.batch_size]
                    senders = provider.get_email_senders([uid.decode() for uid in batch_uids])
                    
                    emails_to_move = {}
                    for uid, sender_address in senders.items():
                        classification = database.get_dominant_classification(sender_address)
                        if classification:
                            if classification not in emails_to_move:
                                emails_to_move[classification] = []
                            emails_to_move[classification].append(uid)
                        else:
                            uids_to_process_pass2.append(uid)
                    
                    for classification, uids in emails_to_move.items():
                        if not args.validate:
                            provider.batch_move_emails(uids, classification)

                logger.info(f"Pass 1 complete. {len(all_uids) - len(uids_to_process_pass2)} emails moved.")
                
                # Pass 2: AI classification for remaining emails
                logger.info("Starting Pass 2: AI classification...")
                if uids_to_process_pass2:
                    full_emails = provider.get_full_emails(uids_to_process_pass2)
                    for email in full_emails:
                        try:
                            category = classifier.classify_email(email)
                            logger.info(
                                f'Email "{email.subject}" from {email.sender_address} -> Category: {category}'
                            )
                            if not args.validate:
                                if category not in ["Unclassified", "À Classer"]:
                                    provider.move_email(email, category)
                                else:
                                    provider.move_email(email, CONFIG.fast_parse.unclassified_folder_name)
                        except Exception as e:
                            logger.error(f"Could not process email {email.msg_id}: {e}")
                logger.info("Pass 2 complete.")

            else: # Original logic for Gmail or other providers
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
                        category = classifier.classify_email(email)
                        logger.info(
                            f'Email "{email.subject}" from {email.sender_address} -> Category: {category}'
                        )
                        if not args.validate and category not in ["Unclassified", "À Classer"]:
                            provider.move_email(email, category)
                    except Exception as e:
                        logger.error(f"Could not process email {email.msg_id}: {e}")

            logger.info("Analysis complete.")

    except (FileNotFoundError, ConnectionError) as e:
        logger.critical(e)
        return


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
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run in validation mode (read-only) to populate the database without moving emails.",
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
            logger.warning("No providers configured or selected. Check your config.toml.")
            return

        for provider in providers_to_run:
            logger.info(f"Running classification for provider: {type(provider).__name__}")
            run_classification(args, provider)
