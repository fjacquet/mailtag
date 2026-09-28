import imaplib

import pytest

from mailtag.models import Email
from mailtag.taxonomy_build import (
    build_centroids,
    control_precision,
    control_sample,
    corpus_refs,
    domain_rules,
    fetch_corpus,
    folder_category,
    folder_disagreement,
    folder_queue,
    gemma_proposals,
    learned_senders,
    learned_to_review,
    review_queue,
    rules_precision,
)


@pytest.fixture(autouse=True)
def personal_domains(monkeypatch):
    monkeypatch.setattr("mailtag.taxonomy_build.is_non_commercial_domain_cached", lambda d: d == "gmail.com")


def entry(domain, **categories):
    return {"name": "", "domain": domain, "categories": categories, "subjects": [], "refs": []}


SENDERS = {
    "big@shop.ch": entry("shop.ch", Achats=40),
    "mixed@shop.ch": entry("shop.ch", Achats=1, Santé=3),
    "one@shop.ch": entry("shop.ch", Achats=1),
    "doc@clinic.ch": entry("clinic.ch", Santé=9),
    "friend@gmail.com": entry("gmail.com", Contacts=5),
}
CROSS = {"big@shop.ch": "Achats", "mixed@shop.ch": "Achats", "one@shop.ch": "Achats",
         "doc@clinic.ch": "Santé", "friend@gmail.com": None}  # fmt: skip


def test_folder_category_is_the_majority():
    assert folder_category(SENDERS["mixed@shop.ch"]) == "Santé"


def test_review_queue_disagreements_first_then_by_volume():
    queue = review_queue(
        SENDERS, CROSS, validated={"doc@clinic.ch": "Santé"}, learned={}, domains={}, min_mails=1
    )
    assert queue == ["friend@gmail.com", "mixed@shop.ch", "big@shop.ch", "one@shop.ch"]


def test_review_queue_skips_senders_rules_already_cover_and_small_senders():
    learned = {"big@shop.ch": {"category": "Achats", "agreements": 2}}
    senders = {**SENDERS, "new@clinic.ch": entry("clinic.ch", Achats=4)}
    domains = {"clinic.ch": "Santé"}
    queue = review_queue(senders, CROSS, validated={}, learned=learned, domains=domains, min_mails=2)
    assert queue == ["friend@gmail.com", "mixed@shop.ch"]


def test_learned_senders_need_agreement_and_enough_mails():
    learned = learned_senders(SENDERS, CROSS, validated={"big@shop.ch": "Santé"}, min_mails=2, agreements=2)
    assert learned == {"doc@clinic.ch": {"category": "Santé", "agreements": 2}}


def test_domain_rules_use_audited_folders_validation_first_and_purity():
    # shop.ch folders: Achats 40 + Santé 3 (mixed) + Achats 1 = 93 % Achats
    assert domain_rules(SENDERS, {}, min_purity=0.9) == {"shop.ch": "Achats", "clinic.ch": "Santé"}
    # clinic.ch: 9 Santé vs 2 Achats = 82 % < 90 %
    senders = {**SENDERS, "x@clinic.ch": entry("clinic.ch", Achats=2)}
    assert "clinic.ch" not in domain_rules(senders, {}, min_purity=0.9)
    # validating x as Santé puts clinic.ch back at 100 %
    assert domain_rules(senders, {"x@clinic.ch": "Santé"}, min_purity=0.9)["clinic.ch"] == "Santé"


def test_personal_domains_never_become_rules():
    validated = {"friend@gmail.com": "Contacts"}
    assert "gmail.com" not in domain_rules(SENDERS, validated, min_purity=0.9)


def test_control_sample_draws_rule_covered_senders_with_their_rule():
    rules = {"big@shop.ch": "Achats", "one@shop.ch": "Achats", "doc@clinic.ch": "Santé"}
    sample = control_sample(SENDERS, rules.get, validated={"doc@clinic.ch": "Santé"}, size=5, seed=0)
    assert sample == {"big@shop.ch": "Achats", "one@shop.ch": "Achats"}
    assert control_sample(SENDERS, rules.get, validated={}, size=2, seed=1) == control_sample(
        SENDERS, rules.get, validated={}, size=2, seed=1
    )
    assert len(control_sample(SENDERS, rules.get, validated={}, size=2, seed=1)) == 2


def test_control_precision_counts_only_checked_senders():
    control = {"a@x.ch": "Achats", "b@x.ch": "Santé", "c@x.ch": "Achats"}
    assert control_precision(control, {"a@x.ch": "Achats", "b@x.ch": "Contacts"}) == (2, 0.5)
    assert control_precision(control, {}) == (0, 0.0)


def test_rules_precision():
    validated = {"big@shop.ch": "Achats", "doc@clinic.ch": "Santé", "one@shop.ch": "Colis & Livraisons",
                 "mixed@shop.ch": "Santé"}  # fmt: skip
    # mixed: dossier Santé != Gemma Achats -> hors mesure ; 3 accords dont 2 justes
    assert rules_precision(SENDERS, CROSS, validated) == (3, pytest.approx(2 / 3))


FOLDERS = {
    "Contacts/Twint": {"category": "Contacts", "senders": {"noreply@twint.ch": 8, "friend@gmail.com": 2}},
    "Finance/BCV": {"category": "Banque & Placements", "senders": {"info@bcv.ch": 30}},
    "Shops/Mixed": {"category": "Achats", "senders": {"a@x.ch": 6, "b@x.ch": 4}},
    "Empty": {"category": "Santé", "senders": {}},
}
FOLDER_CROSS = {"noreply@twint.ch": "Banque & Placements", "friend@gmail.com": "Contacts",
                "info@bcv.ch": "Banque & Placements", "a@x.ch": "Achats", "b@x.ch": None}  # fmt: skip


