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
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pending.json", "pending.json.lock"]


def test_missing_or_corrupt_file_starts_empty(tmp_path):
    assert PendingArchive(tmp_path / "none.json").items() == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert PendingArchive(bad).items() == []


def test_two_instances_saving_different_adds_keep_both(tmp_path):
    path = tmp_path / "pending.json"
    first, second = PendingArchive(path), PendingArchive(path)
    first.add("<a@x>", "Achats", "a@x.ch", "2026-09-27")
    second.add("<b@x>", "Santé", "b@x.ch", "2026-09-27")

    first.save()
    second.save()

    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"<a@x>", "<b@x>"}
    assert second.get("<a@x>") is not None  # the saving instance picked up the other's entry


def test_a_remove_and_an_add_from_two_instances_are_both_applied(tmp_path):
    path = tmp_path / "pending.json"
    seed = PendingArchive(path)
    seed.add("<old@x>", "Achats", "o@x.ch", "2026-09-01")
    seed.save()
    remover, adder = PendingArchive(path), PendingArchive(path)
    remover.remove("<old@x>")
    adder.add("<new@x>", "Santé", "n@x.ch", "2026-09-27")

    adder.save()
    remover.save()

    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"<new@x>"}


def test_concurrent_threads_keep_every_entry(tmp_path):
    import threading

    path = tmp_path / "pending.json"

    def worker(n):
        pending = PendingArchive(path)
        pending.add(f"<{n}@x>", "Achats", "a@x.ch", "2026-09-27")
        pending.save()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set(json.loads(path.read_text(encoding="utf-8"))) == {f"<{n}@x>" for n in range(8)}
