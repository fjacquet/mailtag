#!/usr/bin/env python3

"""
Main CLI entry point for the mailtag email classification script.
"""

from pathlib import Path

import click
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


def run_classification(provider_instance, database, validate):
    """Runs the email classification process using a given provider instance."""
    try:
        classifier = Classifier(CONFIG, database)

        with provider_instance.connect() as provider:
            # Fast Parse Implementation for IMAP
            if isinstance(provider, ImapService):
                logger.info("Starting Fast Parse classification for IMAP...")
                provider.client.select_folder("INBOX")
                all_uids = provider.client.search()

                uids_to_process_pass2 = []

                for i in range(0, len(all_uids), provider.fast_parse_config.batch_size):
                    batch_uids = all_uids[i : i + provider.fast_parse_config.batch_size]
                    headers = provider.get_email_headers(batch_uids)

                    emails_to_move = {}
                    for uid, header_data in headers.items():
                        sender_address = header_data["sender_address"]
                        subject = header_data["subject"]
                        classification = database.get_dominant_classification(sender_address)
                        if classification:
                            logger.info(
                                f'Email "{subject}" from {sender_address} -> Category: {classification} (Pass 1)'
                            )
                            if classification not in emails_to_move:
                                emails_to_move[classification] = []
                            emails_to_move[classification].append(uid)
                        else:
                            uids_to_process_pass2.append(uid)

                    for classification, uids in emails_to_move.items():
                        if not validate:
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
                            if not validate:
                                if category not in ["Unclassified", "À Classer", "(Model Error)"]:
                                    provider.move_email(email, category)
                        except Exception as e:
                            logger.error(f"Could not process email {email.msg_id}: {e}")
                logger.info("Pass 2 complete.")

            else:  # Original logic for Gmail or other providers
                emails = provider.get_emails()

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
                        if not validate and category not in ["Unclassified", "À Classer"]:
                            provider.move_email(email, category)
                    except Exception as e:
                        logger.error(f"Could not process email {email.msg_id}: {e}")

            logger.info("Analysis complete.")

    except (FileNotFoundError, ConnectionError) as e:
        logger.critical(e)
        return


def generate_filters(database):
    """Generates the mailfilter.xml file."""
    output_path = Path("data/mailfilter.xml")
    generator = FilterGenerator(database.suggestion_db_path, output_path)
    generator.generate_filters()
    logger.info(f"Filters generated at {output_path}")


@click.group()
def cli():
    """MailTag: Email Classification Tool"""
    setup_logging(CONFIG.logging.level, CONFIG.logging.file)


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["imap", "gmail", "all"]),
    default="all",
    help="The email provider to use.",
)
@click.option(
    "--validate",
    is_flag=True,
    help="Run in validation mode (read-only) to populate the database without moving emails.",
)
def start_classification_run(provider, validate):
    """Sets up and starts the classification run."""
    suggestion_db_path = Path("db/sender_classification_db.json")
    validated_db_path = Path("db/validated_classification_db.json")
    database = ClassificationDatabase(suggestion_db_path, validated_db_path)

    providers_to_run = []
    if provider == "all":
        if CONFIG.imap:
            providers_to_run.append(ImapService(CONFIG.imap, CONFIG.fast_parse))
        if CONFIG.gmail:
            providers_to_run.append(GmailService(CONFIG.gmail))
    else:
        provider_class = PROVIDER_CLASSES.get(provider)
        if not provider_class:
            raise ValueError(f"Invalid provider: {provider}")

        if provider == "imap" and CONFIG.imap:
            providers_to_run.append(provider_class(CONFIG.imap, CONFIG.fast_parse))
        elif provider == "gmail" and CONFIG.gmail:
            providers_to_run.append(provider_class(CONFIG.gmail))

    if not providers_to_run:
        logger.warning("No providers configured or selected. Check your config.toml.")
        return

    for p in providers_to_run:
        logger.info(f"Running classification for provider: {type(p).__name__}")
        run_classification(p, database, validate)


@click.group()
def cli():
    """MailTag: Email Classification Tool"""
    setup_logging(CONFIG.logging.level, CONFIG.logging.file)


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["imap", "gmail", "all"]),
    default="all",
    help="The email provider to use.",
)
@click.option(
    "--validate",
    is_flag=True,
    help="Run in validation mode (read-only) to populate the database without moving emails.",
)
def run(provider, validate):
    """Run the email classification process."""
    start_classification_run(provider, validate)


@cli.command()
def filters():
    """Generate the mailfilter.xml file from the database."""
    suggestion_db_path = Path("db/sender_classification_db.json")
    validated_db_path = Path("db/validated_classification_db.json")
    database = ClassificationDatabase(suggestion_db_path, validated_db_path)
    generate_filters(database)


if __name__ == "__main__":
    cli()
