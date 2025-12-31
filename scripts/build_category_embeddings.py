#!/usr/bin/env python3
"""Build category embeddings from existing classification databases.

This script generates embeddings for each category based on:
1. Validated sender-category mappings (db/validated_classification_db.json)
2. IMAP folder structure (data/imap_folders.json)
3. Historical classification patterns (db/sender_classification_db.json)

The embeddings are saved to data/category_embeddings.npz for use by
the SemanticRouter during classification.

Usage:
    python scripts/build_category_embeddings.py [--output PATH] [--model MODEL]
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger


def load_json_file(path: Path) -> dict | list | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if not path.exists():
        logger.warning(f"File not found: {path}")
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {path}: {e}")
        return None


def extract_categories_from_validated_db(validated_db: dict[str, str]) -> dict[str, list[str]]:
    """Extract category examples from validated database.

    Args:
        validated_db: Dict mapping sender email to category

    Returns:
        Dict mapping category to list of example texts
    """
    category_examples: dict[str, list[str]] = {}

    for sender, category in validated_db.items():
        if category not in category_examples:
            category_examples[category] = []

        # Create representative text from sender
        domain = sender.split("@")[-1] if "@" in sender else sender
        company = domain.split(".")[0] if "." in domain else domain

        # Add multiple variations for better embedding
        examples = [
            f"Email from {company}",
            f"Message from {domain}",
            f"Correspondence from {sender}",
            f"Category {category} email from {company}",
        ]
        category_examples[category].extend(examples)

    return category_examples


def extract_categories_from_folders(folders: list[str]) -> dict[str, list[str]]:
    """Extract category examples from folder names.

    Args:
        folders: List of folder paths (e.g., "Inbox/Commerce/Amazon")

    Returns:
        Dict mapping category to list of example texts
    """
    category_examples: dict[str, list[str]] = {}

    for folder in folders:
        # Use full folder path as category
        if folder not in category_examples:
            category_examples[folder] = []

        # Extract meaningful parts from folder name
        parts = folder.split("/")
        folder_name = parts[-1] if parts else folder

        # Create example texts based on folder name
        examples = [
            f"Email belonging to {folder_name}",
            f"Message for category {folder_name}",
            f"Content related to {folder_name}",
            f"{folder} folder email",
        ]
        category_examples[folder].extend(examples)

        # If folder has parent, add context
        if len(parts) > 1:
            parent = parts[-2]
            examples.append(f"{folder_name} under {parent}")

    return category_examples


def extract_categories_from_history(sender_db: dict[str, dict]) -> dict[str, list[str]]:
    """Extract category examples from historical sender database.

    Args:
        sender_db: Dict mapping sender to category counts

    Returns:
        Dict mapping category to list of example texts
    """
    category_examples: dict[str, list[str]] = {}

    for sender, categories in sender_db.items():
        if not isinstance(categories, dict):
            continue

        # Find dominant category for this sender
        dominant_category = max(categories, key=categories.get)
        count = categories[dominant_category]

        # Only use high-confidence senders (10+ occurrences)
        if count < 10:
            continue

        if dominant_category not in category_examples:
            category_examples[dominant_category] = []

        domain = sender.split("@")[-1] if "@" in sender else sender
        company = domain.split(".")[0] if "." in domain else domain

        category_examples[dominant_category].append(f"Frequent email from {company}")

    return category_examples


def merge_examples(
    *example_dicts: dict[str, list[str]],
    max_per_category: int = 20,
) -> dict[str, list[str]]:
    """Merge multiple example dictionaries, deduplicating.

    Args:
        *example_dicts: Variable number of example dictionaries
        max_per_category: Maximum examples to keep per category

    Returns:
        Merged dictionary with deduplicated examples
    """
    merged: dict[str, list[str]] = {}

    for examples in example_dicts:
        for category, texts in examples.items():
            if category not in merged:
                merged[category] = []
            merged[category].extend(texts)

    # Deduplicate and limit
    for category in merged:
        unique = list(dict.fromkeys(merged[category]))  # Preserve order, remove dupes
        merged[category] = unique[:max_per_category]

    return merged


def build_embeddings(
    output_path: Path,
    model_name: str,
    validated_db_path: Path,
    folders_path: Path,
    sender_db_path: Path,
) -> bool:
    """Build and save category embeddings.

    Args:
        output_path: Path to save embeddings (.npz file)
        model_name: Embedding model name
        validated_db_path: Path to validated classification database
        folders_path: Path to IMAP folders JSON
        sender_db_path: Path to sender classification database

    Returns:
        True if successful, False otherwise
    """
    from mailtag.mlx_provider import MLXEmbedder
    from mailtag.semantic_router import SemanticRouter

    # Collect examples from all sources
    all_examples: list[dict[str, list[str]]] = []

    # 1. Validated database (highest priority)
    validated_db = load_json_file(validated_db_path)
    if validated_db and isinstance(validated_db, dict):
        examples = extract_categories_from_validated_db(validated_db)
        all_examples.append(examples)
        logger.info(f"Extracted {len(examples)} categories from validated_db")

    # 2. IMAP folders structure
    folders_data = load_json_file(folders_path)
    if folders_data:
        # Handle both list and dict formats
        if isinstance(folders_data, list):
            folders = folders_data
        elif isinstance(folders_data, dict):
            folders = folders_data.get("folders", [])
        else:
            folders = []

        if folders:
            examples = extract_categories_from_folders(folders)
            all_examples.append(examples)
            logger.info(f"Extracted {len(examples)} categories from folder structure")

    # 3. Historical sender database
    sender_db = load_json_file(sender_db_path)
    if sender_db and isinstance(sender_db, dict):
        examples = extract_categories_from_history(sender_db)
        all_examples.append(examples)
        logger.info(f"Extracted {len(examples)} categories from sender history")

    if not all_examples:
        logger.error("No category data found. Please ensure databases exist.")
        return False

    # Merge all examples
    merged = merge_examples(*all_examples)
    logger.info(f"Total categories after merge: {len(merged)}")

    # Filter categories with too few examples
    filtered = {cat: examples for cat, examples in merged.items() if len(examples) >= 2}
    logger.info(f"Categories with 2+ examples: {len(filtered)}")

    if not filtered:
        logger.error("No categories have enough examples to build embeddings")
        return False

    # Build embeddings
    logger.info(f"Loading embedding model: {model_name}")
    embedder = MLXEmbedder(model_name)
    router = SemanticRouter(embedder)

    logger.info("Building category embeddings...")
    router.build_from_examples(filtered)

    # Save embeddings
    success = router.save_embeddings(output_path)
    if success:
        logger.info(f"Successfully saved embeddings to {output_path}")
        logger.info(f"Categories: {len(router.categories)}")
        logger.info(f"Sample categories: {router.categories[:10]}")
    else:
        logger.error(f"Failed to save embeddings to {output_path}")

    return success


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Build category embeddings for semantic routing")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/category_embeddings.npz"),
        help="Output path for embeddings file",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="nomic-ai/nomic-embed-text-v1.5",
        help="Embedding model name",
    )
    parser.add_argument(
        "--validated-db",
        type=Path,
        default=Path("db/validated_classification_db.json"),
        help="Path to validated classification database",
    )
    parser.add_argument(
        "--folders",
        type=Path,
        default=Path("data/imap_folders.json"),
        help="Path to IMAP folders JSON",
    )
    parser.add_argument(
        "--sender-db",
        type=Path,
        default=Path("db/sender_classification_db.json"),
        help="Path to sender classification database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logger.remove()
    level = "DEBUG" if args.verbose else "INFO"
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level:<7} | {message}")

    logger.info("Building category embeddings...")
    logger.info(f"Output: {args.output}")
    logger.info(f"Model: {args.model}")

    success = build_embeddings(
        output_path=args.output,
        model_name=args.model,
        validated_db_path=args.validated_db,
        folders_path=args.folders,
        sender_db_path=args.sender_db,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
