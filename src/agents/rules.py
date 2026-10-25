"""Eligibility & Rules agent (STUB). Every decision cites a section of data/policy.md.

The citations below are placeholder section ids until policy.md is written.
"""

from datetime import date

from src.schemas import EscalationTicket, RuleDecision
from src.state import SilverFileState, current_answers

# Born before 2 January 1961: 1040-SR eligible, and 65 or older at the end of 2025.
SENIOR_CUTOFF = date(1961, 1, 2)


def rules(state: SilverFileState) -> dict:
    answers = current_answers(state)
    status = answers["filing_status"].value
    joint = status == "mfj"

    def value(field, default=None):
        answer = answers.get(field)
        return default if answer is None else answer.value

    taxpayer_65 = value("taxpayer_dob") < SENIOR_CUTOFF
    spouse_65 = joint and value("spouse_dob") is not None and value("spouse_dob") < SENIOR_CUTOFF
    boxes = {
        "taxpayer_65": taxpayer_65,
        "taxpayer_blind": bool(value("taxpayer_blind", False)),
        "spouse_65": spouse_65,
        "spouse_blind": joint and bool(value("spouse_blind", False)),
    }
    boxes["count"] = sum(1 for k, v in boxes.items() if k != "count" and v)
    seniors = 0 if status == "mfs" else int(taxpayer_65) + int(spouse_65)

    tickets: list[EscalationTicket] = []
    if not (taxpayer_65 or spouse_65):
        tickets.append(EscalationTicket(
            ticket_id="out_of_scope:not_1040sr_eligible", reason="out_of_scope", raised_by="rules",
            detail="Neither the taxpayer nor a joint-filing spouse was born before 2 January 1961.",
        ))
    for ref in state.get("document_inventory", []):
        if ref.form_type == "other":
            tickets.append(EscalationTicket(
                ticket_id=f"out_of_scope:{ref.document_id}", reason="out_of_scope", raised_by="rules",
                detail=f"Document {ref.document_id} is out of scope: {ref.description or 'unsupported form'}.",
                evidence={"document_id": ref.document_id},
            ))
    for record in state.get("documents", {}).values():
        if record.form_type == "1099-R" and record.taxable_not_determined:
            tickets.append(EscalationTicket(
                ticket_id=f"1099r_taxable_not_determined:{record.document_id}",
                reason="1099r_taxable_not_determined", raised_by="rules",
                detail=f"1099-R {record.document_id} has box 2b checked (taxable amount not determined).",
                evidence={"document_id": record.document_id},
            ))

    decisions = [
        RuleDecision(rule_id="eligibility_1040sr", outcome=taxpayer_65 or spouse_65,
                     explanation="Born before 2 January 1961 (either spouse on a joint return).",
                     citation="policy.md#1040sr-eligibility"),
        RuleDecision(rule_id="age_blind_boxes", outcome=boxes,
                     explanation="Line 12d boxes: 65 or older and blind, for taxpayer and spouse.",
                     citation="policy.md#standard-deduction"),
        RuleDecision(rule_id="senior_deduction_count", outcome=seniors,
                     explanation="People aged 65+ who qualify for the Schedule 1-A senior deduction.",
                     citation="policy.md#senior-deduction"),
        RuleDecision(rule_id="scope", outcome={"issues": [t.ticket_id for t in tickets]},
                     explanation="Out-of-scope items found; each one escalates to a human.",
                     citation="policy.md#scope"),
    ]
    remaining = [r for r in state.get("revision_requests") or [] if r.target != "rules"]
    return {
        "rule_decisions": {d.rule_id: d for d in decisions},
        "escalations": {t.ticket_id: t for t in tickets},
        "revision_requests": remaining,
        "last_agent": "rules",
    }
