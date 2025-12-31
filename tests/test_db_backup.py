"""Tests for database backup utilities."""

import json
from pathlib import Path

import pytest

from mailtag.utils.db_backup import (
    backup_all_databases,
    backup_database,
    cleanup_old_backups,
    get_backup_stats,
    list_backups,
    restore_database,
)


@pytest.fixture
def db_dir(tmp_path: Path) -> Path:
    """Create a temporary db directory with sample databases."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    # Create sample databases
    sender_db = db_dir / "sender_classification_db.json"
    sender_db.write_text(json.dumps({"test@example.com": {"Category": 1}}))

    domain_db = db_dir / "domain_classifications.json"
    domain_db.write_text(json.dumps({"example.com": "Category"}))

    validated_db = db_dir / "validated_classification_db.json"
    validated_db.write_text(json.dumps({}))

    return db_dir


class TestBackupDatabase:
    def test_backup_creates_file(self, db_dir: Path):
        """Test that backup creates a file."""
        db_path = db_dir / "sender_classification_db.json"
        backup_path = backup_database(db_path)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.parent.name == "backups"

    def test_backup_content_matches(self, db_dir: Path):
        """Test that backup content matches original."""
        db_path = db_dir / "sender_classification_db.json"
        original_content = db_path.read_text()

        backup_path = backup_database(db_path)

        assert backup_path.read_text() == original_content

    def test_backup_nonexistent_file(self, tmp_path: Path):
        """Test that backing up nonexistent file returns None."""
        db_path = tmp_path / "nonexistent.json"
        result = backup_database(db_path)
        assert result is None

    def test_backup_custom_directory(self, db_dir: Path, tmp_path: Path):
        """Test backup to custom directory."""
        db_path = db_dir / "sender_classification_db.json"
        custom_backup_dir = tmp_path / "custom_backups"

        backup_path = backup_database(db_path, custom_backup_dir)

        assert backup_path.parent == custom_backup_dir


class TestBackupAllDatabases:
    def test_backup_all(self, db_dir: Path):
        """Test backing up all databases."""
        backups = backup_all_databases(db_dir)

        assert len(backups) == 3
        backup_dir = db_dir / "backups"
        assert backup_dir.exists()
        assert len(list(backup_dir.glob("*.json"))) == 3


class TestRestoreDatabase:
    def test_restore_from_backup(self, db_dir: Path):
        """Test restoring database from backup."""
        db_path = db_dir / "sender_classification_db.json"
        original_content = db_path.read_text()

        backup_path = backup_database(db_path)

        # Modify original
        db_path.write_text(json.dumps({"modified": True}))

        # Restore
        restore_database(backup_path, db_path)

        assert db_path.read_text() == original_content

    def test_restore_nonexistent_backup(self, tmp_path: Path):
        """Test restoring from nonexistent backup raises error."""
        with pytest.raises(FileNotFoundError):
            restore_database(tmp_path / "nonexistent.json", tmp_path / "db.json")


class TestCleanupOldBackups:
    def test_cleanup_keeps_recent(self, db_dir: Path):
        """Test that cleanup keeps recent backups."""
        # Create multiple backups
        for _ in range(5):
            backup_all_databases(db_dir)

        backup_dir = db_dir / "backups"
        deleted = cleanup_old_backups(backup_dir, keep_count=10)

        assert deleted == 0

    def test_cleanup_removes_excess(self, db_dir: Path):
        """Test that cleanup removes excess backups."""
        import time

        backup_dir = db_dir / "backups"
        backup_dir.mkdir(exist_ok=True)

        # Create multiple backup files manually with different timestamps
        for i in range(5):
            filename = f"sender_classification_db_20251230_10000{i}.json"
            (backup_dir / filename).write_text("{}")
            time.sleep(0.01)  # Ensure different mtime

        deleted = cleanup_old_backups(backup_dir, keep_count=2)

        # Should keep 2, delete 3
        assert deleted == 3
        assert len(list(backup_dir.glob("*.json"))) == 2


class TestListBackups:
    def test_list_backups(self, db_dir: Path):
        """Test listing backups."""
        backup_all_databases(db_dir)

        backup_dir = db_dir / "backups"
        backups = list_backups(backup_dir)

        assert len(backups) == 3
        for backup in backups:
            assert "path" in backup
            assert "name" in backup
            assert "size_bytes" in backup
            assert "created" in backup

    def test_list_empty_directory(self, tmp_path: Path):
        """Test listing backups in empty directory."""
        backups = list_backups(tmp_path)
        assert backups == []


class TestGetBackupStats:
    def test_stats_with_backups(self, db_dir: Path):
        """Test stats with backups."""
        backup_all_databases(db_dir)

        backup_dir = db_dir / "backups"
        stats = get_backup_stats(backup_dir)

        assert stats["total_backups"] == 3
        assert stats["total_size_bytes"] > 0

    def test_stats_empty_directory(self, tmp_path: Path):
        """Test stats with no backups."""
        stats = get_backup_stats(tmp_path)

        assert stats["total_backups"] == 0
        assert stats["oldest_backup"] is None
