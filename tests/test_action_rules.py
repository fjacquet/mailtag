import pytest

from mailtag.action_rules import choose_action


def act(category, sender="alice@example.ch", subject="Bonjour", *, unsub=False, bulk=False):
    return choose_action(category, sender, subject, has_unsubscribe=unsub, is_bulk=bulk)


def test_review_category_goes_to_review():
    assert act("5-A revoir") == "5-A revoir"


@pytest.mark.parametrize(
    "subject",
    ["Votre facture de mars", "FACTURE disponible", "Échéance proche", "Rappel de paiement", "Invoice 42",
     "Ihre Rechnung", "Montant dû", "Your bill is ready", "Payment due soon"],
)  # fmt: skip
def test_bill_in_money_category_is_to_pay(subject):
    assert act("Banque & Placements", "noreply@bcv.ch", subject, unsub=True, bulk=True) == "2-A payer"


@pytest.mark.parametrize(
    "category", ["Énergie & Télécom", "Assurances & Retraite", "Impôts & Administration"]
)
def test_other_money_categories_are_to_pay(category):
    assert act(category, "billing@swisscom.com", "Facture septembre", bulk=True) == "2-A payer"


def test_bill_word_outside_money_category_is_not_to_pay():
    assert act("Achats", "shop@example.ch", "Votre facture", bulk=True) == "4-Pour info"


def test_billet_is_not_a_bill():
    assert act("Banque & Placements", "info@bcv.ch", "Gagnez un billet", bulk=True) == "4-Pour info"


def test_bill_from_a_person_is_to_pay_not_to_do():
    assert act("Banque & Placements", "jean.dupont@bcv.ch", "Facture jointe") == "2-A payer"


def test_person_is_to_do():
    assert act("Contacts", "yann@gmail.com", "On se voit demain ?") == "1-A traiter"


@pytest.mark.parametrize(
    "sender",
    ["noreply@x.ch", "no-reply@x.ch", "notifications@x.ch", "newsletter@x.ch", "info@x.ch", "news@x.ch"],
)
def test_automated_sender_is_not_to_do(sender):
    assert act("Outils & Services en ligne", sender, "Hello") == "4-Pour info"


def test_bulk_mail_is_not_to_do():
    assert act("Outils & Services en ligne", "team@x.ch", "Hello", bulk=True) == "4-Pour info"


@pytest.mark.parametrize(
    "subject", ["-30% sur tout", "Offre spéciale", "Soldes d'été", "Promo", "Big SALE", "Rabatt"]
)
def test_promo_with_unsubscribe_is_promo(subject):
    assert act("Achats", "shop@x.ch", subject, unsub=True, bulk=True) == "Promotions"


def test_promo_word_without_unsubscribe_is_not_promo():
    assert act("Achats", "shop@x.ch", "Offre spéciale", bulk=True) == "4-Pour info"


@pytest.mark.parametrize("category", ["Veille & Newsletters pro", "Médias & Divertissement"])
def test_reading_categories_are_to_read(category):
    assert act(category, "news@x.ch", "Édition du jour", unsub=True, bulk=True) == "3-A lire"


def test_default_is_info():
    assert act("Colis & Livraisons", "noreply@post.ch", "Votre colis arrive", bulk=True) == "4-Pour info"
