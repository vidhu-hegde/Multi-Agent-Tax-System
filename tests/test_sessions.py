"""The staff-side hook the dashboard uses: list sessions, see the HITL queue, resolve and continue."""

import pytest

import run
from src.sessions import StaleEscalation, open_sessions
from tests.conftest import SKELETON_CASE


def config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def test_lists_every_session_with_its_status(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": SKELETON_CASE}, config("done"))
        sessions.graph.invoke({}, config("asking"))
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("escalated"))

        assert sessions.thread_ids() == ["escalated", "asking", "done"]
        by_id = {s.thread_id: s for s in sessions.list_sessions()}

    assert by_id["done"].status == "draft_ready"
    assert by_id["asking"].status == "waiting_on_taxpayer"
    assert by_id["asking"].pending_question.startswith(
        "Which filing status"
    )
    assert "input_type" not in by_id["asking"].pending_question
    assert by_id["escalated"].status == "waiting_on_human"
    assert by_id["escalated"].awaiting_ticket_id == "1099r_taxable_not_determined:r-1"


def test_hitl_queue_lists_open_tickets_across_sessions(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": SKELETON_CASE}, config("done"))
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("escalated"))
        queue = sessions.open_escalations()

    assert [(thread, ticket.ticket_id) for thread, ticket in queue] == [
        ("escalated", "1099r_taxable_not_determined:r-1")
    ]


def test_resolve_records_the_decision_and_continues(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("s"))
        summary = sessions.resolve("s", "1099r_taxable_not_determined:r-1", note="Spoke to client", resolved_by="staff-7")
        ticket = sessions.state("s")["escalations"]["1099r_taxable_not_determined:r-1"]

    assert summary.status == "draft_ready"
    assert summary.open_tickets == []
    assert ticket.resolution == {"action": "continue", "note": "Spoke to client", "resolved_by": "staff-7"}
    assert ticket.resolved_by == "staff-7"


def test_resolve_with_stop_ends_the_session(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("s"))
        summary = sessions.resolve("s", "1099r_taxable_not_determined:r-1", action="stop")
    assert summary.status == "stopped"


def test_tickets_are_resolved_one_at_a_time(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True, other_document=True)}, config("s"))
        first = sessions.summary("s")
        assert len(first.open_tickets) == 2

        second = sessions.resolve("s", first.awaiting_ticket_id)
        assert second.status == "waiting_on_human"
        assert second.awaiting_ticket_id != first.awaiting_ticket_id

        done = sessions.resolve("s", second.awaiting_ticket_id)
    assert done.status == "draft_ready"


def test_stale_or_unknown_tickets_are_rejected(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("s"))
        with pytest.raises(StaleEscalation):
            sessions.resolve("s", "no-such-ticket")
        sessions.resolve("s", "1099r_taxable_not_determined:r-1")
        with pytest.raises(StaleEscalation):
            sessions.resolve("s", "1099r_taxable_not_determined:r-1")  # a second staff member, too late
        with pytest.raises(ValueError):
            sessions.resolve("s", "anything", action="approve")


def test_dashboard_process_sees_sessions_started_elsewhere(settings, make_case):
    with open_sessions(settings) as taxpayer_side:
        taxpayer_side.graph.invoke({"case_path": make_case(r1_2b=True)}, config("s"))

    with open_sessions(settings) as dashboard:  # separate process, same SQLite file
        [(thread_id, ticket)] = dashboard.open_escalations()
        assert dashboard.resolve(thread_id, ticket.ticket_id).status == "draft_ready"


def test_staff_cli_lists_and_resolves(settings, make_case, monkeypatch, capsys):
    monkeypatch.setenv("SILVERFILE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("abc123"))

    run.main(["--sessions"])
    listing = capsys.readouterr().out
    assert "abc123" in listing and "waiting_on_human" in listing
    assert "* 1099r_taxable_not_determined:r-1" in listing

    run.main(["--resolve", "abc123", "1099r_taxable_not_determined:r-1", "--note", "ok", "--staff-id", "staff-7"])
    assert "draft_ready" in capsys.readouterr().out


@pytest.mark.parametrize("action", ["continue", "stop"])
def test_staff_selects_a_conflicting_ticket_resolution(settings, action):
    from src.schemas import EscalationTicket

    first = EscalationTicket(
        ticket_id="conflicted", reason="uncertain", raised_by="intake", detail="Synthetic issue",
        status="resolved", resolution={"action": "continue"},
    )
    second = first.model_copy(update={"resolution": {"action": "stop"}})
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": SKELETON_CASE, "escalations": {"conflicted": first}}, config("conflict"))
        sessions.graph.invoke({"escalations": {"conflicted": second}}, config("conflict"))
        pending = sessions.summary("conflict")
        ticket_id = pending.awaiting_ticket_id
        with pytest.raises(ValueError, match="choice"):
            sessions.resolve("conflict", ticket_id)
        candidates = pending.open_tickets[0].evidence["candidates"]
        choice = next(i for i, candidate in enumerate(candidates, 1) if candidate["resolution"]["action"] == action)
        summary = sessions.resolve("conflict", ticket_id, choice=choice)
        assert summary.status == ("draft_ready" if action == "continue" else "stopped")
        assert sessions.state("conflict")["escalations"]["conflicted"].resolution["action"] == action
