#!/usr/bin/env python3

"""
Main CLI entry point for the mailtag email classification script.
"""

from pathlib import Path

import click
from loguru import logger

from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.filter_generator import FilterGenerator
from mailtag.gmail_service import GmailService
from mailtag.imap_service import ImapService
from mailtag.logging_config import setup_logging
from mailtag.utils.tasks import run_classification

PROVIDER_CLASSES = {
    "imap": ImapService,
    "gmail": GmailService,
}


def generate_filters(database):
    """Generates the mailfilter.xml file."""
    output_path = Path("data/mailfilter.xml")
    generator = FilterGenerator(database.suggestion_db_path, output_path)
    generator.generate_filters()
    logger.info(f"Filters generated at {output_path}")


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
