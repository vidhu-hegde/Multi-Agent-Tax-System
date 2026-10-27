"""End-to-end behaviour of the graph skeleton: routing, fan-out, review bound, loop guard, HITL, resume."""

from decimal import Decimal

import pytest
from langgraph.types import Command

import run
from src.agents.computation import computation
from src.memory import open_checkpointer
from src.schemas import FORM_LINES
from tests.conftest import SKELETON_CASE


def config(thread_id="t"):
    return {"configurable": {"thread_id": thread_id}}


def pending_interrupt(result):
    interrupts = result.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None


def test_clean_case_produces_a_reviewed_draft(make_graph):
    result = make_graph().invoke({"case_path": SKELETON_CASE}, config())

    assert result["status"] == "draft_ready"
    assert result["review_status"] == "passed"
    assert set(result["lines"]) == set(FORM_LINES)
    assert all(line.provenance for line in result["lines"].values())
    assert result["lines"]["1z"].amount == Decimal("18000")
    assert result["lines"]["25d"].amount == Decimal("2100")


def test_extraction_fans_out_one_branch_per_document(make_graph):
    graph = make_graph()
    graph.invoke({"case_path": SKELETON_CASE}, config())
    fan_out_step = [s for s in graph.get_state_history(config()) if s.next and "extract_document" in s.next]
    assert len(fan_out_step[0].tasks) == 4
    assert set(graph.get_state(config()).values["documents"]) == {"w2-1", "int-1", "r-1", "ssa-1"}


def test_routing_order_is_driven_by_state(make_graph):
    result = make_graph().invoke({"case_path": SKELETON_CASE}, config())
    hops = [h.to_agent for h in result["handoffs"]]
    assert hops == ["intake", "extraction", "rules", "computation", "review", "end"]


def test_social_security_runs_after_other_income(make_graph):
    lines = make_graph().invoke({"case_path": SKELETON_CASE}, config())["lines"]
    order = list(lines)
    assert all(order.index(l) < order.index("6b") for l in ["1z", "2b", "3b", "4b", "5b", "10"])
    assert order.index("6b") < order.index("9") < order.index("11a")


def test_review_loop_is_bounded_then_escalates(make_graph, settings):
    def broken_computation(state):
        update = computation(state)
        bad = update["lines"]["6b"].model_copy(update={"amount": Decimal("999999")})
        update["lines"]["6b"] = bad
        return update

    graph = make_graph(agents={"computation": broken_computation})
    result = graph.invoke({"case_path": SKELETON_CASE}, config())

    ticket = pending_interrupt(result)
    assert ticket["reason"] == "review_limit"
    state = graph.get_state(config()).values
    assert state["review_passes"] == settings.max_review_passes

    result = graph.invoke(Command(resume="stop"), config())
    assert result["status"] == "stopped"


def test_loop_guard_breaks_a_pathological_cycle(make_graph, settings):
    def intake_that_never_finishes(state):
        return {}

    graph = make_graph(agents={"intake": intake_that_never_finishes})
    result = graph.invoke({"case_path": SKELETON_CASE}, config())

    ticket = pending_interrupt(result)
    assert ticket["reason"] == "loop_guard"
    hops = [h.to_agent for h in graph.get_state(config()).values["handoffs"]]
    assert hops == ["intake"] * settings.loop_guard_repeats + ["human"]


def test_orchestrator_counts_new_answers_as_progress(make_graph, settings):
    from src.schemas import IntakeAnswer

    def collecting_intake(state):
        count = len(state.get("answers", []))
        if count < settings.loop_guard_repeats + 2:
            return {"answers": [IntakeAnswer(field=f"field-{count}", value="confirmed")]}
        return {}  # no more progress: the guard must now trip

    graph = make_graph(agents={"intake": collecting_intake})
    result = graph.invoke({}, config())
    assert pending_interrupt(result)["reason"] == "loop_guard"
    assert len(result["answers"]) == settings.loop_guard_repeats + 2


