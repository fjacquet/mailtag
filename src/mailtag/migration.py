"""Migrate mails from the 611 legacy folders into the 19 categories (spec section: design)."""

import email
import imaplib
from collections import Counter, defaultdict
from datetime import date

from loguru import logger

from .pending_archive import PendingArchive
from .taxonomy import _NOT_A_CATEGORY, ACTION_FOLDERS, PARA, REVIEW, TAXONOMY, category_folder, to_category
from .taxonomy_store import normalize_address
from .utils.email_parsing import parse_sender

_PARA_FOLDERS = {category_folder(c) for c in TAXONOMY} | set(PARA.values()) | {"Projets"}
_PROTECTED = set(TAXONOMY) | set(ACTION_FOLDERS) | _NOT_A_CATEGORY | {"INBOX"} | _PARA_FOLDERS
_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)]"


def folders_to_migrate(legacy: list[str]) -> list[str]:
    """Legacy folders to sweep: legacy minus categories, action folders, system folders, `INBOX`
    and `Contacts` itself (its children, e.g. `Contacts/Alice`, are ordinary legacy folders)."""
    return [folder for folder in legacy if folder not in _PROTECTED]


def destination_for(sender: str, folder_category: str | None, rules) -> str:
    """Destination category for one mail: the sender's rule (validated > learned > domain; none
    for the owner's own addresses); else the folder category; else REVIEW."""
    return rules.category_for(sender) or folder_category or REVIEW


def migrate_folder(
    provider,
    folder: str,
    folder_category: str | None,
    rules,
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
            destination = destination_for(address, folder_category, rules)
            if destination == folder:
                continue
            if destination not in TAXONOMY and destination != REVIEW:
                # A typo in a rule or override would otherwise create a new top-level folder
                logger.warning(f"Unknown destination {destination!r} for a mail in {folder}, left in place")
                continue
            by_destination[destination].append(uid)
            if destination == REVIEW and not rules.is_own(address):  # never learn a rule for the owner
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
                if entry and pending.get(entry[0]) is None:  # keep an entry a `run` already made
                    message_id, sender = entry
                    pending.add(message_id, None, sender, today.isoformat())
        for start in range(0, len(dest_uids), batch_size):
            provider.batch_move_emails(dest_uids[start : start + batch_size], destination)
        if destination == REVIEW:
            pending.save()  # right after the moves, so a crash later does not lose them

    return counts


def migrate_mailbox(
    provider,
    folders: list[str],
    overrides: dict,
    rules,
    pending: PendingArchive,
    today: date,
    apply: bool,
) -> dict:
    """Sweep every legacy folder; a folder in error is skipped and does not stop the others."""
    report: dict[str, dict] = {}
    totals: Counter[str] = Counter()
    skipped: list[str] = []
    aborted_at = None

    for folder in folders:
        category = overrides[folder] if folder in overrides else to_category(folder)
        try:
            counts = migrate_folder(provider, folder, category, rules, pending, today, apply)
        except imaplib.IMAP4.abort as e:
            # Connection lost: every later folder would fail too; a re-run resumes
            logger.error(f"Connection lost at {folder}: {e}")
            aborted_at = folder
            break
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
        "aborted_at": aborted_at,
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


def delete_empty_folders(client, removable: list[str], live_folders: list[str]) -> list[str]:
    """Delete `removable` (deepest first) if still empty; a folder whose child stays is kept."""
    kept: set[str] = set()
    deleted: list[str] = []
    for folder in removable:
        prefix = f"{folder}/"
        if any(f.startswith(prefix) and f not in deleted for f in live_folders):
            logger.warning(f"Keeping {folder}: a subfolder stays")
            kept.add(folder)
            continue
        try:
            client.select_folder(folder, readonly=True)
            if client.search(["ALL"]):
                logger.warning(f"Keeping {folder}: no longer empty")
                kept.add(folder)
                continue
            client.select_folder("INBOX", readonly=True)  # some servers refuse to delete the selected folder
            client.delete_folder(folder)
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not delete {folder}: {e}")
            kept.add(folder)
            continue
        deleted.append(folder)
        logger.info(f"Deleted {folder}")
    return deleted


# Folders renamed or merged when adopting the standard Promotions folder and PARA (old -> new), and
# duplicate system folders (created by Apple Mail) merged into the ones Infomaniak's webmail uses
_REORGANIZE = {
    **{c: category_folder(c) for c in TAXONOMY},
    "9-A revoir": REVIEW,
    "5-Promos": "Promotions",
    "Archives": "Archive",
    "Junk": "Spam",
    "Deleted Messages": "Trash",
    "Sent Messages": "Sent",
}


def reorganize_plan(live_folders: list[str]) -> dict:
    """Old folder -> new one: a rename when the new one does not exist yet, else a merge of the mails."""
    live = set(live_folders)
    plan: dict[str, list] = {"renames": [], "merges": []}
    for old, new in _REORGANIZE.items():
        if old in live:
            plan["merges" if new in live else "renames"].append((old, new))
    return plan


def reorganize(provider, plan: dict, apply: bool, batch_size: int = 500) -> dict:
    """Rename folders (IMAP RENAME, no mail copied) and merge duplicates, then delete the emptied ones."""
    client = provider.client
    failed: list[str] = []
    for old, new in plan["renames"]:
        logger.info(f"Rename {old} -> {new}")
        if not apply:
            continue
        try:
            client.rename_folder(old, new)
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not rename {old}: {e}")
            failed.append(old)
    for old, new in plan["merges"]:
        try:
            client.select_folder(old, readonly=not apply)
            uids = client.search(["ALL"])
            logger.info(f"Merge {len(uids)} mails {old} -> {new}")
            if not apply:
                continue
            for start in range(0, len(uids), batch_size):
                provider.batch_move_emails(uids[start : start + batch_size], new)
            if client.search(["ALL"]):
                raise imaplib.IMAP4.error(f"{old} is not empty after the merge")
            client.select_folder("INBOX", readonly=True)  # some servers refuse to delete the selected folder
            client.delete_folder(old)
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not merge {old}: {e}")
            failed.append(old)
    return {"renames": plan["renames"], "merges": plan["merges"], "failed": failed}
