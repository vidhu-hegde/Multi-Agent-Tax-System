"""Coordinated invalidation; historical answers, handoffs and approvals remain in state."""
import hashlib
import json
from langgraph.types import Overwrite
from src.schemas import EvidenceSnapshot


def invalidate_evidence(state):
    snapshot = EvidenceSnapshot(epoch=state.get("evidence_epoch", 0), documents=state.get("documents", {}),
                                lines=state.get("lines", {}), rule_decisions=state.get("rule_decisions", {}))
    return {"computed_evidence_fingerprint": None, "evidence_history": [snapshot], "evidence_epoch": state.get("evidence_epoch", 0) + 1,
            "lines": Overwrite({}), "rule_decisions": Overwrite({}),
            "review_status": "pending", "review_passes": 0}


def retract_inventory(state, inventory):
    old = {ref.document_id: ref for ref in state.get("document_inventory", [])}
    new = {ref.document_id: ref for ref in inventory}
    retained = {key: record for key, record in state.get("documents", {}).items()
                if key in new and key in old and new[key] == old[key]}
    return {**invalidate_evidence(state), "documents": Overwrite(retained)}


def evidence_fingerprint(state):
    from src.state import current_answers
    payload = {
        "answers": {key: answer.model_dump(mode="json") for key, answer in current_answers(state).items()},
        "documents": {key: record.model_dump(mode="json") for key, record in state.get("documents", {}).items()},
        "inventory": [ref.model_dump(mode="json") for ref in state.get("document_inventory", [])],
        "readiness": state.get("document_readiness", {}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
