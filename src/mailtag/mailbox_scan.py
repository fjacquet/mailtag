"""Read-only pass over the existing folders: category counts per sender (spec section 1.1)."""

import email
import imaplib

from loguru import logger

from .taxonomy import to_category
from .taxonomy_store import normalize_address
from .utils.domain_utils import extract_domain
from .utils.email_parsing import parse_sender

_FETCH = b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"
_SAMPLES = 5


def scan_mailbox(provider, folders: list[str], overrides: dict | None = None, batch_size: int = 500) -> dict:
    """Sender -> name, domain, mails per category, sample subjects and (folder, uid) references."""
    client = provider.client
    overrides = overrides or {}
    senders: dict[str, dict] = {}
    by_folder: dict[str, dict] = {}
    skipped: list[str] = []

    for folder in folders:
        category = overrides[folder] if folder in overrides else to_category(folder)
        if category is None:
            continue
        folder_senders = by_folder.setdefault(folder, {"category": category, "senders": {}})["senders"]
        try:
            client.select_folder(folder, readonly=True)
            uids = client.search(["ALL"])
            for start in range(0, len(uids), batch_size):
                chunk = uids[start : start + batch_size]
                for uid, data in client.fetch(chunk, [_FETCH]).items():
                    key = next((k for k in data if k.startswith(b"BODY[HEADER.FIELDS")), None)
                    if key is None:
                        continue
                    msg = email.message_from_bytes(data[key])
                    name, address = parse_sender(provider._parse_header_value(msg.get("From")))
                    address = normalize_address(address)
                    if not address:
                        continue
                    entry = senders.setdefault(
                        address,
                        {"name": name, "domain": extract_domain(address), "categories": {},
                         "subjects": [], "refs": []},
                    )  # fmt: skip
                    entry["categories"][category] = entry["categories"].get(category, 0) + 1
                    folder_senders[address] = folder_senders.get(address, 0) + 1
                    if len(entry["refs"]) < _SAMPLES:
                        entry["subjects"].append(provider._parse_header_value(msg.get("Subject")))
                        entry["refs"].append([folder, int(uid)])
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not scan folder {folder}: {e}")
            skipped.append(folder)
            continue
        logger.info(f"Scanned {folder} -> {category}")

    logger.info(f"Scan: {len(senders)} senders, {len(skipped)} folders skipped")
    return {"senders": senders, "folders": by_folder, "skipped_folders": skipped}
