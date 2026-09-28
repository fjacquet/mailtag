import pytest

from mailtag.taxonomy_build import (
    domain_rules,
    folder_category,
    folder_disagreement,
    folder_queue,
    gemma_proposals,
    learned_senders,
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
    queue = review_queue(SENDERS, CROSS, validated={"doc@clinic.ch": "Santé"})
    assert queue == ["friend@gmail.com", "mixed@shop.ch", "big@shop.ch", "one@shop.ch"]


def test_learned_senders_need_agreement_and_enough_mails():
    learned = learned_senders(SENDERS, CROSS, validated={"big@shop.ch": "Santé"}, min_mails=2, agreements=2)
    assert learned == {"doc@clinic.ch": {"category": "Santé", "agreements": 2}}


def test_domain_rules_use_corrected_categories_and_purity():
    validated = {"mixed@shop.ch": "Achats"}
    learned = {"big@shop.ch": {"category": "Achats", "agreements": 2},
               "doc@clinic.ch": {"category": "Santé", "agreements": 2}}  # fmt: skip
    senders = {**SENDERS, "x@clinic.ch": entry("clinic.ch", Achats=2)}
    learned_with_x = {**learned, "x@clinic.ch": {"category": "Achats", "agreements": 2}}

    assert domain_rules(SENDERS, validated, learned, min_purity=0.9) == {
        "shop.ch": "Achats",
        "clinic.ch": "Santé",
    }
    # clinic.ch: 9 Santé vs 2 Achats = 82 % < 90 %
    assert "clinic.ch" not in domain_rules(senders, validated, learned_with_x, min_purity=0.9)


def test_personal_domains_never_become_rules():
    validated = {"friend@gmail.com": "Contacts"}
    assert domain_rules(SENDERS, validated, {}, min_purity=0.9) == {}


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
