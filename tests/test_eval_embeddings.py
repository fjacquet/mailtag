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
