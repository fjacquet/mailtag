import json

import pytest

from mailtag.taxonomy_store import TaxonomyStore, write_json_atomic


@pytest.fixture(autouse=True)
def personal_domains(monkeypatch):
    monkeypatch.setattr(
        "mailtag.taxonomy_store.is_non_commercial_domain_cached", lambda d: d in {"gmail.com", "bluewin.ch"}
    )


def store(tmp_path, **files):
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return TaxonomyStore(tmp_path, min_agreements=2)


def test_rule_order_validated_then_learned_then_domain(tmp_path):
    s = store(
        tmp_path,
        validated={"a@shop.ch": "Santé"},
        senders={"a@shop.ch": {"category": "Achats", "agreements": 5},
                 "b@shop.ch": {"category": "Achats", "agreements": 2}},
        domains={"shop.ch": "Colis & Livraisons"},
    )  # fmt: skip
    assert s.category_for("a@shop.ch") == "Santé"
    assert s.category_for("b@shop.ch") == "Achats"
    assert s.category_for("c@shop.ch") == "Colis & Livraisons"
    assert s.category_for("c@other.ch") is None


def test_own_address_is_never_a_rule_and_never_learned(tmp_path):
    (tmp_path / "validated.json").write_text(json.dumps({"me@shop.ch": "Santé"}), encoding="utf-8")
    (tmp_path / "domains.json").write_text(json.dumps({"shop.ch": "Achats"}), encoding="utf-8")
    s = TaxonomyStore(tmp_path, min_agreements=1, own_addresses=["Me@Shop.ch"])

    assert s.category_for("me@shop.ch") is None
    assert s.category_for("you@shop.ch") == "Achats"
    s.record_agreement("me@shop.ch", "Santé")
    s.save()
    assert not (tmp_path / "senders.json").exists()


def test_own_address_is_never_validated(tmp_path):
    s = TaxonomyStore(tmp_path, own_addresses=["Me@Shop.ch"])

    s.set_validated("me@shop.ch", "Santé")
    s.save()

    assert not (tmp_path / "validated.json").exists()


def test_unpromoted_sender_is_not_a_rule(tmp_path):
    s = store(tmp_path, senders={"b@x.ch": {"category": "Achats", "agreements": 1}})
    assert s.category_for("b@x.ch") is None


def test_personal_domain_is_never_a_rule(tmp_path):
    s = store(tmp_path, domains={"gmail.com": "Contacts"})
    assert s.category_for("someone@gmail.com") is None


def test_lookup_normalizes_address(tmp_path):
    s = store(tmp_path, validated={"a@shop.ch": "Santé"})
    assert s.category_for("  A@Shop.CH ") == "Santé"
    s.set_validated(" B@Shop.CH", "Achats")
    assert s.validated["b@shop.ch"] == "Achats"


def test_two_agreements_promote_a_sender(tmp_path):
    s = store(tmp_path)
    s.record_agreement("n@new.ch", "Santé")
    assert s.category_for("n@new.ch") is None
    s.record_agreement("n@new.ch", "Santé")
    assert s.category_for("n@new.ch") == "Santé"


def test_contradiction_removes_the_entry(tmp_path):
    s = store(tmp_path, senders={"n@new.ch": {"category": "Santé", "agreements": 3}})
    s.record_agreement("n@new.ch", "Achats")
    assert "n@new.ch" not in s.senders
    assert s.category_for("n@new.ch") is None


def test_validated_sender_is_not_learned(tmp_path):
    s = store(tmp_path, validated={"v@x.ch": "Santé"})
    s.record_agreement("v@x.ch", "Achats")
    assert "v@x.ch" not in s.senders


def test_set_validated_drops_learned_entry(tmp_path):
    s = store(tmp_path, senders={"n@x.ch": {"category": "Achats", "agreements": 2}})
    s.set_validated("n@x.ch", "Santé")
    assert "n@x.ch" not in s.senders
    assert s.category_for("n@x.ch") == "Santé"


def test_replace_rules_keeps_runtime_learning_for_unknown_senders(tmp_path):
    s = store(tmp_path, senders={"runtime@x.ch": {"category": "Santé", "agreements": 1},
                                 "old@x.ch": {"category": "Santé", "agreements": 2}})  # fmt: skip
    s.replace_rules({"old@x.ch": {"category": "Achats", "agreements": 2}}, {"x.ch": "Achats"})
    assert s.senders == {
        "runtime@x.ch": {"category": "Santé", "agreements": 1},
        "old@x.ch": {"category": "Achats", "agreements": 2},
    }
    assert s.domains == {"x.ch": "Achats"}


def test_save_writes_all_files_and_reloads(tmp_path):
    s = store(tmp_path)
    s.set_validated("v@x.ch", "Santé")
    s.record_agreement("n@x.ch", "Achats")
    s.replace_rules({}, {"x.ch": "Achats"})
    s.set_folder_category("Finance/Local/Twint", "Banque & Placements")
    s.set_folder_category("Divers", None)
    s.save()

    again = TaxonomyStore(tmp_path)
    assert again.validated == {"v@x.ch": "Santé"}
    assert again.senders == {"n@x.ch": {"category": "Achats", "agreements": 1}}
    assert again.domains == {"x.ch": "Achats"}
    assert again.folder_overrides == {"Finance/Local/Twint": "Banque & Placements", "Divers": None}


def test_read_only_never_writes(tmp_path):
    s = TaxonomyStore(tmp_path, read_only=True)
    s.set_validated("v@x.ch", "Santé")
    s.record_agreement("n@x.ch", "Achats")
    s.save()
    assert list(tmp_path.iterdir()) == []


