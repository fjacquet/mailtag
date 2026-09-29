"""Timestamped backups of the taxonomy rules and pending archives."""

import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger


def backup_database(db_path: Path, backup_dir: Path | None = None) -> Path | None:
    """
    Create a timestamped backup of a database file.

    Args:
        db_path: Path to the database file to backup
        backup_dir: Directory for backups (default: db/backups/)

    Returns:
        Path to the backup file, or None if source doesn't exist
    """
    if not db_path.exists():
        logger.debug(f"No backup needed: {db_path} does not exist")
        return None

    if backup_dir is None:
        backup_dir = db_path.parent / "backups"

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{db_path.stem}_{timestamp}{db_path.suffix}"
    backup_path = backup_dir / backup_name

    shutil.copy2(db_path, backup_path)
    logger.info(f"Created backup: {backup_path}")

    return backup_path


def backup_all_databases(db_dir: Path, backup_dir: Path | None = None) -> list[Path]:
    """Back up the taxonomy rules (`db/taxonomy/*.json`) and each account's pending archive."""
    if backup_dir is None:
        backup_dir = db_dir / "backups"

    db_files = sorted((db_dir / "taxonomy").glob("*.json")) + sorted(db_dir.glob("pending_archive*.json"))
    backups = [path for path in (backup_database(f, backup_dir) for f in db_files) if path]

    logger.info(f"Backed up {len(backups)} database files to {backup_dir}")
    return backups


def cleanup_old_backups(backup_dir: Path, keep_count: int = 10) -> int:
    """
    Remove old backups, keeping the most recent ones.

    Args:
        backup_dir: Directory containing backups
        keep_count: Number of backups to keep per database type

    Returns:
        Number of backup files deleted
    """
    if not backup_dir.exists():
        return 0

    # Group backups by base name (e.g., sender_classification_db)
    backups_by_type: dict[str, list[Path]] = {}

    for backup_file in backup_dir.glob("*.json"):
        # Extract base name (everything before the timestamp)
        # Format: basename_YYYYMMDD_HHMMSS.json
        parts = backup_file.stem.rsplit("_", 2)
        if len(parts) >= 3:
            base_name = parts[0]
            if base_name not in backups_by_type:
                backups_by_type[base_name] = []
            backups_by_type[base_name].append(backup_file)

    deleted_count = 0

    for _base_name, backups in backups_by_type.items():
        # Sort by modification time (newest first)
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Delete excess backups
        for old_backup in backups[keep_count:]:
            old_backup.unlink()
            logger.debug(f"Deleted old backup: {old_backup.name}")
            deleted_count += 1

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old backup files")

    return deleted_count


def get_backup_stats(backup_dir: Path) -> dict:
    """
    Get statistics about backups.

    Args:
        backup_dir: Directory containing backups

    Returns:
        Dictionary with backup statistics
    """
    if not backup_dir.exists():
        return {
            "total_backups": 0,
            "total_size_bytes": 0,
            "oldest_backup": None,
            "newest_backup": None,
        }

    backups = list(backup_dir.glob("*.json"))

    if not backups:
        return {
            "total_backups": 0,
            "total_size_bytes": 0,
            "oldest_backup": None,
            "newest_backup": None,
        }

    total_size = sum(b.stat().st_size for b in backups)
    sorted_backups = sorted(backups, key=lambda p: p.stat().st_mtime)

    return {
        "total_backups": len(backups),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "oldest_backup": sorted_backups[0].name,
        "newest_backup": sorted_backups[-1].name,
    }
