import numpy as np
import pytest

from mailtag.config import LogRegConfig
from mailtag.logreg_provider import (
    PREFIX,
    LogRegClassifier,
    capped_indices,
    corpus_texts,
    embed,
    load_model,
    predict,
    save_model,
    train,
)
from mailtag.models import Email
from tests.fake_embedder import FakeEmbedder

CATS = ["Achats", "Impôts & Administration", "Transports & Mobilité"]
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEmbedder.instances = []
    FakeEmbedder.fail_load = False
    yield
    FakeEmbedder.instances = []
    FakeEmbedder.fail_load = False


def clusters(n=20, seed=0):
    """Three separable clusters in 4 dimensions, one per category of CATS."""
    rng = np.random.default_rng(seed)
    centers = np.array([[3, 0, 0, 0], [0, 3, 0, 0], [0, 0, 3, 0]], dtype=float)
    x = np.vstack([c + rng.normal(scale=0.5, size=(n, 4)) for c in centers])
    y = [cat for cat in CATS for _ in range(n)]
    return x, y


def mail(i=1, subject="pizza", body=""):
    return Email(msg_id=str(i), subject=subject, sender_address=f"s{i}@x.ch", sender_name="", body=body)


def trained_file(tmp_path, embedding_model=MODEL_NAME):
    """A model file trained on FakeEmbedder vectors of 'pizza'/'impot'/'train' mails."""
    texts = [w for w in ("pizza", "impot", "train") for _ in range(5)]
    model = train(embed(FakeEmbedder(), texts), [c for c in CATS for _ in range(5)], C=100.0)
    path = tmp_path / "logreg.npz"
    save_model(path, model, embedding_model)
    return path


def classifier(tmp_path, mocker, path=None):
    mocker.patch("mailtag.mlx_provider.MLXEmbedder", FakeEmbedder)
    config = LogRegConfig(model_file=str(path or tmp_path / "logreg.npz"))
    return LogRegClassifier(config, MODEL_NAME)


def test_predict_matches_scikit_learn_predict_proba():
    from sklearn.linear_model import LogisticRegression

    x, y = clusters()
    model = train(x, y, C=10.0)
    categories, probabilities = predict(model, x)

    reference = LogisticRegression(C=10.0, max_iter=3000).fit(x, y)
    proba = reference.predict_proba(x)
    assert categories == [str(c) for c in reference.classes_[proba.argmax(axis=1)]]
    assert probabilities == pytest.approx(proba.max(axis=1), abs=1e-6)


def test_train_refuses_fewer_than_three_categories():
    x, y = clusters()
    with pytest.raises(ValueError, match="3 categories"):
        train(x[:40], y[:40], C=10.0)


def test_embed_uses_the_classification_prefix_and_normalises():
    embedder = FakeEmbedder()

    emb = embed(embedder, ["pizza impot", "train"])

    assert embedder.prefixes == [PREFIX] == ["classification: "]
    assert np.linalg.norm(emb, axis=1) == pytest.approx([1.0, 1.0])


def test_corpus_texts_use_the_nomic_format():
    corpus = [{"sender_name": "Shop", "sender": "a@shop.ch", "subject": "Commande", "body": "Merci"}]

    assert corpus_texts(corpus) == ["Email from Shop: Commande\nMerci"]


def test_model_file_round_trip(tmp_path):
    x, y = clusters()
    model = train(x, y, C=10.0)
    save_model(tmp_path / "m.npz", model, MODEL_NAME)

    loaded = load_model(tmp_path / "m.npz", MODEL_NAME)

    assert loaded["classes"].tolist() == model["classes"].tolist()
    assert np.array_equal(loaded["coef"], model["coef"])
    assert np.array_equal(loaded["intercept"], model["intercept"])


def test_model_file_without_npz_suffix_lands_exactly_at_the_configured_path(tmp_path):
    x, y = clusters()
    model = train(x, y, C=10.0)
    path = tmp_path / "taxonomy_logreg"
    save_model(path, model, MODEL_NAME)

    assert path.is_file()
    assert not (tmp_path / "taxonomy_logreg.npz").exists()
    assert load_model(path, MODEL_NAME)["classes"].tolist() == model["classes"].tolist()


def test_load_model_refuses_another_embedding_model(tmp_path):
    x, y = clusters()
    save_model(tmp_path / "m.npz", train(x, y, C=10.0), "other/model")

    with pytest.raises(ValueError, match="other/model"):
        load_model(tmp_path / "m.npz", MODEL_NAME)


def test_load_model_refuses_categories_outside_the_taxonomy(tmp_path):
    x, _ = clusters()
    y = [c for c in ("A", "B", "C") for _ in range(20)]
    save_model(tmp_path / "m.npz", train(x, y, C=10.0), MODEL_NAME)

    with pytest.raises(ValueError, match="taxonomy"):
        load_model(tmp_path / "m.npz", MODEL_NAME)


def test_classify_answers_category_and_probability(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))

    answers = clf.classify([mail(1, "pizza"), mail(2, "impot"), mail(3, "train")])

    assert [a[0] for a in answers] == CATS
    assert all(0.0 < a[1] <= 1.0 for a in answers)
    assert FakeEmbedder.instances[-1].prefixes == [PREFIX]


def test_classify_empty_list_loads_nothing(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))
    FakeEmbedder.instances = []

    assert clf.classify([]) == []
    assert FakeEmbedder.instances == []


def test_missing_model_file_sends_everything_to_review(tmp_path, mocker, caplog):
    clf = classifier(tmp_path, mocker)

    assert clf.classify([mail(1), mail(2)]) == [None, None]
    assert "taxonomy_setup.py train" in caplog.text


def test_model_of_another_embedding_model_sends_everything_to_review(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path, embedding_model="other/model"))

    assert clf.classify([mail()]) == [None]


def test_failed_embedder_load_is_tried_once(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))
    FakeEmbedder.instances = []
    FakeEmbedder.fail_load = True

    assert clf.classify([mail()]) == [None]
    assert clf.classify([mail()]) == [None]
    assert len(FakeEmbedder.instances) == 1


def test_failed_batch_goes_to_review_and_next_batch_retries(tmp_path, mocker):
    clf = classifier(tmp_path, mocker, trained_file(tmp_path))
    FakeEmbedder.instances = []
    clf.classify([])  # nothing loaded yet
    first = clf.classify([mail(1, "pizza")])
    FakeEmbedder.instances[-1].fail = 1

    assert first[0][0] == "Achats"
    assert clf.classify([mail(2, "pizza")]) == [None]
    assert clf.classify([mail(3, "train")])[0][0] == "Transports & Mobilité"


def test_capped_indices_keeps_the_first_mails_of_each_sender_in_order():
    corpus = [{"sender": s} for s in ["a", "b", "a", "a", "c", "b", "a"]]

    assert capped_indices(corpus, 2) == [0, 1, 2, 4, 5]
    assert capped_indices(corpus, 10) == list(range(7))
