import sys
import types

import pytest

from mailtag.config import LayaConfig
from mailtag.laya_provider import LayaClassifier, category_answer, category_questions, email_state
from mailtag.models import Email
from mailtag.taxonomy import TAXONOMY, TAXONOMY_EN


def mail(i=1, sender="news@shop.ch", name="Shop", subject="Votre commande", body="Merci pour votre achat"):
    return Email(msg_id=str(i), subject=subject, sender_address=sender, sender_name=name, body=body)


class FakeRouter:
    """Stands in for laya.Router: routes by a marker in the subject, answers the first option."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests = []
        self.batch_size = None
        self.fail = 0
        FakeRouter.instances.append(self)

    def route_batch(self, requests):
        return [{"model": "english" if "EN" in r["state"]["subject"] else "multilingual"} for r in requests]

    def predict_batch(self, requests, batch_size=None, sort_by_length=False):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("checkpoint download failed")
        self.requests += requests
        self.batch_size = batch_size
        results = []
        for r in requests:
            answers = {}
            for qid, q in r["questions"].items():
                labels = list(q["criteria"])
                probs = {label: 0.0 for label in labels}
                probs[labels[1]] = 0.8
                probs[labels[0]] = 0.2
                answers[qid] = {"choice": labels[1], "probabilities": probs, "answer_confidence": 0.8}
            results.append({"answers": answers, "routing": {"model": r["model"]}})
        return results

    def loaded(self):
        return ["multilingual"]

    def load(self, name):
        return types.SimpleNamespace(device="mps")


@pytest.fixture
def fake_laya(monkeypatch):
    FakeRouter.instances = []
    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(Router=FakeRouter))
    return FakeRouter


def test_questions_use_the_checkpoint_language():
    fr = category_questions("multilingual", rotations=False)["category"]
    en = category_questions("english", rotations=False)["category"]

    assert fr["type"] == en["type"] == "choice"
    assert fr["criteria"] == TAXONOMY
    assert en["criteria"] == dict(TAXONOMY_EN.values())


def test_rotations_put_every_option_in_every_slot():
    questions = category_questions("multilingual", rotations=True)

    assert len(questions) == len(TAXONOMY)
    k = len(TAXONOMY)
    firsts = {q["option_order"][0] for q in questions.values()}
    assert firsts == set(range(k))
    assert all(sorted(q["option_order"]) == list(range(k)) for q in questions.values())


def test_english_answer_maps_back_to_the_french_category():
    label = TAXONOMY_EN["Santé"][0]
    answers = {"category": {"choice": label, "probabilities": {label: 0.9}, "answer_confidence": 0.9}}

    assert category_answer(answers, "english") == ("Santé", 0.9)


def test_rotated_answers_are_averaged():
    answers = {
        "category_0": {
            "choice": "Achats",
            "probabilities": {"Achats": 0.6, "Santé": 0.4},
            "answer_confidence": 0.6,
        },
        "category_1": {
            "choice": "Santé",
            "probabilities": {"Achats": 0.2, "Santé": 0.8},
            "answer_confidence": 0.8,
        },
    }

    category, confidence = category_answer(answers, "multilingual")

    assert category == "Santé"
    assert confidence == pytest.approx(0.6)


def test_email_state_with_and_without_a_name():
    assert email_state(mail(), 1500) == {
        "from": "Shop <news@shop.ch>",
        "subject": "Votre commande",
        "body": "Merci pour votre achat",
    }
    assert email_state(mail(name=""), 1500)["from"] == "news@shop.ch"


def test_classify_routes_and_asks_in_the_checkpoint_language(fake_laya):
    config = LayaConfig(batch_size=4, head_max_len=384, max_len=900, device="mps")
    classifier = LayaClassifier(config)

    result = classifier.classify([mail(1), mail(2, subject="EN order")])

    router = fake_laya.instances[0]
    assert router.kwargs["device"] == "mps"
    assert router.kwargs["default"] == "multilingual"
    assert router.kwargs["agent_kwargs"] == {"calibration": "data/laya_neutral_calibration.json"}
    assert router.batch_size == 4
    assert [r["model"] for r in router.requests] == ["multilingual", "english"]
    assert all(r["max_len"] == 900 and r["head_max_len"] == 384 for r in router.requests)
    second = list(TAXONOMY)[1]  # the fake answers the second option; English labels map back to it
    assert result == [(second, 0.8, "multilingual"), (second, 0.8, "english")]


def test_auto_device_and_no_calibration(fake_laya):
    LayaClassifier(LayaConfig(device="auto", calibration="")).classify([mail()])

    router = fake_laya.instances[0]
    assert router.kwargs["device"] is None
    assert router.kwargs["agent_kwargs"] == {}


def test_multilingual_routing_skips_language_detection(fake_laya, mocker):
    classifier = LayaClassifier(LayaConfig(routing="multilingual"))
    route = mocker.spy(FakeRouter, "route_batch")

    classifier.classify([mail(subject="EN order")])

    route.assert_not_called()
    assert fake_laya.instances[0].requests[0]["model"] == "multilingual"


def test_unexpected_checkpoint_is_treated_as_multilingual(fake_laya, mocker):
    mocker.patch.object(FakeRouter, "route_batch", return_value=[{"model": "typed-decisions"}])

    result = LayaClassifier(LayaConfig()).classify([mail()])

    assert fake_laya.instances[0].requests[0]["model"] == "multilingual"
    assert result[0][2] == "multilingual"


def test_empty_mail_is_classified_without_error(fake_laya):
    result = LayaClassifier(LayaConfig()).classify([mail(subject="", body="", name="")])

    assert result[0] is not None


def test_failed_batch_goes_to_review_and_next_batch_retries(fake_laya):
    classifier = LayaClassifier(LayaConfig())
    classifier.classify([])  # builds nothing
    assert fake_laya.instances == []

    classifier._load().fail = 1
    assert classifier.classify([mail(1), mail(2)]) == [None, None]
    assert classifier.classify([mail(3)])[0] is not None
    assert len(fake_laya.instances) == 1  # the Router is built once


def test_missing_laya_sends_everything_to_review(monkeypatch):
    monkeypatch.setitem(sys.modules, "laya", None)  # import laya -> ImportError

    classifier = LayaClassifier(LayaConfig())

    assert classifier.classify([mail(1), mail(2)]) == [None, None]
    assert classifier.classify([mail(3)]) == [None]


def test_devices_reports_loaded_checkpoints(fake_laya):
    classifier = LayaClassifier(LayaConfig())
    assert classifier.devices() == {}
    classifier.classify([mail()])

    assert classifier.devices() == {"multilingual": "mps"}
