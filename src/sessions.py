"""Staff-side access to sessions: list them, inspect one, and resolve an escalation so the graph continues.

The dashboard calls only this module; it never touches the graph or the checkpointer directly.

    with open_sessions() as sessions:
        for s in sessions.list_sessions():                   # every session, newest first
            print(s.thread_id, s.status, [t.ticket_id for t in s.open_tickets])
        sessions.resolve(thread_id, ticket_id, action="continue", note="Checked with client", resolved_by="staff-7")
"""

import threading
from contextlib import contextmanager
from dataclasses import dataclass

from langgraph.types import Command

from src.agents.extraction import StaffEntryError, staff_entered_record
from src.agents.human import REASON_REQUIRED, has_written_reason
from src.config import Settings, load_settings
from src.memory import open_checkpointer
from src.schemas import EscalationTicket

STATUSES = ("in_progress", "waiting_on_taxpayer", "waiting_on_human", "draft_ready", "stopped")


class StaleEscalation(Exception):
    """The ticket is not what this session is waiting on (already resolved, or never raised)."""


@dataclass(frozen=True)
class SessionSummary:
    thread_id: str
    status: str  # one of STATUSES
    updated_at: str  # ISO timestamp of the latest checkpoint
    open_tickets: list[EscalationTicket]
    awaiting_ticket_id: str | None  # the ticket the graph is paused on right now
    pending_question: str | None  # what the taxpayer is being asked, when waiting on them


def _is_escalation(value) -> bool:
    return isinstance(value, dict) and "ticket_id" in value


class Sessions:
    def __init__(self, graph, checkpointer):
        self.graph = graph
        self.checkpointer = checkpointer
        self._lock = threading.Lock()  # one resolve at a time, so two staff can't resume the same pause

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def thread_ids(self) -> list[str]:
        """Every session id, most recently updated first."""
        latest: dict[str, str] = {}
        for checkpoint in self.checkpointer.list(None):
            thread_id = checkpoint.config["configurable"]["thread_id"]
            ts = checkpoint.checkpoint["ts"]
            if ts > latest.get(thread_id, ""):
                latest[thread_id] = ts
        return sorted(latest, key=latest.get, reverse=True)

    def state(self, thread_id: str) -> dict:
        """Full state of one session, for the detail view (lines, provenance, answers, escalations)."""
        return self.graph.get_state(self._config(thread_id)).values

    def summary(self, thread_id: str) -> SessionSummary:
        snapshot = self.graph.get_state(self._config(thread_id))
        values = snapshot.values
        pending = [i.value for i in snapshot.interrupts]
        escalation = next((v for v in pending if _is_escalation(v)), None)
        question = next((v for v in pending if not _is_escalation(v)), None)

        if escalation is not None:
            status = "waiting_on_human"
        elif question is not None:
            status = "waiting_on_taxpayer"
        else:
            status = values.get("status", "in_progress")

        return SessionSummary(
            thread_id=thread_id,
            status=status,
            updated_at=snapshot.created_at,
            open_tickets=[t for t in values.get("escalations", {}).values() if t.status == "open"],
            awaiting_ticket_id=escalation["ticket_id"] if escalation else None,
            pending_question=str(question) if question is not None else None,
        )

    def list_sessions(self, status: str | None = None) -> list[SessionSummary]:
        summaries = [self.summary(t) for t in self.thread_ids()]
        return [s for s in summaries if status is None or s.status == status]

    def open_escalations(self) -> list[tuple[str, EscalationTicket]]:
        """(thread_id, ticket) for every open ticket, across all sessions: the HITL queue."""
        return [(s.thread_id, t) for s in self.list_sessions() for t in s.open_tickets]

    def resolve(
        self, thread_id: str, ticket_id: str, action: str = "continue", note: str = "", resolved_by: str = "staff",
        choice: int | None = None, values: dict | None = None,
    ) -> SessionSummary:
        """Record a staff decision on the ticket the session is paused on, then let the graph continue.

        For a document that could not be read (evidence "needs_document_values"), continuing requires
        `values`: the fields typed from the document (see evidence "required_fields"). Continuing an
        out_of_scope ticket requires a written reason in `note`.

        Returns the new summary: the session may finish, pause on its next ticket, or wait on the taxpayer.
        """
        if action not in ("continue", "stop"):
            raise ValueError(f"action must be 'continue' or 'stop', not {action!r}")
        with self._lock:
            snapshot = self.graph.get_state(self._config(thread_id))
            paused_on = next(
                (i for i in snapshot.interrupts if _is_escalation(i.value) and i.value["ticket_id"] == ticket_id), None
            )
            if paused_on is None:
                raise StaleEscalation(f"Session {thread_id} is not waiting on ticket {ticket_id}.")
            evidence = paused_on.value.get("evidence", {})
            if evidence.get("state_write") and action == "continue":
                if type(choice) is not int or not 1 <= choice <= len(evidence["candidates"]):
                    raise ValueError("Select a conflicting record with choice (numbered from 1), or stop.")
            if paused_on.value.get("reason") in REASON_REQUIRED and action == "continue" and not has_written_reason(note):
                raise ValueError("This is out of scope: write why the session can continue (--note), or stop.")
            if evidence.get("needs_document_values") and action == "continue":
                if not isinstance(values, dict):
                    raise ValueError("Type the document's values (see required_fields), or stop.")
                try:
                    staff_entered_record(evidence["document_id"], evidence["form_type"], values, resolved_by)
                except StaffEntryError as exc:
                    raise ValueError(str(exc)) from None
            decision = {"action": action, "note": note, "resolved_by": resolved_by}
            if choice is not None:
                decision["choice"] = choice
            if values is not None:
                decision["values"] = values
            self.graph.invoke(Command(resume={paused_on.id: decision}), self._config(thread_id))
        return self.summary(thread_id)


@contextmanager
def open_sessions(settings: Settings | None = None, agents: dict | None = None):
    from src.graph import build_graph

    settings = settings or load_settings()
    with open_checkpointer(settings) as checkpointer:
        yield Sessions(build_graph(settings, checkpointer, agents=agents), checkpointer)
