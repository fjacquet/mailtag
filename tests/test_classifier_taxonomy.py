import json

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
from mailtag.models import Email
from mailtag.taxonomy import REVIEW, TAXONOMY


def _config(tmp_path):
    return AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3
        ),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(
            enabled=True, nomic_threshold=0.70, llm_batch_size=8, taxonomy_db_dir=str(tmp_path)
        ),
    )


@pytest.fixture
def classifier(tmp_path):
    return Classifier(config=_config(tmp_path))


def mail(i=1, sender="x@shop.ch", subject="S", body="B"):
    return Email(msg_id=str(i), subject=subject, sender_address=sender, sender_name="", body=body)


def _categories(classifier, emails):
    return [category for category, _ in classifier._classify_uncertain_detailed(emails)]


def write(tmp_path, name, data):
    (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_categories_are_the_taxonomy(classifier):
    assert classifier.categories == list(TAXONOMY)


def test_rules_come_from_the_taxonomy_store(tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    write(tmp_path, "senders", {"l@x.ch": {"category": "Achats", "agreements": 2}})
    write(tmp_path, "domains", {"bcv.ch": "Banque & Placements"})
    mocker.patch("mailtag.taxonomy_store.is_non_commercial_domain_cached", return_value=False)
    uncertain = mocker.patch.object(Classifier, "_classify_uncertain_detailed")
    # the fixture's classifier was built before the files existed: build a fresh one
    classifier = Classifier(config=_config(tmp_path))

    result = classifier.classify_emails_batch(
        [mail(1, sender="v@x.ch"), mail(2, sender="l@x.ch"), mail(3, sender="info@bcv.ch")]
    )

    assert result == ["Santé", "Achats", "Banque & Placements"]
    uncertain.assert_not_called()


def test_classify_email_delegates_to_batch(classifier, mocker):
    mocker.patch.object(classifier, "_classify_uncertain_detailed", return_value=[("Achats", False)])

    assert classifier.classify_email(mail()) == "Achats"


def test_two_agreements_make_a_rule(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classifier.classify_emails_batch([mail(1, sender="doc@clinic.ch")])
    classifier.classify_emails_batch([mail(2, sender="doc@clinic.ch")])

    saved = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert saved == {"doc@clinic.ch": {"category": "Santé", "agreements": 2}}
    nomic = mocker.patch.object(classifier, "_nomic_top")
    assert classifier.classify_emails_batch([mail(3, sender="doc@clinic.ch")]) == ["Santé"]
    nomic.assert_not_called()


def test_nomic_alone_does_not_learn(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.95)])

    assert classifier.classify_emails_batch([mail(sender="shop@x.ch")]) == ["Achats"]
    assert not (tmp_path / "senders.json").exists()


def test_read_only_classifier_writes_nothing(tmp_path, mocker):
    classifier = Classifier(config=_config(tmp_path), read_only=True)
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classifier.classify_emails_batch([mail(sender="doc@clinic.ch")])

    assert list(tmp_path.iterdir()) == []


def test_embeddings_path_uses_taxonomy_centroids(classifier):
    assert str(classifier._embeddings_path()) == "data/taxonomy_centroids.npz"


def test_chain_nomic_above_threshold_wins(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.75)])
    llm = mocker.patch.object(classifier, "_llm_categories")

    assert _categories(classifier, [mail()]) == ["Achats"]
    llm.assert_not_called()


def test_chain_agreement_classifies(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    assert _categories(classifier, [mail()]) == ["Santé"]


def test_chain_disagreement_goes_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Achats"])

    assert _categories(classifier, [mail()]) == [REVIEW]


def test_chain_unparsable_llm_goes_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=[None])

    assert _categories(classifier, [mail()]) == [REVIEW]


def test_chain_mixed_batch_keeps_order(classifier, mocker):
    mocker.patch.object(
        classifier, "_nomic_top", return_value=[("Achats", 0.9), ("Santé", 0.5), ("Contacts", 0.4)]
    )
    llm = mocker.patch.object(classifier, "_llm_categories", return_value=["Santé", "Achats"])

    result = _categories(classifier, [mail(1), mail(2), mail(3)])

    assert result == ["Achats", "Santé", REVIEW]
    assert [e.msg_id for e in llm.call_args.args[0]] == ["2", "3"]


def test_detailed_chain_reports_agreement(classifier, mocker):
    mocker.patch.object(
        classifier, "_nomic_top", return_value=[("Achats", 0.9), ("Santé", 0.5), ("Santé", 0.5)]
    )
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé", "Achats"])

    assert classifier._classify_uncertain_detailed([mail(1), mail(2), mail(3)]) == [
        ("Achats", False),
        ("Santé", True),
        (REVIEW, False),
    ]


def test_nomic_failure_sends_everything_to_review(classifier, mocker):
    mocker.patch.object(classifier, "_init_mlx_components", return_value=True)
    router = mocker.MagicMock()
    router.num_categories = 3
    router.top_batch.side_effect = AttributeError("'NomicBertModel' object has no attribute 'x'")
    classifier._semantic_router = router
    mocker.patch.object(classifier, "_llm_categories", return_value=["Achats", "Santé"])

    assert _categories(classifier, [mail(1), mail(2)]) == [REVIEW, REVIEW]


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


def test_owner_address_is_never_a_rule_and_never_learned(tmp_path, mocker):
    import dataclasses

    write(tmp_path, "validated", {"fred.jacquet@gmail.com": "Achats"})
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, taxonomy=dataclasses.replace(config.taxonomy, own_addresses=["Fred.Jacquet@gmail.com"])
    )
    classifier = Classifier(config=config)
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    assert classifier.classify_emails_batch([mail(sender="fred.jacquet@gmail.com")]) == ["Santé"]
    classifier.classify_emails_batch([mail(sender="fred.jacquet@gmail.com")])

    assert not (tmp_path / "senders.json").exists()


def test_classifier_needs_no_database(tmp_path):
    classifier = Classifier(_config(tmp_path))

    assert classifier.categories == list(TAXONOMY)
