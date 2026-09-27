#!/usr/bin/env python3
"""Compare embedding models for the Semantic Router (Signal 5).

Ground truth is the IMAP folder each email already lives in.

Step 1 - collect a sample (read-only IMAP, cached locally):
    uv run python scripts/eval_embeddings.py collect --per-folder 20

Step 2 - evaluate models on the cached sample:
    uv run python scripts/eval_embeddings.py evaluate

Step 3 - compare nomic prefixes and category-building strategies (leave-one-sender-out):
    uv run python scripts/eval_embeddings.py tune

Category centroids are built exactly as in scripts/build_category_embeddings.py and
queries are formatted exactly as in Classifier._get_category_from_semantic_router,
so results reflect what production would do with each model.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

DEFAULT_SAMPLE = Path("data/eval/embedding_eval_set.json")
DEFAULT_MODELS = ["nomic-ai/nomic-embed-text-v1.5", "Qwen/Qwen3-Embedding-0.6B"]
THRESHOLDS = [0.0, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
PREFIXES = ("search_query", "search_document", "classification")
QWEN_QUERY_PROMPT = "Instruct: Classify the email into the mail folder it belongs to\nQuery:"

# Folders whose content says nothing about a category
SKIP_FOLDERS = {
    "INBOX",
    "Sent",
    "Sent Messages",
    "Drafts",
    "Trash",
    "Deleted Messages",
    "Junk",
    "Spam",
    "Archive",
    "Archives",
    "Notes",
    "Later",
    "A classer",
    "À Classer",
}


def score(
    sims: np.ndarray, categories: list[str], labels: list[str], thresholds: list[float]
) -> dict[str, object]:
    """Score a (n_queries, n_categories) cosine similarity matrix against true labels."""
    cat_index = {c: i for i, c in enumerate(categories)}
    ranked = np.argsort(-sims, axis=1)
    best = sims[np.arange(len(sims)), ranked[:, 0]]

    correct1 = np.array([cat_index.get(lab) == ranked[i, 0] for i, lab in enumerate(labels)])
    correct5 = np.array([cat_index.get(lab) in ranked[i, :5] for i, lab in enumerate(labels)])

    curve = {}
    for t in thresholds:
        accepted = best >= t
        n_accepted = int(accepted.sum())
        curve[t] = {
            "coverage": n_accepted / len(labels),
            "precision": float(correct1[accepted].mean()) if n_accepted else 0.0,
        }

    return {
        "n": len(labels),
        "unreachable": sum(lab not in cat_index for lab in labels),
        "top1": float(correct1.mean()),
        "top5": float(correct5.mean()),
        "curve": curve,
    }


def coverage_at_precision(sims: np.ndarray, categories: list[str], labels: list[str], target: float) -> float:
    """Largest share of emails classifiable with a single score threshold at >= target precision."""
    cat_index = {c: i for i, c in enumerate(categories)}
    pred = sims.argmax(axis=1)
    best = sims[np.arange(len(sims)), pred]
    correct = np.array([cat_index.get(lab) == p for lab, p in zip(labels, pred, strict=True)])

    for t in np.unique(best):  # ascending: the first threshold that works covers the most
        accepted = best >= t
        if correct[accepted].mean() >= target:
            return accepted.sum() / len(labels)
    return 0.0


def _normalize(x: np.ndarray) -> np.ndarray:
    return x / np.linalg.norm(x, axis=-1, keepdims=True)


def centroid_sims_leave_sender_out(
    docs: np.ndarray,
    queries: np.ndarray,
    folders: list[str],
    senders: list[str],
    extra: dict[str, np.ndarray] | None = None,
) -> tuple[list[str], np.ndarray]:
    """Cosine similarity of each query to folder centroids built from real emails.

    A query's own sender is removed from its folder's centroid, so the score reflects
    a sender the router has never seen. `extra` adds fixed example vectors per folder.
    Folders left with no example get similarity -1 for that query.
    """
    extra = extra or {}
    categories = sorted(set(folders) | set(extra))
    index = {c: i for i, c in enumerate(categories)}
    dim = docs.shape[1]

    sums = np.zeros((len(categories), dim))
    counts = np.zeros(len(categories))
    for cat, vecs in extra.items():
        sums[index[cat]] += vecs.sum(axis=0)
        counts[index[cat]] += len(vecs)

    group_sum: dict[tuple[str, str], np.ndarray] = {}
    group_count: dict[tuple[str, str], int] = {}
    for vec, folder, sender in zip(docs, folders, senders, strict=True):
        sums[index[folder]] += vec
        counts[index[folder]] += 1
        key = (folder, sender)
        group_sum[key] = group_sum.get(key, 0) + vec
        group_count[key] = group_count.get(key, 0) + 1

    with np.errstate(invalid="ignore", divide="ignore"):
        centroids = _normalize(sums / counts[:, None])
    q = _normalize(queries)
    sims = np.nan_to_num(q @ centroids.T, nan=-1.0)

    for i, (folder, sender) in enumerate(zip(folders, senders, strict=True)):
        f = index[folder]
        remaining = counts[f] - group_count[(folder, sender)]
        if remaining == 0:
            sims[i, f] = -1.0
        else:
            centroid = (sums[f] - group_sum[(folder, sender)]) / remaining
            sims[i, f] = q[i] @ _normalize(centroid)
    return categories, sims


def knn_sims_leave_sender_out(
    docs: np.ndarray, queries: np.ndarray, folders: list[str], senders: list[str], k: int = 5
) -> tuple[list[str], np.ndarray]:
    """Per-folder score = summed similarity of the k nearest emails from other senders, divided by k."""
    categories = sorted(set(folders))
    index = {c: i for i, c in enumerate(categories)}
    folder_idx = np.array([index[f] for f in folders])
    sender_arr = np.array(senders)

    nn = _normalize(queries) @ _normalize(docs).T
    nn[sender_arr[:, None] == sender_arr[None, :]] = -np.inf  # also masks the email itself

    top = np.argpartition(-nn, k, axis=1)[:, :k]
    sims = np.zeros((len(queries), len(categories)))
    for i, neighbours in enumerate(top):
        np.add.at(sims[i], folder_idx[neighbours], np.maximum(nn[i, neighbours], 0.0))
    return categories, sims / k


def collect(per_folder: int, output: Path) -> None:
    """Fetch the most recent emails of every category folder, read-only."""
    from mailtag.config import CONFIG
    from mailtag.imap_service import ImapService
    from mailtag.utils.text_utils import smart_truncate

    folders = json.loads(Path("data/imap_folders.json").read_text(encoding="utf-8"))
    samples = []

    with ImapService(CONFIG.imap, CONFIG.fast_parse).connect() as imap:
        for folder in folders:
            if folder in SKIP_FOLDERS:
                continue
            imap.client.select_folder(folder, readonly=True)
            uids = imap.client.search("ALL")[-per_folder:]
            if not uids:
                continue
            for mail in imap.get_full_emails(uids):
                samples.append(
                    {
                        "folder": folder,
                        "sender_name": mail.sender_name,
                        "sender_address": mail.sender_address,
                        "subject": mail.subject,
                        # Classifier truncates to 500 chars before routing
                        "body": smart_truncate(mail.body, max_chars=500) if mail.body else "",
                    }
                )
            logger.info(f"{folder}: {len(uids)} emails")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info(f"Saved {len(samples)} emails from {len({s['folder'] for s in samples})} folders to {output}")


def query_text(sample: dict[str, str]) -> str:
    """Same format as Classifier._get_category_from_semantic_router."""
    sender = sample["sender_name"] or sample["sender_address"] or "Unknown"
    text = f"Email from {sender}: {sample['subject']}"
    if sample["body"]:
        text += f"\n{sample['body']}"
    return text


def category_examples() -> dict[str, list[str]]:
    """Same training examples as scripts/build_category_embeddings.py."""
    from build_category_embeddings import (
        extract_categories_from_folders,
        extract_categories_from_history,
        extract_categories_from_validated_db,
        load_json_file,
        merge_examples,
    )

    sources = [
        extract_categories_from_validated_db(
            load_json_file(Path("db/validated_classification_db.json")) or {}
        ),
        extract_categories_from_folders(load_json_file(Path("data/imap_folders.json")) or []),
        extract_categories_from_history(load_json_file(Path("db/sender_classification_db.json")) or {}),
    ]
    merged = merge_examples(*sources)
    return {cat: ex for cat, ex in merged.items() if len(ex) >= 2}


def evaluate(sample_path: Path, models: list[str]) -> None:
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.semantic_router import SemanticRouter

    samples = json.loads(sample_path.read_text(encoding="utf-8"))
    queries = [query_text(s) for s in samples]
    labels = [s["folder"] for s in samples]
    examples = category_examples()
    logger.info(f"{len(samples)} emails, {len(set(labels))} folders, {len(examples)} router categories")

    variants = []
    for model in models:
        variants.append((model, None))
        if "qwen3-embedding" in model.lower():
            # Qwen recommends an instruction on queries; MLXEmbedder does not add one today
            variants.append((model, QWEN_QUERY_PROMPT))

    for model, prompt in variants:
        embedder = MLXEmbedder(model)
        router = SemanticRouter(embedder)
        router.build_from_examples(examples)

        start = time.perf_counter()
        chunks = []
        for i in range(0, len(queries), 500):
            chunk = queries[i : i + 500]
            if prompt:
                chunks.append(embedder.model.encode(chunk, prompt=prompt, convert_to_numpy=True))
            else:
                chunks.append(embedder.encode(chunk, prefix="search_query: "))
            logger.info(f"Encoded {i + len(chunk)}/{len(queries)} emails")
        q = np.vstack(chunks)
        ms_per_email = (time.perf_counter() - start) * 1000 / len(queries)

        q = q / np.linalg.norm(q, axis=1, keepdims=True)
        result = score(q @ router._embedding_matrix.T, router.categories, labels, THRESHOLDS)

        name = model + (" + query instruction" if prompt else "")
        print(f"\n=== {name} ===")
        print(f"emails={result['n']}  unreachable={result['unreachable']}  {ms_per_email:.1f} ms/email")
        print(f"top-1={result['top1']:.1%}  top-5={result['top5']:.1%}")
        print("threshold  coverage  precision")
        for t, c in result["curve"].items():
            print(f"  {t:>5.2f}    {c['coverage']:>6.1%}    {c['precision']:>6.1%}")


def encode_cached(embedder, texts: list[str], prefix: str, cache: Path) -> np.ndarray:
    """Encode texts with a nomic task prefix, reusing a .npy cache when it matches."""
    if cache.exists():
        vecs = np.load(cache)
        if len(vecs) == len(texts):
            logger.info(f"Loaded cached '{prefix}' embeddings from {cache}")
            return vecs

    chunks = []
    for i in range(0, len(texts), 500):
        chunks.append(embedder.encode(texts[i : i + 500], prefix=f"{prefix}: "))
        logger.info(f"[{prefix}] encoded {min(i + 500, len(texts))}/{len(texts)}")
    vecs = np.vstack(chunks)
    np.save(cache, vecs)
    return vecs


def tune(sample_path: Path, model: str) -> None:
    """Compare nomic prefixes and ways of building categories, leave-one-sender-out."""
    from mailtag.mlx_provider import MLXEmbedder

    samples = json.loads(sample_path.read_text(encoding="utf-8"))
    queries = [query_text(s) for s in samples]
    labels = [s["folder"] for s in samples]
    senders = [s["sender_address"].lower() for s in samples]
    embedder = MLXEmbedder(model)
    cache_dir = sample_path.parent

    emails = {p: encode_cached(embedder, queries, p, cache_dir / f"emails_{p}.npy") for p in PREFIXES}

    examples = category_examples()
    flat = [text for texts in examples.values() for text in texts]
    synthetic = {}
    for p in ("search_document", "classification"):
        vecs = encode_cached(embedder, flat, p, cache_dir / f"synthetic_{p}.npy")
        synthetic[p], start = {}, 0
        for cat, texts in examples.items():
            synthetic[p][cat] = vecs[start : start + len(texts)]
            start += len(texts)

    def synthetic_only(doc_prefix: str, query_prefix: str) -> tuple[list[str], np.ndarray]:
        cats = list(synthetic[doc_prefix])
        centroids = _normalize(np.stack([synthetic[doc_prefix][c].mean(axis=0) for c in cats]))
        return cats, _normalize(emails[query_prefix]) @ centroids.T

    qd = ("search_document", "search_query")
    cls = ("classification", "classification")
    variants = {
        "synthetic centroids, query/document (prod)": synthetic_only(*qd),
        "synthetic centroids, classification": synthetic_only(*cls),
        "real-mail centroids, query/document": centroid_sims_leave_sender_out(
            emails[qd[0]], emails[qd[1]], labels, senders
        ),
        "real-mail centroids, classification": centroid_sims_leave_sender_out(
            emails[cls[0]], emails[cls[1]], labels, senders
        ),
        "real + synthetic centroids, query/document": centroid_sims_leave_sender_out(
            emails[qd[0]], emails[qd[1]], labels, senders, synthetic[qd[0]]
        ),
        "real + synthetic centroids, classification": centroid_sims_leave_sender_out(
            emails[cls[0]], emails[cls[1]], labels, senders, synthetic[cls[0]]
        ),
    }
    for k in (5, 10):
        variants[f"kNN k={k}, query/document"] = knn_sims_leave_sender_out(
            emails[qd[0]], emails[qd[1]], labels, senders, k
        )
        variants[f"kNN k={k}, classification"] = knn_sims_leave_sender_out(
            emails[cls[0]], emails[cls[1]], labels, senders, k
        )

    print(f"\n{len(samples)} emails, leave-one-sender-out\n")
    print(f"{'variant':<46} {'top-1':>6} {'top-5':>6} {'cov@85%':>8} {'cov@90%':>8}")
    for name, (cats, sims) in variants.items():
        r = score(sims, cats, labels, [])
        c85 = coverage_at_precision(sims, cats, labels, 0.85)
        c90 = coverage_at_precision(sims, cats, labels, 0.90)
        print(f"{name:<46} {r['top1']:>6.1%} {r['top5']:>6.1%} {c85:>8.1%} {c90:>8.1%}")


def gemma(sample_path: Path, n: int, seed: int, nomic_threshold: float) -> None:
    """Score the Signal 6 LLM on a random subset and compare with nomic on the same emails.

    Builds the prompt exactly like Classifier._get_category_from_ai; an answer counts as
    classified when confidence >= mlx.llm_confidence and the category is a known folder.
    Needs the nomic caches written by `tune`.
    """
    import random

    from mailtag.classifier import Classifier
    from mailtag.config import CONFIG
    from mailtag.database import ClassificationDatabase
    from mailtag.models import Email

    samples = json.loads(sample_path.read_text(encoding="utf-8"))
    picked = sorted(random.Random(seed).sample(range(len(samples)), n))
    database = ClassificationDatabase(
        Path("db/sender_classification_db.json"), Path("db/validated_classification_db.json")
    )
    classifier = Classifier(CONFIG, database)
    if not classifier._init_mlx_components() or classifier._mlx_llm is None:
        sys.exit("MLX LLM unavailable")

    results = []
    start = time.perf_counter()
    for done, i in enumerate(picked, 1):
        s = samples[i]
        mail = Email(msg_id=str(i), subject=s["subject"], sender_address=s["sender_address"],
                     sender_name=s["sender_name"], body=s["body"])  # fmt: skip
        sender = f"{mail.sender_name} <{mail.sender_address}>" if mail.sender_name else mail.sender_address
        prompt = (
            f"Sujet: {mail.subject}\nDe: {sender}\nCorps: {classifier._truncate_body(mail.body)}\n\n"
            f"{classifier._build_llm_prompt_prefix()}"
        )
        category, confidence, _reason = classifier._mlx_llm.classify(prompt)
        results.append({"i": i, "folder": s["folder"], "category": category, "confidence": confidence})
        if done % 50 == 0:
            logger.info(f"Gemma {done}/{n} ({(time.perf_counter() - start) / done:.1f} s/email)")

    sec_per_email = (time.perf_counter() - start) / n
    (sample_path.parent / "gemma_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))

    known = set(classifier.categories)
    correct = np.array([r["category"] == r["folder"] for r in results])
    conf = np.array([r["confidence"] if r["category"] in known else -1.0 for r in results])

    # nomic on the same emails, production setup (synthetic centroids, query/document prefixes)
    examples = category_examples()
    vecs = np.load(sample_path.parent / "synthetic_search_document.npy")
    cats, centroids, start_row = list(examples), [], 0
    for texts in examples.values():
        centroids.append(vecs[start_row : start_row + len(texts)].mean(axis=0))
        start_row += len(texts)
    sims = (
        _normalize(np.load(sample_path.parent / "emails_search_query.npy")[picked])
        @ _normalize(np.stack(centroids)).T
    )
    n_pred = sims.argmax(axis=1)
    n_best = sims[np.arange(n), n_pred]
    n_correct = np.array([cats[p] == samples[i]["folder"] for p, i in zip(n_pred, picked, strict=True)])

    print(f"\n{n} random emails (seed {seed}), Gemma {sec_per_email:.1f} s/email\n")
    print(f"Gemma top-1 (any confidence): {correct.mean():.1%}")
    print("confidence  coverage  precision")
    for t in (0.5, 0.7, 0.8, CONFIG.mlx.llm_confidence, 0.9, 0.95):
        a = conf >= t
        print(f"  {t:>5.2f}     {a.mean():>6.1%}    {correct[a].mean() if a.any() else 0:>6.1%}")
    a = n_best >= nomic_threshold
    print(f"\nnomic top-1: {n_correct.mean():.1%}")
    print(f"nomic @ {nomic_threshold:.2f}: coverage {a.mean():.1%}, precision {n_correct[a].mean():.1%}")
    both = a & (conf >= CONFIG.mlx.llm_confidence)
    if both.any():
        print(f"on the {both.sum()} emails both accept: nomic {n_correct[both].mean():.1%}, "
              f"Gemma {correct[both].mean():.1%}")  # fmt: skip


def taxonomy_prompt(sample: dict[str, str]) -> str:
    """Gemma prompt for the 19-category taxonomy; the static part comes first so it can be cached."""
    from mailtag.taxonomy import TAXONOMY

    categories = "\n".join(f"- {name} : {desc}" for name, desc in TAXONOMY.items())
    sender = f"{sample['sender_name']} <{sample['sender_address']}>" if sample["sender_name"] else (
        sample["sender_address"]
    )  # fmt: skip
    return (
        "Classe cet email dans UNE des catégories suivantes, selon le métier de l'expéditeur :\n"
        f"{categories}\n\n"
        "Réponds uniquement en JSON : "
        '{"category": "<nom exact de la catégorie>", "confidence": <0.0 à 1.0>}\n\n'
        f"Sujet: {sample['subject']}\nDe: {sender}\nCorps: {sample['body']}"
    )


def taxonomy_eval(sample_path: Path, n_gemma: int, seed: int) -> None:
    """Measure nomic (from caches) and Gemma on the 19-category taxonomy."""
    import random

    from mailtag.taxonomy import TAXONOMY, map_folder

    samples = json.loads(sample_path.read_text(encoding="utf-8"))
    keep = [i for i, s in enumerate(samples) if map_folder(s["folder"])]
    labels = [map_folder(samples[i]["folder"]) for i in keep]
    senders = [samples[i]["sender_address"].lower() for i in keep]
    cache = sample_path.parent
    q = _normalize(np.load(cache / "emails_search_query.npy")[keep])
    d = np.load(cache / "emails_search_document.npy")[keep]

    # Old synthetic centroids, as in production
    examples = category_examples()
    vecs = np.load(cache / "synthetic_search_document.npy")
    old_cats, old_centroids, row = [], [], 0
    for cat, texts in examples.items():
        if map_folder(cat):
            old_cats.append(cat)
            old_centroids.append(vecs[row : row + len(texts)].mean(axis=0))
        row += len(texts)
    old_sims = q @ _normalize(np.stack(old_centroids)).T

    cats = list(TAXONOMY)
    # A: nearest old folder, reported as its new category (max over sub-centroids)
    to_new = np.array([cats.index(map_folder(c)) for c in old_cats])
    sims_a = np.full((len(keep), len(cats)), -1.0)
    for j in range(len(cats)):
        sims_a[:, j] = old_sims[:, to_new == j].max(axis=1)

    from mailtag.mlx_provider import MLXEmbedder

    desc = MLXEmbedder("nomic-ai/nomic-embed-text-v1.5").encode_documents(
        [f"{name} : {text}" for name, text in TAXONOMY.items()]
    )
    variants = {
        "nomic, nearest old folder -> category": (cats, sims_a),
        "nomic, category descriptions only": (cats, q @ _normalize(desc).T),
        "nomic, real-mail centroids (leave sender out)": centroid_sims_leave_sender_out(
            d, q, labels, senders
        ),
        "nomic, kNN k=10 (leave sender out)": knn_sims_leave_sender_out(d, q, labels, senders, 10),
    }

    print(f"\n{len(keep)} emails, {len(cats)} categories\n")
    print(f"{'variant':<48} {'top-1':>6} {'top-3':>6} {'cov@85%':>8} {'cov@90%':>8}")
    for name, (vc, sims) in variants.items():
        ranked = np.argsort(-sims, axis=1)[:, :3]
        top3 = np.mean([labels[i] in {vc[j] for j in ranked[i]} for i in range(len(labels))])
        r = score(sims, vc, labels, [])
        c85 = coverage_at_precision(sims, vc, labels, 0.85)
        c90 = coverage_at_precision(sims, vc, labels, 0.90)
        print(f"{name:<48} {r['top1']:>6.1%} {top3:>6.1%} {c85:>8.1%} {c90:>8.1%}")

    if not n_gemma:
        return

    from mailtag.classifier import Classifier
    from mailtag.config import CONFIG
    from mailtag.database import ClassificationDatabase

    classifier = Classifier(
        CONFIG,
        ClassificationDatabase(
            Path("db/sender_classification_db.json"), Path("db/validated_classification_db.json")
        ),
    )
    if not classifier._init_mlx_components() or classifier._mlx_llm is None:
        sys.exit("MLX LLM unavailable")

    picked = sorted(random.Random(seed).sample(range(len(keep)), n_gemma))
    results = []
    start = time.perf_counter()
    for done, k in enumerate(picked, 1):
        category, confidence, _ = classifier._mlx_llm.classify(taxonomy_prompt(samples[keep[k]]))
        results.append({"label": labels[k], "category": category, "confidence": confidence})
        if done % 10 == 0:
            logger.info(f"Gemma {done}/{n_gemma} ({(time.perf_counter() - start) / done:.1f} s/email)")
    (cache / "gemma_taxonomy_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))

    correct = np.array([r["category"] == r["label"] for r in results])
    conf = np.array([r["confidence"] if r["category"] in TAXONOMY else -1.0 for r in results])
    print(f"\nGemma on {n_gemma} emails: top-1 {correct.mean():.1%}, "
          f"{(time.perf_counter() - start) / n_gemma:.1f} s/email")  # fmt: skip
    for t in (0.7, 0.85, 0.9, 0.95):
        a = conf >= t
        precision = correct[a].mean() if a.any() else 0
        print(f"  confidence >= {t:.2f}: coverage {a.mean():.1%}, precision {precision:.1%}")
    sub = np.array(picked)
    for name, (vc, sims) in variants.items():
        pred = [vc[j] for j in sims[sub].argmax(axis=1)]
        hits = np.mean([p == labels[k] for p, k in zip(pred, picked, strict=True)])
        print(f"  same emails, {name}: {hits:.1%}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Sample emails from IMAP folders (read-only)")
    p_collect.add_argument("--per-folder", type=int, default=20)
    p_collect.add_argument("--output", type=Path, default=DEFAULT_SAMPLE)

    p_eval = sub.add_parser("evaluate", help="Compare embedding models on the sample")
    p_eval.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    p_eval.add_argument("--models", nargs="+", default=DEFAULT_MODELS)

    p_tune = sub.add_parser("tune", help="Compare nomic prefixes and category-building strategies")
    p_tune.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    p_tune.add_argument("--model", default="nomic-ai/nomic-embed-text-v1.5")

    p_gemma = sub.add_parser("gemma", help="Score the Signal 6 LLM and compare with nomic")
    p_gemma.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    p_gemma.add_argument("-n", type=int, default=500)
    p_gemma.add_argument("--seed", type=int, default=0)
    p_gemma.add_argument("--nomic-threshold", type=float, default=0.70)

    p_tax = sub.add_parser("taxonomy", help="Measure nomic and Gemma on the 19-category taxonomy")
    p_tax.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    p_tax.add_argument("--gemma", type=int, default=0, help="number of emails to send to Gemma")
    p_tax.add_argument("--seed", type=int, default=2)

    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

    if args.command == "collect":
        collect(args.per_folder, args.output)
    elif args.command == "gemma":
        gemma(args.sample, args.n, args.seed, args.nomic_threshold)
    elif args.command == "taxonomy":
        taxonomy_eval(args.sample, args.gemma, args.seed)
    elif args.command == "tune":
        tune(args.sample, args.model)
    else:
        evaluate(args.sample, args.models)


if __name__ == "__main__":
    main()
