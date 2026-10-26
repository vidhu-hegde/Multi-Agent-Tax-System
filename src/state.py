"""The shared LangGraph state, and the reducers that merge concurrent writes into it."""

import json
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
    StateWriteConflict,
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
            value = conflicting_writes(merged[key], value)
        merged[key] = value
    return merged


def conflicting_writes(left, right) -> StateWriteConflict:
    candidates = {}
    for value in (left, right):
        for record in value.candidates if isinstance(value, StateWriteConflict) else [value]:
            candidates[json.dumps(record.model_dump(mode="json"), sort_keys=True)] = record
    return StateWriteConflict(candidates=[candidates[key] for key in sorted(candidates)])


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


def merge_escalations(left: dict | None, right: dict | None) -> dict:
    """Resolve dominates open retries; preserve contradictory writes for staff review."""
    merged = dict(left or {})
    for ticket_id, ticket in (right or {}).items():
        existing = merged.get(ticket_id)
        if existing is not None:
            if isinstance(existing, StateWriteConflict) or isinstance(ticket, StateWriteConflict):
                merged[ticket_id] = conflicting_writes(existing, ticket)
                continue
            mutable = {"status", "resolution", "resolved_by", "resolved_at", "created_at"}
            if existing.model_dump(exclude=mutable) != ticket.model_dump(exclude=mutable):
                merged[ticket_id] = conflicting_writes(existing, ticket)
                continue
            if existing.status != ticket.status:
                merged[ticket_id] = existing if existing.status == "resolved" else ticket
                continue
            if existing.resolution != ticket.resolution or existing.resolved_by != ticket.resolved_by:
                merged[ticket_id] = conflicting_writes(existing, ticket)
                continue
            ticket = min((existing, ticket), key=lambda t: (t.created_at, t.resolved_at or t.created_at))
        merged[ticket_id] = ticket
    return merged


class SilverFileState(TypedDict, total=False):
    case_path: str | None  # optional JSON case file with answers and documents

    # Intake
    messages: Annotated[list[AnyMessage], add_messages]
    input_token_usage: Annotated[dict[str, int], merge_dicts]  # actual provider input tokens per model call
    answers: Annotated[list[IntakeAnswer], merge_answers]  # single Intake writer; see current_answers()
    intake_complete: bool
    intake_revisit: str | None  # explicit one-field correction; existing orchestrator still owns routing
    document_inventory: list[DocumentRef]

    # Work products
    documents: Annotated[dict[str, TaxDocument | StateWriteConflict], merge_documents]
    rule_decisions: Annotated[dict[str, RuleDecision], merge_dicts]
    lines: Annotated[dict[str, LineValue], merge_dicts]

    # Review loop
    revision_requests: list[RevisionRequest]
    review_status: Literal["pending", "failed", "passed"]
    review_passes: int

    # Escalation and control
    escalations: Annotated[dict[str, EscalationTicket | StateWriteConflict], merge_escalations]
    handoffs: Annotated[list[Handoff], operator.add]
    guard_window_start: int  # loop guard only looks at handoffs after this index
    guard_answer_count: int  # orchestrator's count of confirmed answers at the last progress reset
    last_agent: str
    next_agent: str
    status: Literal["in_progress", "waiting_on_human", "draft_ready", "stopped"]


def current_answers(state: SilverFileState) -> dict[str, IntakeAnswer]:
    """Latest confirmed answer per field, including checkpoints written before ordered merging."""
    latest: dict[str, IntakeAnswer] = {}
    for answer in merge_answers([], state.get("answers", [])):
        latest[answer.field] = answer
    return latest
