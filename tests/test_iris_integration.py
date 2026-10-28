"""Iris's offline evidence over the merged graph, CLI driver and SQLite processes."""

import json
import os
import subprocess
import sys
from decimal import Decimal

from langgraph.types import Command

from src.memory import thread_config
from src.state import current_answers


def test_restart_correction_recomputes_and_preserves_audit_and_isolation(settings, tmp_path):
    case = json.loads(open("data/fixtures/skeleton_case.json").read())
    case["answers"].pop("estimated_payments")
    case_path = tmp_path / "resume-case.json"
    case_path.write_text(json.dumps(case))
    script = """
import json, sys
from run import drive
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
        'pending': [i.value for i in snapshot.interrupts],
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
    assert [a["value"] for a in finished["history"] if a["field"] == "adjustments"] == ["0", "100"]
    source = finished["lines"]["26"]["provenance"][0]
    answer = next(a for a in finished["history"] if a["field"] == "estimated_payments")
    assert source["entered_by"] == "taxpayer"
    assert source["recorded_at"] == answer["answered_at"]

    reopened = process("iris-return", {"intake_complete": False, "intake_revisit": "estimated_payments"}, ["3000"])
    assert reopened["status"] == "draft_ready" and reopened["review"] == "passed"
    assert reopened["lines"]["26"]["amount"] == "3000"
    assert Decimal(reopened["lines"]["33"]["amount"]) == Decimal("5100")
    assert reopened["archives"][-1]["lines"]["26"]["amount"] == "2000"
    assert [a["value"] for a in reopened["history"] if a["field"] == "estimated_payments"] == ["2000", "3000"]
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
