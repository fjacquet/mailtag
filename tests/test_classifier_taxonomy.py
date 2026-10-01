import json

import pytest

from mailtag.classifier import Classifier
from mailtag.config import (
    AppConfig,
    ClassifierConfig,
    FastParseConfig,
    GmailConfig,
    ImapConfig,
    LayaConfig,
    LayaThresholds,
    LoggingConfig,
    LogRegConfig,
    MLXConfig,
    TaxonomyConfig,
)
from mailtag.models import Email
from mailtag.taxonomy import REVIEW, TAXONOMY


def _config(tmp_path):
    return AppConfig(
        logging=LoggingConfig(level="DEBUG", file=""),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
        taxonomy=TaxonomyConfig(nomic_threshold=0.70, llm_batch_size=8, taxonomy_db_dir=str(tmp_path)),
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


def classify_and_learn(classifier, emails):
    """What `run` does for mails that moved: classify, then learn from the agreements."""
    results = classifier.classify_detailed(emails)
    classifier.learn(emails, results)
    return [category for category, _ in results]


def test_classify_detailed_alone_learns_nothing(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    assert classifier.classify_detailed([mail(sender="doc@clinic.ch")]) == [("Santé", True)]
    assert not (tmp_path / "senders.json").exists()


def test_rules_come_from_the_taxonomy_store(tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    write(tmp_path, "senders", {"l@x.ch": {"category": "Achats", "agreements": 2}})
    write(tmp_path, "domains", {"bcv.ch": "Banque & Placements"})
    mocker.patch("mailtag.taxonomy_store.is_non_commercial_domain_cached", return_value=False)
    uncertain = mocker.patch.object(Classifier, "_classify_uncertain_detailed")
    # the fixture's classifier was built before the files existed: build a fresh one
    classifier = Classifier(config=_config(tmp_path))

    result = classify_and_learn(
        classifier, [mail(1, sender="v@x.ch"), mail(2, sender="l@x.ch"), mail(3, sender="info@bcv.ch")]
    )

    assert result == ["Santé", "Achats", "Banque & Placements"]
    uncertain.assert_not_called()


def test_two_agreements_make_a_rule(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classify_and_learn(classifier, [mail(1, sender="doc@clinic.ch")])
    classify_and_learn(classifier, [mail(2, sender="doc@clinic.ch")])

    saved = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert saved == {"doc@clinic.ch": {"category": "Santé", "agreements": 2}}
    nomic = mocker.patch.object(classifier, "_nomic_top")
    assert classify_and_learn(classifier, [mail(3, sender="doc@clinic.ch")]) == ["Santé"]
    nomic.assert_not_called()


def test_nomic_alone_does_not_learn(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Achats", 0.95)])

    assert classify_and_learn(classifier, [mail(sender="shop@x.ch")]) == ["Achats"]
    assert not (tmp_path / "senders.json").exists()


def test_read_only_classifier_writes_nothing(tmp_path, mocker):
    classifier = Classifier(config=_config(tmp_path), read_only=True)
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])

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

    assert classify_and_learn(classifier, [mail(sender="fred.jacquet@gmail.com")]) == ["Santé"]
    classify_and_learn(classifier, [mail(sender="fred.jacquet@gmail.com")])

    assert not (tmp_path / "senders.json").exists()


def test_classifier_needs_no_database(tmp_path):
    classifier = Classifier(_config(tmp_path))

    assert classifier.categories == list(TAXONOMY)


def test_without_mlx_uncovered_mail_goes_to_review(tmp_path, mocker):
    network = mocker.patch("socket.socket.connect", side_effect=AssertionError("no network"))
    classifier = Classifier(_config(tmp_path))

    assert classify_and_learn(classifier, [mail(sender="new@unknown.ch")]) == [REVIEW]
    network.assert_not_called()


def test_no_nomic_category_means_no_llm_call(classifier, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[(None, 0.0), ("Santé", 0.60)])
    llm = mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])

    assert _categories(classifier, [mail(1), mail(2)]) == [REVIEW, "Santé"]
    assert llm.call_args.args[0] == [mail(2)]


def test_classify_detailed_learns_nothing_until_learn_is_called(classifier, tmp_path, mocker):
    mocker.patch.object(classifier, "_nomic_top", return_value=[("Santé", 0.60)])
    mocker.patch.object(classifier, "_llm_categories", return_value=["Santé"])
    emails = [mail(sender="doc@clinic.ch")]

    results = classifier.classify_detailed(emails)

    assert results == [("Santé", True)]
    assert not (tmp_path / "senders.json").exists()
    classifier.learn(emails, results)
    assert json.loads((tmp_path / "senders.json").read_text(encoding="utf-8")) == {
        "doc@clinic.ch": {"category": "Santé", "agreements": 1}
    }


def _laya_classifier(tmp_path, answers, mocker, **thresholds):
    config = _config(tmp_path)
    config.classifier = ClassifierConfig(mode="laya")
    config.laya = LayaConfig(
        english=thresholds.get("english", LayaThresholds(0.7, 0.95)),
        multilingual=thresholds.get("multilingual", LayaThresholds(0.6, 0.9)),
    )
    classifier = Classifier(config=config)
    mocker.patch.object(classifier._laya, "classify", return_value=answers)
    return classifier


def test_laya_mode_applies_each_checkpoints_thresholds(tmp_path, mocker):
    answers = [
        ("Santé", 0.65, "english"),  # below english classify (0.7)
        ("Santé", 0.65, "multilingual"),  # above multilingual classify (0.6), below learn
        ("Achats", 0.95, "english"),  # exactly english learn: inclusive
        ("Achats", 0.6, "multilingual"),  # exactly multilingual classify: inclusive
        None,  # Laya could not answer
    ]
    classifier = _laya_classifier(tmp_path, answers, mocker)

    assert classifier._classify_uncertain_detailed([mail(i) for i in range(5)]) == [
        (REVIEW, False),
        ("Santé", False),
        ("Achats", True),
        ("Achats", False),
        (REVIEW, False),
    ]


def test_laya_mode_never_learns_with_the_inert_default(tmp_path, mocker):
    classifier = _laya_classifier(
        tmp_path, [("Santé", 1.0, "multilingual")], mocker, multilingual=LayaThresholds(0.5, 1.01)
    )

    assert classifier._classify_uncertain_detailed([mail()]) == [("Santé", False)]


def test_laya_mode_runs_rules_first_and_never_loads_mlx(tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    classifier = _laya_classifier(tmp_path, [("Achats", 0.99, "multilingual")], mocker)
    mlx = mocker.patch.object(classifier, "_init_mlx_components")

    result = classifier.classify_detailed([mail(1, sender="v@x.ch"), mail(2, sender="new@shop.ch")])

    assert result == [("Santé", False), ("Achats", True)]
    classifier._laya.classify.assert_called_once()
    assert [e.sender_address for e in classifier._laya.classify.call_args.args[0]] == ["new@shop.ch"]
    mlx.assert_not_called()


def test_laya_mode_agreements_teach_rules(tmp_path, mocker):
    classifier = _laya_classifier(tmp_path, [("Santé", 0.97, "multilingual")], mocker)

    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])
    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])

    learned = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert learned["doc@clinic.ch"]["category"] == "Santé"


