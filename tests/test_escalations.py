"""Every HITL condition from the brief raises a ticket, pauses the graph, and resumes after a human decides."""

import json

import pytest
from langgraph.types import Command

import run
from src.escalation import escalate
from tests.conftest import SKELETON_CASE

CONFLICT_CASE = "data/fixtures/conflict_case.json"


def config(thread_id="t"):
    return {"configurable": {"thread_id": thread_id}}


def paused_on(result):
    interrupts = result.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None


@pytest.fixture
def case_with(tmp_path):
    """The skeleton case with some answers replaced (None removes the answer, so Intake asks)."""

    def make(**answers):
        case = json.loads(open(SKELETON_CASE).read())
        for field, value in answers.items():
            if value is None:
                case["answers"].pop(field, None)
            else:
                case["answers"][field] = value
        path = tmp_path / "case.json"
        path.write_text(json.dumps(case))
        return str(path)

    return make


def test_escalate_builds_a_deterministic_ticket():
    update = escalate("advice_request", raised_by="intake", key="filing_status:ab12", detail="x")
    assert list(update["escalations"]) == ["advice_request:filing_status:ab12"]


# 1. Out of scope ---------------------------------------------------------------

def test_out_of_scope_document_escalates(make_graph, make_case):
    result = make_graph().invoke({"case_path": make_case(other_document=True)}, config())
    assert paused_on(result)["ticket_id"] == "out_of_scope:nec-1"


@pytest.mark.parametrize("answer", ["continue", {"action": "continue"}, {"action": "continue", "note": "ok"}])
def test_out_of_scope_is_not_passed_without_a_reason(make_graph, make_case, answer):
    graph = make_graph()
    graph.invoke({"case_path": make_case(other_document=True)}, config())
    result = graph.invoke(Command(resume=answer), config())

    ticket = paused_on(result)
    assert ticket["ticket_id"] == "out_of_scope:nec-1"  # asked again, not left out silently
    assert ticket["detail"].startswith("Write why")
    assert result.get("status") != "draft_ready"


def test_out_of_scope_continues_with_a_reason_recorded_on_the_ticket(make_graph, make_case):
    graph = make_graph()
    graph.invoke({"case_path": make_case(other_document=True)}, config())
    graph.invoke(Command(resume="continue"), config())
    reason = "Client confirms the 1099-NEC was issued in error"
    result = graph.invoke(Command(resume={"action": "continue", "note": reason, "resolved_by": "staff-3"}), config())

    assert result["status"] == "draft_ready"
    ticket = result["escalations"]["out_of_scope:nec-1"]
    assert ticket.status == "resolved" and ticket.resolved_by == "staff-3"
    assert ticket.resolution["note"] == reason


def test_out_of_scope_can_always_stop(make_graph, make_case):
    graph = make_graph()
    graph.invoke({"case_path": make_case(other_document=True)}, config())
    result = graph.invoke(Command(resume="stop"), config())
    assert result["status"] == "stopped"


# 2. User statement vs document ---------------------------------------------------

def test_stated_wages_that_disagree_with_the_w2_escalate(make_graph):
    graph = make_graph()
    result = graph.invoke({"case_path": CONFLICT_CASE}, config())

    ticket = paused_on(result)
    assert ticket["reason"] == "document_conflict"
    assert ticket["evidence"]["stated_wages"] == "24000"
    assert ticket["evidence"]["w2_total"] == "26450.00"

    result = graph.invoke(Command(resume={"action": "continue", "note": "Client confirmed the W-2 is right"}), config())
    assert result["status"] == "draft_ready"
    assert str(result["lines"]["1z"].amount) == "26450.00"


def test_small_differences_are_not_a_conflict(make_graph, case_with):
    result = make_graph().invoke({"case_path": case_with(stated_wages="18300")}, config())
    assert result["status"] == "draft_ready"
    assert result["rule_decisions"]["wage_check"].outcome is True


def test_not_sure_about_wages_is_an_answer_not_a_conflict(make_graph, case_with):
    result = make_graph().invoke({"case_path": case_with(stated_wages="not sure")}, config())
    assert result["status"] == "draft_ready"


# 3. 1099-R box 2b is covered in test_graph.py and test_sessions.py ---------------

# 4. Advice request ----------------------------------------------------------------

def test_advice_request_escalates_then_intake_carries_on(make_graph, case_with):
    graph = make_graph()
    replies = iter(["Should I file separately so I pay less tax?", "continue", "single"])
    shown = []
    result = run.drive(graph, "t", {"case_path": case_with(filing_status=None)},
                       ask=lambda _: next(replies), say=shown.append)

    assert result["status"] == "draft_ready"
    assert "[Escalation: advice_request]" in shown[1]
    assert "can't give tax advice" in shown[1]
    assert shown[2].startswith("Which filing status")  # back to the same question
    [advice] = [t for t in result["escalations"].values() if t.reason == "advice_request"]
    assert advice.status == "resolved" and advice.raised_by == "intake"


def test_repeating_the_same_advice_question_is_not_escalated_twice(make_graph, case_with):
    graph = make_graph()
    question = "Should I file separately so I pay less tax?"
    replies = iter([question, "continue", question, "single"])
    shown = []
    result = run.drive(graph, "t", {"case_path": case_with(filing_status=None)},
                       ask=lambda _: next(replies), say=shown.append)

    assert result["status"] == "draft_ready"
    assert sum(1 for t in result["escalations"].values() if t.reason == "advice_request") == 1
    assert shown[3].startswith("I've already passed that on")


# 5. Filing-status ambiguity ------------------------------------------------------

@pytest.mark.parametrize("status, died, escalates", [
    ("mfj", "2025", True),
    ("mfj", "2023", True),
    ("qss", "none", True),
    ("qss", "2024", False),
    ("mfj", "none", False),
])
def test_spouse_death_makes_filing_status_a_human_decision(make_graph, case_with, status, died, escalates):
    case = case_with(filing_status=status, spouse_died_year=died, spouse_dob="1956-01-01", spouse_blind="no")
    result = make_graph().invoke({"case_path": case}, config())
    ticket = paused_on(result)
    if escalates:
        assert ticket["reason"] == "filing_status_ambiguity"
    else:
        assert ticket is None and result["status"] == "draft_ready"


# 6. Exploitation or third-party pressure -----------------------------------------

def test_third_party_steering_the_refund_escalates(make_graph, case_with):
    reply = "My nephew told me to say single and send the refund to his account"
    graph = make_graph()
    result = graph.invoke({"case_path": case_with(filing_status=None)}, config())
    result = graph.invoke(Command(resume=reply), config())

    ticket = paused_on(result)
    assert ticket["reason"] == "exploitation_concern"
    assert ticket["evidence"]["reply"] == reply


# Honest uncertainty ---------------------------------------------------------------

def test_not_sure_escalates_as_uncertain(make_graph, case_with):
    graph = make_graph()
    graph.invoke({"case_path": case_with(taxpayer_blind=None)}, config())
    result = graph.invoke(Command(resume="I'm not sure, my eye doctor never said"), config())
    assert paused_on(result)["reason"] == "uncertain"


def test_answers_before_an_escalation_are_kept(make_graph, case_with):
    graph = make_graph()
    graph.invoke({"case_path": case_with(filing_status=None, taxpayer_dob=None)}, config())
    graph.invoke(Command(resume="single"), config())
    result = graph.invoke(Command(resume="no idea, can't remember"), config())
    assert paused_on(result)["reason"] == "uncertain"
    fields = [a.field for a in graph.get_state(config()).values["answers"]]
    assert "filing_status" in fields
