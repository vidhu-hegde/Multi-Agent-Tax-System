"""Iris's offline evidence over the merged graph, CLI driver and SQLite processes."""

import json
import os
import subprocess
import sys
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from evals import run_evals
from src.memory import thread_config
from src.state import current_answers


def test_restart_correction_recomputes_and_preserves_audit_and_isolation(settings, tmp_path):
    case = json.loads(open("data/fixtures/skeleton_case.json").read())
    case["answers"].pop("estimated_payments")
    case_path = tmp_path / "resume-case.json"
    case_path.write_text(json.dumps(case))
    script = """
import json, sys
from run import drive, format_interrupt
from src.config import load_settings
from src.graph import build_graph
from src.memory import open_checkpointer, thread_config
from src.state import current_answers
thread, first, replies = sys.argv[1], json.loads(sys.argv[2]), iter(json.loads(sys.argv[3]))
shown = []
def ask(_):
    try:
        return next(replies)
    except StopIteration:
        raise EOFError
with open_checkpointer(load_settings()) as saver:
    graph = build_graph(load_settings(), saver)
    drive(graph, thread, first, ask=ask, say=shown.append)
    snapshot = graph.get_state(thread_config(thread))
    state = snapshot.values
    print(json.dumps({
        'shown': shown,
        'pending': [format_interrupt(i.value) for i in snapshot.interrupts],
        'status': state.get('status'),
        'review': state.get('review_status'),
        'answers': {k: str(v.value) for k, v in current_answers(state).items()},
        'history': [a.model_dump(mode='json') for a in state.get('answers', [])],
        'lines': {k: v.model_dump(mode='json') for k, v in state.get('lines', {}).items()},
        'archives': [s.model_dump(mode='json') for s in state.get('evidence_history', [])],
    }))
"""
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "SILVERFILE_DB_PATH": str(settings.db_path)}

    def process(thread, first, replies):
        result = subprocess.run(
            [sys.executable, "-c", script, thread, json.dumps(first), json.dumps(replies)],
            env=env, text=True, capture_output=True, check=True, timeout=30,
        )
        return json.loads(result.stdout)

    first = process("iris-return", {"case_path": str(case_path)}, [])
    assert "estimated tax" in first["pending"][0]
    assert "So far:" not in first["shown"][0]
    assert first["answers"]["adjustments"] == "0"
    assert len([a for a in first["history"] if a["field"] == "adjustments"]) == 1
    assert "w2-1" in first["answers"]["document_inventory"]

    finished = process("iris-return", None, [
        "I was walking my dog earlier", "go back to adjustments", "100", "2000",
    ])
    assert finished["status"] == "draft_ready" and finished["review"] == "passed"
    assert finished["pending"] == []
    assert finished["shown"][0].startswith("So far:")
    assert sum("So far:" in prompt for prompt in finished["shown"]) == 1
    assert "1957-05-01" not in "".join(finished["shown"])
    assert finished["lines"]["10"]["amount"] == "100"
    assert finished["lines"]["26"]["amount"] == "2000"
    assert Decimal(finished["lines"]["33"]["amount"]) == Decimal("4100")
    # Changing adjustments must propagate through the Social Security worksheet and tax,
    # not merely replace line 10 while leaving a stale reviewed draft behind.
    for line, amount in {"6b": "5690", "9": "30110", "11a": "30010", "15": "6260", "16": "626", "34": "3474"}.items():
        assert Decimal(finished["lines"][line]["amount"]) == Decimal(amount)
    assert [a["value"] for a in finished["history"] if a["field"] == "adjustments"] == ["0", "100"]
    source = finished["lines"]["26"]["provenance"][0]
    answer = next(a for a in finished["history"] if a["field"] == "estimated_payments")
    assert source["entered_by"] == "taxpayer"
    assert source["recorded_at"] == answer["answered_at"]

    reopened = process("iris-return", {"intake_complete": False, "intake_revisit": "estimated_payments"}, ["3000"])
    assert reopened["status"] == "draft_ready" and reopened["review"] == "passed"
    assert reopened["lines"]["26"]["amount"] == "3000"
    assert Decimal(reopened["lines"]["33"]["amount"]) == Decimal("5100")
    assert Decimal(reopened["lines"]["34"]["amount"]) == Decimal("4474")
    assert reopened["archives"][-1]["lines"]["26"]["amount"] == "2000"
    assert [a["value"] for a in reopened["history"] if a["field"] == "estimated_payments"] == ["2000", "3000"]
    corrected = reopened["lines"]["26"]["provenance"][0]
    assert corrected["source"] == "intake: estimated_payments"
    assert corrected["value"] == "3000" and corrected["entered_by"] == "taxpayer"
    corrected_answer = next(a for a in reversed(reopened["history"]) if a["field"] == "estimated_payments")
    assert corrected["recorded_at"] == corrected_answer["answered_at"]
    assert reopened["archives"][-1]["lines"]["26"]["provenance"][0] == source
    persisted = process("iris-return", None, [])
    assert persisted["history"] == reopened["history"]
    assert persisted["lines"] == reopened["lines"]

    other = process("iris-other-return", {}, [])
    assert other["answers"] == {} and other["lines"] == {}
    assert "Which filing status" in other["pending"][0]


