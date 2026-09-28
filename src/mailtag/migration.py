"""Migrate mails from the 611 legacy folders into the 19 categories (spec section: design)."""

from .taxonomy import _NOT_A_CATEGORY, ACTION_FOLDERS, REVIEW, TAXONOMY

_PROTECTED = set(TAXONOMY) | set(ACTION_FOLDERS) | _NOT_A_CATEGORY | {"INBOX"}


def folders_to_migrate(legacy: list[str]) -> list[str]:
    """Legacy folders to sweep: legacy minus categories, action folders, system folders, `INBOX`
    and `Contacts` itself (its children, e.g. `Contacts/Alice`, are ordinary legacy folders)."""
    return [folder for folder in legacy if folder not in _PROTECTED]


def destination_for(sender: str, folder_category: str | None, rules, own: set[str]) -> str:
    """Destination category for one mail: owner's address -> folder category; else the
    sender's rule (validated > learned > domain); else the folder category; else REVIEW."""
    if sender not in own:
        category = rules.category_for(sender)
        if category:
            return category
    return folder_category or REVIEW
