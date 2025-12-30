import json
from collections import defaultdict

import pytest

from mailtag.database import ClassificationDatabase


@pytest.fixture
def db_paths(tmp_path):
    """Fixture providing temp paths for database files."""
    return {
        "suggestion": tmp_path / "suggestion_db.json",
        "validated": tmp_path / "validated_db.json",
        "domain": tmp_path / "domain_db.json",
    }


def test_load_db_file_not_found(db_paths):
    """Tests that an empty db is created when the file doesn't exist."""
    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    assert db.suggestion_db == defaultdict(lambda: defaultdict(int))
    assert db.validated_db == defaultdict(lambda: defaultdict(int))


def test_load_db_with_content(db_paths):
    """Tests loading a database with existing content."""
    suggestion_db_content = {
        "sender@example.com": {"Finance/Bloomberg": 1},
        "another@sender.com": {"À Classer": 5},
    }
    validated_db_content = {"validated@sender.com": {"Validated/Category": 1}}

    # Write the test data to files
    db_paths["suggestion"].write_text(json.dumps(suggestion_db_content), encoding="utf-8")
    db_paths["validated"].write_text(json.dumps(validated_db_content), encoding="utf-8")

    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    assert db.get_classification_count("sender@example.com", "Finance/Bloomberg") == 1
    assert db.get_classification_count("another@sender.com", "À Classer") == 5
    assert db.get_dominant_classification("validated@sender.com") == "Validated/Category"


def test_update_suggestion_db(db_paths):
    """Tests updating the suggestion database."""
    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )

    db.update_suggestion("sender@example.com", "Finance/Bloomberg")
    assert db.get_classification_count("sender@example.com", "Finance/Bloomberg") == 1

    db.update_suggestion("sender@example.com", "Finance/Bloomberg")
    assert db.get_classification_count("sender@example.com", "Finance/Bloomberg") == 2

    # Verify persistence
    assert db_paths["suggestion"].exists()
    saved_data = json.loads(db_paths["suggestion"].read_text(encoding="utf-8"))
    assert saved_data["sender@example.com"]["Finance/Bloomberg"] == 2


def test_promote_to_validated(db_paths):
    """Tests promoting a classification to the validated database."""
    suggestion_db_content = {"sender@example.com": {"Finance/Bloomberg": 1}}
    db_paths["suggestion"].write_text(json.dumps(suggestion_db_content), encoding="utf-8")

    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )

    db.promote_to_validated("sender@example.com", "Finance/Bloomberg")

    assert "sender@example.com" not in db.suggestion_db
    assert db.validated_db["sender@example.com"] == {"Finance/Bloomberg": 1}

    # Verify persistence
    saved_validated = json.loads(db_paths["validated"].read_text(encoding="utf-8"))
    assert saved_validated["sender@example.com"] == {"Finance/Bloomberg": 1}


def test_get_dominant_classification(db_paths):
    """Tests that the dominant classification is correctly retrieved."""
    suggestion_db_content = {"sender@example.com": {"Suggestion/Category": 5}}
    validated_db_content = {"sender@example.com": {"Validated/Category": 1}}

    db_paths["suggestion"].write_text(json.dumps(suggestion_db_content), encoding="utf-8")
    db_paths["validated"].write_text(json.dumps(validated_db_content), encoding="utf-8")

    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )

    # Validated DB takes priority
    assert db.get_dominant_classification("sender@example.com") == "Validated/Category"
    assert db.get_dominant_classification("new@sender.com") is None


def test_domain_classification(db_paths):
    """Tests domain classification functionality."""
    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )

    # Store a domain classification
    db.store_domain_classification("example.com", "Services/Example")

    # Retrieve it
    assert db.get_category_by_domain("example.com") == "Services/Example"
    assert db.get_category_by_domain("EXAMPLE.COM") == "Services/Example"  # Case insensitive
    assert db.get_category_by_domain("unknown.com") is None

    # Check email lookup
    assert db.get_category_by_email("user@example.com") == "Services/Example"

    # Check existence
    assert db.has_domain_classification("example.com") is True
    assert db.has_domain_classification("unknown.com") is False

    # Remove
    assert db.remove_domain_classification("example.com") is True
    assert db.get_category_by_domain("example.com") is None


def test_load_domain_db_with_content(db_paths):
    """Tests loading domain database with existing content."""
    domain_db_content = {"example.com": "Services/Example", "test.org": "Testing/Org"}
    db_paths["domain"].write_text(json.dumps(domain_db_content), encoding="utf-8")

    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )

    assert db.get_category_by_domain("example.com") == "Services/Example"
    assert db.get_category_by_domain("test.org") == "Testing/Org"


def test_case_insensitive_sender_lookup(db_paths):
    """Tests that sender lookups are case-insensitive."""
    db = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )

    db.update_suggestion("User@Example.COM", "Finance/Test")
    assert db.get_classification_count("user@example.com", "Finance/Test") == 1
    assert db.get_classification_count("USER@EXAMPLE.COM", "Finance/Test") == 1
