"""The one way an agent raises a human-in-the-loop escalation.

An agent returns escalate(...) (or merges it into its own update). The orchestrator sees the open ticket
and routes to the human node, which pauses the graph with interrupt() until staff resolve it.

    return escalate("advice_request", raised_by="intake", key="filing_status:3f2a",
                    detail="Asked whether filing separately would lower their tax.",
                    evidence={"reply": text})

`key` must identify this particular occurrence (a document id, a question and reply, ...). The ticket id is
"<reason>:<key>", and a resolved ticket is never reopened, so raising the same issue again is harmless.
"""

from typing import Any

from src.schemas import AgentName, EscalationReason, EscalationTicket


def ticket(
    reason: EscalationReason, *, raised_by: AgentName, key: str, detail: str, evidence: dict[str, Any] | None = None
) -> EscalationTicket:
    return EscalationTicket(
        ticket_id=f"{reason}:{key}", reason=reason, raised_by=raised_by, detail=detail, evidence=evidence or {}
    )


def escalate(
    reason: EscalationReason, *, raised_by: AgentName, key: str, detail: str, evidence: dict[str, Any] | None = None
) -> dict:
    """A state update that raises one ticket."""
    raised = ticket(reason, raised_by=raised_by, key=key, detail=detail, evidence=evidence)
    return {"escalations": {raised.ticket_id: raised}}
