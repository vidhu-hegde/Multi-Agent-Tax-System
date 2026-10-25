"""Parallel branches write to the same state keys; the merged result must not depend on arrival order."""

from itertools import permutations

import pytest

from src import state
from src.schemas import EscalationTicket, IntakeAnswer, Provenance, W2Record
from src.state import merge_dicts, merge_escalations


def test_merge_dicts_is_order_independent():
    writes = [{"w2-1": "a"}, {"int-1": "b"}, {"ssa-1": "c"}]
    results = set()
    for order in permutations(writes):
        merged = {}
        for write in order:
            merged = merge_dicts(merged, write)
        results.add(tuple(sorted(merged.items())))
    assert results == {(("int-1", "b"), ("ssa-1", "c"), ("w2-1", "a"))}


def test_resolved_ticket_is_never_reopened():
    open_ticket = EscalationTicket(ticket_id="t1", reason="uncertain", raised_by="rules", detail="x")
    resolved = open_ticket.model_copy(update={"status": "resolved", "resolution": {"action": "continue"}})
    for order in permutations([{"t1": open_ticket}, {"t1": resolved}]):
        merged = {}
        for write in order:
            merged = merge_escalations(merged, write)
        assert merged["t1"].status == "resolved"


def test_parallel_documents_survive_both_merge_orders():
    source = Provenance(kind="document", source="synthetic")
    a = W2Record(document_id="a", employer_name="A", wages="10", source=source)
    b = W2Record(document_id="b", employer_name="B", wages="20", source=source)
    for first, second in (({"a": a}, {"b": b}), ({"b": b}, {"a": a})):
        assert state.merge_documents(first, second) == {"a": a, "b": b}
    assert state.merge_documents({"a": a}, {"a": a}) == {"a": a}


def test_conflicting_document_keys_fail_in_both_orders():
    for left, right in (({"a": "old"}, {"a": "new"}), ({"a": "new"}, {"a": "old"})):
        with pytest.raises(ValueError, match="a"):
            state.merge_documents(left, right)


def test_answer_replay_is_idempotent_but_corrections_keep_history():
    original = IntakeAnswer(field="filing_status", value="single")
    correction = IntakeAnswer(field="filing_status", value="mfj")
    repeated = IntakeAnswer(field="filing_status", value="mfj")
    answers = state.merge_answers([original], [original, correction, repeated])
    assert [a.value for a in answers] == ["single", "mfj"]
    assert state.current_answers({"answers": answers})["filing_status"].value == "mfj"
    assert [a.value for a in state.merge_answers(answers, [original])] == ["single", "mfj"]


def test_same_answer_event_cannot_change_its_value():
    answer = IntakeAnswer(field="estimated_payments", value="10")
    with pytest.raises(ValueError, match="answer"):
        state.merge_answers([answer], [answer.model_copy(update={"value": "20"})])


def test_conflicting_escalation_identity_or_resolution_is_rejected_in_both_orders():
    first = EscalationTicket(ticket_id='same', reason='uncertain', raised_by='intake', detail='original')
    other = first.model_copy(update={'detail': 'different issue'})
    for left, right in ((first, other), (other, first)):
        with pytest.raises(ValueError, match='same'):
            merge_escalations({'same': left}, {'same': right})
    yes = first.model_copy(update={'status': 'resolved', 'resolution': {'action': 'continue'}})
    no = first.model_copy(update={'status': 'resolved', 'resolution': {'action': 'stop'}})
    for left, right in ((yes, no), (no, yes)):
        with pytest.raises(ValueError, match='same'):
            merge_escalations({'same': left}, {'same': right})
