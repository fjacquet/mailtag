import pytest

from mailtag.sender_crosscheck import crosscheck_senders
from mailtag.taxonomy import llm_sender_static_prompt


def sender(name, n, subjects=("S",)):
    return {
        "name": name,
        "domain": "x.ch",
        "categories": {"Achats": n},
        "subjects": list(subjects),
        "refs": [],
    }


def test_answers_are_parsed_in_volume_order(mocker):
    senders = {"small@x.ch": sender("Small", 1), "big@x.ch": sender("Big", 50, ["Facture"])}
    llm = mocker.MagicMock()
    llm.classify_batch.return_value = ["8", "banana"]

    result = crosscheck_senders(senders, llm, done={})

    assert result == {"big@x.ch": "Achats", "small@x.ch": None}
    static, parts = llm.classify_batch.call_args.args
    assert static == llm_sender_static_prompt()
    assert parts[0] == "Expéditeur: Big <big@x.ch>\nSujets:\n- Facture"
    assert llm.classify_batch.call_args.kwargs == {"batch_size": 8}


def test_resume_skips_done_and_keeps_progress_on_failure(mocker):
    senders = {f"s{i}@x.ch": sender("", 10 - i) for i in range(4)}
    llm = mocker.MagicMock()
    llm.classify_batch.side_effect = [["1", "2"], RuntimeError("metal crash")]
    saved = []

    with pytest.raises(RuntimeError):
        crosscheck_senders(senders, llm, done={"s0@x.ch": "Santé"}, save_every=2, on_save=saved.append)

    assert saved == [
        {"s0@x.ch": "Santé", "s1@x.ch": "Banque & Placements", "s2@x.ch": "Assurances & Retraite"}
    ]
    assert llm.classify_batch.call_args_list[0].args[1][0].startswith("Expéditeur: s1@x.ch")


def test_nothing_to_do(mocker):
    llm = mocker.MagicMock()
    assert crosscheck_senders({"a@x.ch": sender("", 1)}, llm, done={"a@x.ch": None}) == {"a@x.ch": None}
    llm.classify_batch.assert_not_called()
