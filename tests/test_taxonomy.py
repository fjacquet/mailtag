import pytest

from mailtag.taxonomy import (
    ACTION_FOLDERS,
    REVIEW,
    TAXONOMY,
    llm_email_part,
    llm_static_prompt,
    map_folder,
    parse_category_number,
    to_category,
)


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("Contacts/Yann Duscher", "Contacts"),
        ("Contacts", "Contacts"),
        ("Finance/Local/BCV", "Banque & Placements"),
        ("Finance/Locale/Vaudoise", "Assurances & Retraite"),
        ("Finance/Local/Swisscom Bills", "Énergie & Télécom"),
        ("Services/Local/Delivery/DHL", "Colis & Livraisons"),
        ("Services/Online/Security/Dashlane", "Sécurité & Comptes"),
        ("Services/Online/Streaming/Netflix", "Médias & Divertissement"),
        ("Services/Development/GitHub", "Outils & Services en ligne"),
        ("Services/Development/Docker", "Éditeurs IT & Cloud"),
        ("Services/Professional/Veeam", "Éditeurs IT & Cloud"),
        ("Services/Professional/LinkedIn", "Carrière & Formation"),
        ("Shopping/Toys", "Achats"),
        ("Shopping/Smart Home", "Logement & Maison"),
        ("Voyages/Sixt", "Voyages & Loisirs"),
        ("Voyages/Mobility", "Transports & Mobilité"),
        ("System Notifications/Oracle Cloud", "Éditeurs IT & Cloud"),
        ("Informations/Newsletters/Tech", "Veille & Newsletters pro"),
        ("Informations/Newsletters/Recipes", "Médias & Divertissement"),
    ],
)
def test_map_folder(folder, expected):
    assert map_folder(folder) == expected


def test_map_folder_returns_none_for_mailbox_system_folders():
    for folder in ("INBOX", "Sent", "Trash", "Junk", "A classer", "Promos", "Promotions"):
        assert map_folder(folder) is None


def test_every_mapped_category_is_in_taxonomy():
    folders = ["Services/Online/Whatever", "Services/Local/Whatever", "Finance/Online/X", "Famille/X"]
    assert all(map_folder(f) in TAXONOMY for f in folders)


def test_action_folders_exact_names():
    assert ACTION_FOLDERS == ("1-A traiter", "2-A payer", "3-A lire", "4-Pour info", "5-Promos", "9-A revoir")
    assert REVIEW == "9-A revoir"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Banque & Placements", "Banque & Placements"),  # already a category
        ("Voyages/Sixt", "Voyages & Loisirs"),  # old folder path
        ("À Classer", None),
        ("Promotions", None),
        ("INBOX", None),
        ("", None),
        (None, None),
    ],
)
def test_to_category(value, expected):
    assert to_category(value) == expected


def test_llm_static_prompt_numbers_every_category_in_order():
    prompt = llm_static_prompt()
    for number, name in enumerate(TAXONOMY, 1):
        assert f"{number}. {name} : " in prompt
    assert prompt.endswith("Réponds uniquement par le numéro de la catégorie, sans autre texte.\n\n")


def test_llm_email_part_format():
    assert llm_email_part("Facture", "BCV <info@bcv.ch>", "Montant") == (
        "Sujet: Facture\nDe: BCV <info@bcv.ch>\nCorps: Montant"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", "Banque & Placements"),
        (" 19\n", "Contacts"),
        ("Catégorie 11", "Voyages & Loisirs"),
        ("0", None),
        ("20", None),
        ("Banque", None),
        ("", None),
    ],
)
def test_parse_category_number(text, expected):
    assert parse_category_number(text) == expected


def test_llm_sender_prompt_lists_categories_and_asks_for_a_number():
    from mailtag.taxonomy import TAXONOMY, llm_sender_static_prompt

    prompt = llm_sender_static_prompt()
    assert prompt.startswith("Classe cet expéditeur dans UNE des catégories suivantes")
    assert "19. Contacts : personnes qui écrivent directement" in prompt
    assert len([line for line in prompt.splitlines() if line[:1].isdigit()]) == len(TAXONOMY)
    assert prompt.endswith("Réponds uniquement par le numéro de la catégorie, sans autre texte.\n\n")


def test_llm_sender_part():
    from mailtag.taxonomy import llm_sender_part

    assert llm_sender_part("BCV", "info@bcv.ch", ["Relevé", "Alerte"]) == (
        "Expéditeur: BCV <info@bcv.ch>\nSujets:\n- Relevé\n- Alerte"
    )
    assert llm_sender_part("", "a@x.ch", []) == "Expéditeur: a@x.ch\nSujets:\n- (aucun)"


def test_nomic_text_matches_production_format():
    from mailtag.taxonomy import nomic_text

    assert nomic_text("BCV", "info@bcv.ch", "Relevé", "") == "Email from BCV: Relevé"
    assert nomic_text("", "info@bcv.ch", "Relevé", "") == "Email from info@bcv.ch: Relevé"
    assert nomic_text("", "", "S", "") == "Email from Unknown: S"
    assert nomic_text("BCV", "info@bcv.ch", "Relevé", "Votre solde") == "Email from BCV: Relevé\nVotre solde"
