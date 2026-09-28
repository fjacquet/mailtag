"""Build learned rules, domain rules, the review queue and the centroid corpus (spec section 1)."""

import imaplib
from collections import Counter, defaultdict

from loguru import logger

from .semantic_router import SemanticRouter
from .taxonomy import nomic_text
from .utils.domain_utils import is_non_commercial_domain_cached


def mail_count(entry: dict) -> int:
    return sum(entry["categories"].values())


def folder_category(entry: dict) -> str:
    return max(entry["categories"], key=entry["categories"].get)


def review_queue(senders: dict, crosscheck: dict, validated: dict) -> list[str]:
    """Senders to review: folder/Gemma disagreements first, then agreements, biggest senders first."""
    todo = [s for s in senders if s not in validated]
    disagree = [s for s in todo if crosscheck.get(s) != folder_category(senders[s])]
    agree = [s for s in todo if crosscheck.get(s) == folder_category(senders[s])]

    def by_volume(sender: str) -> int:
        return -mail_count(senders[sender])

    return sorted(disagree, key=by_volume) + sorted(agree, key=by_volume)


def learned_senders(
    senders: dict, crosscheck: dict, validated: dict, min_mails: int, agreements: int
) -> dict:
    """Senders whose folder category and Gemma agree, with enough mails, not already validated."""
    return {
        s: {"category": folder_category(e), "agreements": agreements}
        for s, e in senders.items()
        if s not in validated and mail_count(e) >= min_mails and crosscheck.get(s) == folder_category(e)
    }


def _sender_category(sender: str, validated: dict, learned: dict) -> str | None:
    return validated.get(sender) or (learned.get(sender) or {}).get("category")


def domain_rules(senders: dict, validated: dict, learned: dict, min_purity: float) -> dict[str, str]:
    """Business domains whose mails go to one category at least `min_purity` of the time."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for sender, entry in senders.items():
        category = _sender_category(sender, validated, learned)
        domain = entry["domain"]
        if category and domain and not is_non_commercial_domain_cached(domain):
            counts[domain][category] += mail_count(entry)
    rules = {}
    for domain, by_category in counts.items():
        category, n = by_category.most_common(1)[0]
        if n / sum(by_category.values()) >= min_purity:
            rules[domain] = category
    return rules


def folder_disagreement(folder: dict, crosscheck: dict) -> float:
    """Share of the folder's mails whose sender Gemma puts in another category (or could not read)."""
    total = sum(folder["senders"].values())
    if not total:
        return 0.0
    other = sum(n for s, n in folder["senders"].items() if crosscheck.get(s) != folder["category"])
    return other / total


def gemma_proposals(folder: dict, crosscheck: dict) -> list[tuple[str, int]]:
    """Gemma categories of the folder's senders, weighted by mails, most frequent first."""
    counts: Counter = Counter()
    for sender, n in folder["senders"].items():
        if crosscheck.get(sender):
            counts[crosscheck[sender]] += n
    return counts.most_common()


def folder_queue(folders: dict, crosscheck: dict, reviewed: dict, min_rate: float = 0.30) -> list[str]:
    """Folders to audit: not yet reviewed, contested at `min_rate` or more, most contested first."""
    rates = {f: folder_disagreement(e, crosscheck) for f, e in folders.items() if f not in reviewed}
    todo = [f for f, rate in rates.items() if rate >= min_rate]
    return sorted(todo, key=lambda f: (-rates[f], -sum(folders[f]["senders"].values())))


def rules_precision(senders: dict, crosscheck: dict, validated: dict) -> tuple[int, float]:
    """On reviewed senders where folder and Gemma agree, how often that agreement matches the user."""
    agreed = [s for s in validated if s in senders and crosscheck.get(s) == folder_category(senders[s])]
    if not agreed:
        return 0, 0.0
    right = sum(folder_category(senders[s]) == validated[s] for s in agreed)
    return len(agreed), right / len(agreed)


def corpus_refs(senders: dict, validated: dict, learned: dict, per_category: int = 200) -> list[dict]:
    """Mail references of validated or learned senders, biggest senders first, capped per category."""
    by_category: dict[str, list[dict]] = defaultdict(list)
    for sender, entry in sorted(senders.items(), key=lambda kv: -mail_count(kv[1])):
        category = _sender_category(sender, validated, learned)
        if not category:
            continue
        for folder, uid in entry["refs"]:
            by_category[category].append(
                {"sender": sender, "category": category, "verified": sender in validated,
                 "folder": folder, "uid": uid}
            )  # fmt: skip
    return [ref for refs in by_category.values() for ref in refs[:per_category]]


def fetch_corpus(provider, refs: list[dict]) -> list[dict]:
    """Read the referenced mails (read-only) and keep what nomic needs."""
    by_folder: dict[str, list[dict]] = defaultdict(list)
    for ref in refs:
        by_folder[ref["folder"]].append(ref)
    corpus = []
    for folder, folder_refs in by_folder.items():
        try:
            provider.client.select_folder(folder, readonly=True)
            emails = {e.msg_id: e for e in provider.get_full_emails([r["uid"] for r in folder_refs])}
        except (imaplib.IMAP4.error, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Could not read folder {folder}: {e}")
            continue
        for ref in folder_refs:
            mail = emails.get(str(ref["uid"]))
            if mail:
                corpus.append(
                    {"sender": ref["sender"], "category": ref["category"], "verified": ref["verified"],
                     "sender_name": mail.sender_name, "subject": mail.subject, "body": mail.body}
                )  # fmt: skip
    return corpus


def build_centroids(embedder, corpus: list[dict]) -> SemanticRouter:
    """One nomic centroid per category, from the production text of real mails."""
    examples: dict[str, list[str]] = defaultdict(list)
    for mail in corpus:
        examples[mail["category"]].append(
            nomic_text(mail["sender_name"], mail["sender"], mail["subject"], mail["body"])
        )
    router = SemanticRouter(embedder, score_threshold=0.0)
    router.build_from_examples(dict(examples))
    return router
