"""Bulk review of 5-A revoir (spec docs/superpowers/specs/2026-09-29-revue-en-masse-design.md):
group review mails by domain or sender, then move the mails a rule now covers to their category."""

import imaplib
from collections import defaultdict

from loguru import logger

from .taxonomy import (
    REVIEW,
    category_folder,
    llm_sender_part,
    llm_sender_static_prompt,
    parse_category_number,
)
from .taxonomy_store import normalize_address
from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached

# A failed move loses only this many mails for the run (they stay in review, with their entries)
_MOVE_CHUNK = 500


def group_key(address: str) -> tuple[str, str]:
    """`("domain", domain)` for a commercial domain, else `("sender", address)`."""
    address = normalize_address(address)
    domain = extract_domain(address)
    if domain and not is_non_commercial_domain_cached(domain):
        return "domain", domain
    return "sender", address


def read_review_mails(provider, readonly: bool = True) -> list[dict]:
    """Headers (sender, subject, Message-ID) of every mail waiting in 5-A revoir."""
    client = provider.client
    if not client.folder_exists(REVIEW):
        return []
    client.select_folder(REVIEW, readonly=readonly)  # IMAP refuses to move out of a read-only mailbox
    uids = client.search(["ALL"])
    headers = provider.get_email_headers(uids) if uids else {}
    return [{"uid": uid, **h} for uid, h in headers.items()]


def review_groups(mails: list[dict], category_for, own: set[str], max_subjects: int = 5) -> dict[str, dict]:
    """Group mails a rule does not already cover, by domain or by sender for personal domains."""
    groups: dict[str, dict] = {}
    for m in mails:
        address = normalize_address(m["sender_address"])
        if not address or address in own or category_for(address):
            continue
        kind, key = group_key(address)
        g = groups.setdefault(key, {"kind": kind, "mails": 0, "senders": {}, "subjects": []})
        g["mails"] += 1
        s = g["senders"].setdefault(address, {"name": m.get("sender_name") or "", "mails": 0})
        s["mails"] += 1
        if m["subject"] and len(g["subjects"]) < max_subjects and m["subject"] not in g["subjects"]:
            g["subjects"].append(m["subject"])
    return groups


def suggest_categories(groups: dict[str, dict], llm, done: dict[str, str | None], batch_size: int = 8):
    """Gemma's category guess per group, reusing `done` (a previous `review-scan`'s suggestions)."""
    results = dict(done)
    todo = [k for k in sorted(groups, key=lambda k: -groups[k]["mails"]) if k not in results]
    if not todo:
        return results
    parts = []
    for key in todo:
        g = groups[key]
        top = max(g["senders"].items(), key=lambda kv: kv[1]["mails"])
        name = top[1]["name"] if g["kind"] == "sender" else key
        parts.append(llm_sender_part(name, top[0], g["subjects"]))
    answers = llm.classify_batch(llm_sender_static_prompt(), parts, batch_size=batch_size)
    for key, answer in zip(todo, answers, strict=True):
        results[key] = parse_category_number(answer)
    return results


def _uncovered(group: dict, category_for) -> dict[str, dict]:
    return {a: s for a, s in group["senders"].items() if not category_for(a)}


def review_queue(groups: dict[str, dict], category_for, split: set[str], skipped: set[str]):
    """Groups still without a rule, sorted by uncovered mails descending; `split` domains become
    one row per sender; `skipped` keys are dropped."""
    rows = []
    for key, g in groups.items():
        senders = _uncovered(g, category_for)
        if not senders:
            continue
        if key in split and g["kind"] == "domain":
            for address, s in senders.items():
                if address not in skipped:
                    rows.append(
                        (
                            address,
                            {
                                "kind": "sender",
                                "mails": s["mails"],
                                "senders": {address: s},
                                "subjects": g["subjects"],
                                "domain": key,
                            },
                        )
                    )
        elif key not in skipped:
            rows.append((key, {**g, "senders": senders, "mails": sum(s["mails"] for s in senders.values())}))
    return sorted(rows, key=lambda row: -row[1]["mails"])


def coverage(groups: dict[str, dict], category_for) -> tuple[int, int]:
    """(mails now covered by a rule, total mails) across every group."""
    total = sum(g["mails"] for g in groups.values())
    left = sum(s["mails"] for g in groups.values() for s in _uncovered(g, category_for).values())
    return total - left, total


def refile_review(provider, category_for, pending, own: set[str], apply: bool) -> dict:
    """Move mails from 5-A revoir that a rule now covers to their category folder."""
    mails = read_review_mails(provider, readonly=not apply)
    moves: dict[str, list] = defaultdict(list)
    left = 0
    for m in mails:
        address = normalize_address(m["sender_address"])
        category = None if address in own else category_for(address)
        if category:
            moves[category].append(m)
        else:
            left += 1
    report = {"moves": {c: len(ms) for c, ms in moves.items()}, "left": left}
    if not apply:
        return report
    for category, ms in moves.items():
        report["moves"][category] = 0
        for start in range(0, len(ms), _MOVE_CHUNK):
            chunk = ms[start : start + _MOVE_CHUNK]
            try:
                provider.batch_move_emails([m["uid"] for m in chunk], category_folder(category))
            except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
                logger.error(f"Could not move {len(chunk)} emails to {category}: {e}")
                continue
            report["moves"][category] += len(chunk)
            for m in chunk:
                if m.get("message_id") and pending.get(m["message_id"]):
                    pending.remove(m["message_id"])
    pending.save()
    return report
