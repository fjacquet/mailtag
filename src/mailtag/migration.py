"""Migrate mails from the 611 legacy folders into the 19 categories (spec section: design)."""

import email
import imaplib
from collections import Counter, defaultdict
from datetime import date

from loguru import logger

from .pending_archive import PendingArchive
from .taxonomy import _NOT_A_CATEGORY, ACTION_FOLDERS, REVIEW, TAXONOMY, to_category
from .taxonomy_store import normalize_address
from .utils.email_parsing import parse_sender

_PROTECTED = set(TAXONOMY) | set(ACTION_FOLDERS) | _NOT_A_CATEGORY | {"INBOX"}
_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)]"


def folders_to_migrate(legacy: list[str]) -> list[str]:
    """Legacy folders to sweep: legacy minus categories, action folders, system folders, `INBOX`
    and `Contacts` itself (its children, e.g. `Contacts/Alice`, are ordinary legacy folders)."""
    return [folder for folder in legacy if folder not in _PROTECTED]


def destination_for(sender: str, folder_category: str | None, rules, own: set[str]) -> str:
    """Destination category for one mail: owner's address -> folder category; else the
    sender's rule (validated > learned > domain); else the folder category; else REVIEW."""
    if sender not in own:
        category = rules.category_for(sender)
        if category:
            return category
    return folder_category or REVIEW


def migrate_folder(
    provider,
    folder: str,
    folder_category: str | None,
    rules,
    own: set[str],
    pending: PendingArchive,
    today: date,
    apply: bool,
    batch_size: int = 500,
) -> Counter[str]:
    """Sweep one legacy folder: group its mails by destination, move them when `apply` is set."""
    client = provider.client
    client.select_folder(folder, readonly=not apply)
    uids = client.search(["ALL"])
    by_destination: dict[str, list[int]] = defaultdict(list)
    review_entries: dict[int, tuple[str, str]] = {}  # uid -> (message_id, sender)

    for start in range(0, len(uids), batch_size):
        chunk = uids[start : start + batch_size]
        for uid, data in client.fetch(chunk, [_FETCH]).items():
            key = next((k for k in data if k.startswith(b"BODY[HEADER.FIELDS")), None)
            if key is None:
                continue
            msg = email.message_from_bytes(data[key])
            _, address = parse_sender(provider._parse_header_value(msg.get("From")))
            address = normalize_address(address)
            destination = destination_for(address, folder_category, rules, own)
            if destination == folder:
                continue
            by_destination[destination].append(uid)
            if destination == REVIEW:
                message_id = str(msg.get("Message-ID") or "").strip()
                if message_id:
                    review_entries[uid] = (message_id, address)

    counts: Counter[str] = Counter()
    for destination, dest_uids in by_destination.items():
        counts[destination] = len(dest_uids)
        if not apply:
            continue
        if destination == REVIEW:
            for uid in dest_uids:
                entry = review_entries.get(uid)
                if entry:
                    message_id, sender = entry
                    pending.add(message_id, None, sender, today.isoformat())
        provider.batch_move_emails(dest_uids, destination)

    if apply:
        pending.save()
    return counts


def migrate_mailbox(
    provider,
    folders: list[str],
    overrides: dict,
    rules,
    own: set[str],
    pending: PendingArchive,
    today: date,
    apply: bool,
) -> dict:
    """Sweep every legacy folder; a folder in error is skipped and does not stop the others."""
    report: dict[str, dict] = {}
    totals: Counter[str] = Counter()
    skipped: list[str] = []

    for folder in folders:
        category = overrides[folder] if folder in overrides else to_category(folder)
        try:
            counts = migrate_folder(provider, folder, category, rules, own, pending, today, apply)
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not migrate folder {folder}: {e}")
            skipped.append(folder)
            continue
        if counts:
            report[folder] = dict(counts)
            totals.update(counts)

    logger.info(f"Migration: {sum(totals.values())} mails, {len(skipped)} folders skipped")
    return {
        "folders": report,
        "totals": dict(totals),
        "review_total": totals.get(REVIEW, 0),
        "skipped_folders": skipped,
    }
