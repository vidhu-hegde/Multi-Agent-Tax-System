"""End-to-end behaviour of the graph skeleton: routing, fan-out, review bound, loop guard, HITL, resume."""

import json
from decimal import Decimal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

import run
from src.agents.computation import computation
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


def test_1099r_box_2b_escalates_and_resolves(make_graph, tmp_path):
    case = json.loads(open(SKELETON_CASE).read())
    case["documents"][2]["values"]["taxable_not_determined"] = True
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps(case))

    graph = make_graph()
    result = graph.invoke({"case_path": str(case_path)}, config())
    assert pending_interrupt(result)["reason"] == "1099r_taxable_not_determined"
    assert result["status"] == "waiting_on_human"

    result = graph.invoke(Command(resume={"action": "continue", "note": "checked with client", "resolved_by": "staff-1"}), config())
    assert result["status"] == "draft_ready"
    ticket = result["escalations"]["1099r_taxable_not_determined:r-1"]
    assert ticket.resolved_by == "staff-1"


def test_interactive_intake_asks_one_question_at_a_time(make_graph):
    replies = iter(["widowed", "single", "1950-02-03", "no", "0", "250"])
    asked = []
    result = run.drive(make_graph(), "t", {}, ask=lambda _: next(replies), say=asked.append)

    assert result["status"] == "draft_ready"
    assert asked[1].startswith("Sorry, I didn't understand that.")
    assert all("?" in q and q.count("?") == 1 for q in asked)
    assert result["lines"]["26"].amount == Decimal("250")
    assert result["lines"]["26"].provenance[0].entered_by == "taxpayer"


def test_session_resumes_from_sqlite_after_restart(settings, make_graph, tmp_path):
    db = str(tmp_path / "silverfile.sqlite")
    with SqliteSaver.from_conn_string(db) as saver:
        graph = make_graph(checkpointer=saver)
        graph.invoke({}, config("resume"))
        graph.invoke(Command(resume="single"), config("resume"))

    with SqliteSaver.from_conn_string(db) as saver:  # a new process on Friday
        graph = make_graph(checkpointer=saver)
        waiting_on = graph.get_state(config("resume")).interrupts[0].value
        assert "date of birth" in waiting_on  # picks up at the next question, not the first
        replies = iter(["1950-02-03", "no", "0", "0"])
        result = run.drive(graph, "resume", None, ask=lambda _: next(replies), say=lambda _: None)

    assert result["status"] == "draft_ready"
    assert {a.field: a.value for a in result["answers"]}["filing_status"] == "single"
