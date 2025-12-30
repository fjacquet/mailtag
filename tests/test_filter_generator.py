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


def test_generate_filters(db_paths):
    """Tests the filter generation logic."""
    db_content = {
        "sender1@example.com": {"Finance/Bloomberg": 5, "À Classer": 1},
        "sender2@example.com": {"Services/Apple": 10},
        "sender3@example.com": {},
    }
    db_paths["suggestion"].write_text(json.dumps(db_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(database=database, output_path=db_paths["output"])

    generator.generate_filters()

    assert db_paths["output"].exists()
    written_content = db_paths["output"].read_text(encoding="utf-8")

    # Perform some basic checks on the generated XML
    assert "sender1@example.com" in written_content
    assert "Finance/Bloomberg" in written_content
    assert "sender2@example.com" in written_content
    assert "Services/Apple" in written_content
    # sender3 has no dominant category (empty dict)
    assert "sender3@example.com" not in written_content


def test_generate_filters_empty_db(db_paths):
    """Tests filter generation with an empty database."""
    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(database=database, output_path=db_paths["output"])

    generator.generate_filters()

    assert db_paths["output"].exists()
    written_content = db_paths["output"].read_text(encoding="utf-8")
    assert "<entry>" not in written_content


def test_generate_filters_with_validated(db_paths):
    """Tests filter generation with validated database entries."""
    suggestion_content = {"sender1@example.com": {"Finance/Bloomberg": 5}}
    validated_content = {"sender2@example.com": {"Validated/Category": 1}}

    db_paths["suggestion"].write_text(json.dumps(suggestion_content), encoding="utf-8")
    db_paths["validated"].write_text(json.dumps(validated_content), encoding="utf-8")

    database = ClassificationDatabase(
        suggestion_db_path=db_paths["suggestion"],
        validated_db_path=db_paths["validated"],
        domain_db_path=db_paths["domain"],
    )
    generator = FilterGenerator(database=database, output_path=db_paths["output"])

    generator.generate_filters()

    written_content = db_paths["output"].read_text(encoding="utf-8")

    # Both suggestion and validated entries should be included
    assert "sender1@example.com" in written_content
    assert "Finance/Bloomberg" in written_content
    assert "sender2@example.com" in written_content
    assert "Validated/Category" in written_content
