import numpy as np
import pytest


def test_chain_metrics_success_criteria():
    from scripts.eval_embeddings import chain_metrics

    labels = ["A"] * 10
    results = ["A"] * 5 + ["B"] * 0 + ["5-A revoir"] * 5  # 50% auto, 100% precise
    m = chain_metrics(results, labels, llm_seconds=6.0, llm_calls=5)
    assert m == {"auto": 0.5, "precision": 1.0, "sec_per_llm_email": 1.2, "passed": True}

    bad = chain_metrics(["A", "B", "5-A revoir", "5-A revoir"], ["A"] * 4, llm_seconds=8.0, llm_calls=4)
    assert bad["precision"] == 0.5
    assert bad["passed"] is False


def test_leave_sender_out_excludes_the_query_sender():
    from scripts.eval_embeddings import leave_sender_out_top

    doc = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    cats = ["Achats", "Achats", "Santé"]
    senders = ["a@x", "b@x", "c@x"]
    query = np.array([[1.0, 0.0], [1.0, 0.1]])

    top = leave_sender_out_top(doc, cats, senders, query, ["a@x", "c@x"])

    assert top[0][0] == "Achats" and top[0][1] == pytest.approx(1.0)  # b@x still defines Achats
    assert top[1][0] == "Achats"  # Santé has no document left once c@x is excluded


def test_leave_sender_out_with_no_centroid_left():
    from scripts.eval_embeddings import leave_sender_out_top

    top = leave_sender_out_top(np.array([[1.0, 0.0]]), ["Achats"], ["a@x"], np.array([[1.0, 0.0]]), ["a@x"])

    assert top == [(None, 0.0)]


def test_threshold_sweep_and_best():
    from scripts.eval_embeddings import best_threshold, threshold_sweep

    nomic = [("A", 0.9), ("A", 0.6), ("B", 0.65), ("B", 0.5)]
    llm = [None, "A", None, "C"]
    labels = ["A", "A", "C", "B"]

    sweep = threshold_sweep(nomic, llm, labels, [0.6, 0.8])

    assert sweep[0] == {"threshold": 0.6, "auto": 0.75, "precision": pytest.approx(2 / 3)}
    assert sweep[1] == {"threshold": 0.8, "auto": 0.5, "precision": 1.0}
    assert best_threshold(sweep) == sweep[1]
    assert best_threshold(sweep, min_precision=1.1) is None


def test_confidence_sweep():
    from scripts.eval_embeddings import confidence_sweep

    answers = [("A", 0.9), ("B", 0.6), ("C", 0.95), None]
    labels = ["A", "A", "C", "B"]

    sweep = confidence_sweep(answers, labels, [0.5, 0.8])

    assert sweep[0] == {"threshold": 0.5, "auto": 0.75, "precision": pytest.approx(2 / 3), "classified": 3}
    assert sweep[1] == {"threshold": 0.8, "auto": 0.5, "precision": 1.0, "classified": 2}


def test_learn_threshold_needs_precision_and_enough_mails():
    from scripts.eval_embeddings import learn_threshold

    sweep = [
        {"threshold": 0.8, "auto": 0.9, "precision": 0.95, "classified": 90},
        {"threshold": 0.9, "auto": 0.5, "precision": 0.98, "classified": 50},
        {"threshold": 0.95, "auto": 0.2, "precision": 1.0, "classified": 20},
    ]

    assert learn_threshold(sweep) == 0.9
    assert learn_threshold(sweep, min_mails=60) == 1.01
    assert learn_threshold([]) == 1.01


def test_fold_group_is_the_domain_or_the_address_on_personal_domains():
    from scripts.eval_embeddings import fold_group

    assert fold_group("News@Shop.ch") == "shop.ch"
    assert fold_group("jane.doe@gmail.com") == "jane.doe@gmail.com"


def test_group_folds_never_share_a_group_and_test_each_mail_once():
    from scripts.eval_embeddings import group_folds

    train_groups = [f"d{i % 7}.ch" for i in range(60)]  # 7 domains in the training corpus
    test_groups = [f"d{i % 6}.ch" for i in range(30)]  # 6 of them in the test set

    tested = []
    for train, test in group_folds(train_groups, test_groups, n_splits=3):
        assert not {train_groups[i] for i in train} & {test_groups[i] for i in test}
        assert len(train) > 0
        tested += test.tolist()

    assert sorted(tested) == list(range(30))


def test_pick_winner_keeps_the_baseline_on_a_tie():
    from scripts.eval_embeddings import pick_winner

    scored = [(0.0, 0.70, "base"), (0.0, 0.72, "h per_sender=5"), (0.0, 0.71, "h per_sender=10")]

    assert pick_winner(scored, "base") == "base"


def test_pick_winner_adopts_a_harvested_corpus_only_when_strictly_better():
    from scripts.eval_embeddings import pick_winner

    scored = [(0.10, 0.70, "base"), (0.12, 0.69, "h per_sender=5"), (0.10, 0.80, "h per_sender=10")]

    assert pick_winner(scored, "base") == "h per_sender=5"


def test_pick_winner_among_harvested_prefers_coverage_then_top1():
    from scripts.eval_embeddings import pick_winner

    scored = [(0.0, 0.70, "base"), (0.2, 0.60, "h5"), (0.2, 0.65, "h10"), (0.1, 0.90, "h20")]

    assert pick_winner(scored, "base") == "h10"


def test_pick_winner_baseline_alone():
    from scripts.eval_embeddings import pick_winner

    assert pick_winner([(0.3, 0.7, "base")], "base") == "base"


def test_reaches_pass3_drops_only_mails_whose_domain_has_a_rule():
    from scripts.eval_embeddings import reaches_pass3

    rules = {"shop.ch": "Achats"}
    mails = [
        {"sender": "jane@gmail.com"},
        {"sender": "news@unknown.org"},
        {"sender": "news@shop.ch"},
        {"sender": "News@SHOP.CH"},
    ]

    kept = reaches_pass3(mails, rules.get)

    assert [m["sender"] for m in kept] == ["jane@gmail.com", "news@unknown.org"]


def test_reaches_pass3_keeps_a_personal_domain_even_if_a_rule_claims_it():
    from scripts.eval_embeddings import reaches_pass3

    assert reaches_pass3([{"sender": "jane@gmail.com"}], lambda d: "Achats") == [{"sender": "jane@gmail.com"}]
