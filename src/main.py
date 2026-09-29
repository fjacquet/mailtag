#!/usr/bin/env python3

"""
Main CLI entry point for the mailtag email classification script.
"""

import sys
from pathlib import Path

import click
from loguru import logger

try:
    from mailtag.config import CONFIG
except RuntimeError as e:
    print(f"❌ Configuration file error: {e}")
    print("Please ensure config.toml exists and is valid TOML format")
    sys.exit(1)
except ValueError as e:
    print(f"❌ Configuration validation error: {e}")
    print("Please check your config.toml and .env file settings")
    sys.exit(1)
from mailtag.gmail_api import GmailApiService
from mailtag.imap_service import ImapService
from mailtag.logging_config import setup_logging
from mailtag.utils.tasks import run_classification


def start_classification_run(provider, validate):
    """Sets up and starts the classification run."""
    from mailtag.utils.db_backup import backup_all_databases, cleanup_old_backups

    db_dir = Path("db")
    logger.info("Creating database backups...")
    backup_all_databases(db_dir)
    cleanup_old_backups(db_dir / "backups", keep_count=10)

    providers_to_run = []
    if provider in ("imap", "all") and CONFIG.imap:
        providers_to_run.append(ImapService(CONFIG.imap, CONFIG.fast_parse))
    if provider in ("gmail", "all") and CONFIG.gmail:
        providers_to_run.append(GmailApiService(CONFIG.gmail, CONFIG.fast_parse))

    if not providers_to_run:
        logger.warning("No providers configured or selected. Check your config.toml.")
        return

    for p in providers_to_run:
        logger.info(f"Running classification for provider: {type(p).__name__}")
        run_classification(p, validate)


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
    help="Run in validation mode (read-only): classify and log, move and learn nothing.",
)
def run(provider, validate):
    """Run the email classification process."""
    start_classification_run(provider, validate)


@cli.command()
@click.option("--host", default=None, help="Host to bind to (overrides config.toml)")
@click.option("--port", default=None, type=int, help="Port to bind to (overrides config.toml)")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def serve(host, port, reload):
    """Start the webhook API server.

    Launches a FastAPI server with classification endpoints for N8N
    and other webhook integrations. See /docs for Swagger UI.
    """
    import uvicorn

    from mailtag.api import create_app

    if not CONFIG.webhook.api_key:
        logger.warning("No WEBHOOK_API_KEY set — API will be unprotected!")

    app = create_app()
    uvicorn_host = host or CONFIG.webhook.host
    uvicorn_port = port or CONFIG.webhook.port

    logger.info(f"Starting MailTag API on {uvicorn_host}:{uvicorn_port}")
    logger.info(f"Swagger UI: http://{uvicorn_host}:{uvicorn_port}/docs")

    uvicorn.run(app, host=uvicorn_host, port=uvicorn_port, reload=reload)


if __name__ == "__main__":
    cli()
