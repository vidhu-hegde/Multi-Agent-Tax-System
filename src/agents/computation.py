"""Computation agent. Fills every derived line; every number comes from call_tool(), never local arithmetic.

Lines are computed in dependency order. Line 6b (taxable Social Security) needs all other income and
line 10 first, and lines 9 and 11a need 6b, so the order below is load-bearing.
"""

from src.schemas import LineValue, Provenance
from src.state import SilverFileState, current_answers
from src.tools import call_tool

INCOME_BEFORE_SOCIAL_SECURITY = ["1z", "2b", "3b", "4b", "5b"]
WITHHOLDING_BOX = {"W-2": "2", "1099-INT": "4", "1099-DIV": "4", "1099-R": "4", "SSA-1099": "6"}


def computation(state: SilverFileState) -> dict:
    records = list(state.get("documents", {}).values())
    answers = current_answers(state)
    decisions = state["rule_decisions"]
    filing_status = answers["filing_status"].value
    lines: dict[str, LineValue] = {}

    def of_type(form_type, **match):
        return [r for r in records if r.form_type == form_type and all(getattr(r, k) == v for k, v in match.items())]

    def amount(line):
        return lines[line].amount

    def from_documents(line, docs, field, box):
        sources = [
            Provenance(
                kind="document",
                source=f"{r.form_type} {r.document_id}, box {box if isinstance(box, str) else box[r.form_type]}",
                value=getattr(r, field),
                inputs={"record_source": r.source.source},
            )
            for r in docs
            if getattr(r, field) is not None
        ]
        total, tool = call_tool("sum", values=[p.value for p in sources])
        lines[line] = LineValue(line=line, amount=total, provenance=[*sources, tool])

    def from_answer(line, field):
        answer = answers[field]
        lines[line] = LineValue(line=line, amount=answer.value, provenance=[Provenance(
            kind="user_input", source=f"intake: {field}", value=answer.value,
            entered_by=answer.entered_by, recorded_at=answer.answered_at,
        )])

    def derive(line, tool, depends_on, rule=None, **inputs):
        result, step = call_tool(tool, **inputs)
        steps = [step]
        if rule:
            decision = decisions[rule]
            steps.insert(0, Provenance(kind="rule", source=decision.rule_id, value=decision.outcome,
                                       citation=decision.citation))
        lines[line] = LineValue(line=line, amount=result, provenance=steps, depends_on=depends_on)

    def total_of(line, parts):
        derive(line, "sum", parts, values=[amount(p) for p in parts])

    w2 = of_type("W-2")
    interest = of_type("1099-INT")
    dividends = of_type("1099-DIV")
    ira = of_type("1099-R", ira_sep_simple=True)
    pensions = of_type("1099-R", ira_sep_simple=False)
    ssa = of_type("SSA-1099")

    # Income from documents
    from_documents("1z", w2, "wages", "1")
    from_documents("2a", interest, "tax_exempt_interest", "8")
    from_documents("2b", interest, "interest", "1")
    from_documents("3a", dividends, "qualified_dividends", "1b")
    from_documents("3b", dividends, "ordinary_dividends", "1a")
    from_documents("4a", ira, "gross_distribution", "1")
    from_documents("4b", ira, "taxable_amount", "2a")
    from_documents("5a", pensions, "gross_distribution", "1")
    from_documents("5b", pensions, "taxable_amount", "2a")
    from_documents("6a", ssa, "net_benefits", "5")
    from_answer("10", "adjustments")

    # Social Security last: it needs every other income line and the adjustments
    derive(
        "6b", "taxable_social_security", ["6a", "2a", "10", *INCOME_BEFORE_SOCIAL_SECURITY],
        filing_status=filing_status,
        benefits=amount("6a"),
        other_income=[amount(l) for l in INCOME_BEFORE_SOCIAL_SECURITY],
        tax_exempt_interest=amount("2a"),
        adjustments=amount("10"),
    )
    total_of("9", [*INCOME_BEFORE_SOCIAL_SECURITY, "6b"])
    derive("11a", "subtract", ["9", "10"], a=amount("9"), b=amount("10"))

    # Deductions and tax
    derive("12e", "standard_deduction", [], rule="age_blind_boxes",
           filing_status=filing_status, boxes=decisions["age_blind_boxes"].outcome["count"])
    derive("13b", "senior_deduction", ["11a"], rule="senior_deduction_count",
           filing_status=filing_status, magi=amount("11a"),
           qualifying_people=decisions["senior_deduction_count"].outcome)
    total_of("14", ["12e", "13b"])
    derive("15", "subtract_floor_zero", ["11a", "14"], a=amount("11a"), b=amount("14"))
    derive("16", "tax_from_schedule", ["15"], filing_status=filing_status, taxable_income=amount("15"))
    total_of("24", ["16"])

    # Payments and result
    from_documents("25a", w2, "federal_withheld", WITHHOLDING_BOX)
    from_documents("25b", [*interest, *dividends, *ira, *pensions, *ssa], "federal_withheld", WITHHOLDING_BOX)
    total_of("25d", ["25a", "25b"])
    from_answer("26", "estimated_payments")
    total_of("33", ["25d", "26"])
    derive("34", "subtract_floor_zero", ["33", "24"], a=amount("33"), b=amount("24"))
    derive("37", "subtract_floor_zero", ["24", "33"], a=amount("24"), b=amount("33"))

    remaining = [r for r in state.get("revision_requests") or [] if r.target != "computation"]
    return {"lines": lines, "revision_requests": remaining, "review_status": "pending", "last_agent": "computation"}
