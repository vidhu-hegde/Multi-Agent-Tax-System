"""The shared LangGraph state, and the reducers that merge concurrent writes into it."""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.schemas import (
    DocumentRef,
    EscalationReason,
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
    """Order single-writer events by confirmation time before collapsing repeated values.

    A retry may replay an event whose unchanged value was previously suppressed.
    Its original timestamp must not let arrival order undo a later correction.
    """
    events = {}
    for answer in [*(left or []), *(right or [])]:
        key = (answer.field, answer.answered_at, answer.entered_by)
        if key in events:
            if events[key] != answer:
                raise ValueError(f"Conflicting answer event for {answer.field}")
            continue
        events[key] = answer
    merged = []
    latest = {}
    for answer in sorted(events.values(), key=lambda a: a.answered_at):
        previous = latest.get(answer.field)
        if previous is not None and previous.answered_at == answer.answered_at and previous.value != answer.value:
            raise ValueError(f"Conflicting answer confirmations for {answer.field}")
        if answer.field in latest and latest[answer.field].value == answer.value:
            continue
        merged.append(answer)
        latest[answer.field] = answer
    return merged


def merge_escalations(
    left: dict[str, EscalationTicket] | None, right: dict[str, EscalationTicket] | None
) -> dict[str, EscalationTicket]:
    """Resolve dominates open; identical retries are safe; contradictory identities/resolutions fail."""
    merged = dict(left or {})
    for ticket_id, ticket in (right or {}).items():
        existing = merged.get(ticket_id)
        if existing is not None:
            mutable = {"status", "resolution", "resolved_by", "resolved_at", "created_at"}
            if existing.model_dump(exclude=mutable) != ticket.model_dump(exclude=mutable):
                raise ValueError(f"Conflicting escalation identity for {ticket_id}")
            if existing.status != ticket.status:
                merged[ticket_id] = existing if existing.status == "resolved" else ticket
                continue
            if existing.resolution != ticket.resolution or existing.resolved_by != ticket.resolved_by:
                raise ValueError(f"Conflicting escalation resolution for {ticket_id}")
            ticket = min((existing, ticket), key=lambda t: (t.created_at, t.resolved_at or t.created_at))
        merged[ticket_id] = ticket
    return merged


class SilverFileState(TypedDict, total=False):
    case_path: str | None  # optional JSON case file with answers and documents

    # Intake
    messages: Annotated[list[AnyMessage], add_messages]
    input_token_usage: Annotated[dict[str, int], merge_dicts]  # actual provider input tokens per model call
    context_item: str  # synthetic current item for the isolated context benchmark
    context_reason: EscalationReason | None
    answers: Annotated[list[IntakeAnswer], merge_answers]  # single Intake writer; see current_answers()
    intake_complete: bool
    intake_revisit: str | None  # explicit one-field correction; existing orchestrator still owns routing
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
    """Latest confirmed answer per field, including checkpoints written before ordered merging."""
    latest: dict[str, IntakeAnswer] = {}
    for answer in merge_answers([], state.get("answers", [])):
        latest[answer.field] = answer
    return latest
