from typing import Union

from loguru import logger

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.gmail_service import GmailService
from mailtag.imap_service import ImapService

Provider = Union[ImapService, GmailService]


def run_classification(provider_instance: Provider, database: ClassificationDatabase, validate: bool) -> None:
    """Runs the email classification process using a given provider instance."""
    try:
        classifier = Classifier(CONFIG, database)

        with provider_instance.connect() as provider:
            if isinstance(provider, ImapService):
                provider.get_folder_hierarchy()
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