def test_mlx_mode_builds_no_laya_classifier(classifier):
    assert classifier._laya is None


def _logreg_classifier(tmp_path, answers, mocker, classify=0.9, learn=0.97):
    config = _config(tmp_path)
    config.mlx = MLXConfig(enabled=True)
    config.classifier = ClassifierConfig(mode="logreg")
    config.logreg = LogRegConfig(classify_threshold=classify, learn_threshold=learn)
    classifier = Classifier(config=config)
    mocker.patch.object(classifier._logreg, "classify", return_value=answers)
    return classifier


def test_logreg_mode_applies_its_thresholds_inclusively(tmp_path, mocker):
    answers = [
        ("Santé", 0.89),  # below classify
        ("Santé", 0.9),  # exactly classify: inclusive
        ("Achats", 0.97),  # exactly learn: inclusive
        None,  # the model could not answer
    ]
    classifier = _logreg_classifier(tmp_path, answers, mocker)

    assert classifier._classify_uncertain_detailed([mail(i) for i in range(4)]) == [
        (REVIEW, False),
        ("Santé", False),
        ("Achats", True),
        (REVIEW, False),
    ]


def test_logreg_mode_never_learns_with_the_inert_default(tmp_path, mocker):
    classifier = _logreg_classifier(tmp_path, [("Santé", 1.0)], mocker, classify=0.5, learn=1.01)

    assert classifier._classify_uncertain_detailed([mail()]) == [("Santé", False)]


def test_logreg_mode_runs_rules_first_and_never_calls_gemma_or_centroids(tmp_path, mocker):
    write(tmp_path, "validated", {"v@x.ch": "Santé"})
    classifier = _logreg_classifier(tmp_path, [("Achats", 0.99)], mocker)
    mlx = mocker.patch.object(classifier, "_init_mlx_components")
    llm = mocker.patch.object(classifier, "_llm_categories")

    result = classifier.classify_detailed([mail(1, sender="v@x.ch"), mail(2, sender="new@shop.ch")])

    assert result == [("Santé", False), ("Achats", True)]
    assert [e.sender_address for e in classifier._logreg.classify.call_args.args[0]] == ["new@shop.ch"]
    mlx.assert_not_called()
    llm.assert_not_called()


def test_logreg_mode_agreements_teach_rules(tmp_path, mocker):
    classifier = _logreg_classifier(tmp_path, [("Santé", 0.98)], mocker)

    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])
    classify_and_learn(classifier, [mail(sender="doc@clinic.ch")])

    learned = json.loads((tmp_path / "senders.json").read_text(encoding="utf-8"))
    assert learned["doc@clinic.ch"]["category"] == "Santé"


def test_logreg_mode_without_mlx_sends_uncovered_mail_to_review(tmp_path, mocker):
    network = mocker.patch("socket.socket.connect", side_effect=AssertionError("no network"))
    config = _config(tmp_path)  # MLX disabled
    config.classifier = ClassifierConfig(mode="logreg")
    classifier = Classifier(config=config)

    assert classifier._logreg is None
    assert classify_and_learn(classifier, [mail(sender="new@unknown.ch")]) == [REVIEW]
    network.assert_not_called()


def test_mlx_mode_builds_no_logreg_classifier(classifier):
    assert classifier._logreg is None
