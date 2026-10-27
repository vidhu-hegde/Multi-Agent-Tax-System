"""Validate agent writes before LangGraph merges them. Existing shared contracts remain authoritative."""
from functools import wraps
from typing import Annotated, Literal
from pydantic import Field, StrictBool

from langgraph.types import Overwrite
from pydantic import TypeAdapter, ValidationError

from src.schemas import (DocumentRef, EvidenceSnapshot, EscalationTicket, Handoff, IntakeAnswer, LineValue,
                         RevisionRequest, RuleDecision, StateWriteConflict, TaxDocument)

COMMON = {"last_agent", "escalations"}
ALLOWED_OUTPUTS = {
    "intake": COMMON | {"answers", "messages", "input_token_usage", "intake_complete", "intake_revisit",
                         "document_inventory", "revision_requests", "review_status", "review_passes", "status",
                         "documents", "lines", "rule_decisions", "evidence_epoch", "evidence_history", "computed_evidence_fingerprint"},
    "extraction": {"documents", "escalations", "document_readiness"},
    "aggregate_documents": {"last_agent", "evidence_history", "evidence_epoch", "lines", "rule_decisions", "review_status", "review_passes", "revision_requests", "computed_evidence_fingerprint"},
    "rules": COMMON | {"rule_decisions", "revision_requests"},
    "computation": COMMON | {"lines", "revision_requests", "review_status", "computed_evidence_fingerprint"},
    "review": {"revision_requests", "review_status", "review_passes", "last_agent"},
    "human": COMMON | {"documents", "document_readiness", "revision_requests", "review_status", "review_passes", "guard_window_start",
                        "rule_decisions", "lines", "evidence_epoch", "evidence_history", "computed_evidence_fingerprint"},
    "orchestrator": {"next_agent", "handoffs", "escalations", "status", "guard_window_start", "guard_answer_count", "evidence_history", "evidence_epoch", "lines", "rule_decisions", "review_status", "review_passes", "computed_evidence_fingerprint"},
}
Count = Annotated[int, Field(ge=0, strict=True)]
TYPES = {
    "document_readiness": dict[str, StrictBool],
    "next_agent": Literal["intake", "extraction", "rules", "computation", "review", "human", "end"],
    "intake_complete": StrictBool, "evidence_epoch": Count, "review_passes": Count,
    "guard_window_start": Count, "guard_answer_count": Count,
    "input_token_usage": dict[str, Count],
    "status": Literal["in_progress", "waiting_on_human", "waiting_on_taxpayer", "draft_ready", "stopped"],
    "review_status": Literal["pending", "failed", "passed"],
    "evidence_history": list[EvidenceSnapshot],
    "answers": list[IntakeAnswer], "document_inventory": list[DocumentRef],
    "documents": dict[str, TaxDocument | StateWriteConflict],
    "rule_decisions": dict[str, RuleDecision], "lines": dict[str, LineValue],
    "revision_requests": list[RevisionRequest],
    "escalations": dict[str, EscalationTicket | StateWriteConflict], "handoffs": list[Handoff],
}
IDENTITY = {"documents": "document_id", "rule_decisions": "rule_id", "lines": "line", "escalations": "ticket_id"}


def validate_update(agent: str, update: dict) -> dict:
    if not isinstance(update, dict) or set(update) - ALLOWED_OUTPUTS[agent]:
        raise ValueError(f"Invalid output channels for {agent}")
    result = dict(update)
    for key, value in update.items():
        overwrite = isinstance(value, Overwrite)
        raw = value.value if overwrite else value
        if key in TYPES:
            try:
                raw = TypeAdapter(TYPES[key]).validate_python(raw)
            except ValidationError:
                raise ValueError(f"Malformed {key} message from {agent}") from None
            if key in IDENTITY:
                for name, record in raw.items():
                    records = record.candidates if isinstance(record, StateWriteConflict) else [record]
                    if any(getattr(r, IDENTITY[key], None) != name for r in records):
                        raise ValueError(f"Mismatched {key} identity from {agent}")
            result[key] = Overwrite(raw) if overwrite else raw
    expected = "extraction" if agent == "aggregate_documents" else agent
    if "last_agent" in result and result["last_agent"] != expected:
        raise ValueError("Agent cannot impersonate another agent")
    if agent == "orchestrator" and "next_agent" in result:
        TypeAdapter(Handoff).validate_python({"from_agent": "orchestrator", "to_agent": result["next_agent"], "reason": "route"})
    if agent not in {"orchestrator", "human", "intake", "aggregate_documents"} and any(isinstance(v, Overwrite) for v in result.values()):
        raise ValueError("Only coordinated evidence changes may bypass reducers")
    if agent == "intake" and set(result) & {"documents", "lines", "rule_decisions"}:
        if any(not isinstance(result[k], Overwrite) for k in set(result) & {"documents", "lines", "rule_decisions"}):
            raise ValueError("Intake may invalidate work products only through coordinated replacement")
    if agent in {"intake", "human", "aggregate_documents"}:
        for key in ("lines", "rule_decisions"):
            if key in result and (not isinstance(result[key], Overwrite) or result[key].value):
                raise ValueError("Input agents may invalidate derived work, never manufacture it")
    return result


def checked_agent(agent, node):
    @wraps(node)
    def checked(state):
        if agent == "extraction":
            state = {**state, "doc": DocumentRef.model_validate(state["doc"])}
        else:
            # Validate consumed shared contracts too, including checkpoint / external ingress.
            state = dict(state)
            for key, annotation in TYPES.items():
                if key in state:
                    state[key] = TypeAdapter(annotation).validate_python(state[key])
                    if key in IDENTITY:
                        for name, record in state[key].items():
                            records = record.candidates if isinstance(record, StateWriteConflict) else [record]
                            if any(getattr(r, IDENTITY[key], None) != name for r in records):
                                raise ValueError(f"Mismatched incoming {key} identity")
            if agent == "orchestrator":
                ids = {ref.document_id for ref in state.get("document_inventory", [])}
                for request in state.get("revision_requests", []):
                    if request.target == "extraction" and request.document_id not in ids:
                        raise ValueError("Extraction revision references a document outside the inventory")
        invalidated = {}
        if agent == "orchestrator" and state.get("computed_evidence_fingerprint"):
            from src.evidence import evidence_fingerprint, invalidate_evidence
            if evidence_fingerprint(state) != state["computed_evidence_fingerprint"]:
                invalidated = invalidate_evidence(state)
                state = {**state, **{k: v.value if isinstance(v, Overwrite) else v for k, v in invalidated.items()}}
        result = {**invalidated, **node(state)}
        if agent == "computation":
            from src.evidence import evidence_fingerprint
            result["computed_evidence_fingerprint"] = evidence_fingerprint(state)
        if agent == "rules" and state.get("evidence_epoch", 0):
            # Preserve historical approvals while giving new evidence a fresh ticket identity.
            epoch = state["evidence_epoch"]
            renamed = {key: f"{key}:evidence-{epoch}" for key in result.get("escalations", {})}
            result = dict(result)
            result["escalations"] = {renamed[k]: t.model_copy(update={"ticket_id": renamed[k]})
                                      for k, t in result.get("escalations", {}).items()}
            decisions = dict(result.get("rule_decisions", {}))
            if "scope" in decisions:
                decision = decisions["scope"]
                decisions["scope"] = decision.model_copy(update={"outcome": {
                    **decision.outcome, "issues": [renamed.get(k, k) for k in decision.outcome["issues"]]}})
            result["rule_decisions"] = decisions
        return validate_update(agent, result)
    return checked
