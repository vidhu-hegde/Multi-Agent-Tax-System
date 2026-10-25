"""Review / Audit agent. Tries to falsify the assembled return and sends work back; never fixes anything.

Checks: required lines present with provenance, totals recomputed independently through the same tools,
"taxable" never larger than "total", and no out-of-scope item left unresolved.
"""

from src.schemas import FORM_LINES, RevisionRequest
from src.state import SilverFileState
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
NOT_MORE_THAN = [("2a", None), ("4b", "4a"), ("5b", "5a"), ("6b", "6a")]


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

    for line, parts in SUM_CHECKS.items():
        expected, _ = call_tool("sum", values=[lines[p].amount for p in parts])
        if lines[line].amount != expected:
            problem(line, f"total does not recompute (expected {expected})")
    for line, (tool, a, b) in SUBTRACT_CHECKS.items():
        expected, _ = call_tool(tool, a=lines[a].amount, b=lines[b].amount)
        if lines[line].amount != expected:
            problem(line, f"total does not recompute (expected {expected})")

    for taxable, total in NOT_MORE_THAN:
        if total and lines[taxable].amount > lines[total].amount:
            problem(taxable, f"line {taxable} is larger than line {total}")

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