def test_model_reasks_without_answers_cannot_reset_loop_guard(make_graph, settings):
    from importlib import import_module
    from langchain_core.messages import AIMessage

    class Provider:
        def invoke(self, messages):
            return AIMessage(
                content='{"reason":null}',
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    intake = import_module("src.agents.intake")
    graph = make_graph(agents={"intake": intake.make_intake(Provider())})
    graph.invoke({}, config())
    for _ in range(settings.loop_guard_repeats + 1):
        result = graph.invoke(Command(resume="unrelated reply"), config())
    assert pending_interrupt(result)["reason"] == "loop_guard"


def test_1099r_box_2b_escalates_and_resolves(make_graph, make_case):
    case_path = make_case(r1_2b=True)

    graph = make_graph()
    result = graph.invoke({"case_path": case_path}, config())
    assert pending_interrupt(result)["reason"] == "1099r_taxable_not_determined"
    assert result["status"] == "waiting_on_human"

    result = graph.invoke(
        Command(
            resume={
                "action": "continue",
                "note": "checked with client",
                "resolved_by": "staff-1",
                "corrections": {
                    "taxable_amount": "5500",
                },
            }
        ),
        config(),
    )

    assert result["status"] == "draft_ready"
    ticket = result["escalations"]["1099r_taxable_not_determined:r-1"]
    assert ticket.resolved_by == "staff-1"


def test_interactive_intake_asks_one_question_at_a_time(make_graph):
    replies = iter(["widowed", "single", "none", "1950-02-03", "no", "no", "no", "none", "0", "0", "0", "0", "0", "250"])
    asked = []
    result = run.drive(make_graph(), "t", {}, ask=lambda _: next(replies), say=asked.append)

    assert result["status"] == "draft_ready"
    assert asked[1].startswith("Sorry, I didn't understand that.")
    assert all("?" in q and q.count("?") == 1 for q in asked)
    assert result["lines"]["26"].amount == Decimal("250")
    assert result["lines"]["26"].provenance[0].entered_by == "taxpayer"


def test_session_resumes_from_sqlite_after_restart(settings, make_graph):
    with open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        graph.invoke({}, config("resume"))
        graph.invoke(Command(resume="single"), config("resume"))
        graph.invoke(Command(resume="none"), config("resume"))

    with open_checkpointer(settings) as saver:  # a new process on Friday
        graph = make_graph(checkpointer=saver)
        waiting_on = graph.get_state(config("resume")).interrupts[0].value
        assert waiting_on["type"] == "intake_question"
        assert waiting_on["field"] == "taxpayer_dob"
        assert "date of birth" in waiting_on["prompt"]
        assert "So far:" not in waiting_on
        replies = iter(["1950-02-03", "no", "no", "no", "none", "0", "0", "0", "0", "0", "0"])
        result = run.drive(graph, "resume", None, ask=lambda _: next(replies), say=lambda _: None)

    assert result["status"] == "draft_ready"
    assert {a.field: a.value for a in result["answers"]}["filing_status"] == "single"


def test_conflicting_reread_pauses_until_staff_select_a_document(settings, make_graph):
    from src.schemas import W2Record, Provenance

    first = W2Record(document_id="w2-reread", employer_name="Synthetic", wages="100", source=Provenance(kind="document", source="test"))
    second = first.model_copy(update={"wages": Decimal("200")})
    cfg = config("reread-conflict")
    with open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        result = graph.invoke({"case_path": SKELETON_CASE, "documents": {first.document_id: first}}, cfg)
        assert result["status"] == "draft_ready"
        result = graph.invoke({"documents": {second.document_id: second}}, cfg)
        ticket = pending_interrupt(result)
        assert ticket["reason"] == "document_conflict"

    with open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        result = graph.invoke(Command(resume="continue"), cfg)
        ticket = pending_interrupt(result)
        assert ticket["reason"] == "document_conflict"  # no silent winner
        candidates = ticket["evidence"]["candidates"]
        choice = next(i for i, record in enumerate(candidates, 1) if record["wages"] == "200")
        result = graph.invoke(Command(resume={"action": "continue", "choice": choice}), cfg)
        assert result["documents"][first.document_id].wages == Decimal("200")
        assert result["lines"]["1z"].amount == Decimal("18200")
        assert result["status"] == "draft_ready"


def test_conflicting_ticket_resolutions_pause_and_allow_stop(make_graph):
    from src.schemas import EscalationTicket

    first = EscalationTicket(ticket_id="same", reason="uncertain", raised_by="intake", detail="test", status="resolved", resolution={"action": "continue"})
    second = first.model_copy(update={"resolution": {"action": "stop"}})
    graph = make_graph()
    graph.invoke({"case_path": SKELETON_CASE, "escalations": {"same": first}}, config())
    result = graph.invoke({"escalations": {"same": second}}, config())
    ticket = pending_interrupt(result)
    assert ticket["reason"] == "uncertain"
    assert len(ticket["evidence"]["candidates"]) == 2
    result = graph.invoke(Command(resume="stop"), config())
    assert result["status"] == "stopped"


@pytest.mark.parametrize("count,schedule2", [("1", "0"), ("0", "120")])
def test_nonzero_interactive_intake_finishes_after_one_staff_approval(make_graph, count, schedule2):
    replies = ["single", "none", "1950-02-03", "no", "no", "no", "none", count, "0", schedule2, "0", "0", "0"]
    if count == "1":
        replies.extend(["Synthetic Child", "child", "901-12-3456"])
    replies.append("continue")
    replies = iter(replies)
    shown = []
    result = run.drive(make_graph(), "interactive-nonzero", {}, ask=lambda _: next(replies), say=shown.append)
    assert result["intake_complete"]
    assert result["status"] == "draft_ready"
    assert sum("[Escalation:" in prompt for prompt in shown) == 1
