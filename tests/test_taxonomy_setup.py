import os


def test_missing_inputs(tmp_path):
    from scripts.taxonomy_setup import missing_inputs

    present = tmp_path / "scan.json"
    present.write_text("{}")
    absent = tmp_path / "crosscheck.json"

    assert missing_inputs([present, absent]) == [absent]
    assert missing_inputs([present]) == []


def test_needs_rescan_overrides_missing(tmp_path):
    from scripts.taxonomy_setup import needs_rescan

    scan = tmp_path / "scan.json"
    scan.write_text("{}")
    overrides = tmp_path / "folder_overrides.json"

    assert needs_rescan(scan, overrides) is False


def test_needs_rescan_scan_older(tmp_path):
    from scripts.taxonomy_setup import needs_rescan

    scan = tmp_path / "scan.json"
    overrides = tmp_path / "folder_overrides.json"
    scan.write_text("{}")
    overrides.write_text("{}")
    os.utime(scan, (1000, 1000))
    os.utime(overrides, (2000, 2000))

    assert needs_rescan(scan, overrides) is True


def test_needs_rescan_scan_newer(tmp_path):
    from scripts.taxonomy_setup import needs_rescan

    scan = tmp_path / "scan.json"
    overrides = tmp_path / "folder_overrides.json"
    scan.write_text("{}")
    overrides.write_text("{}")
    os.utime(overrides, (1000, 1000))
    os.utime(scan, (2000, 2000))

    assert needs_rescan(scan, overrides) is False
