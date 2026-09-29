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
