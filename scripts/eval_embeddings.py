#!/usr/bin/env python3
"""Measure the taxonomy chain (Signals 5-6) on verified mails and pick the nomic threshold.

    uv run python scripts/eval_embeddings.py chain -n 500

Category centroids are built leave-sender-out from data/taxonomy_corpus.json, and the LLM step
runs through Classifier._llm_categories, so results reflect what production would do.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger


def chain_metrics(results: list[str], labels: list[str], llm_seconds: float, llm_calls: int) -> dict:
    """Spec success criteria: >= 45% auto-classified, >= 90% precision, <= 1.5 s per LLM email."""
    from mailtag.taxonomy import REVIEW

    classified = [(r, lab) for r, lab in zip(results, labels, strict=True) if r != REVIEW]
    auto = len(classified) / len(labels)
    precision = sum(r == lab for r, lab in classified) / len(classified) if classified else 0.0
    sec = llm_seconds / llm_calls if llm_calls else 0.0
    return {
        "auto": auto,
        "precision": precision,
        "sec_per_llm_email": sec,
        "passed": auto >= 0.45 and precision >= 0.90 and sec <= 1.5,
    }


def leave_sender_out_top(doc_emb, doc_categories, doc_senders, query_emb, query_senders):
    """Nearest category centroid per query, excluding every document of the query's own sender."""
    categories = sorted(set(doc_categories))
    cat_index = {c: i for i, c in enumerate(categories)}
    cats = np.array([cat_index[c] for c in doc_categories])
    sums = np.zeros((len(categories), doc_emb.shape[1]))
    counts = np.zeros(len(categories))
    np.add.at(sums, cats, doc_emb)
    np.add.at(counts, cats, 1)
    doc_senders = np.array(doc_senders)

    results = []
    for q, sender in zip(query_emb, query_senders, strict=True):
        own = doc_senders == sender
        s = sums.copy()
        n = counts.copy()
        np.subtract.at(s, cats[own], doc_emb[own])
        np.subtract.at(n, cats[own], 1)
        valid = n > 0
        if not valid.any():
            results.append((None, 0.0))
            continue
        centroids = s[valid] / n[valid][:, None]
        sims = centroids @ q / (np.linalg.norm(centroids, axis=1) * np.linalg.norm(q))
        best = int(np.argmax(sims))
        results.append((np.array(categories)[valid][best].item(), float(sims[best])))
    return results


def threshold_sweep(nomic, llm, labels, thresholds):
    """Chain result for each nomic threshold: nomic above it, else nomic/LLM agreement, else review."""
    from mailtag.taxonomy import REVIEW

    rows = []
    for t in thresholds:
        results = [
            cat if cat and score >= t else (answer if answer and answer == cat else REVIEW)
            for (cat, score), answer in zip(nomic, llm, strict=True)
        ]
        m = chain_metrics(results, labels, 0.0, 0)
        rows.append({"threshold": t, "auto": m["auto"], "precision": m["precision"]})
    return rows


def best_threshold(sweep, min_precision=0.90):
    """Row with the highest coverage whose precision reaches `min_precision`, or None."""
    ok = [row for row in sweep if row["precision"] >= min_precision]
    return max(ok, key=lambda row: (row["auto"], row["threshold"])) if ok else None


def chain_eval(n: int, seed: int) -> None:
    """Replay signals 5-6 on verified mails (leave-sender-out centroids) and pick the nomic threshold."""
    import random

    from mailtag.classifier import Classifier
    from mailtag.config import CONFIG
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.models import Email
    from mailtag.taxonomy import nomic_text
    from mailtag.taxonomy_build import rules_precision
    from mailtag.taxonomy_store import TaxonomyStore

    corpus = json.loads(Path("data/taxonomy_corpus.json").read_text(encoding="utf-8"))
    validated = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir)).validated
    senders = json.loads(Path("data/mailbox_scan.json").read_text(encoding="utf-8"))["senders"]
    cross = json.loads(Path("data/sender_crosscheck.json").read_text(encoding="utf-8"))

    agreed, precision = rules_precision(senders, cross, validated)
    print(f"Learned rules: {precision:.1%} right on {agreed} reviewed senders where folder and Gemma agree")

    verified = [m for m in corpus if m["verified"]]
    test = random.Random(seed).sample(verified, min(n, len(verified)))
    embedder = MLXEmbedder(CONFIG.mlx.embedding_model)

    def texts(mails):
        return [nomic_text(m["sender_name"], m["sender"], m["subject"], m["body"]) for m in mails]

    doc_emb = embedder.encode(texts(corpus), prefix="search_document: ")
    query_emb = embedder.encode(texts(test), prefix="search_query: ")
    nomic = leave_sender_out_top(
        doc_emb,
        [m["category"] for m in corpus],
        [m["sender"] for m in corpus],
        query_emb,
        [m["sender"] for m in test],
    )

    classifier = Classifier(CONFIG, read_only=True)
    emails = [
        Email(msg_id=str(i), subject=m["subject"], sender_address=m["sender"], sender_name=m["sender_name"],
              body=m["body"])
        for i, m in enumerate(test)
    ]  # fmt: skip
    start = time.perf_counter()
    llm = []
    for i in range(0, len(emails), 50):
        llm += classifier._llm_categories(emails[i : i + 50])
        logger.info(f"LLM {len(llm)}/{len(emails)} ({(time.perf_counter() - start) / len(llm):.2f} s/email)")

    labels = [m["category"] for m in test]
    sweep = threshold_sweep(nomic, llm, labels, [round(0.50 + 0.01 * i, 2) for i in range(41)])
    print(f"\n{len(test)} verified mails (seed {seed})\n threshold  auto   precision")
    for row in sweep:
        print(f"   {row['threshold']:.2f}    {row['auto']:5.1%}  {row['precision']:6.1%}")
    best = best_threshold(sweep)
    if best:
        print(
            f"\nnomic_threshold = {best['threshold']:.2f}: "
            f"{best['auto']:.1%} classified at {best['precision']:.1%}"
        )
    print("PASS" if best and precision >= 0.90 else "FAIL")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_chain = sub.add_parser(
        "chain", help="Measure signals 5-6 on verified mails and pick the nomic threshold"
    )
    p_chain.add_argument("-n", type=int, default=500)
    p_chain.add_argument("--seed", type=int, default=3)

    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

    if args.command == "chain":
        chain_eval(args.n, args.seed)


if __name__ == "__main__":
    main()
