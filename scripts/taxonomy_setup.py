"""Taxonomy preparation (docs/superpowers/specs/2026-09-28-taxonomie-signaux-design.md, section 1).

    uv run python scripts/taxonomy_setup.py scan        # read-only header pass over existing folders
    uv run python scripts/taxonomy_setup.py crosscheck  # Gemma category per sender (resumable, ~1 s/sender)
    uv run streamlit run scripts/taxonomy_review.py     # review disagreements
    uv run python scripts/taxonomy_setup.py build       # rules, corpus and the 19 nomic centroids
    uv run python scripts/taxonomy_setup.py train       # logistic regression from the corpus (build runs it)

No preparation step moves an email. Legacy folder migration (docs/superpowers/specs/
2026-09-28-migration-dossiers-design.md), a dry run unless given --apply:

    uv run python scripts/taxonomy_setup.py migrate [--apply]  # legacy folder mail -> the 19 categories
    uv run python scripts/taxonomy_setup.py prune [--apply]    # delete emptied legacy folders
    uv run python scripts/taxonomy_setup.py reorganize [--apply]  # PARA folders, standard Promotions

Bulk review of 5-A revoir (docs/superpowers/specs/2026-09-29-revue-en-masse-design.md):

    uv run python scripts/taxonomy_setup.py review-scan --provider imap|gmail     # group, suggest categories
    uv run python scripts/taxonomy_setup.py refile-review --provider imap|gmail [--apply]  # move covered mail
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger

from mailtag.config import CONFIG, TaxonomyConfig
from mailtag.taxonomy_store import TaxonomyStore, write_json_atomic

SCAN = Path("data/mailbox_scan.json")
CROSSCHECK = Path("data/sender_crosscheck.json")
CORPUS = Path("data/taxonomy_corpus.json")
TRAINING_CORPUS = Path("data/training_corpus.json")
MIGRATION_REPORT = Path("data/migration_report.json")


def review_scan_path(provider: str) -> Path:
    return Path("data") / f"review_scan_{provider}.json"


def missing_inputs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def migration_blocked(cfg: TaxonomyConfig) -> str | None:
    """Reason `migrate`/`prune` must not run, or None if the taxonomy rules are ready."""
    db_dir = Path(cfg.taxonomy_db_dir)
    if missing := missing_inputs([db_dir / "senders.json", db_dir / "domains.json"]):
        return f"Missing {missing[0]}: run `scan`, `crosscheck` and `build` first"
    return None


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


def _account(provider: str):
    """The service and account config for `--provider imap|gmail` (not connected yet)."""
    if provider == "gmail":
        from mailtag.gmail_api import GmailApiService

        if CONFIG.gmail is None:
            sys.exit("No [gmail] section in config.toml")
        return GmailApiService(CONFIG.gmail, CONFIG.fast_parse), CONFIG.gmail
    from mailtag.imap_service import ImapService

    return ImapService(CONFIG.imap, CONFIG.fast_parse), CONFIG.imap


def _store() -> TaxonomyStore:
    cfg = CONFIG.taxonomy
    return TaxonomyStore(
        Path(cfg.taxonomy_db_dir), min_agreements=cfg.learn_min_agreements, own_addresses=cfg.own_addresses
    )


def scan() -> None:
    from mailtag.mailbox_scan import scan_mailbox

    folders = json.loads(Path(CONFIG.taxonomy.legacy_folders_file).read_text(encoding="utf-8"))
    store = _store()
    with _imap() as provider:
        result = scan_mailbox(
            provider, folders, overrides=store.folder_overrides, ignored=store.own_addresses
        )
    write_json_atomic(SCAN, result)
    logger.info(f"Wrote {SCAN}: {len(result['senders'])} senders")


def crosscheck() -> None:
    from mailtag.mlx_provider import MLXLLM
    from mailtag.sender_crosscheck import crosscheck_senders

    if missing := missing_inputs([SCAN]):
        sys.exit(f"Missing {missing[0]}: run `scan` first")
    done = _read(CROSSCHECK) if CROSSCHECK.exists() else {}
    llm = MLXLLM(CONFIG.mlx.llm_model)
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
    store = _store()
    learned = learned_senders(
        senders, cross, store.validated, min_mails=cfg.sender_min_mails, agreements=cfg.learn_min_agreements
    )
    domains = domain_rules(senders, store.validated, min_purity=cfg.domain_min_purity)
    store.replace_rules(learned, domains)
    store.save()
    logger.info(f"Rules: {len(store.validated)} validated, {len(learned)} learned, {len(domains)} domains")

    with _imap() as provider:
        corpus = fetch_corpus(provider, corpus_refs(senders, store.validated, learned))
    write_json_atomic(CORPUS, corpus)
    router = build_centroids(MLXEmbedder(CONFIG.mlx.embedding_model), corpus)
    router.save_embeddings(Path(cfg.centroids_file))
    logger.info(f"Centroids for {router.num_categories} categories from {len(corpus)} mails")
    train()


def train() -> None:
    """Fit the [logreg] model on data/training_corpus.json (capped to [logreg] per_sender) if it
    exists, else on data/taxonomy_corpus.json (no IMAP, no rule touched)."""
    from mailtag.logreg_provider import capped_indices, corpus_texts, embed, save_model
    from mailtag.logreg_provider import train as fit
    from mailtag.mlx_provider import MLXEmbedder

    source = TRAINING_CORPUS if TRAINING_CORPUS.exists() else CORPUS
    if missing := missing_inputs([source]):
        sys.exit(f"Missing {missing[0]}: run `build` first")
    corpus = _read(source)
    if source == TRAINING_CORPUS:
        corpus = [corpus[i] for i in capped_indices(corpus, CONFIG.logreg.per_sender)]
    if len({m["category"] for m in corpus}) < 3:
        sys.exit(f"{source} needs mails in at least 3 categories to train")
    embedding_model = CONFIG.mlx.embedding_model
    embeddings = embed(MLXEmbedder(embedding_model), corpus_texts(corpus))
    model = fit(embeddings, [m["category"] for m in corpus], CONFIG.logreg.C)
    save_model(Path(CONFIG.logreg.model_file), model, embedding_model)
    logger.info(
        f"Logistic regression from {len(corpus)} mails of {source}, {len(model['classes'])} categories "
        f"-> {CONFIG.logreg.model_file}"
    )


def migrate(apply: bool) -> None:
    from mailtag.migration import folders_to_migrate, migrate_mailbox
    from mailtag.pending_archive import PendingArchive

    cfg = CONFIG.taxonomy
    if reason := migration_blocked(cfg):
        sys.exit(reason)
    if apply:
        logger.warning("migrate --apply is running: do not run `run` or `serve` until it finishes")

    legacy = json.loads(Path(cfg.legacy_folders_file).read_text(encoding="utf-8"))
    rules = _store()
    pending = PendingArchive(Path(cfg.pending_archive_file))

    with _imap() as provider:
        report = migrate_mailbox(
            provider, folders_to_migrate(legacy), rules.folder_overrides, rules, pending,
            date.today(), apply,
        )  # fmt: skip
    write_json_atomic(MIGRATION_REPORT, report)
    logger.info(
        f"Migration: {sum(report['totals'].values())} mails {'moved' if apply else 'to move'}, "
        f"{report['review_total']} to review, {len(report['skipped_folders'])} folders skipped"
    )
    if report["aborted_at"]:
        logger.error(f"Connection lost at {report['aborted_at']}: run `migrate` again to resume")


def prune(apply: bool) -> None:
    from mailtag.migration import delete_empty_folders, empty_legacy_folders

    cfg = CONFIG.taxonomy
    if reason := migration_blocked(cfg):
        sys.exit(reason)
    legacy = json.loads(Path(cfg.legacy_folders_file).read_text(encoding="utf-8"))

    with _imap() as provider:
        client = provider.client
        live_folders = [folder[2] for folder in client.list_folders()]
        removable = empty_legacy_folders(client, legacy, live_folders)
        if not apply:
            logger.info(f"{len(removable)} empty legacy folders could be deleted:")
            for folder in removable:
                logger.info(f"  {folder}")
            return
        deleted = delete_empty_folders(client, removable, live_folders)
        logger.info(f"Deleted {len(deleted)} of {len(removable)} empty legacy folders")


def reorganize_folders(apply: bool) -> None:
    from mailtag.migration import reorganize, reorganize_plan

    if reason := migration_blocked(CONFIG.taxonomy):
        sys.exit(reason)
    if apply:
        logger.warning("reorganize --apply is running: do not run `run` or `serve` until it finishes")
    with _imap() as provider:
        plan = reorganize_plan([folder[2] for folder in provider.client.list_folders()])
        report = reorganize(provider, plan, apply)
    logger.info(
        f"Reorganize: {len(plan['renames'])} renames, {len(plan['merges'])} merges"
        f"{'' if apply else ' (dry run)'}, {len(report['failed'])} failed {report['failed']}"
    )


def review_scan(provider: str) -> None:
    from mailtag.mlx_provider import MLXLLM
    from mailtag.review_refile import read_review_mails, review_groups, suggest_categories

    cfg = CONFIG.taxonomy
    store = _store()
    service, _ = _account(provider)
    with service.connect() as p:
        mails = read_review_mails(p)
    groups = review_groups(mails, store)

    path = review_scan_path(provider)
    # An unreadable Gemma answer (None) is asked again
    done = {k: v for k, v in _read(path)["suggestions"].items() if v} if path.exists() else {}
    if any(key not in done for key in groups):
        llm = MLXLLM(CONFIG.mlx.llm_model)
        suggestions = suggest_categories(groups, llm, done, batch_size=cfg.llm_batch_size)
    else:
        suggestions = done
    write_json_atomic(path, {"groups": groups, "suggestions": suggestions})
    total_mails = sum(g["mails"] for g in groups.values())
    logger.info(f"Wrote {path}: {len(groups)} groups, {total_mails} mails")


def refile(provider: str, apply: bool) -> None:
    from mailtag.pending_archive import PendingArchive
    from mailtag.review_refile import refile_review
    from mailtag.utils.tasks import pending_archive_path

    cfg = CONFIG.taxonomy
    if reason := migration_blocked(cfg):
        sys.exit(reason)
    if apply:
        logger.warning("refile-review --apply is running: do not run `run` or `serve` until it finishes")

    store = _store()
    service, account_cfg = _account(provider)
    pending = PendingArchive(pending_archive_path(account_cfg, cfg.pending_archive_file))

    with service.connect() as p:
        report = refile_review(p, store.category_for, pending, apply)

    for category, count in sorted(report["moves"].items()):
        logger.info(f"  {category}: {count}")
    total = sum(report["moves"].values())
    moved = "mails moved" if apply else "mails would move (dry run)"
    logger.info(f"Refile: {total} {moved}, {report['left']} left")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command",
        choices=[
            "scan", "crosscheck", "build", "train", "migrate", "prune", "reorganize", "review-scan",
            "refile-review",
        ],
    )  # fmt: skip
    parser.add_argument("--apply", action="store_true", help="Actually move/delete (default: dry run)")
    parser.add_argument("--provider", choices=["imap", "gmail"], default="imap", help="Account to use")
    args = parser.parse_args()
    if args.command in ("migrate", "prune", "reorganize"):
        {"migrate": migrate, "prune": prune, "reorganize": reorganize_folders}[args.command](args.apply)
    elif args.command == "review-scan":
        review_scan(args.provider)
    elif args.command == "refile-review":
        refile(args.provider, args.apply)
    else:
        {"scan": scan, "crosscheck": crosscheck, "build": build, "train": train}[args.command]()


if __name__ == "__main__":
    main()