def test_uncertainty_is_visible_to_staff_and_resumes_the_same_question(settings):
    from src.sessions import open_sessions

    config = thread_config("iris-volunteer")
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({}, config)
        sessions.graph.invoke(Command(resume="single"), config)
        sessions.graph.invoke(Command(resume="I'm not sure"), config)
        summary = sessions.summary("iris-volunteer")
        assert summary.status == "waiting_on_human"
        [(_, ticket)] = sessions.open_escalations()
        assert ticket.reason == "uncertain"
        assert "let me flag this for a volunteer" in ticket.evidence["said_to_taxpayer"]

    # A separate checkpointer/graph is what a staff process opens, not the old Python object.
    with open_sessions(settings) as sessions:
        summary = sessions.summary("iris-volunteer")
        resolved = sessions.resolve(
            "iris-volunteer", summary.awaiting_ticket_id,
            note="Volunteer clarified the question", resolved_by="iris-demo-volunteer",
        )
        assert resolved.status == "waiting_on_taxpayer"
        assert "spouse who died" in resolved.pending_question
        assert not sessions.open_escalations()
        state = sessions.state("iris-volunteer")
        assert current_answers(state)["filing_status"].value == "single"
        ticket = state["escalations"][summary.awaiting_ticket_id]
        assert ticket.resolved_by == "iris-demo-volunteer"
        assert ticket.resolution["note"] == "Volunteer clarified the question"
        sessions.graph.invoke(Command(resume="none"), config)
        assert "date of birth" in sessions.summary("iris-volunteer").pending_question
        assert current_answers(sessions.state("iris-volunteer"))["spouse_died_year"].value is None


@pytest.mark.parametrize("fault", ["lost_input", "unrelated_pause"])
@pytest.mark.parametrize("case", [
    case for case in run_evals.load_cases()
    if case["id"].startswith("iris-") and "escalation_evidence" in case["expect"]
], ids=lambda case: case["id"])
def test_readiness_evals_reject_lost_inputs_and_unrelated_pauses(settings, monkeypatch, case, fault):
    """The same generic uncertainty pause must not hide data loss or the wrong handoff."""
    from langgraph.types import Overwrite
    from src.agents.intake import intake
    from src.graph import build_graph
    from src.state import merge_answers

    assert run_evals.run_case(case).passed
    fields = case["expect"]["escalation_evidence"]["fields"]

    def broken_intake(state):
        update = intake(state)
        if any(t.evidence.get("fields") == fields for t in update.get("escalations", {}).values()):
            if fault == "lost_input":
                update["answers"] = Overwrite([
                    a for a in merge_answers(state.get("answers", []), update["answers"])
                    if a.field not in fields
                ])
            else:
                update["escalations"] = {
                    key: ticket.model_copy(update={"evidence": {"fields": ["unrelated"]}})
                    for key, ticket in update["escalations"].items()
                }
        return update

    monkeypatch.setattr(run_evals, "make_graph", lambda _: build_graph(
        settings, InMemorySaver(), agents={"intake": broken_intake},
    ))
    outcome = run_evals.run_case(case)
    assert not outcome.passed
    expected = "confirmed answer" if fault == "lost_input" else "pending escalation evidence"
    assert any(expected in problem for problem in outcome.problems)


@pytest.mark.parametrize("case", [
    case for case in run_evals.load_cases()
    if case["id"].startswith("iris-schedule")
], ids=lambda case: case["id"])
def test_schedule_evals_reject_zeroed_intake_totals(settings, monkeypatch, case):
    """A reviewed draft must not hide a lost nonzero Schedule input."""
    from langgraph.types import Overwrite
    from src.agents.intake import intake
    from src.graph import build_graph
    from src.state import merge_answers

    assert run_evals.run_case(case).passed
    [field] = case["answers"]

    def broken_intake(state):
        update = intake(state)
        if update.get("intake_complete"):
            update["answers"] = Overwrite([
                answer.model_copy(update={"value": "0"}) if answer.field == field else answer
                for answer in merge_answers(state.get("answers", []), update.get("answers", []))
            ])
        return update

    monkeypatch.setattr(run_evals, "make_graph", lambda _: build_graph(
        settings, InMemorySaver(), agents={"intake": broken_intake},
    ))
    outcome = run_evals.run_case(case)
    assert not outcome.passed
    assert outcome.status == "draft_ready"
    assert any("confirmed answer" in problem for problem in outcome.problems)
    assert any(problem.startswith("line ") for problem in outcome.problems)
