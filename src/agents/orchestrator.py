"""Orchestrator. Decides which agent acts next and owns termination.

It never extracts, computes or talks to the user: it only reads state and applies the routing table
in decide() (documented in docs/IMPLEMENTATION_NOTES.md). It also enforces the two loop bounds:
the review -> revise limit and the loop guard on repeated identical handoffs.
"""

import hashlib
import json

from langgraph.types import Overwrite

from src.config import Settings
from src.schemas import DocumentRef, EscalationTicket, Handoff, StateWriteConflict
from src.state import SilverFileState


def pending_documents(state: SilverFileState) -> list[DocumentRef]:
    """In-scope documents without a record yet.

    A document that cannot be read is not skipped: its ticket stays open until staff type the values in
    (which creates the record) or stop the session. So a draft is never produced with a document missing.
    """
    documents = state.get("documents", {})
    return [
        ref
        for ref in state.get("document_inventory", [])
        if ref.form_type != "other" and ref.document_id not in documents
    ]


def decide(state: SilverFileState, settings: Settings) -> tuple[str, str, list[EscalationTicket]]:
    """The routing table: (next agent, reason, new tickets). First matching row wins."""
    escalations = state.get("escalations", {})
    open_tickets = [t for t in escalations.values() if t.status == "open"]
    if open_tickets:
        return "human", f"escalation {open_tickets[0].ticket_id}", []
    if any((t.resolution or {}).get("action") == "stop" for t in escalations.values()):
        return "end", "stopped by a human", []
    if not state.get("intake_complete"):
        return "intake", "intake incomplete", []
    pending = pending_documents(state)
    if pending:
        return "extraction", f"{len(pending)} document(s) to extract", []
    if "scope" not in state.get("rule_decisions", {}):
        return "rules", "rules not evaluated", []

    requests = state.get("revision_requests") or []
    if requests:
        passes = state.get("review_passes", 0)
        if passes >= settings.max_review_passes:
            count = sum(1 for t in escalations.values() if t.reason == "review_limit")
            ticket = EscalationTicket(
                ticket_id=f"review_limit:{count + 1}", reason="review_limit", raised_by="orchestrator",
                detail=f"Review still finds problems after {passes} passes.",
                evidence={"open_requests": [r.model_dump(mode="json") for r in requests]},
            )
            return "human", "review limit reached", [ticket]
        first = requests[0]
        return first.target, f"revision: line {first.line or '-'}: {first.reason}", []

    if not state.get("lines"):
        return "computation", "lines not computed", []
    if state.get("review_status") != "passed":
        return "review", "draft not reviewed", []
    return "end", "draft ready", []


def loop_guard(state: SilverFileState, handoff: Handoff, settings: Settings) -> EscalationTicket | None:
    """Trip when this exact handoff (from, to, reason) already happened N times since the last reset."""
    history = state.get("handoffs", [])
    window = history[state.get("guard_window_start", 0):]
    repeats = sum(1 for h in window if h == handoff)
    if repeats < settings.loop_guard_repeats:
        return None
    return EscalationTicket(
        ticket_id=f"loop_guard:{len(history)}", reason="loop_guard", raised_by="orchestrator",
        detail=f"{handoff.from_agent} -> {handoff.to_agent} ({handoff.reason}) repeated {repeats} times without progress.",
        evidence={"handoff": handoff.model_dump()},
    )


def make_orchestrator(settings: Settings):
    def orchestrator(state: SilverFileState) -> dict:
        escalations = dict(state.get("escalations", {}))
        conflicts = False
        for channel in ("documents", "escalations"):
            for key, value in state.get(channel, {}).items():
                if not isinstance(value, StateWriteConflict):
                    continue
                conflicts = True
                if channel == "escalations":
                    del escalations[key]
                candidates = [record.model_dump(mode="json") for record in value.candidates]
                fingerprint = hashlib.sha256(json.dumps(candidates, sort_keys=True).encode()).hexdigest()[:12]
                conflict_reason = "document_conflict" if channel == "documents" else "uncertain"
                ticket_id = f"{conflict_reason}:state-write:{channel}:{key}:{fingerprint}"
                if ticket_id not in escalations:
                    escalations[ticket_id] = EscalationTicket(
                        ticket_id=ticket_id,
                        reason=conflict_reason,
                        raised_by="orchestrator",
                        detail=f"Conflicting writes for {channel} / {key}. Staff must select a record before continuing.",
                        evidence={"state_write": channel, "key": key, "candidates": candidates},
                    )
        if conflicts:
            state = {**state, "escalations": escalations}
        progress = {}
        answer_count = len(state.get("answers", []))
        if answer_count > state.get("guard_answer_count", 0):
            progress = {"guard_window_start": len(state.get("handoffs", [])), "guard_answer_count": answer_count}
            state = {**state, **progress}
        next_agent, reason, tickets = decide(state, settings)
        handoff = Handoff(from_agent=state.get("last_agent", "start"), to_agent=next_agent, reason=reason)
        if next_agent not in ("human", "end"):
            tripped = loop_guard(state, handoff, settings)
            if tripped:
                tickets = [tripped]
                next_agent = "human"
                handoff = Handoff(from_agent=handoff.from_agent, to_agent="human", reason="loop guard")

        if next_agent == "human":
            status = "waiting_on_human"
        elif next_agent == "end":
            status = "stopped" if reason == "stopped by a human" else "draft_ready"
        else:
            status = "in_progress"
        return {
            **progress,
            "next_agent": next_agent,
            "handoffs": [handoff],
            "escalations": (
                Overwrite({**escalations, **{t.ticket_id: t for t in tickets}})
                if conflicts else {t.ticket_id: t for t in tickets}
            ),
            "status": status,
        }

    return orchestrator
