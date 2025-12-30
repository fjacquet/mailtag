"""Tests for data cleanup utilities."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mailtag.utils.data_cleanup import (
    cleanup_old_pass3_files,
    consolidate_duplicate_pass3_files,
    get_pass3_file_stats,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with pass3 files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


def create_pass3_file(data_dir: Path, date_str: str, time_str: str) -> Path:
    """Helper to create a pass3 file with given date and time."""
    filename = f"pass3_manual_matching_{date_str}_{time_str}.json"
    file_path = data_dir / filename
    file_path.write_text(
        json.dumps({"timestamp": f"{date_str}T{time_str}", "emails_for_manual_matching": []})
    )
    return file_path


class TestCleanupOldPass3Files:
    def test_cleanup_old_files(self, data_dir: Path):
        """Test that old files are deleted."""
        today = datetime.now()
        old_date = (today - timedelta(days=35)).strftime("%Y%m%d")
        recent_date = (today - timedelta(days=5)).strftime("%Y%m%d")

        create_pass3_file(data_dir, old_date, "120000")
        create_pass3_file(data_dir, recent_date, "120000")

        deleted = cleanup_old_pass3_files(data_dir, max_age_days=30)

        assert deleted == 1
        files = list(data_dir.glob("pass3_manual_matching_*.json"))
        assert len(files) == 1
        assert recent_date in files[0].name

    def test_keep_recent_files(self, data_dir: Path):
        """Test that recent files are kept."""
        today = datetime.now()
        recent_date = (today - timedelta(days=5)).strftime("%Y%m%d")

        create_pass3_file(data_dir, recent_date, "120000")
        create_pass3_file(data_dir, recent_date, "130000")

        deleted = cleanup_old_pass3_files(data_dir, max_age_days=30)

        assert deleted == 0
        files = list(data_dir.glob("pass3_manual_matching_*.json"))
        assert len(files) == 2

    def test_empty_directory(self, data_dir: Path):
        """Test cleanup on empty directory."""
        deleted = cleanup_old_pass3_files(data_dir, max_age_days=30)
        assert deleted == 0


class TestConsolidateDuplicatePass3Files:
    def test_consolidate_same_day_files(self, data_dir: Path):
        """Test that duplicate files from same day are consolidated."""
        date_str = "20251225"
        create_pass3_file(data_dir, date_str, "100000")  # First - keep
        create_pass3_file(data_dir, date_str, "110000")  # Middle - delete
        create_pass3_file(data_dir, date_str, "120000")  # Middle - delete
        create_pass3_file(data_dir, date_str, "130000")  # Last - keep

        deleted = consolidate_duplicate_pass3_files(data_dir)

        assert deleted == 2
        files = sorted(data_dir.glob("pass3_manual_matching_*.json"))
        assert len(files) == 2
        assert "100000" in files[0].name
        assert "130000" in files[1].name

    def test_keep_single_file(self, data_dir: Path):
        """Test that single file per day is kept."""
        create_pass3_file(data_dir, "20251225", "120000")

        deleted = consolidate_duplicate_pass3_files(data_dir)

        assert deleted == 0
        files = list(data_dir.glob("pass3_manual_matching_*.json"))
        assert len(files) == 1

    def test_keep_two_files(self, data_dir: Path):
        """Test that two files per day are both kept."""
        create_pass3_file(data_dir, "20251225", "100000")
        create_pass3_file(data_dir, "20251225", "120000")

        deleted = consolidate_duplicate_pass3_files(data_dir)

        assert deleted == 0
        files = list(data_dir.glob("pass3_manual_matching_*.json"))
        assert len(files) == 2


class TestGetPass3FileStats:
    def test_stats_with_files(self, data_dir: Path):
        """Test stats calculation with multiple files."""
        create_pass3_file(data_dir, "20251220", "100000")
        create_pass3_file(data_dir, "20251225", "120000")
        create_pass3_file(data_dir, "20251225", "130000")

        stats = get_pass3_file_stats(data_dir)

        assert stats["total_files"] == 3
        assert stats["oldest_date"] == "20251220"
        assert stats["newest_date"] == "20251225"
        assert stats["files_by_date"]["20251220"] == 1
        assert stats["files_by_date"]["20251225"] == 2

    def test_stats_empty_directory(self, data_dir: Path):
        """Test stats on empty directory."""
        stats = get_pass3_file_stats(data_dir)

        assert stats["total_files"] == 0
        assert stats["oldest_date"] is None
        assert stats["newest_date"] is None
