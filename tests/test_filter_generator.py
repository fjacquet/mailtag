import json

import pytest

from mailtag.database import ClassificationDatabase
from mailtag.filter_generator import FilterGenerator


@pytest.fixture
def db_paths(tmp_path):
    """Fixture providing temp paths for database files."""
    return {
        "suggestion": tmp_path / "suggestion_db.json",
        "validated": tmp_path / "validated_db.json",
        "domain": tmp_path / "domain_db.json",
        "output": tmp_path / "mailfilter.xml",
    }


def test_generate_filters_no_consolidation(db_paths):
    """Tests the filter generation logic without domain consolidation."""
    db_content = {
        "sender1@example.com": {"Finance/Bloomberg": 5, "À Classer": 1},
        "sender2@other.com": {"Services/Apple": 10},
        "sender3@example.com": {},
    }
    db_paths["suggestion"].write_text(json.dumps(db_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(
        database=database,
        output_path=db_paths["output"],
        consolidate_domains=False,
    )

    count = generator.generate_filters()

    assert db_paths["output"].exists()
    written_content = db_paths["output"].read_text(encoding="utf-8")

    # Perform some basic checks on the generated XML
    assert "sender1@example.com" in written_content
    assert "Finance/Bloomberg" in written_content
    assert "sender2@other.com" in written_content
    assert "Services/Apple" in written_content
    # sender3 has no dominant category (empty dict)
    assert "sender3@example.com" not in written_content
    assert count == 2


def test_generate_filters_with_consolidation(db_paths):
    """Tests domain consolidation for commercial domains."""
    db_content = {
        # Multiple senders from same commercial domain with same category
        "sales@acme.com": {"Shopping/Retail": 5},
        "support@acme.com": {"Shopping/Retail": 3},
        "billing@acme.com": {"Shopping/Retail": 2},
        # Another domain with same category
        "info@other.com": {"Services/Online": 10},
    }
    db_paths["suggestion"].write_text(json.dumps(db_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(
        database=database,
        output_path=db_paths["output"],
        consolidate_domains=True,
        consolidation_threshold=2,
    )

    count = generator.generate_filters()

    written_content = db_paths["output"].read_text(encoding="utf-8")

    # acme.com should be consolidated into wildcard
    assert "*@acme.com" in written_content
    assert "sales@acme.com" not in written_content
    assert "support@acme.com" not in written_content
    assert "billing@acme.com" not in written_content

    # other.com has only 1 sender, should remain individual
    assert "info@other.com" in written_content
    assert "*@other.com" not in written_content

    # 2 entries: *@acme.com and info@other.com
    assert count == 2


def test_generate_filters_non_commercial_not_consolidated(db_paths):
    """Tests that non-commercial domains (gmail, etc.) are never consolidated."""
    db_content = {
        # Multiple gmail addresses with same category
        "user1@gmail.com": {"Contacts/Personal": 5},
        "user2@gmail.com": {"Contacts/Personal": 3},
        "user3@gmail.com": {"Contacts/Personal": 2},
        # Commercial domain for comparison
        "sales@company.com": {"Shopping/Retail": 5},
        "support@company.com": {"Shopping/Retail": 3},
    }
    db_paths["suggestion"].write_text(json.dumps(db_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(
        database=database,
        output_path=db_paths["output"],
        consolidate_domains=True,
        consolidation_threshold=2,
    )

    count = generator.generate_filters()

    written_content = db_paths["output"].read_text(encoding="utf-8")

    # Gmail should NOT be consolidated - each user gets individual entry
    assert "*@gmail.com" not in written_content
    assert "user1@gmail.com" in written_content
    assert "user2@gmail.com" in written_content
    assert "user3@gmail.com" in written_content

    # Commercial domain should be consolidated
    assert "*@company.com" in written_content
    assert "sales@company.com" not in written_content

    # 4 entries: 3 gmail + 1 wildcard
    assert count == 4


def test_generate_filters_empty_db(db_paths):
    """Tests filter generation with an empty database."""
    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(database=database, output_path=db_paths["output"])

    count = generator.generate_filters()

    assert db_paths["output"].exists()
    written_content = db_paths["output"].read_text(encoding="utf-8")
    assert "<entry>" not in written_content
    assert count == 0


def test_generate_filters_with_validated(db_paths):
    """Tests filter generation with validated database entries."""
    suggestion_content = {"sender1@example.com": {"Finance/Bloomberg": 5}}
    validated_content = {"sender2@other.com": {"Validated/Category": 1}}

    db_paths["suggestion"].write_text(json.dumps(suggestion_content), encoding="utf-8")
    db_paths["validated"].write_text(json.dumps(validated_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(
        database=database,
        output_path=db_paths["output"],
        consolidate_domains=False,
    )

    generator.generate_filters()

    written_content = db_paths["output"].read_text(encoding="utf-8")

    # Both suggestion and validated entries should be included
    assert "sender1@example.com" in written_content
    assert "Finance/Bloomberg" in written_content
    assert "sender2@other.com" in written_content
    assert "Validated/Category" in written_content


def test_generate_filters_different_categories_same_domain(db_paths):
    """Tests that same domain with different categories creates separate entries."""
    db_content = {
        # Same domain but different categories - should not consolidate
        "sales@acme.com": {"Shopping/Retail": 5},
        "support@acme.com": {"Services/Support": 3},
        "newsletter@acme.com": {"Shopping/Retail": 2},
    }
    db_paths["suggestion"].write_text(json.dumps(db_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(
        database=database,
        output_path=db_paths["output"],
        consolidate_domains=True,
        consolidation_threshold=2,
    )

    count = generator.generate_filters()

    written_content = db_paths["output"].read_text(encoding="utf-8")

    # Shopping/Retail has 2 senders (sales, newsletter) -> should consolidate
    # Services/Support has 1 sender (support) -> should stay individual
    assert "*@acme.com" in written_content  # For Shopping/Retail
    assert "support@acme.com" in written_content  # Stays individual

    # 2 entries: wildcard for Shopping/Retail + individual for Services/Support
    assert count == 2
