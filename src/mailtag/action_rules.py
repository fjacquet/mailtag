"""Pick the action folder for a classified email (spec section 4). Pure functions, no I/O."""

import re
import unicodedata

from .taxonomy import ACTION_INFO, ACTION_PAY, ACTION_PROMO, ACTION_READ, ACTION_TODO, REVIEW

_MONEY_CATEGORIES = {
    "Banque & Placements",
    "Énergie & Télécom",
    "Assurances & Retraite",
    "Impôts & Administration",
}
_READING_CATEGORIES = {"Veille & Newsletters pro", "Médias & Divertissement"}

# Matched on accent-stripped, lower-cased subjects
_BILL_RE = re.compile(
    r"\b(facture|echeance|rappel|paiement|montant du|invoice|rechnung|mahnung|bill|payment due)\b"
)
_PROMO_RE = re.compile(r"%|\b(offre|promo|rabais|soldes|reduction|sale|rabatt|angebot)\b")
_AUTOMATED_LOCAL_PART_RE = re.compile(r"no-?reply|notification|newsletter")
_AUTOMATED_LOCAL_PARTS = {"info", "news"}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _is_person(sender_address: str, is_bulk: bool) -> bool:
    if is_bulk:
        return False
    local_part = (sender_address or "").split("@")[0].lower()
    return not (_AUTOMATED_LOCAL_PART_RE.search(local_part) or local_part in _AUTOMATED_LOCAL_PARTS)


def choose_action(
    category: str, sender_address: str, subject: str, *, has_unsubscribe: bool, is_bulk: bool
) -> str:
    """Return the action folder for an email; the first matching rule wins."""
    if category == REVIEW:
        return REVIEW
    normalized_subject = _normalize(subject)
    if category in _MONEY_CATEGORIES and _BILL_RE.search(normalized_subject):
        return ACTION_PAY
    if _is_person(sender_address, is_bulk):
        return ACTION_TODO
    if has_unsubscribe and _PROMO_RE.search(normalized_subject):
        return ACTION_PROMO
    if category in _READING_CATEGORIES:
        return ACTION_READ
    return ACTION_INFO
