"""Tests for data validation utilities."""

import json
from pathlib import Path

import pytest

from mailtag.utils.data_validation import (
    fix_domain_classifications,
    get_database_stats,
    normalize_domain,
    normalize_email,
    prune_low_confidence_senders,
    validate_domain_classifications,
    validate_domain_format,
    validate_sender_classifications,
)


class TestNormalizeEmail:
    def test_simple_email(self):
        """Test normalizing a simple email."""
        assert normalize_email("Test@Example.COM") == "test@example.com"

    def test_email_with_angle_brackets(self):
        """Test normalizing email with angle brackets."""
        assert normalize_email("<test@example.com>") == "test@example.com"

    def test_email_with_name(self):
        """Test normalizing email with display name."""
        # The normalize_email function extracts the email from angle brackets
        result = normalize_email("John Doe <john@example.com>")
        assert result == "john@example.com"

    def test_empty_email(self):
        """Test normalizing empty email."""
        assert normalize_email("") == ""

    def test_email_with_whitespace(self):
        """Test normalizing email with whitespace."""
        assert normalize_email("  test@example.com  ") == "test@example.com"


class TestNormalizeDomain:
    def test_simple_domain(self):
        """Test normalizing a simple domain."""
        assert normalize_domain("Example.COM") == "example.com"

    def test_domain_with_trailing_gt(self):
        """Test normalizing domain with trailing >."""
        assert normalize_domain("example.com>") == "example.com"

    def test_domain_with_angle_brackets(self):
        """Test normalizing domain with angle brackets."""
        assert normalize_domain("<example.com>") == "example.com"

    def test_empty_domain(self):
        """Test normalizing empty domain."""
        assert normalize_domain("") == ""


class TestValidateDomainFormat:
    def test_valid_domain(self):
        """Test valid domain formats."""
        assert validate_domain_format("example.com") is True
        assert validate_domain_format("sub.example.com") is True
        assert validate_domain_format("example.co.uk") is True

    def test_invalid_domain(self):
        """Test invalid domain formats."""
        assert validate_domain_format("") is False
        assert validate_domain_format("example") is False
        assert validate_domain_format("-example.com") is False


class TestValidateDomainClassifications:
    def test_valid_db(self, tmp_path: Path):
        """Test validation of valid database."""
        db_path = tmp_path / "domain_db.json"
        db_path.write_text(json.dumps({"example.com": "Category/Sub"}))

        issues = validate_domain_classifications(db_path)
        assert issues == []

    def test_malformed_domain(self, tmp_path: Path):
        """Test detection of malformed domain."""
        db_path = tmp_path / "domain_db.json"
        db_path.write_text(json.dumps({"example.com>": "Category"}))

        issues = validate_domain_classifications(db_path)
        assert len(issues) == 1
        assert "Malformed domain" in issues[0]

    def test_empty_category(self, tmp_path: Path):
        """Test detection of empty category."""
        db_path = tmp_path / "domain_db.json"
        db_path.write_text(json.dumps({"example.com": ""}))

        issues = validate_domain_classifications(db_path)
        assert len(issues) == 1
        assert "Empty category" in issues[0]

    def test_missing_file(self, tmp_path: Path):
        """Test validation of missing file."""
        db_path = tmp_path / "nonexistent.json"
        issues = validate_domain_classifications(db_path)
        assert len(issues) == 1
        assert "File not found" in issues[0]


class TestValidateSenderClassifications:
    def test_valid_db(self, tmp_path: Path):
        """Test validation of valid database."""
        db_path = tmp_path / "sender_db.json"
        db_path.write_text(json.dumps({"test@example.com": {"Category": 5}}))

        issues = validate_sender_classifications(db_path)
        assert issues == []

    def test_needs_normalization(self, tmp_path: Path):
        """Test detection of sender needing normalization."""
        db_path = tmp_path / "sender_db.json"
        db_path.write_text(json.dumps({"<Test@Example.COM>": {"Category": 1}}))

        issues = validate_sender_classifications(db_path)
        assert len(issues) == 1
        assert "needs normalization" in issues[0]


class TestFixDomainClassifications:
    def test_fix_malformed_domains(self, tmp_path: Path):
        """Test fixing malformed domains."""
        db_path = tmp_path / "domain_db.json"
        db_path.write_text(json.dumps({"example.com>": "Category1", "good.com": "Category2"}))

        fixed = fix_domain_classifications(db_path)

        assert fixed == 1
        with open(db_path) as f:
            data = json.load(f)
        assert "example.com" in data
        assert "example.com>" not in data


class TestPruneLowConfidenceSenders:
    def test_prune_low_count(self, tmp_path: Path):
        """Test pruning low-count entries."""
        db_path = tmp_path / "sender_db.json"
        db_path.write_text(
            json.dumps(
                {
                    "low@example.com": {"Category": 1},
                    "high@example.com": {"Category": 10},
                }
            )
        )

        pruned = prune_low_confidence_senders(db_path, min_count=3)

        assert pruned == 1
        with open(db_path) as f:
            data = json.load(f)
        assert "low@example.com" not in data
        assert "high@example.com" in data

    def test_no_prune_needed(self, tmp_path: Path):
        """Test when no pruning is needed."""
        db_path = tmp_path / "sender_db.json"
        db_path.write_text(json.dumps({"high@example.com": {"Category": 10}}))

        pruned = prune_low_confidence_senders(db_path, min_count=3)
        assert pruned == 0


class TestGetDatabaseStats:
    def test_stats_with_all_dbs(self, tmp_path: Path):
        """Test stats with all databases present."""
        # Create sender db
        sender_db = tmp_path / "sender_classification_db.json"
        sender_db.write_text(
            json.dumps(
                {
                    "a@test.com": {"Cat1": 5},
                    "b@test.com": {"Cat2": 15},
                }
            )
        )

        # Create domain db
        domain_db = tmp_path / "domain_classifications.json"
        domain_db.write_text(
            json.dumps(
                {
                    "test.com": "Category1",
                    "example.com": "Category2",
                }
            )
        )

        # Create validated db
        validated_db = tmp_path / "validated_classification_db.json"
        validated_db.write_text(json.dumps({}))

        stats = get_database_stats(tmp_path)

        assert "sender_db" in stats
        assert stats["sender_db"]["entries"] == 2
        assert stats["sender_db"]["high_confidence_entries"] == 1

        assert "domain_db" in stats
        assert stats["domain_db"]["entries"] == 2
        assert stats["domain_db"]["unique_categories"] == 2

        assert "validated_db" in stats
        assert stats["validated_db"]["entries"] == 0
