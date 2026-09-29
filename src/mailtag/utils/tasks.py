import imaplib
from datetime import date
from pathlib import Path

from loguru import logger

from mailtag.archive import run_archive
from mailtag.classifier import Classifier
from mailtag.config import CONFIG, GmailConfig, ImapConfig
from mailtag.imap_service import ImapService
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders
from mailtag.taxonomy_store import TaxonomyStore


def _run_fast_parse_on_folder(
    provider: ImapService,
    folder_name: str,
    validate: bool,
    pending: PendingArchive,
    rules: TaxonomyStore,
) -> list[str]:
    """Pass 1: route each email a taxonomy rule covers; return the UIDs left for Pass 3."""
    logger.info(f"Starting Pass 1 on folder: {folder_name}")
    try:
        provider.client.select_folder(folder_name)
    except (imaplib.IMAP4.error, KeyError, ValueError) as e:
        logger.warning(f"Could not select folder '{folder_name}'. It might not exist. Skipping. Error: {e}")
        return []

    all_uids = provider.client.search()
    if not all_uids:
        logger.info(f"No emails to process in {folder_name}.")
        return []

    logger.info(f"Found {len(all_uids)} emails in {folder_name}.")
    remaining: list[str] = []
    for i in range(0, len(all_uids), provider.fast_parse_config.batch_size):
        batch_uids = all_uids[i : i + provider.fast_parse_config.batch_size]
        routed: list[RoutedMail] = []
        for uid, header_data in provider.get_email_headers(batch_uids).items():
            category = rules.category_for(header_data["sender_address"])
            if category:
                logger.info(
                    f'Email "{header_data["subject"]}" from {header_data["sender_address"]}'
                    f" -> Category: {category} (Pass 1)"
                )
                routed.append(RoutedMail.from_headers(uid, category, header_data))
            else:
                remaining.append(uid)
        if routed:
            route_to_action_folders(provider, pending, routed, validate, date.today())

    logger.info(f"Pass 1 on {folder_name} complete. {len(all_uids) - len(remaining)} emails routed.")
    return remaining


def pending_archive_path(config: ImapConfig | GmailConfig, default: str) -> Path:
    """Each IMAP account keeps its own pending archive: one account's sweep cannot see the
    other's mails and would remove their entries as orphans."""
    return Path(config.pending_archive_file or default)


def junk_folder(provider: ImapService) -> str | None:
    return provider.config.junk_folder_name or provider.fast_parse_config.junk_folder_name


def run_classification(provider_instance: ImapService, validate: bool, classifier: Classifier) -> None:
    """Pass 1 (rules) on junk and INBOX, Pass 3 (nomic/Gemma) on the rest, then the archive sweep.

    The classifier is built once per run and shared by the providers, so the models load once.
    """
    try:
        rules = classifier.taxonomy_store
        pending = PendingArchive(
            pending_archive_path(provider_instance.config, CONFIG.taxonomy.pending_archive_file)
        )

        with provider_instance.connect() as provider:
            junk = junk_folder(provider)
            if junk:
                _run_fast_parse_on_folder(provider, junk, validate, pending, rules)
            remaining = _run_fast_parse_on_folder(provider, "INBOX", validate, pending, rules)

            logger.info(f"Starting Pass 3: AI classification for {len(remaining)} remaining emails...")
            if remaining:
                emails = provider.get_full_emails(remaining)
                results = classifier.classify_detailed(emails)
                moved = route_to_action_folders(
                    provider,
                    pending,
                    [RoutedMail.from_email(e, c) for e, (c, _) in zip(emails, results, strict=True)],
                    validate,
                    date.today(),
                )
                # Only mails that moved teach a rule: a failed move is retried next run
                moved_uids = {m.uid for m in moved}
                kept = [(e, r) for e, r in zip(emails, results, strict=True) if e.msg_id in moved_uids]
                if kept:
                    classifier.learn([e for e, _ in kept], [r for _, r in kept])
            logger.info("Pass 3 complete.")

            run_archive(provider, pending, rules, CONFIG.taxonomy.archive_after_days, date.today(), validate)
            logger.info("Analysis complete.")

    except (FileNotFoundError, ConnectionError) as e:
        logger.critical(e)
