import imaplib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from loguru import logger

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.gmail_service import GmailService
from mailtag.imap_service import ImapService
from mailtag.utils.domain_utils import extract_domain, is_non_commercial_domain_cached

Provider = ImapService | GmailService


def _run_fast_parse_on_folder(
    provider: ImapService, database: ClassificationDatabase, folder_name: str, validate: bool
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """
    Runs the fast parse (Pass 1) on a specific folder.

    Args:
        provider: The IMAP service provider.
        database: The classification database.
        folder_name: The name of the folder to process.
        validate: A boolean indicating if it's a dry run.

    Returns:
        Tuple of (UIDs for Pass 2, headers dict for reuse in Pass 2).
    """
    logger.info(f"Starting Pass 1 on folder: {folder_name}")
    try:
        provider.client.select_folder(folder_name)
    except (imaplib.IMAP4.error, KeyError, ValueError) as e:
        logger.warning(f"Could not select folder '{folder_name}'. It might not exist. Skipping. Error: {e}")
        return [], {}

    all_uids = provider.client.search()
    if not all_uids:
        logger.info(f"No emails to process in {folder_name}.")
        return [], {}

    logger.info(f"Found {len(all_uids)} emails in {folder_name}.")
    uids_to_process_pass2 = []
    pass2_headers: dict[str, dict[str, str]] = {}

    for i in range(0, len(all_uids), provider.fast_parse_config.batch_size):
        batch_uids = all_uids[i : i + provider.fast_parse_config.batch_size]
        headers = provider.get_email_headers(batch_uids)

        emails_to_move = {}
        for uid, header_data in headers.items():
            sender_address = header_data["sender_address"]
            subject = header_data["subject"]
            classification = database.get_dominant_classification(sender_address)
            if classification:
                logger.info(f'Email "{subject}" from {sender_address} -> Category: {classification} (Pass 1)')
                if classification not in emails_to_move:
                    emails_to_move[classification] = []
                emails_to_move[classification].append(uid)
            else:
                uids_to_process_pass2.append(uid)
                pass2_headers[uid] = header_data

        for classification, uids in emails_to_move.items():
            if not validate:
                provider.batch_move_emails(uids, classification)

    moved_count = len(all_uids) - len(uids_to_process_pass2)
    logger.info(f"Pass 1 on {folder_name} complete. {moved_count} emails moved.")
    return uids_to_process_pass2, pass2_headers


def _run_domain_classification_pass(
    provider: ImapService,
    database: ClassificationDatabase,
    uids_to_process: list[str],
    validate: bool,
    prefetched_headers: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """
    Runs the domain-based classification (Pass 2) on remaining emails.
    Groups emails by domain, deduplicates, and applies domain-based rules.

    Args:
        provider: The IMAP service provider.
        database: The classification database.
        uids_to_process: List of UIDs from Pass 1 that need further processing.
        validate: A boolean indicating if it's a dry run.
        prefetched_headers: Headers already fetched in Pass 1 (avoids duplicate IMAP fetch).

    Returns:
        A list of UIDs that still need AI classification (Pass 3).
    """
    logger.info(f"Starting Pass 2: Domain-based classification for {len(uids_to_process)} emails...")

    if not uids_to_process:
        return []

    # Reuse headers from Pass 1 if available, otherwise fetch
    if prefetched_headers and len(prefetched_headers) == len(uids_to_process):
        headers = prefetched_headers
        logger.debug("Reusing headers from Pass 1 (skipping duplicate IMAP fetch)")
    else:
        headers = provider.get_email_headers(uids_to_process)

    # Group emails by domain
    domain_groups = defaultdict(list)
    non_commercial_uids = []

    for uid, header_data in headers.items():
        sender_address = header_data["sender_address"]
        domain = extract_domain(sender_address)

        if not domain:
            non_commercial_uids.append(uid)
            continue

        # Skip non-commercial domains (gmail.com, yahoo.com, etc.)
        if is_non_commercial_domain_cached(domain):
            logger.debug(f"Skipping non-commercial domain {domain} for UID {uid}")
            non_commercial_uids.append(uid)
            continue

        domain_groups[domain].append(uid)

    logger.info(
        f"Found {len(domain_groups)} commercial domains and {len(non_commercial_uids)} non-commercial emails"
    )

    uids_for_pass3 = non_commercial_uids.copy()
    emails_moved = 0

    # Process each domain group
    for domain, domain_uids in domain_groups.items():
        logger.debug(f"Processing domain {domain} with {len(domain_uids)} emails")

        # Check if we have a domain classification
        category = database.get_category_by_domain(domain)

        if category:
            logger.info(f"Found domain classification: {domain} -> {category}")

            # Apply category to ALL emails from this domain
            for uid in domain_uids:
                try:
                    header_data = headers[uid]
                    sender_address = header_data["sender_address"]
                    subject = header_data["subject"]

                    logger.info(
                        f'Email "{subject}" from {sender_address} -> Category: {category} (domain rule)'
                    )

                    # Update suggestion database to learn from domain classification
                    database.update_suggestion(sender_address, category)

                except (KeyError, ValueError, TypeError, OSError) as e:
                    logger.error(f"Could not update database for email UID {uid}: {e}")

            # Batch move all emails from this domain
            if not validate and category not in ["Unclassified", "À Classer", "(Model Error)"]:
                try:
                    provider.batch_move_emails(domain_uids, category)
                    emails_moved += len(domain_uids)
                    logger.info(f"Moved {len(domain_uids)} emails from {domain} to {category}")
                except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                    logger.error(f"Could not move emails from domain {domain}: {e}")
                    uids_for_pass3.extend(domain_uids)
        else:
            # No domain classification found, keep for Pass 3
            logger.debug(
                f"No domain classification for {domain}, keeping {len(domain_uids)} emails for Pass 3"
            )
            uids_for_pass3.extend(domain_uids)

    logger.info(
        f"Pass 2 complete. Moved {emails_moved} emails via domain rules."
        + f" {len(uids_for_pass3)} emails remain for Pass 3."
    )
    return uids_for_pass3


def run_classification(provider_instance: Provider, database: ClassificationDatabase, validate: bool) -> None:
    """Runs the email classification process using a given provider instance."""
    try:
        classifier = Classifier(CONFIG, database)

        with provider_instance.connect() as provider:
            if isinstance(provider, ImapService):
                provider.get_folder_hierarchy()

                # --- Fast Parse (Pass 1) on Junk Folder ---
                junk_folder = provider.fast_parse_config.junk_folder_name
                if junk_folder:
                    _run_fast_parse_on_folder(provider, database, junk_folder, validate)
                    database.flush()

                # --- Fast Parse (Pass 1) on INBOX ---
                uids_to_process_pass2, pass2_headers = _run_fast_parse_on_folder(
                    provider, database, "INBOX", validate
                )
                database.flush()

                # --- Pass 2: Domain-based classification ---
                uids_to_process_pass3 = _run_domain_classification_pass(
                    provider, database, uids_to_process_pass2, validate,
                    prefetched_headers=pass2_headers,
                )
                database.flush()

                # --- Pass 3: AI classification for remaining emails ---
                logger.info(
                    f"Starting Pass 3: AI classification for {len(uids_to_process_pass3)} remaining emails..."
                )
                if uids_to_process_pass3:
                    full_emails = provider.get_full_emails(uids_to_process_pass3)

                    # Dump email addresses for manual matching
                    _dump_pass3_emails_for_manual_matching(full_emails)

                    # Batch classify: uses batch embeddings for Signal 5
                    categories = classifier.classify_emails_batch(full_emails)

                    # Accumulate moves by category for batch IMAP operations
                    moves: dict[str, list[str]] = {}
                    for email_obj, category in zip(full_emails, categories, strict=True):
                        logger.info(
                            f'Email "{email_obj.subject}" from {email_obj.sender_address}'
                            f" -> Category: {category}"
                        )
                        if not validate and category not in [
                            "Unclassified",
                            "À Classer",
                            "(Model Error)",
                        ]:
                            moves.setdefault(category, []).append(email_obj.msg_id)

                    # Execute batch moves per category
                    for category, uids in moves.items():
                        try:
                            provider.batch_move_emails(uids, category)
                        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                            logger.error(f"Could not batch-move {len(uids)} emails to {category}: {e}")

                    database.flush()
                logger.info("Pass 3 complete.")

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
                    except (KeyError, ValueError, TypeError, AttributeError) as e:
                        logger.error(f"Could not process email {email.msg_id}: {e}")

                classifier.flush_proposals()
                database.flush()

            logger.info("Analysis complete.")

    except (FileNotFoundError, ConnectionError) as e:
        logger.critical(e)
        return


def _dump_pass3_emails_for_manual_matching(emails):
    """
    Dump all email addresses that reach Pass 3 (AI classification) to a file for manual matching.

    Args:
        emails: List of Email objects that need AI classification
    """
    if not emails:
        return

    # Create dump data structure
    dump_data = {
        "timestamp": datetime.now().isoformat(),
        "total_emails": len(emails),
        "emails_for_manual_matching": [],
    }

    # Extract unique sender addresses with sample subjects
    sender_data = defaultdict(list)
    for email in emails:
        sender_data[email.sender_address].append(
            {
                "subject": email.subject[:100],  # Truncate long subjects
                "sender_name": email.sender_name,
                "msg_id": email.msg_id,
            }
        )

    # Build the dump with sender statistics
    for sender_address, email_samples in sender_data.items():
        domain = extract_domain(sender_address)
        dump_data["emails_for_manual_matching"].append(
            {
                "sender_address": sender_address,
                "domain": domain,
                "email_count": len(email_samples),
                "is_non_commercial": is_non_commercial_domain_cached(domain),
                "sample_emails": email_samples[:3],  # Keep max 3 samples per sender
                "suggested_category": "",  # Empty field for manual filling
                "notes": "",  # Empty field for manual notes
            }
        )

    # Sort by email count (most frequent senders first)
    dump_data["emails_for_manual_matching"].sort(key=lambda x: x["email_count"], reverse=True)

    # Save to file
    dump_file = Path("data") / f"pass3_manual_matching_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    dump_file.parent.mkdir(exist_ok=True)

    with open(dump_file, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Dumped {len(emails)} emails from {len(sender_data)} unique senders to {dump_file}")
    logger.info(
        "Top senders: "
        + f"{', '.join([f'{addr} ({len(samples)})' for addr, samples in list(sender_data.items())[:5]])}"
    )
