"""Move classified emails into action folders and remember their category (spec section 5)."""

import imaplib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from loguru import logger

from .action_rules import choose_action
from .models import Email
from .pending_archive import PendingArchive
from .taxonomy import REVIEW


@dataclass(frozen=True)
class RoutedMail:
    uid: str
    category: str
    sender_address: str
    subject: str
    message_id: str
    has_unsubscribe: bool
    is_bulk: bool

    @classmethod
    def from_headers(cls, uid: str, category: str, header: dict) -> "RoutedMail":
        return cls(
            uid,
            category,
            header["sender_address"],
            header["subject"],
            header.get("message_id", ""),
            header.get("has_unsubscribe", False),
            header.get("is_bulk", False),
        )

    @classmethod
    def from_email(cls, email: Email, category: str) -> "RoutedMail":
        return cls(
            email.msg_id,
            category,
            email.sender_address,
            email.subject,
            email.message_id,
            email.has_unsubscribe,
            email.is_bulk,
        )


def route_to_action_folders(
    provider, pending: PendingArchive, mails: list[RoutedMail], validate: bool, today: date
) -> int:
    """Move each email to its action folder and record its category; return the number moved."""
    by_folder: dict[str, list[RoutedMail]] = defaultdict(list)
    for m in mails:
        folder = choose_action(
            m.category, m.sender_address, m.subject, has_unsubscribe=m.has_unsubscribe, is_bulk=m.is_bulk
        )
        logger.info(f'Email "{m.subject}" from {m.sender_address} -> {m.category} / {folder}')
        by_folder[folder].append(m)

    if validate:
        return 0

    moved = 0
    for folder, group in by_folder.items():
        try:
            provider.batch_move_emails([m.uid for m in group], folder)
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"Could not move {len(group)} emails to {folder}: {e}")
            continue
        moved += len(group)
        for m in group:
            if not m.message_id:
                logger.warning(f"No Message-ID for UID {m.uid} ({m.sender_address}); it will not be archived")
                continue
            category = None if m.category == REVIEW else m.category
            pending.add(m.message_id, category, m.sender_address, today.isoformat())
        pending.save()
    return moved
