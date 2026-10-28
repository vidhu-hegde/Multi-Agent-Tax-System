"""Review / Audit agent: independently challenges draft values and returns revision requests.

Checks source-to-line amounts, four core tax rules via deterministic tools, internal
totals, provenance presence, out-of-scope issues, and contradictory values.
Never repairs the draft itself.
"""

from datetime import date

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


# 2025 Form 1040-SR: the same DOB cutoff as the Rules agent, independently
# reconstructed from confirmed Intake answers rather than trusting rule outcomes.
SENIOR_CUTOFF = date(1961, 1, 2)
TAX_RULE_LINES = ("6b", "12e", "13b", "16")
SOCIAL_SECURITY_OTHER_INCOME = ("1z", "2b", "3b", "4b", "5b")


def check_tax_rules(state: SilverFileState) -> list[RevisionRequest]:
    """Rebuild inputs and independently check four core calculated tax lines.

    The dollar arithmetic lives exclusively in the deterministic tax_math tool
    interface. Rules/Computation own repairs; Review does not change State.
    """
    lines = state.get("lines", {})
    # find_problems already reports absent form rows. Avoid indexing a partial
    # draft or incorrectly escalating incomplete calculations as tool failures.
    required = set(TAX_RULE_LINES) | {"6a", "2a", "10", "11a", "15", *SOCIAL_SECURITY_OTHER_INCOME}
    if not required.issubset(lines):
        return []

    problems: list[RevisionRequest] = []
    answers = current_answers(state)
    status_answer = answers.get("filing_status")
    if status_answer is None:
        return [RevisionRequest(
            target="intake", field="filing_status",
            reason="filing status is missing; independent tax-rule review cannot proceed",
        )]
    filing_status = status_answer.value
    decisions = state.get("rule_decisions", {})

    def rule_decision(name: str, line: str):
        decision = decisions.get(name)
        if decision is None:
            problems.append(RevisionRequest(
                target="rules", field=name, line=line,
                reason=f"rule decision {name} is missing for independent tax review",
            ))
            # Even after Rules rebuild the decision, old calculated lines must
            # be replaced before the return can be reviewed again.
            problems.append(RevisionRequest(
                target="computation", line=line,
                reason=f"recompute line {line} after missing rule decision {name} is restored",
            ))
        return decision

    def verify(line: str, tool_name: str, **inputs):
        expected, _ = call_tool(tool_name, **inputs)
        if lines[line].amount != expected:
            problems.append(RevisionRequest(
                target="computation", line=line,
                reason=f"line {line} does not match independent tax_math.{tool_name} calculation",
            ))

    base = rule_decision("social_security_base", "6b")
    if base is not None:
        base_outcome = base.outcome
        if not isinstance(base_outcome, dict) or "mfs_lived_with_spouse" not in base_outcome:
            problems.extend([
                RevisionRequest(target="rules", field="social_security_base", line="6b",
                                reason="social_security_base rule decision is malformed"),
                RevisionRequest(target="computation", line="6b",
                                reason="recompute taxable Social Security after rule decision correction"),
            ])
        else:
            # The filing-status-specific base itself must agree with Intake.
            # Otherwise two agents could agree on the same incorrect MFS case.
            if filing_status == "mfs" and lines["6a"].amount > 0:
                residence = answers.get("mfs_lived_with_spouse")
                if residence is None:
                    problems.append(RevisionRequest(
                        target="intake", field="mfs_lived_with_spouse", line="6b",
                        reason="MFS residence answer is missing for the Social Security worksheet",
                    ))
                elif base_outcome["mfs_lived_with_spouse"] != residence.value:
                    problems.extend([
                        RevisionRequest(target="rules", field="social_security_base", line="6b",
                                        reason="Social Security base disagrees with confirmed MFS residence answer"),
                        RevisionRequest(target="computation", line="6b",
                                        reason="recompute taxable Social Security after correcting the MFS base"),
                    ])
            verify("6b", "taxable_social_security",
                   filing_status=filing_status,
                   benefits=lines["6a"].amount,
                   other_income=[lines[line].amount for line in SOCIAL_SECURITY_OTHER_INCOME],
                   tax_exempt_interest=lines["2a"].amount,
                   adjustments=lines["10"].amount,
                   lived_with_spouse=base_outcome["mfs_lived_with_spouse"])

    boxes_decision = rule_decision("age_blind_boxes", "12e")
    if boxes_decision is not None:
        boxes = boxes_decision.outcome
        if not isinstance(boxes, dict) or type(boxes.get("count")) is not int:
            problems.extend([
                RevisionRequest(target="rules", field="age_blind_boxes", line="12e",
                                reason="age_blind_boxes rule decision has no valid box count"),
                RevisionRequest(target="computation", line="12e",
                                reason="recompute standard deduction after rule decision correction"),
            ])
        else:
            verify("12e", "standard_deduction", filing_status=filing_status, boxes=boxes["count"])

    seniors_decision = rule_decision("senior_deduction_count", "13b")
    if seniors_decision is not None:
        people = seniors_decision.outcome
        if type(people) is not int:
            problems.extend([
                RevisionRequest(target="rules", field="senior_deduction_count", line="13b",
                                reason="senior_deduction_count decision is not an integer"),
                RevisionRequest(target="computation", line="13b",
                                reason="recompute senior deduction after rule decision correction"),
            ])
        else:
            verify("13b", "senior_deduction", filing_status=filing_status,
                   magi=lines["11a"].amount, qualifying_people=people)

    verify("16", "tax_from_schedule", filing_status=filing_status,
           taxable_income=lines["15"].amount)

    # Recheck high-impact eligibility decisions against *confirmed* Intake
    # evidence. Otherwise a wrong count used by both agents could pass the
    # independent amount recomputation. This is NOT a replacement for Rules.
    dob_answer = answers.get("taxpayer_dob")
    if dob_answer is None:
        problems.append(RevisionRequest(
            target="intake", field="taxpayer_dob",
            reason="taxpayer birth date is missing for independent age-rule verification",
        ))
    else:
        dob = dob_answer.value
        if isinstance(dob, str):
            try:
                dob = date.fromisoformat(dob)
            except ValueError:
                dob = None
        if not isinstance(dob, date):
            problems.append(RevisionRequest(
                target="intake", field="taxpayer_dob",
                reason="taxpayer birth date cannot be validated for age-rule verification",
            ))
        else:
            taxpayer_senior = dob < SENIOR_CUTOFF
            spouse_dob_answer = answers.get("spouse_dob")
            spouse_dob = spouse_dob_answer.value if spouse_dob_answer else None
            if isinstance(spouse_dob, str):
                try:
                    spouse_dob = date.fromisoformat(spouse_dob)
                except ValueError:
                    spouse_dob = None
            if filing_status == "mfj" and spouse_dob_answer is not None and spouse_dob is None:
                problems.append(RevisionRequest(target="intake", field="spouse_dob",
                                               reason="joint-filing spouse birth date cannot be validated"))
            else:
                spouse_senior = filing_status == "mfj" and spouse_dob is not None and spouse_dob < SENIOR_CUTOFF
                expected_boxes = (
                    int(taxpayer_senior) + int(bool(answers.get("taxpayer_blind") and answers["taxpayer_blind"].value))
                    + int(spouse_senior)
                    + (int(bool(answers.get("spouse_blind") and answers["spouse_blind"].value)) if filing_status == "mfj" else 0)
                )
                expected_seniors = 0 if filing_status == "mfs" else int(taxpayer_senior) + int(spouse_senior)
                if boxes_decision is not None and isinstance(boxes_decision.outcome, dict) and boxes_decision.outcome.get("count") != expected_boxes:
                    problems.extend([
                        RevisionRequest(target="rules", field="age_blind_boxes", line="12e",
                                        reason="age/blind box count disagrees with confirmed intake facts"),
                        RevisionRequest(target="computation", line="12e",
                                        reason="recompute standard deduction after age/blind decision correction"),
                    ])
                if seniors_decision is not None and seniors_decision.outcome != expected_seniors:
                    problems.extend([
                        RevisionRequest(target="rules", field="senior_deduction_count", line="13b",
                                        reason="senior deduction count disagrees with confirmed intake birth dates"),
                        RevisionRequest(target="computation", line="13b",
                                        reason="recompute senior deduction after eligibility decision correction"),
                    ])
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
    problems.extend(check_tax_rules(state))

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
