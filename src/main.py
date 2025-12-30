#!/usr/bin/env python3

"""
Main CLI entry point for the mailtag email classification script.
"""

import json
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


def refresh_imap_folders(imap_service: ImapService) -> None:
    """Refresh the IMAP folder structure from the live server."""
    try:
        with imap_service.connect():
            # Get the folder hierarchy from the IMAP server
            folders = imap_service.get_folder_hierarchy()

            # Save to imap_folders.json
            folder_path = Path("data/imap_folders.json")
            with folder_path.open("w", encoding="utf-8") as f:
                json.dump(folders, f, indent=2)

            logger.info(f"Successfully refreshed IMAP folders: {len(folders)} folders found")
    except Exception as e:
        logger.error(f"Failed to refresh IMAP folders: {e}")
        # If refresh fails, stop processing - critical error
        raise RuntimeError("Cannot proceed without fresh IMAP folder structure") from e


def generate_filters(database):
    """Generates the mailfilter.xml file."""
    output_path = Path("data/mailfilter.xml")
    generator = FilterGenerator(database, output_path)
    generator.generate_filters()
    logger.info(f"Filters generated at {output_path}")


def start_classification_run(provider, validate):
    """Sets up and starts the classification run."""
    from mailtag.utils.db_backup import backup_all_databases, cleanup_old_backups

    db_dir = Path("db")
    suggestion_db_path = db_dir / "sender_classification_db.json"
    validated_db_path = db_dir / "validated_classification_db.json"

    # Backup databases once at start of run
    logger.info("Creating database backups...")
    backup_all_databases(db_dir)
    cleanup_old_backups(db_dir / "backups", keep_count=10)

    database = ClassificationDatabase(suggestion_db_path, validated_db_path)

    providers_to_run = []
    if provider == "all":
        if CONFIG.imap:
            imap_service = ImapService(CONFIG.imap, CONFIG.fast_parse)
            # Refresh IMAP folders at startup if configured
            if CONFIG.general.use_imap_folders_for_classification:
                logger.info("Refreshing IMAP folders at startup...")
                refresh_imap_folders(imap_service)
            providers_to_run.append(imap_service)
        if CONFIG.gmail:
            providers_to_run.append(GmailService(CONFIG.gmail))
    else:
        provider_class = PROVIDER_CLASSES.get(provider)
        if not provider_class:
            raise ValueError(f"Invalid provider: {provider}")

        if provider == "imap" and CONFIG.imap:
            imap_service = provider_class(CONFIG.imap, CONFIG.fast_parse)
            # Refresh IMAP folders at startup if configured
            if CONFIG.general.use_imap_folders_for_classification:
                logger.info("Refreshing IMAP folders at startup...")
                refresh_imap_folders(imap_service)
            providers_to_run.append(imap_service)
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


