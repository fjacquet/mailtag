import pytest

from scripts.taxonomy import TAXONOMY, map_folder


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