def test_folder_disagreement_counts_mails():
    assert folder_disagreement(FOLDERS["Contacts/Twint"], FOLDER_CROSS) == pytest.approx(0.8)
    assert folder_disagreement(FOLDERS["Finance/BCV"], FOLDER_CROSS) == 0.0
    assert folder_disagreement(FOLDERS["Shops/Mixed"], FOLDER_CROSS) == pytest.approx(
        0.4
    )  # unreadable counts
    assert folder_disagreement(FOLDERS["Empty"], FOLDER_CROSS) == 0.0


def test_gemma_proposals():
    assert gemma_proposals(FOLDERS["Contacts/Twint"], FOLDER_CROSS) == [
        ("Banque & Placements", 8),
        ("Contacts", 2),
    ]


def test_folder_queue_most_contested_first_and_skips_reviewed():
    assert folder_queue(FOLDERS, FOLDER_CROSS, reviewed={}) == ["Contacts/Twint", "Shops/Mixed"]
    assert folder_queue(FOLDERS, FOLDER_CROSS, reviewed={"Contacts/Twint": "Banque & Placements"}) == [
        "Shops/Mixed"
    ]
    assert folder_queue(FOLDERS, FOLDER_CROSS, reviewed={}, min_rate=0.5) == ["Contacts/Twint"]


def with_refs(domain, refs, **categories):
    e = entry(domain, **categories)
    e["refs"] = refs
    return e


def test_corpus_refs_take_verified_or_learned_senders_capped_per_category():
    senders = {
        "a@x.ch": with_refs("x.ch", [["F", 1], ["F", 2]], Achats=9),
        "b@x.ch": with_refs("x.ch", [["F", 3]], Achats=1),
        "c@x.ch": with_refs("x.ch", [["G", 4]], Santé=5),
        "unknown@x.ch": with_refs("x.ch", [["F", 5]], Achats=3),
    }
    refs = corpus_refs(
        senders, validated={"c@x.ch": "Santé"}, learned={"a@x.ch": {"category": "Achats", "agreements": 2},
                                                         "b@x.ch": {"category": "Achats", "agreements": 2}},
        per_category=2,
    )  # fmt: skip
    assert refs == [
        {"sender": "a@x.ch", "category": "Achats", "verified": False, "folder": "F", "uid": 1},
        {"sender": "a@x.ch", "category": "Achats", "verified": False, "folder": "F", "uid": 2},
        {"sender": "c@x.ch", "category": "Santé", "verified": True, "folder": "G", "uid": 4},
    ]


def test_fetch_corpus_reads_each_folder_read_only(mocker):
    provider = mocker.MagicMock()
    provider.get_full_emails.side_effect = lambda uids: [
        Email(msg_id=str(u), subject=f"S{u}", sender_address="a@x.ch", sender_name="A", body=f"B{u}")
        for u in uids
    ]
    refs = [
        {"sender": "a@x.ch", "category": "Achats", "verified": True, "folder": "F", "uid": 1},
        {"sender": "a@x.ch", "category": "Achats", "verified": True, "folder": "F", "uid": 2},
    ]

    corpus = fetch_corpus(provider, refs)

    provider.client.select_folder.assert_called_once_with("F", readonly=True)
    assert corpus[1] == {"sender": "a@x.ch", "category": "Achats", "verified": True,
                         "sender_name": "A", "subject": "S2", "body": "B2"}  # fmt: skip


def test_fetch_corpus_skips_unreadable_folder(mocker):
    provider = mocker.MagicMock()
    provider.client.select_folder.side_effect = imaplib.IMAP4.error("gone")
    refs = [{"sender": "a@x.ch", "category": "Achats", "verified": True, "folder": "F", "uid": 1}]

    assert fetch_corpus(provider, refs) == []


def test_build_centroids_groups_production_texts_by_category(mocker):
    router_cls = mocker.patch("mailtag.taxonomy_build.SemanticRouter")
    corpus = [
        {
            "sender": "a@x.ch",
            "category": "Achats",
            "verified": True,
            "sender_name": "A",
            "subject": "S",
            "body": "",
        },
        {
            "sender": "b@x.ch",
            "category": "Santé",
            "verified": False,
            "sender_name": "",
            "subject": "T",
            "body": "B",
        },
    ]

    build_centroids("EMBEDDER", corpus)

    router_cls.assert_called_once_with("EMBEDDER", score_threshold=0.0)
    router_cls.return_value.build_from_examples.assert_called_once_with(
        {"Achats": ["Email from A: S"], "Santé": ["Email from b@x.ch: T\nB"]}
    )


def test_learned_to_review_lists_promoted_senders_scan_does_not_know():
    learned = {
        "new@shop.ch": {"category": "Achats", "agreements": 3},
        "newer@shop.ch": {"category": "Santé", "agreements": 5},
        "learning@shop.ch": {"category": "Achats", "agreements": 1},
        "big@shop.ch": {"category": "Achats", "agreements": 2},
        "checked@shop.ch": {"category": "Achats", "agreements": 4},
    }
    validated = {"checked@shop.ch": "Achats"}

    assert learned_to_review(learned, SENDERS, validated, min_agreements=2) == [
        "newer@shop.ch",
        "new@shop.ch",
    ]
