"""A document that can't be read is never left out: staff type its values in, or stop the session."""

import json
from decimal import Decimal

import pytest
from langgraph.types import Command

import run
from src.agents.extraction import RECORD_TYPES, STAFF_ENTRY_FIELDS, StaffEntryError, staff_entered_record
from src.sessions import open_sessions
from tests.conftest import SKELETON_CASE

W2_VALUES = {
    "employer_name": "Finger Lakes Hardware Co.", "wages": "18000.00", "federal_withheld": "1500.00",
    "medicare_wages": "18000.00", "allocated_tips": None, "dependent_care_benefits": None, "box12": [],
    "statutory_employee": False,
}


def config(thread_id="t"):
    return {"configurable": {"thread_id": thread_id}}


def paused_on(result):
    interrupts = result.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None


@pytest.fixture
def image_only_case(tmp_path):
    """The skeleton case, but the W-2 is an image with no typed values (and no API key to read it)."""
    case = json.loads(open(SKELETON_CASE).read())
    case["documents"][0] = {"document_id": "w2-1", "form_type": "W-2", "image_path": "demo/w2_image_1.jpg"}
    path = tmp_path / "case.json"
    path.write_text(json.dumps(case))
    return str(path)


def test_unreadable_w2_asks_staff_for_its_values(make_graph, image_only_case):
    ticket = paused_on(make_graph().invoke({"case_path": image_only_case}, config()))
    assert ticket["evidence"]["needs_document_values"] is True
    assert ticket["evidence"]["required_fields"] == list(W2_VALUES)
    assert '"values"' in ticket["how_to_resolve"]


def test_plain_continue_does_not_leave_the_document_out(make_graph, image_only_case):
    graph = make_graph()
    graph.invoke({"case_path": image_only_case}, config())
    result = graph.invoke(Command(resume="continue"), config())

    assert paused_on(result)["detail"].startswith("Type the document's values")
    assert result["status"] == "waiting_on_human"
    assert "1z" not in result.get("lines", {})


def test_staff_typed_values_become_a_sourced_record(make_graph, image_only_case):
    graph = make_graph()
    graph.invoke({"case_path": image_only_case}, config())
    result = graph.invoke(Command(resume={"action": "continue", "values": W2_VALUES, "resolved_by": "staff-7"}), config())

    assert result["status"] == "draft_ready"
    assert result["lines"]["1z"].amount == Decimal("18000.00")
    source = result["documents"]["w2-1"].source
    assert source.kind == "user_input" and source.source.startswith("direct user input")
    assert source.entered_by == "staff-7" and source.recorded_at is not None
    [ticket] = [t for t in result["escalations"].values() if t.evidence.get("needs_document_values")]
    assert "values" not in ticket.resolution  # the record holds them; the ticket doesn't duplicate them
    assert ticket.resolution["entered_document"] == "w2-1"


def test_invalid_values_are_asked_again_without_echoing_them(make_graph, image_only_case):
    graph = make_graph()
    graph.invoke({"case_path": image_only_case}, config())
    result = graph.invoke(Command(resume={"action": "continue", "values": {**W2_VALUES, "wages": "lots"}}), config())

    detail = paused_on(result)["detail"]
    assert "wages" in detail and "lots" not in detail
    assert result["status"] == "waiting_on_human"


def test_stop_ends_the_session(make_graph, image_only_case):
    graph = make_graph()
    graph.invoke({"case_path": image_only_case}, config())
    assert graph.invoke(Command(resume="stop"), config())["status"] == "stopped"


def test_dashboard_resolve_requires_valid_values(settings, image_only_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": image_only_case}, config("s"))
        [(_, ticket)] = sessions.open_escalations()

        with pytest.raises(ValueError, match="Type the document's values"):
            sessions.resolve("s", ticket.ticket_id)
        with pytest.raises(ValueError, match="wages"):
            sessions.resolve("s", ticket.ticket_id, values={**W2_VALUES, "wages": "lots"})
        summary = sessions.resolve("s", ticket.ticket_id, values=W2_VALUES, resolved_by="staff-7")

    assert summary.status == "draft_ready"


def test_staff_cli_accepts_values(settings, image_only_case, monkeypatch, capsys):
    monkeypatch.setenv("SILVERFILE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": image_only_case}, config("abc"))
        [(_, ticket)] = sessions.open_escalations()

    run.main(["--resolve", "abc", ticket.ticket_id, "--values", json.dumps(W2_VALUES), "--staff-id", "staff-7"])
    assert "draft_ready" in capsys.readouterr().out


def test_every_form_has_an_explicit_staff_entry_list():
    assert set(STAFF_ENTRY_FIELDS) == set(RECORD_TYPES)
    for form_type, names in STAFF_ENTRY_FIELDS.items():
        assert set(names) <= set(RECORD_TYPES[form_type].model_fields), form_type


def test_an_omitted_field_is_rejected_not_treated_as_zero():
    values = {k: v for k, v in W2_VALUES.items() if k != "federal_withheld"}
    with pytest.raises(StaffEntryError, match="Missing values for: federal_withheld"):
        staff_entered_record("w2-1", "W-2", values, "staff-7")


def test_an_explicit_zero_is_accepted():
    record = staff_entered_record("w2-1", "W-2", {**W2_VALUES, "federal_withheld": "0"}, "staff-7")
    assert record.federal_withheld == Decimal("0")


def test_staff_missing_a_field_is_asked_again(make_graph, image_only_case):
    graph = make_graph()
    graph.invoke({"case_path": image_only_case}, config())
    values = {k: v for k, v in W2_VALUES.items() if k != "federal_withheld"}
    result = graph.invoke(Command(resume={"action": "continue", "values": values}), config())

    assert "federal_withheld" in paused_on(result)["detail"]
    assert result["status"] == "waiting_on_human"


def test_staff_entered_document_is_marked_ready_so_the_draft_page_shows(make_graph, image_only_case):
    from src.render import render_draft

    graph = make_graph()
    graph.invoke({"case_path": image_only_case}, config())
    result = graph.invoke(Command(resume={"action": "continue", "values": W2_VALUES}), config())

    assert result["document_readiness"]["w2-1"] is True
    assert "Sources and calculation" in render_draft(result)


def test_staff_cli_marks_a_finished_return_submitted(settings, monkeypatch, capsys):
    from tests.conftest import SKELETON_CASE

    monkeypatch.setenv("SILVERFILE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # submitting needs neither the model nor the tax math
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": SKELETON_CASE}, config("done"))

    run.main(["--submit", "done", "--staff-id", "staff-7"])
    assert "submitted" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="already submitted by staff-7"):
        run.main(["--submit", "done", "--staff-id", "staff-8"])
