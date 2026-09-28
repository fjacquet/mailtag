def test_missing_inputs(tmp_path):
    from scripts.taxonomy_setup import missing_inputs

    present = tmp_path / "scan.json"
    present.write_text("{}")
    absent = tmp_path / "crosscheck.json"

    assert missing_inputs([present, absent]) == [absent]
    assert missing_inputs([present]) == []
