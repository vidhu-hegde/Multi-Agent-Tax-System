"""Parallel branches write to the same state keys; the merged result must not depend on arrival order."""

from itertools import permutations

from src.schemas import EscalationTicket
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
