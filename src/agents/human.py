"""Human-in-the-loop node. Pauses the graph with interrupt() once per open escalation ticket.

Resume with Command(resume=...) where the value is either a string ("stop", or any note meaning
continue) or a dict {"action": "continue" | "stop", "note": str, "resolved_by": str}. The dashboard
will send the dict form.
"""

from datetime import datetime, timezone

from langgraph.types import interrupt

from src.state import SilverFileState


def normalize_resolution(answer) -> dict:
    if isinstance(answer, dict):
        return {"action": "continue", **answer}
    text = str(answer).strip()
    return {"action": "stop" if text.lower() == "stop" else "continue", "note": text}


def human(state: SilverFileState) -> dict:
    open_tickets = sorted(
        (t for t in state.get("escalations", {}).values() if t.status == "open"), key=lambda t: t.created_at
    )
    update: dict = {"last_agent": "human"}
    resolved = {}
    for ticket in open_tickets:
        answer = interrupt({
            "ticket_id": ticket.ticket_id,
            "reason": ticket.reason,
            "detail": ticket.detail,
            "evidence": ticket.evidence,
            "how_to_resolve": "Reply 'continue' (with an optional note) to carry on, or 'stop' to end the session.",
        })
        resolution = normalize_resolution(answer)
        resolved[ticket.ticket_id] = ticket.model_copy(update={
            "status": "resolved",
            "resolution": resolution,
            "resolved_by": resolution.get("resolved_by", "staff"),
            "resolved_at": datetime.now(timezone.utc),
        })
        if ticket.reason == "review_limit":
            update["review_passes"] = 0
        if ticket.reason == "loop_guard":
            update["guard_window_start"] = len(state.get("handoffs", []))
    update["escalations"] = resolved
    return update
