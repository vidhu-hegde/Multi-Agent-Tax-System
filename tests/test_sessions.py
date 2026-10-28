"""The staff-side hook the dashboard uses: list sessions, see the HITL queue, resolve and continue."""

import pytest

import run
from src.sessions import StaleEscalation, open_sessions
from tests.conftest import SKELETON_CASE
from decimal import Decimal

from langgraph.types import Command


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
        summary = sessions.resolve(
            "s",
            "1099r_taxable_not_determined:r-1",
            note="Spoke to client",
            resolved_by="staff-7",
            corrections={
                "taxable_amount": "5500",
            },
        )
        ticket = sessions.state("s")["escalations"]["1099r_taxable_not_determined:r-1"]

    assert summary.status == "draft_ready"
    assert summary.open_tickets == []
    assert ticket.resolution == {
        "action": "continue",
        "note": "Spoke to client",
        "resolved_by": "staff-7",
        "corrections": {
            "taxable_amount": "5500",
        },
    }
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

        reason = "Client confirms the 1099-NEC was issued in error"  # out_of_scope needs one to continue
        second = sessions.resolve("s", first.awaiting_ticket_id, note=reason)
        assert second.status == "waiting_on_human"
        assert second.awaiting_ticket_id != first.awaiting_ticket_id

        done = sessions.resolve(
            "s",
            second.awaiting_ticket_id,
            corrections={
                "taxable_amount": "5500",
            },
        )
    assert done.status == "draft_ready"


def test_stale_or_unknown_tickets_are_rejected(settings, make_case):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("s"))
        with pytest.raises(StaleEscalation):
            sessions.resolve("s", "no-such-ticket")
        sessions.resolve(
            "s",
            "1099r_taxable_not_determined:r-1",
            corrections={
                "taxable_amount": "5500",
            },
        )
        with pytest.raises(StaleEscalation):
            sessions.resolve("s", "1099r_taxable_not_determined:r-1")  # a second staff member, too late
        with pytest.raises(ValueError):
            sessions.resolve("s", "anything", action="approve")


def test_dashboard_process_sees_sessions_started_elsewhere(settings, make_case):
    with open_sessions(settings) as taxpayer_side:
        taxpayer_side.graph.invoke({"case_path": make_case(r1_2b=True)}, config("s"))

    with open_sessions(settings) as dashboard:  # separate process, same SQLite file
        [(thread_id, ticket)] = dashboard.open_escalations()
        assert dashboard.resolve(
            thread_id,
            ticket.ticket_id,
            corrections={
                "taxable_amount": "5500",
            },
        ).status == "draft_ready"


def test_staff_cli_lists_and_resolves(settings, make_case, monkeypatch, capsys):
    monkeypatch.setenv("SILVERFILE_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(r1_2b=True)}, config("abc123"))

    run.main(["--sessions"])
    listing = capsys.readouterr().out
    assert "abc123" in listing and "waiting_on_human" in listing
    assert "* 1099r_taxable_not_determined:r-1" in listing

    run.main([
        "--resolve",
        "abc123",
        "1099r_taxable_not_determined:r-1",
        "--note",
        "ok",
        "--staff-id",
        "staff-7",
        "--taxable-amount",
        "5500",
    ])
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


def test_1099r_continue_requires_corrected_taxable_amount(
    settings,
    make_case,
):
    """Box 2b cannot be cleared by an unstructured continue decision."""

    thread_id = "1099r-required-correction"

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {"case_path": make_case(r1_2b=True)},
            config(thread_id),
        )

        ticket_id = sessions.summary(thread_id).awaiting_ticket_id
        assert (
            ticket_id
            == "1099r_taxable_not_determined:r-1"
        )

        with pytest.raises(
            ValueError,
            match="taxable amount",
        ):
            sessions.resolve(
                thread_id,
                ticket_id,
                action="continue",
                note="Reviewed with taxpayer",
                resolved_by="staff-7",
            )

        pending = sessions.summary(thread_id)

        assert pending.status == "waiting_on_human"
        assert pending.awaiting_ticket_id == ticket_id
        assert any(
            ticket.ticket_id == ticket_id
            for ticket in pending.open_tickets
        )


