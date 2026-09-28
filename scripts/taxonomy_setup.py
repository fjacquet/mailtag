"""Taxonomy preparation (docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md, section 1).

    uv run python scripts/taxonomy_setup.py scan        # read-only header pass over existing folders
    uv run python scripts/taxonomy_setup.py crosscheck  # Gemma category per sender (resumable, ~1 s/sender)
    uv run streamlit run scripts/taxonomy_review.py     # review disagreements
    uv run python scripts/taxonomy_setup.py build       # rules, corpus and the 19 nomic centroids

No step moves an email.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mailtag.config import CONFIG
from mailtag.taxonomy_store import TaxonomyStore, write_json_atomic

SCAN = Path("data/mailbox_scan.json")
CROSSCHECK = Path("data/sender_crosscheck.json")
CORPUS = Path("data/taxonomy_corpus.json")


def missing_inputs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def needs_rescan(scan_path: Path, overrides_path: Path) -> bool:
    """True if the folder audit ran after the last scan, so the scan is stale."""
    if not overrides_path.exists():
        return False
    if not scan_path.exists():
        return True
    return scan_path.stat().st_mtime < overrides_path.stat().st_mtime


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _imap():
    from mailtag.imap_service import ImapService

    return ImapService(CONFIG.imap, CONFIG.fast_parse).connect()


def scan() -> None:
    from mailtag.mailbox_scan import scan_mailbox

    folders = json.loads(Path(CONFIG.taxonomy.legacy_folders_file).read_text(encoding="utf-8"))
    overrides = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir)).folder_overrides
    with _imap() as provider:
        result = scan_mailbox(provider, folders, overrides=overrides)
    write_json_atomic(SCAN, result)
    logger.info(f"Wrote {SCAN}: {len(result['senders'])} senders")


def crosscheck() -> None:
    from mailtag.mlx_provider import MLXLLM
    from mailtag.sender_crosscheck import crosscheck_senders

    if missing := missing_inputs([SCAN]):
        sys.exit(f"Missing {missing[0]}: run `scan` first")
    done = _read(CROSSCHECK) if CROSSCHECK.exists() else {}
    llm = MLXLLM(CONFIG.mlx.llm_model, max_tokens=4, temperature=0.0)
    crosscheck_senders(
        _read(SCAN)["senders"], llm, done, batch_size=CONFIG.taxonomy.llm_batch_size,
        on_save=lambda results: write_json_atomic(CROSSCHECK, results),
    )  # fmt: skip


def build() -> None:
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.taxonomy_build import (
        build_centroids,
        corpus_refs,
        domain_rules,
        fetch_corpus,
        learned_senders,
    )

    if missing := missing_inputs([SCAN, CROSSCHECK]):
        sys.exit(f"Missing {missing[0]}: run `scan` and `crosscheck` first")
    cfg = CONFIG.taxonomy
    senders, cross = _read(SCAN)["senders"], _read(CROSSCHECK)
    store = TaxonomyStore(Path(cfg.taxonomy_db_dir), min_agreements=cfg.learn_min_agreements)
    learned = learned_senders(
        senders, cross, store.validated, min_mails=cfg.sender_min_mails, agreements=cfg.learn_min_agreements
    )
    domains = domain_rules(senders, store.validated, learned, min_purity=cfg.domain_min_purity)
    store.replace_rules(learned, domains)
    store.save()
    logger.info(f"Rules: {len(store.validated)} validated, {len(learned)} learned, {len(domains)} domains")

    with _imap() as provider:
        corpus = fetch_corpus(provider, corpus_refs(senders, store.validated, learned))
    write_json_atomic(CORPUS, corpus)
    router = build_centroids(MLXEmbedder(CONFIG.mlx.embedding_model), corpus)
    router.save_embeddings(Path(cfg.centroids_file))
    logger.info(f"Centroids for {router.num_categories} categories from {len(corpus)} mails")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["scan", "crosscheck", "build"])
    {"scan": scan, "crosscheck": crosscheck, "build": build}[parser.parse_args().command]()


if __name__ == "__main__":
    main()
