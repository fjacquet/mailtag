#!/usr/bin/env python3
"""Measure the taxonomy chain (Signals 5-6) on verified mails and pick the nomic threshold,
or measure Laya and propose its per-checkpoint thresholds.

    uv run python scripts/eval_embeddings.py chain -n 500
    uv run python scripts/eval_embeddings.py laya -n 500 [--routing multilingual] [--rotations]

Category centroids are built leave-sender-out from data/taxonomy_corpus.json, and the LLM step
runs through Classifier._llm_categories, so results reflect what production would do. Laya runs
through LayaClassifier with the [laya] settings of config.toml (overridable by flag).
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


def confidence_sweep(answers, labels, thresholds):
    """Laya result for each threshold: its category at or above it, else review."""
    from mailtag.taxonomy import REVIEW

    rows = []
    for t in thresholds:
        results = [a[0] if a and a[1] >= t else REVIEW for a in answers]
        m = chain_metrics(results, labels, 0.0, 0)
        classified = sum(r != REVIEW for r in results)
        rows.append(
            {"threshold": t, "auto": m["auto"], "precision": m["precision"], "classified": classified}
        )
    return rows


def learn_threshold(sweep, min_precision=0.97, min_mails=30):
    """Lowest threshold whose precision reaches `min_precision` on at least `min_mails` mails, else 1.01."""
    ok = [row for row in sweep if row["precision"] >= min_precision and row["classified"] >= min_mails]
    return min(row["threshold"] for row in ok) if ok else 1.01


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


def laya_eval(n: int, seed: int, overrides: dict) -> None:
    """Run Laya on the verified mails `chain` uses, sweep thresholds per checkpoint, propose them."""
    import dataclasses
    import random

    from mailtag.config import CONFIG
    from mailtag.laya_provider import LayaClassifier
    from mailtag.models import Email
    from mailtag.taxonomy import REVIEW

    config = dataclasses.replace(CONFIG.laya, **overrides)
    corpus = json.loads(Path("data/taxonomy_corpus.json").read_text(encoding="utf-8"))
    verified = [m for m in corpus if m["verified"]]
    test = random.Random(seed).sample(verified, min(n, len(verified)))
    emails = [
        Email(msg_id=str(i), subject=m["subject"], sender_address=m["sender"], sender_name=m["sender_name"],
              body=m["body"])
        for i, m in enumerate(test)
    ]  # fmt: skip
    labels = [m["category"] for m in test]

    classifier = LayaClassifier(config)
    start = time.perf_counter()
    answers = []
    for i in range(0, len(emails), 50):
        answers += classifier.classify(emails[i : i + 50])
        logger.info(
            f"Laya {len(answers)}/{len(emails)} ({(time.perf_counter() - start) / len(answers):.2f} s/email)"
        )
    seconds = time.perf_counter() - start

    print(f"\n{len(test)} verified mails (seed {seed}), {config}")
    print(f"devices: {classifier.devices()}, {seconds / len(emails):.2f} s/email")
    print(f"unanswered: {sum(a is None for a in answers)}")

    thresholds = [round(0.30 + 0.01 * i, 2) for i in range(70)]
    proposed = {}
    for checkpoint in ("english", "multilingual"):
        idx = [i for i, a in enumerate(answers) if a and a[2] == checkpoint]
        if not idx:
            continue
        sub_answers = [answers[i][:2] for i in idx]
        sub_labels = [labels[i] for i in idx]
        top1 = sum(a[0] == lab for a, lab in zip(sub_answers, sub_labels, strict=True)) / len(idx)
        sweep = confidence_sweep(sub_answers, sub_labels, thresholds)
        print(f"\n[{checkpoint}] {len(idx)} mails ({len(idx) / len(test):.0%}), top-1 accuracy {top1:.1%}")
        print(" threshold  auto   precision  classified")
        for row in sweep[::5]:
            print(
                f"   {row['threshold']:.2f}    {row['auto']:5.1%}  {row['precision']:6.1%}  "
                f"{row['classified']:6d}"
            )
        best = best_threshold(sweep)
        proposed[checkpoint] = (best["threshold"] if best else 1.01, learn_threshold(sweep))

    print("\nProposed [laya] thresholds:")
    for checkpoint, (classify_t, learn_t) in proposed.items():
        print(f"{checkpoint} = {{ classify_threshold = {classify_t:.2f}, learn_threshold = {learn_t:.2f} }}")

    results = [a[0] if a and a[1] >= proposed.get(a[2], (1.01, 1.01))[0] else REVIEW for a in answers]
    m = chain_metrics(results, labels, seconds, len(emails))
    print(
        f"\nWith these thresholds: {m['auto']:.1%} classified at {m['precision']:.1%}, "
        f"{m['sec_per_llm_email']:.2f} s/email -> {'PASS' if m['passed'] else 'FAIL'}"
    )
    print(f"Compare with: uv run python scripts/eval_embeddings.py chain -n {n} --seed {seed}")


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

    p_laya = sub.add_parser("laya", help="Measure Laya on verified mails and propose its thresholds")
    p_laya.add_argument("-n", type=int, default=500)
    p_laya.add_argument("--seed", type=int, default=3)
    p_laya.add_argument("--routing", choices=["router", "multilingual"])
    p_laya.add_argument("--rotations", action="store_true", default=None)
    p_laya.add_argument("--head-max-len", type=int)
    p_laya.add_argument("--max-len", type=int)
    p_laya.add_argument("--body-chars", type=int)
    p_laya.add_argument("--calibration", help='calibration JSON path, "" for the shipped temperatures')

    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

    if args.command == "chain":
        chain_eval(args.n, args.seed)
    elif args.command == "laya":
        overrides = {
            key: value
            for key, value in {
                "routing": args.routing,
                "rotations": args.rotations,
                "head_max_len": args.head_max_len,
                "max_len": args.max_len,
                "body_chars": args.body_chars,
                "calibration": args.calibration,
            }.items()
            if value is not None
        }
        laya_eval(args.n, args.seed, overrides)


if __name__ == "__main__":
    main()