@cli.command()
@click.option(
    "--output",
    default="data/domain_candidates.json",
    help="Output file path for domain candidates JSON.",
)
@click.option(
    "--min-emails",
    default=5,
    type=int,
    help="Minimum number of emails required from a domain to be a candidate.",
)
@click.option(
    "--top",
    default=50,
    type=int,
    help="Number of top candidates to show in report.",
)
def analyze_domains(output: str, min_emails: int, top: int):
    """Analyze Pass 3 files to identify domain classification candidates.

    This command scans pass3_manual_matching_*.json files to find commercial domains
    that frequently appear in AI fallback cases. These domains can be added to the
    domain classification database to reduce AI usage.

    Workflow:
    \b
    1. Run this command to generate domain_candidates.json
    2. Review the JSON file and add 'suggested_category' for each domain
    3. Run: python scripts/update_domain_db.py
    4. Re-run classification to measure impact
    """
    from mailtag.utils.domain_analyzer import DomainAnalyzer

    logger.info("Analyzing Pass 3 files for domain classification candidates...")

    # Initialize analyzer
    non_commercial_domains_path = Path("data/non_commercial_domains.yaml")
    if not non_commercial_domains_path.exists():
        logger.error(f"Non-commercial domains file not found: {non_commercial_domains_path}")
        return

    analyzer = DomainAnalyzer(non_commercial_domains_path)

    # Analyze Pass 3 files
    data_dir = Path("data")
    candidates = analyzer.analyze_pass3_files(data_dir, min_email_count=min_emails)

    if not candidates:
        logger.warning(
            "No domain candidates found. Make sure pass3_manual_matching_*.json files exist in data/"
        )
        return

    # Export to JSON
    output_path = Path(output)
    analyzer.export_candidates(candidates, output_path)

    # Generate and print report
    report = analyzer.generate_report(candidates, top_n=top)
    print()
    print(report)

    # Analyze existing domain DB for comparison
    domain_db_path = Path("db/domain_classifications.json")
    if domain_db_path.exists():
        stats = analyzer.analyze_existing_domains(domain_db_path)
        print()
        print("Current Domain Database Statistics:")
        print("-" * 80)
        print(f"Total domains: {stats.get('total_domains', 0)}")
        print(f"Total categories: {stats.get('total_categories', 0)}")
        print(f"Parent categories: {', '.join(stats.get('parent_categories', []))}")
        print()
        print("Top 5 categories:")
        for category, count in list(stats.get("top_categories", {}).items())[:5]:
            print(f"  {category}: {count} domains")
        print()

    logger.info(f"Review {output_path} and add categories, then run: python scripts/update_domain_db.py")


@cli.command()
@click.option(
    "--max-age",
    default=30,
    type=int,
    help="Maximum age in days for pass3 files to keep.",
)
@click.option(
    "--consolidate/--no-consolidate",
    default=True,
    help="Consolidate duplicate pass3 files from the same day.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deleted without actually deleting.",
)
def cleanup(max_age: int, consolidate: bool, dry_run: bool):
    """Clean up old data files and validate databases.

    Removes pass3_manual_matching files older than --max-age days.
    Optionally consolidates duplicate files from the same day.
    """
    from mailtag.utils.data_cleanup import (
        cleanup_old_pass3_files,
        consolidate_duplicate_pass3_files,
        get_pass3_file_stats,
    )
    from mailtag.utils.data_validation import validate_domain_classifications, validate_sender_classifications

    data_dir = Path("data")
    db_dir = Path("db")

    # Show current stats
    stats = get_pass3_file_stats(data_dir)
    print("\nPass3 Files Statistics:")
    print("-" * 40)
    print(f"Total files: {stats['total_files']}")
    print(f"Total size: {stats.get('total_size_mb', 0)} MB")
    print(f"Date range: {stats.get('oldest_date', 'N/A')} to {stats.get('newest_date', 'N/A')}")
    print()

    if dry_run:
        print("[DRY RUN] Would perform the following operations:\n")

    # Consolidate duplicates first
    if consolidate:
        if dry_run:
            print("- Consolidate duplicate pass3 files (keep first and last per day)")
        else:
            deleted = consolidate_duplicate_pass3_files(data_dir)
            print(f"Consolidated: deleted {deleted} duplicate files")

    # Clean old files
    if dry_run:
        print(f"- Delete pass3 files older than {max_age} days")
    else:
        deleted = cleanup_old_pass3_files(data_dir, max_age)
        print(f"Cleaned: deleted {deleted} old files")

    # Validate databases
    print("\nDatabase Validation:")
    print("-" * 40)

    domain_issues = validate_domain_classifications(db_dir / "domain_classifications.json")
    if domain_issues:
        print(f"Domain DB issues ({len(domain_issues)}):")
        for issue in domain_issues[:5]:
            print(f"  - {issue}")
        if len(domain_issues) > 5:
            print(f"  ... and {len(domain_issues) - 5} more")
    else:
        print("Domain DB: OK")

    sender_issues = validate_sender_classifications(db_dir / "sender_classification_db.json")
    if sender_issues:
        print(f"Sender DB issues ({len(sender_issues)}):")
        for issue in sender_issues[:5]:
            print(f"  - {issue}")
        if len(sender_issues) > 5:
            print(f"  ... and {len(sender_issues) - 5} more")
    else:
        print("Sender DB: OK")


