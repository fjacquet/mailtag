import json

from mailtag.pending_archive import PendingArchive


def test_add_get_remove_and_persist(tmp_path):
    path = tmp_path / "pending.json"
    store = PendingArchive(path)
    store.add("<a@x>", "Achats", "shop@x.ch", "2026-09-27")
    store.add("<b@x>", None, "p@x.ch", "2026-09-27")
    store.remove("<missing@x>")
    store.save()

    reloaded = PendingArchive(path)
    assert reloaded.get("<a@x>") == {"category": "Achats", "sender": "shop@x.ch", "added": "2026-09-27"}
    assert reloaded.get("<b@x>")["category"] is None
    reloaded.remove("<a@x>")
    assert [mid for mid, _ in reloaded.items()] == ["<b@x>"]


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "pending.json"
    store = PendingArchive(path)
    store.add("<a@x>", "Santé", "d@x.ch", "2026-09-27")
    store.save()

    assert json.loads(path.read_text(encoding="utf-8"))["<a@x>"]["category"] == "Santé"
    assert [p.name for p in tmp_path.iterdir()] == ["pending.json"]


def test_missing_or_corrupt_file_starts_empty(tmp_path):
    assert PendingArchive(tmp_path / "none.json").items() == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert PendingArchive(bad).items() == []
