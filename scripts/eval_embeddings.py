#!/usr/bin/env python3
"""Measure the taxonomy chain (Signals 5-6) on verified mails and pick the nomic threshold,
measure Laya and propose its per-checkpoint thresholds, or measure the logistic regression
and propose the [logreg] thresholds.

    uv run python scripts/eval_embeddings.py chain -n 500
    uv run python scripts/eval_embeddings.py laya -n 500 [--routing multilingual] [--rotations]
    uv run python scripts/eval_embeddings.py logreg [--train-corpus PATH] [--per-sender 5 10 20]
        [--min-precision 0.85]

Category centroids are built leave-sender-out from data/taxonomy_corpus.json, and the LLM step
runs through Classifier._llm_categories, so results reflect what production would do. Laya runs
through LayaClassifier with the [laya] settings of config.toml (overridable by flag).
The logistic regression is tested on the verified mails of data/taxonomy_corpus.json whose sender's domain has
no domain rule (only those reach Pass 3 in production), with 5 folds grouped by domain (by sender on personal
domains); each fold trains on the training corpus minus the fold's groups. data/taxonomy_corpus.json and
data/training_corpus.json (one row per --per-sender value) are compared; the harvested corpus is adopted only
if it classifies strictly more mails at the target precision (spec decision 7).
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
    thin = {}  # checkpoint -> mails behind a proposed classify_threshold, when too few to trust it
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
        if best and best["classified"] < 30:
            thin[checkpoint] = best["classified"]

    print("\nProposed [laya] thresholds:")
    for checkpoint, (classify_t, learn_t) in proposed.items():
        print(f"{checkpoint} = {{ classify_threshold = {classify_t:.2f}, learn_threshold = {learn_t:.2f} }}")
        if checkpoint in thin:
            print(f"# warning: {checkpoint} classify_threshold rests on {thin[checkpoint]} mails")

    results = [a[0] if a and a[1] >= proposed.get(a[2], (1.01, 1.01))[0] else REVIEW for a in answers]
    m = chain_metrics(results, labels, seconds, len(emails))
    print(
        f"\nWith these thresholds: {m['auto']:.1%} classified at {m['precision']:.1%}, "
        f"{m['sec_per_llm_email']:.2f} s/email -> {'PASS' if m['passed'] else 'FAIL'}"
    )
    print(f"Compare with: uv run python scripts/eval_embeddings.py chain -n {n} --seed {seed}")


def fold_group(address: str) -> str:
    """Fold grouping key: the sender's domain, or the address itself on a non-commercial domain
    (Pass 3 only meets senders and domains no rule covers)."""
    from mailtag.utils.domain_utils import extract_domain, is_non_commercial_domain_cached

    address = address.strip().lower()
    domain = extract_domain(address) or address
    return address if is_non_commercial_domain_cached(domain) else domain


def group_folds(train_groups: list[str], test_groups: list[str], n_splits: int = 5):
    """(train indices, test positions): GroupKFold over the test mails by group; each fold trains on the
    training mails of every other group."""
    from sklearn.model_selection import GroupKFold

    train_arr, test_arr = np.array(train_groups), np.array(test_groups)
    for _, fold in GroupKFold(n_splits=n_splits).split(test_arr, groups=test_arr):
        yield np.where(~np.isin(train_arr, test_arr[fold]))[0], fold


def reaches_pass3(mails: list[dict], domain_rule) -> list[dict]:
    """Mails whose sender's domain has no domain rule (`domain_rule(domain)` is None): only those
    reach Pass 3 in production. Personal domains never have a domain rule."""
    from mailtag.utils.domain_utils import extract_domain, is_non_commercial_domain_cached

    kept = []
    for mail in mails:
        domain = extract_domain(mail["sender"].strip().lower())
        if is_non_commercial_domain_cached(domain) or domain_rule(domain) is None:
            kept.append(mail)
    return kept


def pick_winner(scored: list[tuple[float, float, str]], baseline: str) -> str:
    """The baseline corpus unless a harvested candidate classifies strictly more mails at the target
    precision (spec decision 7); among harvested candidates, the best (coverage, top-1)."""
    base = next(row for row in scored if row[2] == baseline)
    others = [row for row in scored if row[2] != baseline]
    best = max(others, default=None)
    return best[2] if best is not None and best[0] > base[0] else baseline


TAXONOMY_CORPUS = Path("data/taxonomy_corpus.json")
TRAINING_CORPUS = Path("data/training_corpus.json")


def logreg_eval(C: float, min_precision: float, train_corpus: Path | None, per_senders: list[int]) -> None:
    """Compare training corpora on the verified mails that can reach Pass 3 (domain-grouped folds),
    propose the [logreg] settings of the best one."""
    from mailtag.config import CONFIG
    from mailtag.logreg_provider import capped_indices, corpus_texts, embed, predict, train
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.taxonomy_store import TaxonomyStore

    corpus = json.loads(TAXONOMY_CORPUS.read_text(encoding="utf-8"))
    store = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir), own_addresses=CONFIG.taxonomy.own_addresses)

    def domain_rule(domain: str) -> str | None:
        return store.validated_domains.get(domain) or store.domains.get(domain)

    verified = [m for m in corpus if m["verified"]]
    test = reaches_pass3(verified, domain_rule)
    labels = [m["category"] for m in test]
    test_groups = [fold_group(m["sender"]) for m in test]
    if len(set(test_groups)) < 5:
        sys.exit(
            f"Only {len(set(test_groups))} fold groups among {len(test)} mails that reach Pass 3 (need 5)"
        )
    embedder = MLXEmbedder(CONFIG.mlx.embedding_model)
    test_emb = embed(embedder, corpus_texts(test))

    def answers_for(rows: list[dict], emb: np.ndarray) -> list[tuple[str, float]]:
        answers: list = [None] * len(test)
        for train_idx, fold in group_folds([fold_group(m["sender"]) for m in rows], test_groups):
            model = train(emb[train_idx], [rows[i]["category"] for i in train_idx], C)
            cats, probs = predict(model, test_emb[fold])
            for i, c, p in zip(fold, cats, probs, strict=True):
                answers[int(i)] = (c, float(p))
        return answers

    # name -> (answers, training rows, per_sender or None)
    candidates: dict[str, tuple[list, list[dict], int | None]] = {}
    candidates[str(TAXONOMY_CORPUS)] = (
        answers_for(corpus, embed(embedder, corpus_texts(corpus))),
        corpus,
        None,
    )
    harvested_path = train_corpus or (TRAINING_CORPUS if TRAINING_CORPUS.exists() else None)
    if harvested_path is not None and harvested_path != TAXONOMY_CORPUS:
        harvested = json.loads(harvested_path.read_text(encoding="utf-8"))
        harvested_emb = embed(embedder, corpus_texts(harvested))
        for n in per_senders:
            keep = capped_indices(harvested, n)
            rows = [harvested[i] for i in keep]
            candidates[f"{harvested_path} per_sender={n}"] = (answers_for(rows, harvested_emb[keep]), rows, n)

    # Centroids on the taxonomy corpus, same folds, for reference
    doc = embedder.encode(corpus_texts(corpus), prefix="search_document: ")
    query = embedder.encode(corpus_texts(test), prefix="search_query: ")
    centroid: list = [None] * len(test)
    for train_idx, fold in group_folds([fold_group(m["sender"]) for m in corpus], test_groups):
        top = leave_sender_out_top(
            doc[train_idx],
            [corpus[i]["category"] for i in train_idx],
            [corpus[i]["sender"] for i in train_idx],
            query[fold],
            [test[i]["sender"] for i in fold],
        )
        for i, (c, _) in zip(fold, top, strict=True):
            centroid[int(i)] = c
    print(
        f"\n{len(verified)} verified mails, {len(verified) - len(test)} excluded (their domain has a domain "
        f"rule: never in Pass 3), {len(test)} tested, {len(set(test_groups))} fold groups "
        f"(domains / personal senders), C={C:g}"
    )
    print(f"centroids top-1: {np.mean([c == y for c, y in zip(centroid, labels, strict=True)]):.1%}")

    thresholds = [round(0.30 + 0.01 * i, 2) for i in range(70)]
    print(f"\n training corpus{'':48} mails  senders  top-1  classified@{min_precision:.0%}")
    scored = []
    for name, (answers, rows, _) in candidates.items():
        top1 = np.mean([a[0] == y for a, y in zip(answers, labels, strict=True)])
        best = best_threshold(confidence_sweep(answers, labels, thresholds), min_precision)
        coverage = best["auto"] if best else 0.0
        scored.append((coverage, top1, name))
        senders = len({m["sender"] for m in rows})
        print(f" {name:63} {len(rows):6} {senders:7} {top1:6.1%}  {coverage:6.1%}")

    winner = pick_winner(scored, str(TAXONOMY_CORPUS))
    answers, rows, n = candidates[winner]
    print(f"\nBest: {winner}")
    # Production cost per mail: embed + predict with the winner trained on all its rows
    model = train(embed(embedder, corpus_texts(rows)), [m["category"] for m in rows], C)
    start = time.perf_counter()
    predict(model, embed(embedder, corpus_texts(test)))
    print(f"{(time.perf_counter() - start) / len(test):.3f} s/email (embedding + prediction)")

    sweep = confidence_sweep(answers, labels, thresholds)
    print(" threshold  auto   precision  mails")
    for row in sweep:
        t, auto, precision, k = row["threshold"], row["auto"], row["precision"], row["classified"]
        print(f"   {t:.2f}    {auto:5.1%}  {precision:6.1%}  {k:5}")
    best = best_threshold(sweep, min_precision)
    classify = best["threshold"] if best else 1.01
    if best and best["classified"] < 30:
        print(f"WARNING: classify_threshold rests on {best['classified']} mails (< 30)")
    if not best:
        print(f"\nNo threshold reaches {min_precision:.0%} precision")
    print("\n[logreg]")
    if n is not None:
        print(f"per_sender = {n}")
    print(f"classify_threshold = {classify:.2f}\nlearn_threshold = {learn_threshold(sweep):.2f}")
    if harvested_path is not None and harvested_path != TAXONOMY_CORPUS:
        if winner == str(TAXONOMY_CORPUS):
            print(
                f"\nKeep {TAXONOMY_CORPUS}: move {harvested_path} aside "
                f"(e.g. data/training_corpus.rejected.json), "
                f"since train uses {TRAINING_CORPUS} whenever it exists."
            )
        else:
            print(
                f"\nUse {harvested_path} as {TRAINING_CORPUS}, set per_sender = {n}, "
                "then run taxonomy_setup.py train."
            )


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

    p_logreg = sub.add_parser("logreg", help="Compare training corpora and propose the [logreg] settings")
    p_logreg.add_argument("--C", type=float, help="regularisation (default: [logreg] C)")
    p_logreg.add_argument("--min-precision", type=float, default=0.85)
    p_logreg.add_argument(
        "--train-corpus", type=Path, help="harvested corpus (default: data/training_corpus.json)"
    )
    p_logreg.add_argument(
        "--per-sender", type=int, nargs="+", help="caps to compare (default: [logreg] per_sender)"
    )

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
    elif args.command == "logreg":
        from mailtag.config import CONFIG

        logreg_eval(
            args.C if args.C is not None else CONFIG.logreg.C,
            args.min_precision,
            args.train_corpus,
            args.per_sender or [CONFIG.logreg.per_sender],
        )


if __name__ == "__main__":
    main()
