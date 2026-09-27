from collections import defaultdict

import pytest

from mailtag.classifier import Classifier
from mailtag.config import (
    AppConfig,
    ClassifierConfig,
    FastParseConfig,
    GeneralConfig,
    GmailConfig,
    ImapConfig,
    LoggingConfig,
    MLXConfig,
    TaxonomyConfig,
)
from mailtag.database import ClassificationDatabase
from mailtag.models import Email
from mailtag.taxonomy import REVIEW, TAXONOMY


@pytest.fixture
def db(mocker):
    db = mocker.MagicMock(spec=ClassificationDatabase)
    db.get_dominant_classification.return_value = None
    db.get_sender_classifications.return_value = {}
    db.get_category_by_domain.return_value = None
    db.suggestion_db = defaultdict(lambda: defaultdict(int))
    return db


@pytest.fixture
def classifier(db, mocker):
    config = AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3
        ),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(enabled=True, nomic_threshold=0.70, llm_batch_size=8),
    )
    return Classifier(config=config, database=db)


def mail(i=1, sender="x@shop.ch", subject="S", body="B", labels=None):
    return Email(
        msg_id=str(i), subject=subject, sender_address=sender, sender_name="", body=body, labels=labels or []
    )


def test_categories_are_the_taxonomy(classifier):
    assert classifier.categories == list(TAXONOMY)


def test_validated_old_path_is_mapped(classifier, db, mocker):
    db.get_dominant_classification.return_value = "Voyages/Sixt"
    uncertain = mocker.patch.object(classifier, "_classify_uncertain")

    assert classifier.classify_emails_batch([mail()]) == ["Voyages & Loisirs"]
    uncertain.assert_not_called()


def test_domain_rule_is_mapped(classifier, db, mocker):
    db.get_category_by_domain.return_value = "Finance/Local/BCV"
    mocker.patch.object(classifier, "_classify_uncertain")

    assert classifier.classify_emails_batch([mail(sender="a@bcv.ch")]) == ["Banque & Placements"]


def test_rules_skip_unmappable_old_values(classifier, db, mocker):
    db.get_dominant_classification.return_value = "À Classer"
    mocker.patch.object(classifier, "_classify_uncertain", return_value=[REVIEW])

    assert classifier.classify_emails_batch([mail()]) == [REVIEW]


def test_classify_email_delegates_to_batch(classifier, mocker):
    mocker.patch.object(classifier, "_classify_uncertain", return_value=["Achats"])

    assert classifier.classify_email(mail()) == "Achats"


def test_chain_nomic_above_threshold_wins(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.75)])
    llm = mocker.patch.object(classifier, "_llm_categories")

    assert classifier._classify_uncertain([mail()]) == ["Achats"]
    llm.assert_not_called()


def test_chain_agreement_classifies(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    assert classifier._classify_uncertain([mail()]) == ["Santé"]


def test_chain_disagreement_goes_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Achats"])

    assert classifier._classify_uncertain([mail()]) == [REVIEW]


def test_chain_unparsable_llm_goes_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=[None])

    assert classifier._classify_uncertain([mail()]) == [REVIEW]


def test_chain_mixed_batch_keeps_order(classifier, mocker):
    mocker.patch.object(
        classifier, "_nomic_top", return_value=[("Achats", 0.9), ("Santé", 0.5), ("Contacts", 0.4)]
    )
    llm = mocker.patch.object(classifier, "_llm_categories", return_value=["Santé", "Achats"])

    result = classifier._classify_uncertain([mail(1), mail(2), mail(3)])

    assert result == ["Achats", "Santé", REVIEW]
    assert [e.msg_id for e in llm.call_args.args[0]] == ["2", "3"]


def test_nomic_failure_sends_everything_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    router = mocker.MagicMock()
    router.num_categories = 3
    router.top_batch.side_effect = AttributeError("'NomicBertModel' object has no attribute 'x'")
    classifier._semantic_router = router
    mocker.patch.object(classifier, "_llm_categories", return_value=["Achats", "Santé"])

    assert classifier._classify_uncertain([mail(1), mail(2)]) == [REVIEW, REVIEW]


def test_nomic_top_maps_old_folder_to_category(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    router = mocker.MagicMock()
    router.num_categories = 3
    router.top_batch.return_value = [("Voyages/Sixt", 0.8), ("INBOX", 0.9)]
    classifier._semantic_router = router

    assert classifier._nomic_top([mail(1), mail(2)]) == [("Voyages & Loisirs", 0.8), (None, 0.9)]


def test_llm_categories_parses_numbers(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    llm = mocker.MagicMock()
    llm.classify_batch.return_value = ["8", "abc"]
    classifier._mlx_llm = llm

    assert classifier._llm_categories([mail(1), mail(2, body="x" * 2000)]) == ["Achats", None]
    static, parts = llm.classify_batch.call_args.args[:2]
    assert static.startswith("Classe cet email")
    assert len(parts[1]) < 700  # body truncated to 500 chars
    assert llm.classify_batch.call_args.kwargs["batch_size"] == 8


def test_llm_failure_returns_none(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    llm = mocker.MagicMock()
    llm.classify_batch.side_effect = RuntimeError("metal")
    classifier._mlx_llm = llm

    assert classifier._llm_categories([mail()]) == [None]
