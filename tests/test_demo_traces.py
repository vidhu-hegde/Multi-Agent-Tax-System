"""python -m evals.run_evals --trace writes the demo_* trace files for the two graded walkthroughs."""

import json

import pytest

from evals import run_evals

CASES = [
    ("eval-case-1-clean-run", "2455.50", "$2,455.50", False),
    ("eval-case-2-wage-conflict", "1460.25", "$1,460.25", True),
]


@pytest.mark.parametrize("case_id, refund, shown, paused", CASES, ids=[c[0] for c in CASES])
def test_trace_writes_state_draft_and_ticket(tmp_path, capsys, case_id, refund, shown, paused):
    assert run_evals.main(["--case", case_id, "--trace", str(tmp_path)]) == 0
    stem = f"demo_{case_id}"
    expected = {f"{stem}_state.json", f"{stem}_draft.html"} | ({f"{stem}_ticket.json"} if paused else set())
    assert {p.name for p in tmp_path.iterdir()} == expected

    state = json.loads((tmp_path / f"{stem}_state.json").read_text())
    assert "case_path" not in state  # a temporary path, meaningless outside the run
    assert state["status"] == "draft_ready" and state["review_status"] == "passed"
    assert state["lines"]["34"]["amount"] == refund  # line 34: amount overpaid (the refund)
    assert all(step["kind"] for line in state["lines"].values() for step in line["provenance"])
    assert shown in (tmp_path / f"{stem}_draft.html").read_text()

    if paused:
        tickets = json.loads((tmp_path / f"{stem}_ticket.json").read_text())
        assert [t["ticket_id"] for t in tickets] == ["document_conflict:wages"]
        assert state["escalations"]["document_conflict:wages"]["status"] == "resolved"
