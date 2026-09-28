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
            if destination == REVIEW and address not in own:  # never learn a rule for the owner
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
        for start in range(0, len(dest_uids), batch_size):
            provider.batch_move_emails(dest_uids[start : start + batch_size], destination)

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


def empty_legacy_folders(client, legacy: list[str], live_folders: list[str]) -> list[str]:
    """Legacy folders with no mail, whose live children are also removable; deepest first.

    A folder counts as removable only if every still-existing folder nested under it (a
    protected folder, a folder with mail, or one that never was a legacy folder) is itself
    removable - so a parent is never listed ahead of a child that must stay.
    """
    candidates = set(folders_to_migrate(legacy)) & set(live_folders)
    order = sorted(candidates, key=lambda f: (-f.count("/"), f))
    removable: dict[str, bool] = {}

    for folder in order:
        try:
            client.select_folder(folder, readonly=True)
            is_empty = client.search(["ALL"]) == []
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not read folder {folder}: {e}")
            is_empty = False
        prefix = f"{folder}/"
        children = [f for f in live_folders if f.startswith(prefix)]
        removable[folder] = is_empty and all(removable.get(child, False) for child in children)

    return [folder for folder in order if removable[folder]]
