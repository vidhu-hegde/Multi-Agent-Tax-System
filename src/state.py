"""The shared LangGraph state, and the reducers that merge concurrent writes into it."""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.schemas import (
    DocumentRef,
    EscalationTicket,
    Handoff,
    IntakeAnswer,
    LineValue,
    RevisionRequest,
    RuleDecision,
    TaxDocument,
)


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """Replace keyed, sequential work products during revision. Collisions are order-dependent."""
    return {**(left or {}), **(right or {})}


def merge_documents(left: dict | None, right: dict | None) -> dict:
    """Merge independent extraction writes; identical retries are safe, conflicts must be resolved."""
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key in merged and merged[key] != value:
            raise ValueError(f"Conflicting document writes for {key}; resolve before replacing the record")
        merged[key] = value
    return merged


def merge_answers(left: list[IntakeAnswer] | None, right: list[IntakeAnswer] | None) -> list[IntakeAnswer]:
    """Single-writer answer history: deduplicate replayed events and repeated effective values."""
    merged = list(left or [])
    events = {(a.field, a.answered_at, a.entered_by): a for a in merged}
    latest = {a.field: a for a in merged}
    for answer in right or []:
        key = (answer.field, answer.answered_at, answer.entered_by)
        if key in events:
            if events[key] != answer:
                raise ValueError(f"Conflicting answer event for {answer.field}")
            continue
        events[key] = answer
        if answer.field in latest and latest[answer.field].value == answer.value:
            continue
        merged.append(answer)
        latest[answer.field] = answer
    return merged


def merge_escalations(
    left: dict[str, EscalationTicket] | None, right: dict[str, EscalationTicket] | None
) -> dict[str, EscalationTicket]:
    """Keyed merge that never reopens a resolved ticket, so an agent re-raising the same issue is harmless."""
    merged = dict(left or {})
    for ticket_id, ticket in (right or {}).items():
        existing = merged.get(ticket_id)
        if existing is not None and existing.status == "resolved" and ticket.status == "open":
            continue
        merged[ticket_id] = ticket
    return merged


class SilverFileState(TypedDict, total=False):
    case_path: str | None  # optional JSON case file with answers and documents

    # Intake
    messages: Annotated[list[AnyMessage], add_messages]
    answers: Annotated[list[IntakeAnswer], merge_answers]  # single Intake writer; see current_answers()
    intake_complete: bool
    document_inventory: list[DocumentRef]

    # Work products
    documents: Annotated[dict[str, TaxDocument], merge_documents]  # independent parallel extraction writes
    rule_decisions: Annotated[dict[str, RuleDecision], merge_dicts]
    lines: Annotated[dict[str, LineValue], merge_dicts]

    # Review loop
    revision_requests: list[RevisionRequest]
    review_status: Literal["pending", "failed", "passed"]
    review_passes: int

    # Escalation and control
    escalations: Annotated[dict[str, EscalationTicket], merge_escalations]
    handoffs: Annotated[list[Handoff], operator.add]
    guard_window_start: int  # loop guard only looks at handoffs after this index
    last_agent: str
    next_agent: str
    status: Literal["in_progress", "waiting_on_human", "draft_ready", "stopped"]


def current_answers(state: SilverFileState) -> dict[str, IntakeAnswer]:
    """Latest answer per field. Earlier answers stay in state["answers"] as history."""
    latest: dict[str, IntakeAnswer] = {}
    for answer in state.get("answers", []):
        latest[answer.field] = answer
    return latest
