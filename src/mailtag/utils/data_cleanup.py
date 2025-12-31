"""Utilities for cleaning up data files."""

import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


def cleanup_old_pass3_files(data_dir: Path, max_age_days: int = 30) -> int:
    """
    Remove pass3_manual_matching files older than max_age_days.

    Args:
        data_dir: Path to the data directory
        max_age_days: Maximum age in days for files to keep

    Returns:
        Number of files deleted
    """
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    pattern = re.compile(r"pass3_manual_matching_(\d{8})_\d{6}\.json")
    deleted_count = 0

    for file_path in data_dir.glob("pass3_manual_matching_*.json"):
        match = pattern.match(file_path.name)
        if match:
            date_str = match.group(1)
            try:
                file_date = datetime.strptime(date_str, "%Y%m%d")
                if file_date < cutoff_date:
                    file_path.unlink()
                    logger.info(f"Deleted old pass3 file: {file_path.name}")
                    deleted_count += 1
            except ValueError:
                logger.warning(f"Could not parse date from filename: {file_path.name}")

    logger.info(f"Cleanup complete: deleted {deleted_count} pass3 files older than {max_age_days} days")
    return deleted_count


def consolidate_duplicate_pass3_files(data_dir: Path) -> int:
    """
    Remove duplicate pass3 files, keeping first and last of each day.

    Args:
        data_dir: Path to the data directory

    Returns:
        Number of files deleted
    """
    pattern = re.compile(r"pass3_manual_matching_(\d{8})_(\d{6})\.json")

    # Group files by date
    files_by_date: dict[str, list[tuple[str, Path]]] = defaultdict(list)

    for file_path in data_dir.glob("pass3_manual_matching_*.json"):
        match = pattern.match(file_path.name)
        if match:
            date_str = match.group(1)
            time_str = match.group(2)
            files_by_date[date_str].append((time_str, file_path))

    deleted_count = 0

    for date_str, files in files_by_date.items():
        if len(files) <= 2:
            continue  # Keep all if 2 or fewer files for this date

        # Sort by time
        files.sort(key=lambda x: x[0])

        # Keep first and last, delete the rest
        first_file = files[0][1]
        last_file = files[-1][1]

        for _time_str, file_path in files[1:-1]:
            file_path.unlink()
            logger.info(f"Deleted duplicate pass3 file: {file_path.name}")
            deleted_count += 1

        logger.debug(f"Date {date_str}: kept {first_file.name} and {last_file.name}")

    logger.info(f"Consolidation complete: deleted {deleted_count} duplicate pass3 files")
    return deleted_count


def get_pass3_file_stats(data_dir: Path) -> dict:
    """
    Get statistics about pass3 files.

    Args:
        data_dir: Path to the data directory

    Returns:
        Dictionary with statistics
    """
    pattern = re.compile(r"pass3_manual_matching_(\d{8})_\d{6}\.json")
    files = list(data_dir.glob("pass3_manual_matching_*.json"))

    if not files:
        return {
            "total_files": 0,
            "total_size_bytes": 0,
            "oldest_date": None,
            "newest_date": None,
            "files_by_date": {},
        }

    total_size = sum(f.stat().st_size for f in files)
    dates: list[str] = []
    files_by_date: dict[str, int] = defaultdict(int)

    for file_path in files:
        match = pattern.match(file_path.name)
        if match:
            date_str = match.group(1)
            dates.append(date_str)
            files_by_date[date_str] += 1

    dates.sort()

    return {
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "oldest_date": dates[0] if dates else None,
        "newest_date": dates[-1] if dates else None,
        "files_by_date": dict(files_by_date),
    }