@cli.command("db-stats")
def db_stats():
    """Show database statistics and health check."""
    from mailtag.utils.data_cleanup import get_pass3_file_stats
    from mailtag.utils.data_validation import get_database_stats
    from mailtag.utils.db_backup import get_backup_stats

    db_dir = Path("db")
    data_dir = Path("data")
    backup_dir = db_dir / "backups"

    # Database stats
    stats = get_database_stats(db_dir)

    print("\nDatabase Statistics:")
    print("=" * 60)

    if "sender_db" in stats:
        s = stats["sender_db"]
        print("\nSender Classification DB:")
        print(f"  Entries: {s['entries']}")
        print(f"  Total occurrences: {s['total_occurrences']}")
        print(f"  High-confidence entries (10+): {s['high_confidence_entries']}")
        print(f"  Size: {s['size_bytes']:,} bytes")

    if "domain_db" in stats:
        d = stats["domain_db"]
        print("\nDomain Classification DB:")
        print(f"  Entries: {d['entries']}")
        print(f"  Unique categories: {d['unique_categories']}")
        print(f"  Size: {d['size_bytes']:,} bytes")

    if "validated_db" in stats:
        v = stats["validated_db"]
        print("\nValidated Classification DB:")
        print(f"  Entries: {v['entries']}")
        print(f"  Size: {v['size_bytes']:,} bytes")

    # Pass3 stats
    pass3_stats = get_pass3_file_stats(data_dir)
    print("\nPass3 Manual Matching Files:")
    print(f"  Total files: {pass3_stats['total_files']}")
    print(f"  Total size: {pass3_stats.get('total_size_mb', 0)} MB")
    if pass3_stats.get('oldest_date'):
        print(f"  Date range: {pass3_stats['oldest_date']} to {pass3_stats['newest_date']}")

    # Backup stats
    backup_stats = get_backup_stats(backup_dir)
    print("\nBackups:")
    print(f"  Total backups: {backup_stats['total_backups']}")
    if backup_stats['total_backups'] > 0:
        print(f"  Total size: {backup_stats.get('total_size_mb', 0)} MB")
        print(f"  Oldest: {backup_stats.get('oldest_backup', 'N/A')}")
        print(f"  Newest: {backup_stats.get('newest_backup', 'N/A')}")


@cli.command("prune-db")
@click.option(
    "--min-count",
    default=3,
    type=int,
    help="Minimum occurrence count to keep (entries below this are removed).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be pruned without actually removing.",
)
def prune_db(min_count: int, dry_run: bool):
    """Remove low-confidence entries from sender classification database.

    Entries with total occurrence count below --min-count are removed.
    This helps reduce database size and improve signal quality.
    """
    import json

    from mailtag.utils.data_validation import prune_low_confidence_senders

    db_path = Path("db/sender_classification_db.json")

    if not db_path.exists():
        print("Sender classification database not found.")
        return

    # Load current data for analysis
    with open(db_path) as f:
        data = json.load(f)

    total_entries = len(data)
    would_prune = sum(1 for cats in data.values() if sum(cats.values()) < min_count)

    print("\nSender Classification Database Pruning:")
    print("=" * 60)
    print(f"Current entries: {total_entries}")
    print(f"Entries below threshold ({min_count}): {would_prune}")
    print(f"Would keep: {total_entries - would_prune}")
    print(f"Reduction: {would_prune / total_entries * 100:.1f}%")

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    if would_prune == 0:
        print("\nNo entries to prune.")
        return

    # Confirm before pruning
    if click.confirm(f"\nRemove {would_prune} low-confidence entries?"):
        pruned = prune_low_confidence_senders(db_path, min_count)
        print(f"\nPruned {pruned} entries from database.")
    else:
        print("\nPruning cancelled.")


if __name__ == "__main__":
    cli()