def test_missing_or_corrupt_files_start_empty(tmp_path):
    (tmp_path / "senders.json").write_text("{not json", encoding="utf-8")
    s = TaxonomyStore(tmp_path)
    assert s.validated == {} and s.senders == {} and s.domains == {} and s.folder_overrides == {}


def test_write_json_atomic_creates_parent_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "sub" / "f.json"
    write_json_atomic(target, {"é": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"é": 1}
    assert [p.name for p in target.parent.iterdir()] == ["f.json"]


def test_concurrent_learning_and_saves_are_safe(tmp_path):
    """The webhook API shares one store across FastAPI's thread pool."""
    import threading

    s = TaxonomyStore(tmp_path)
    errors = []

    def learn(worker):
        try:
            for i in range(400):
                s.record_agreement(f"s{worker}-{i}@x.ch", "Achats")
                if i % 20 == 0:
                    s.save()
        except Exception as e:  # noqa: BLE001 - any race surfaces here
            errors.append(e)

    threads = [threading.Thread(target=learn, args=(w,)) for w in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s.save()

    assert errors == []
    assert len(TaxonomyStore(tmp_path).senders) == 8 * 400


def test_two_processes_keep_each_others_rules(tmp_path):
    """The webhook API and a `run` each hold a store on the same files."""
    api, run = TaxonomyStore(tmp_path), TaxonomyStore(tmp_path)
    api.record_agreement("a@x.ch", "Santé")
    run.record_agreement("b@x.ch", "Achats")
    run.set_validated("v@x.ch", "Achats")
    api.save()
    run.save()

    disk = TaxonomyStore(tmp_path)
    assert disk.senders == {
        "a@x.ch": {"category": "Santé", "agreements": 1},
        "b@x.ch": {"category": "Achats", "agreements": 1},
    }
    assert disk.validated == {"v@x.ch": "Achats"}


def test_agreements_from_two_processes_add_up(tmp_path):
    api, run = TaxonomyStore(tmp_path), TaxonomyStore(tmp_path)
    api.record_agreement("a@x.ch", "Santé")
    run.record_agreement("a@x.ch", "Santé")
    api.save()
    run.save()

    assert TaxonomyStore(tmp_path).category_for("a@x.ch") == "Santé"


def test_lookup_sees_what_another_process_saved(tmp_path):
    api, run = TaxonomyStore(tmp_path), TaxonomyStore(tmp_path)
    run.set_validated("v@x.ch", "Achats")
    run.save()

    assert api.category_for("v@x.ch") == "Achats"


def test_validation_elsewhere_wins_over_local_learning(tmp_path):
    api, review = TaxonomyStore(tmp_path), TaxonomyStore(tmp_path)
    api.record_agreement("s@x.ch", "Santé")
    review.set_validated("s@x.ch", "Achats")
    review.save()
    api.save()

    disk = TaxonomyStore(tmp_path)
    assert disk.validated == {"s@x.ch": "Achats"}
    assert "s@x.ch" not in disk.senders


def test_failed_save_writes_nothing_and_does_not_count_twice(tmp_path, monkeypatch):
    import mailtag.taxonomy_store as module

    s = TaxonomyStore(tmp_path)
    s.record_agreement("a@x.ch", "Santé")
    s.set_validated("v@x.ch", "Achats")
    real_dump, calls = module.json.dump, []

    def dump_failing_on_second_file(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_dump(*args, **kwargs)

    monkeypatch.setattr(module.json, "dump", dump_failing_on_second_file)
    with pytest.raises(OSError):
        s.save()
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".json") == []

    monkeypatch.setattr(module.json, "dump", real_dump)
    s.save()
    assert TaxonomyStore(tmp_path).senders == {"a@x.ch": {"category": "Santé", "agreements": 1}}


def test_save_does_not_reload_when_no_other_process_wrote(tmp_path, mocker):
    import mailtag.taxonomy_store as module

    s = TaxonomyStore(tmp_path)
    load = mocker.spy(module, "_load")
    s.record_agreement("a@x.ch", "Santé")
    s.save()
    s.record_agreement("a@x.ch", "Santé")
    s.save()

    load.assert_not_called()
    assert TaxonomyStore(tmp_path).category_for("a@x.ch") == "Santé"


def test_read_only_store_keeps_learning_in_memory_without_piling_up(tmp_path):
    s = TaxonomyStore(tmp_path, read_only=True)
    for _ in range(3):
        s.record_agreement("a@x.ch", "Santé")

    assert s.category_for("a@x.ch") == "Santé"
    assert s._ops == []


def test_validated_domain_is_used_after_senders_and_before_computed_domains(tmp_path):
    store = TaxonomyStore(tmp_path)
    store.replace_rules({}, {"shop.ch": "Achats"})
    store.set_validated_domain("shop.ch", "Voyages & Loisirs")
    assert store.category_for("news@shop.ch") == "Voyages & Loisirs"
    store.set_validated("promo@shop.ch", "Achats")
    assert store.category_for("promo@shop.ch") == "Achats"


def test_validated_domain_survives_build_and_reload(tmp_path):
    store = TaxonomyStore(tmp_path)
    store.set_validated_domain("Shop.CH", "Achats")
    store.save()
    store.replace_rules({}, {})
    store.save()
    assert TaxonomyStore(tmp_path).category_for("a@shop.ch") == "Achats"


def test_non_commercial_domain_is_never_a_validated_domain_rule(tmp_path):
    store = TaxonomyStore(tmp_path)
    store.set_validated_domain("gmail.com", "Contacts")
    assert store.category_for("someone@gmail.com") is None
