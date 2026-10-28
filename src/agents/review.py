"""Review / Audit agent. Tries to falsify the assembled return and sends work back; never fixes anything.

Checks: required lines present with provenance, totals recomputed independently through the same tools,
"taxable" never larger than "total", and no out-of-scope item left unresolved.
"""

from src.schemas import FORM_LINES, RevisionRequest, StateWriteConflict
from src.state import SilverFileState, current_answers
from src.tools import call_tool

SUM_CHECKS = {
    "9": ["1z", "2b", "3b", "4b", "5b", "6b"],
    "14": ["12e", "13b"],
    "24": ["16"],
    "25d": ["25a", "25b"],
    "33": ["25d", "26"],
}
SUBTRACT_CHECKS = {
    "11a": ("subtract", "9", "10"),
    "15": ("subtract_floor_zero", "11a", "14"),
    "34": ("subtract_floor_zero", "33", "24"),
    "37": ("subtract_floor_zero", "24", "33"),
}
NOT_MORE_THAN = [
    ("3a", "3b"),
    ("4b", "4a"),
    ("5b", "5a"),
    ("6b", "6a"),
]


# The source ledger is independent of the assembled LineValues. These are the same
# field destinations as the Computation agent, but the expected amounts are rebuilt
# directly from confirmed source records, never from the draft's own provenance.
# 1099-R's IRA checkbox must be honored: IRA -> line 4, pension -> line 5.
SOURCE_DOCUMENT_LINES = {
    "1z": (("W-2",), "wages", None),
    "2a": (("1099-INT",), "tax_exempt_interest", None),
    "2b": (("1099-INT",), "interest", None),
    "3a": (("1099-DIV",), "qualified_dividends", None),
    "3b": (("1099-DIV",), "ordinary_dividends", None),
    "4a": (("1099-R",), "gross_distribution", True),
    "4b": (("1099-R",), "taxable_amount", True),
    "5a": (("1099-R",), "gross_distribution", False),
    "5b": (("1099-R",), "taxable_amount", False),
    "6a": (("SSA-1099",), "net_benefits", None),
    "25a": (("W-2",), "federal_withheld", None),
    "25b": (("1099-INT", "1099-DIV", "1099-R", "SSA-1099"), "federal_withheld", None),
}
SOURCE_INTAKE_LINES = {"10": "adjustments", "26": "estimated_payments"}


def check_source_lines(state: SilverFileState) -> list[RevisionRequest]:
    """Independently compare draft entry lines with confirmed documents/intake.

    Use only typed source records and the deterministic calculation interface.
    Never edit any line or source record; send discrepancies back to their owner.
    """
    problems: list[RevisionRequest] = []
    lines = state.get("lines", {})

    # An explicitly confirmed empty inventory is a valid zero-document case;
    # a missing ledger with no inventory evidence is not.
    inventory = state.get("document_inventory")
    if "documents" not in state and inventory is None:
        problems.append(RevisionRequest(
            target="intake", field="document_inventory",
            reason="source document records unavailable for review",
        ))
    else:
        document_map = state.get("documents", {})
        for ref in inventory or []:
            if ref.form_type != "other" and ref.document_id not in document_map:
                problems.append(RevisionRequest(
                    target="extraction", document_id=ref.document_id,
                    reason="document listed in inventory has no extracted source record",
                ))

        records = []
        for document_id, record in document_map.items():
            if isinstance(record, StateWriteConflict):
                # Normally the orchestrator stops these before reaching Review.
                problems.append(RevisionRequest(
                    target="extraction", document_id=document_id,
                    reason="source document record has an unresolved write conflict",
                ))
            else:
                records.append(record)

        if not any(isinstance(r, StateWriteConflict) for r in document_map.values()):
            for line, (form_types, field, ira_flag) in SOURCE_DOCUMENT_LINES.items():
                values = [
                    getattr(record, field)
                    for record in records
                    if record.form_type in form_types
                    and (ira_flag is None or record.ira_sep_simple == ira_flag)
                    and getattr(record, field) is not None
                ]
                expected, _ = call_tool("sum", values=values)
                if line in lines and lines[line].amount != expected:
                    problems.append(RevisionRequest(
                        target="computation", line=line,
                        reason=f"line {line} does not match confirmed {field} in source documents",
                    ))

    answers = current_answers(state)
    for line, field in SOURCE_INTAKE_LINES.items():
        answer = answers.get(field)
        if answer is None:
            problems.append(RevisionRequest(
                target="intake", field=field, line=line,
                reason=f"confirmed intake value for {field} is missing",
            ))
            continue
        expected, _ = call_tool("sum", values=[answer.value])
        if line in lines and lines[line].amount != expected:
            problems.append(RevisionRequest(
                target="computation", line=line,
                reason=f"line {line} does not match confirmed intake field {field}",
            ))

    return problems


def find_problems(state: SilverFileState) -> list[RevisionRequest]:
    lines = state.get("lines", {})
    problems: list[RevisionRequest] = []

    def problem(line, reason, target="computation"):
        problems.append(RevisionRequest(target=target, line=line, reason=reason))

    missing = [line for line in FORM_LINES if line not in lines]
    for line in missing:
        problem(line, "line missing from the draft")
    if missing:
        return problems

    for line, value in lines.items():
        if not value.provenance:
            problem(line, "no provenance record")
        elif value.is_stub:
            problem(
                line,
                "stub/placeholder provenance is not acceptable in a reviewed draft",
            )

    for line, parts in SUM_CHECKS.items():
        expected, _ = call_tool("sum", values=[lines[p].amount for p in parts])
        if lines[line].amount != expected:
            problem(line, f"total does not recompute (expected {expected})")
    for line, (tool, a, b) in SUBTRACT_CHECKS.items():
        expected, _ = call_tool(tool, a=lines[a].amount, b=lines[b].amount)
        if lines[line].amount != expected:
            problem(line, f"total does not recompute (expected {expected})")

    for taxable, total in NOT_MORE_THAN:
        if lines[taxable].amount > lines[total].amount:
            problem(
                taxable,
                f"line {taxable} is larger than line {total}",
            )

    if lines["34"].amount > 0 and lines["37"].amount > 0:
        problem(
            "34",
            "refund line 34 and amount owed line 37 are both positive",
        )

    problems.extend(check_source_lines(state))

    scope = state.get("rule_decisions", {}).get("scope")
    escalations = state.get("escalations", {})
    if scope is None:
        problem(None, "scope was never checked", target="rules")
    else:
        for ticket_id in scope.outcome["issues"]:
            ticket = escalations.get(ticket_id)
            if ticket is None or ticket.status != "resolved":
                problem(None, f"out-of-scope item {ticket_id} not resolved by a human", target="rules")
    return problems


def review(state: SilverFileState) -> dict:
    problems = find_problems(state)
    return {
        "revision_requests": problems,
        "review_status": "failed" if problems else "passed",
        "review_passes": state.get("review_passes", 0) + 1,
        "last_agent": "review",
    }
