import numpy as np
import pytest

from scripts.eval_embeddings import score


def test_score_top1_top5_and_threshold_curve():
    categories = ["A", "B", "C"]
    labels = ["A", "B", "C", "A"]
    sims = np.array(
        [
            [0.9, 0.1, 0.0],  # A correct, high score
            [0.2, 0.6, 0.1],  # B correct, mid score
            [0.8, 0.3, 0.1],  # C wrong (predicts A), high score
            [0.1, 0.5, 0.4],  # A wrong (predicts B), rank 3
        ]
    )

    result = score(sims, categories, labels, thresholds=[0.0, 0.7])

    assert result["n"] == 4
    assert result["top1"] == pytest.approx(0.5)
    assert result["top5"] == pytest.approx(1.0)
    assert result["curve"][0.0] == {"coverage": pytest.approx(1.0), "precision": pytest.approx(0.5)}
    # Only rows 0 and 2 clear 0.7: one right, one wrong
    assert result["curve"][0.7] == {"coverage": pytest.approx(0.5), "precision": pytest.approx(0.5)}


def test_score_counts_labels_missing_from_router_as_wrong():
    result = score(np.array([[0.9, 0.1]]), ["A", "B"], ["Z"], thresholds=[0.0])

    assert result["unreachable"] == 1
    assert result["top1"] == 0.0
    assert result["top5"] == 0.0


def test_coverage_at_precision_picks_lowest_threshold_meeting_target():
    from scripts.eval_embeddings import coverage_at_precision

    sims = np.array([[0.9, 0.1], [0.8, 0.1], [0.6, 0.1], [0.4, 0.1]])
    labels = ["A", "A", "B", "A"]  # third row is wrong

    # Precision >= 90% needs threshold above 0.6 -> 2 of 4 emails classified
    assert coverage_at_precision(sims, ["A", "B"], labels, 0.9) == pytest.approx(0.5)
    # 75% precision reached at threshold 0.4 -> everything classified
    assert coverage_at_precision(sims, ["A", "B"], labels, 0.75) == pytest.approx(1.0)


def test_centroid_sims_leave_sender_out_ignores_own_sender():
    from scripts.eval_embeddings import centroid_sims_leave_sender_out

    vecs = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]])
    folders = ["A", "A", "B", "B"]
    senders = ["x", "y", "z", "z"]

    cats, sims = centroid_sims_leave_sender_out(vecs, vecs, folders, senders)

    assert cats == ["A", "B"]
    # Email 0: folder A still has sender y, identical vector
    assert sims[0, 0] == pytest.approx(1.0)
    # Emails 2-3: folder B only has sender z, so B is unreachable for them
    assert sims[2, 1] == -1.0


def test_centroid_sims_leave_sender_out_blends_extra_examples():
    from scripts.eval_embeddings import centroid_sims_leave_sender_out

    vecs = np.array([[1.0, 0.0]])
    extra = {"A": np.array([[0.0, 1.0]]), "C": np.array([[0.0, 1.0]])}

    cats, sims = centroid_sims_leave_sender_out(vecs, vecs, ["A"], ["x"], extra)

    assert cats == ["A", "C"]
    # Own sender removed, A falls back to its extra example only
    assert sims[0, 0] == pytest.approx(0.0)


def test_knn_sims_leave_sender_out_votes_by_neighbour_folder():
    from scripts.eval_embeddings import knn_sims_leave_sender_out

    vecs = np.array([[1.0, 0.0], [0.9, 0.1], [0.95, 0.05], [0.0, 1.0]])
    folders = ["A", "A", "B", "B"]
    senders = ["x", "y", "x", "w"]

    cats, sims = knn_sims_leave_sender_out(vecs, vecs, folders, senders, k=1)

    # Email 0 cannot see email 2 (same sender x), nearest is email 1 in A
    assert cats[int(np.argmax(sims[0]))] == "A"


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
