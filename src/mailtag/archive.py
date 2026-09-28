"""End-of-run sweep: archive read emails, learn from review, drop orphan entries (spec section 6)."""

import email
import imaplib
from collections import defaultdict
from datetime import date, timedelta

from loguru import logger

from .pending_archive import PendingArchive
from .taxonomy import ACTION_FOLDERS, REVIEW, TAXONOMY

_MESSAGE_ID_FETCH = b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"


def _message_ids(client, uids: list[int]) -> dict[int, str]:
    if not uids:
        return {}
    ids = {}
    for uid, data in client.fetch(uids, [_MESSAGE_ID_FETCH]).items():
        key = next((k for k in data if k.startswith(b"BODY[HEADER.FIELDS")), None)
        if key:
            mid = str(email.message_from_bytes(data[key]).get("Message-ID") or "").strip()
            if mid:
                ids[uid] = mid
    return ids


def _learn_from_review(client, pending: PendingArchive, rules, present: set[str], validate: bool) -> int:
    """Entries sent to review that the user filed into a category become validated sender rules."""
    waiting = {mid: e for mid, e in pending.items() if e["category"] is None and mid not in present}
    learned = 0
    for category in TAXONOMY:
        if not waiting:
            break
        try:
            if not client.folder_exists(category):
                continue
            client.select_folder(category)
            found_mids = [mid for mid in list(waiting) if client.search(["HEADER", "Message-ID", mid])]
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not read folder {category}: {e}")
            continue
        for mid in found_mids:
            logger.info(f"Learned rule from review: {waiting[mid]['sender']} -> {category}")
            if not validate:
                rules.set_validated(waiting[mid]["sender"], category)
                pending.remove(mid)
            del waiting[mid]
            learned += 1
    return learned


def run_archive(
    provider, pending: PendingArchive, rules, days: int, today: date, validate: bool = False
) -> dict:
    """Archive seen, unflagged emails received `days` ago or more into their category."""
    client = provider.client
    cutoff = today - timedelta(days=days)
    present: set[str] = set()
    archived = 0
    unreadable = False

    for folder in ACTION_FOLDERS:
        try:
            if not client.folder_exists(folder):
                continue
            client.select_folder(folder)
            ids = _message_ids(client, client.search(["ALL"]))
            eligible = (
                None if folder == REVIEW else set(client.search(["SEEN", "UNFLAGGED", "BEFORE", cutoff]))
            )
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not read folder {folder}: {e}")
            unreadable = True
            continue

        present.update(ids.values())
        if folder == REVIEW:
            continue

        moves: dict[str, list[int]] = defaultdict(list)
        for uid, mid in ids.items():
            entry = pending.get(mid)
            if uid in eligible and entry and entry["category"]:
                moves[entry["category"]].append(uid)

        for category, uids in moves.items():
            logger.info(f"Archiving {len(uids)} emails from {folder} to {category}")
            if validate:
                continue
            try:
                provider.batch_move_emails(uids, category)
            except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                logger.error(f"Could not archive {len(uids)} emails to {category}: {e}")
                continue
            for uid in uids:
                pending.remove(ids[uid])
                present.discard(ids[uid])
            archived += len(uids)

    learned = _learn_from_review(client, pending, rules, present, validate)

    # A folder that could not be read tells us nothing about whether its entries are
    # orphans — never treat that as evidence, so skip orphan removal entirely this run.
    orphans = [] if unreadable else [mid for mid, _ in pending.items() if mid not in present]
    if not validate:
        for mid in orphans:
            pending.remove(mid)
        pending.save()
        rules.save()

    logger.info(f"Archive sweep: {archived} archived, {learned} learned, {len(orphans)} orphan entries")
    return {"archived": archived, "learned": learned, "orphans": len(orphans)}
