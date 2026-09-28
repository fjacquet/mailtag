from mailtag.migration import destination_for, folders_to_migrate
from mailtag.taxonomy import REVIEW


def test_categories_and_action_folders_and_inbox_are_excluded():
    legacy = ["Voyages", "1-A traiter", "9-A revoir", "INBOX", "Santé"]

    assert folders_to_migrate(legacy) == ["Voyages"]


def test_system_folders_are_excluded():
    legacy = ["Promotions", "Spam", "Sent", "Trash", "Voyages"]

    assert folders_to_migrate(legacy) == ["Voyages"]


def test_contacts_itself_excluded_but_contacts_children_kept():
    legacy = ["Contacts", "Contacts/Alice", "Contacts/Bob"]

    assert folders_to_migrate(legacy) == ["Contacts/Alice", "Contacts/Bob"]


def test_ordinary_legacy_folders_are_kept():
    legacy = ["Finance/Local/EDF", "Services/Development/GitHub"]

    assert folders_to_migrate(legacy) == legacy


class FakeRules:
    def __init__(self, categories):
        self.categories = categories

    def category_for(self, sender):
        return self.categories.get(sender)


def test_validated_sender_rule_wins_over_folder_category():
    rules = FakeRules({"a@x.ch": "Santé"})

    assert destination_for("a@x.ch", "Achats", rules, own=set()) == "Santé"


def test_folder_category_used_when_no_sender_rule():
    rules = FakeRules({})

    assert destination_for("a@x.ch", "Achats", rules, own=set()) == "Achats"


def test_review_when_no_sender_rule_and_no_folder_category():
    rules = FakeRules({})

    assert destination_for("a@x.ch", None, rules, own=set()) == REVIEW


def test_own_address_uses_folder_category_ignoring_sender_rules():
    rules = FakeRules({"me@x.ch": "Achats"})

    assert destination_for("me@x.ch", "Santé", rules, own={"me@x.ch"}) == "Santé"


def test_own_address_with_no_folder_category_goes_to_review():
    rules = FakeRules({"me@x.ch": "Achats"})

    assert destination_for("me@x.ch", None, rules, own={"me@x.ch"}) == REVIEW
