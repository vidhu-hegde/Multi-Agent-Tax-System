"""Eligibility & Rules agent (STUB). Every decision cites a section of data/policy.md.

The citations below are placeholder section ids until policy.md is written.
"""

from datetime import date
from decimal import Decimal

from src.escalation import ticket
from src.schemas import EscalationTicket, RuleDecision
from src.state import SilverFileState, current_answers
from src.tools import call_tool

# Born before 2 January 1961: 1040-SR eligible, and 65 or older at the end of 2025.
SENIOR_CUTOFF = date(1961, 1, 2)
# Stated wages and W-2 box 1 may differ by rounding or memory; beyond this it is a conflict for a human.
WAGE_TOLERANCE = Decimal("500")


def filing_status_problem(status: str, spouse_died_year: int | None) -> str | None:
    """A spouse's death makes MFJ vs QSS vs Single a judgement call; SilverFile does not make it."""
    if spouse_died_year == 2025:
        return "Spouse died in 2025: whether to file MFJ, QSS or Single needs a person to decide."
    if status == "qss" and spouse_died_year not in (2023, 2024):
        return "Qualifying surviving spouse needs a spouse who died in 2023 or 2024."
    if status == "mfj" and spouse_died_year is not None:
        return f"Filing jointly, but the spouse died in {spouse_died_year}."
    return None


def wage_conflict(stated, w2_records) -> dict | None:
    """Compare what the taxpayer said they earned with the total of W-2 box 1."""
    if stated is None or not w2_records:
        return None
    total, _ = call_tool("sum", values=[r.wages for r in w2_records])
    difference, _ = call_tool("subtract", a=total, b=stated)
    if abs(difference) <= WAGE_TOLERANCE:
        return None
    return {"stated_wages": str(stated), "w2_total": str(total), "documents": [r.document_id for r in w2_records]}


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
        tickets.append(ticket(
            "out_of_scope", raised_by="rules", key="not_1040sr_eligible",
            detail="Neither the taxpayer nor a joint-filing spouse was born before 2 January 1961.",
        ))
    for ref in state.get("document_inventory", []):
        if ref.form_type == "other":
            tickets.append(ticket(
                "out_of_scope", raised_by="rules", key=ref.document_id,
                detail=f"Document {ref.document_id} is out of scope: {ref.description or 'unsupported form'}.",
                evidence={"document_id": ref.document_id},
            ))
    records = list(state.get("documents", {}).values())
    for record in records:
        if record.form_type == "1099-R" and record.taxable_not_determined:
            tickets.append(ticket(
                "1099r_taxable_not_determined", raised_by="rules", key=record.document_id,
                detail=f"1099-R {record.document_id} has box 2b checked (taxable amount not determined).",
                evidence={"document_id": record.document_id},
            ))

    status_problem = filing_status_problem(status, value("spouse_died_year"))
    if status_problem:
        tickets.append(ticket(
            "filing_status_ambiguity", raised_by="rules", key="spouse_death", detail=status_problem,
            evidence={"filing_status": status, "spouse_died_year": value("spouse_died_year")},
        ))

    conflict = wage_conflict(value("stated_wages"), [r for r in records if r.form_type == "W-2"])
    if conflict:
        tickets.append(ticket(
            "document_conflict", raised_by="rules", key="wages",
            detail=f"The taxpayer said about ${conflict['stated_wages']} in wages; the W-2s show ${conflict['w2_total']}.",
            evidence=conflict,
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
        RuleDecision(rule_id="filing_status_check", outcome=status_problem is None,
                     explanation=status_problem or "No spouse death affects the filing status.",
                     citation="policy.md#filing-status"),
        RuleDecision(rule_id="wage_check", outcome=conflict is None,
                     explanation="Stated wages agree with the W-2s." if conflict is None else "Stated wages and W-2s disagree.",
                     citation="policy.md#document-conflicts"),
        RuleDecision(rule_id="scope", outcome={"issues": [t.ticket_id for t in tickets]},
                     explanation="Items that need a human before the draft can be trusted; each one escalates.",
                     citation="policy.md#scope"),
    ]
    remaining = [r for r in state.get("revision_requests") or [] if r.target != "rules"]
    return {
        "rule_decisions": {d.rule_id: d for d in decisions},
        "escalations": {t.ticket_id: t for t in tickets},
        "revision_requests": remaining,
        "last_agent": "rules",
    }