def test_1099r_correction_updates_document_and_recomputes_return(
    settings,
    make_case,
):
    """A valid correction must clear box 2b and flow into the reviewed draft."""

    thread_id = "1099r-corrected"
    ticket_id = "1099r_taxable_not_determined:r-1"

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {"case_path": make_case(r1_2b=True)},
            config(thread_id),
        )

        summary = sessions.resolve(
            thread_id,
            ticket_id,
            action="continue",
            note="Taxable amount confirmed from source document",
            resolved_by="staff-7",
            corrections={
                "taxable_amount": "5500",
            },
        )

        state = sessions.state(thread_id)
        record = state["documents"]["r-1"]
        ticket = state["escalations"][ticket_id]

    assert summary.status == "draft_ready"

    assert record.taxable_amount == Decimal("5500")
    assert record.taxable_not_determined is False

    # r-1 is marked as IRA/SEP/SIMPLE, so it feeds Form 1040-SR line 4b.
    assert state["lines"]["4b"].amount == Decimal("5500")
    assert state["review_status"] == "passed"

    assert ticket.status == "resolved"
    assert ticket.resolution["corrections"] == {
        "taxable_amount": "5500",
    }


def test_1099r_correction_cannot_exceed_gross_distribution(
    settings,
    make_case,
):
    """Box 2a cannot exceed the gross distribution in box 1."""

    thread_id = "1099r-invalid-correction"
    ticket_id = "1099r_taxable_not_determined:r-1"

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {
                "case_path": make_case(
                    r1_2b=True,
                ),
            },
            config(thread_id),
        )

        with pytest.raises(
            ValueError,
            match="gross distribution",
        ):
            sessions.resolve(
                thread_id,
                ticket_id,
                corrections={
                    "taxable_amount": "6001",
                },
            )

        state = sessions.state(thread_id)
        record = state["documents"]["r-1"]
        ticket = state["escalations"][ticket_id]

    assert record.taxable_amount == Decimal("6000")
    assert record.taxable_not_determined is True
    assert ticket.status == "open"


@pytest.mark.parametrize("recovery", ["continue", "stop"])
def test_1099r_invalid_correction_can_be_recovered(
    settings,
    make_case,
    recovery,
):
    """A rejected staff value must not poison the pending LangGraph interrupt."""

    thread_id = f"1099r-recover-{recovery}"
    ticket_id = "1099r_taxable_not_determined:r-1"

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {"case_path": make_case(name=thread_id, r1_2b=True)},
            config(thread_id),
        )

        with pytest.raises(ValueError, match="gross distribution"):
            sessions.resolve(
                thread_id,
                ticket_id,
                corrections={"taxable_amount": "6001"},
            )

        if recovery == "continue":
            summary = sessions.resolve(
                thread_id,
                ticket_id,
                corrections={"taxable_amount": "5500"},
            )
            assert summary.status == "draft_ready"
            assert sessions.state(thread_id)["documents"]["r-1"].taxable_amount == Decimal("5500")
        else:
            summary = sessions.resolve(thread_id, ticket_id, action="stop")
            assert summary.status == "stopped"


def test_direct_graph_invalid_1099r_resume_can_be_retried(
    settings,
    make_case,
):
    """The node re-interrupts instead of replaying a rejected direct resume forever."""

    thread_id = "1099r-direct-resume"
    ticket_id = "1099r_taxable_not_determined:r-1"
    thread_config = config(thread_id)

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {
                "case_path": make_case(
                    r1_2b=True,
                ),
            },
            thread_config,
        )

        snapshot = sessions.graph.get_state(
            thread_config
        )
        [pending_interrupt] = snapshot.interrupts

        sessions.graph.invoke(
            Command(
                resume={
                    pending_interrupt.id: {
                        "action": "continue",
                        "corrections": {"taxable_amount": "6001"},
                    },
                }
            ),
            thread_config,
        )

        [retry_interrupt] = sessions.graph.get_state(thread_config).interrupts
        assert "gross distribution" in retry_interrupt.value["detail"]

        result = sessions.graph.invoke(
            Command(
                resume={
                    retry_interrupt.id: {
                        "action": "continue",
                        "corrections": {"taxable_amount": "5500"},
                    },
                }
            ),
            thread_config,
        )

    assert result["status"] == "draft_ready"
    assert result["documents"]["r-1"].taxable_amount == Decimal("5500")
    assert result["escalations"][ticket_id].status == "resolved"


@pytest.mark.parametrize("note", ["", "continue", "  OK. "])
def test_out_of_scope_needs_a_written_reason_to_continue(settings, make_case, note):
    with open_sessions(settings) as sessions:
        sessions.graph.invoke({"case_path": make_case(other_document=True)}, config("s"))
        with pytest.raises(ValueError, match="out of scope"):
            sessions.resolve("s", "out_of_scope:nec-1", note=note)
        assert sessions.summary("s").awaiting_ticket_id == "out_of_scope:nec-1"  # nothing was recorded

        done = sessions.resolve("s", "out_of_scope:nec-1", note="Issued in error; client never did contract work")
    assert done.status == "draft_ready"
