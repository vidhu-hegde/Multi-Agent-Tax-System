"""Review / Audit agent: independently challenges draft values and returns revision requests.

Checks source-to-line amounts, four core tax rules via deterministic tools, internal
totals, provenance presence, out-of-scope issues, and contradictory values.
Never repairs the draft itself.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from src.schemas import FORM_LINES, RevisionRequest, StateWriteConflict
from src.state import SilverFileState, current_answers
from src.tools import call_tool

SUM_CHECKS = {
    "9": ["1z", "2b", "3b", "4b", "5b", "6b"],
    "14": ["12e", "13b"],
    "18": ["16", "17"],
    "21": ["20"],
    "24": ["22", "23"],
    "25d": ["25a", "25b"],
    "32": ["31"],
    "33": ["25d", "26", "32"],
}
SUBTRACT_CHECKS = {
    "11a": ("subtract", "9", "10"),
    "15": ("subtract_floor_zero", "11a", "14"),
    "22": ("subtract_floor_zero", "18", "21"),
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
SOURCE_INTAKE_LINES = {
    "10": "adjustments",
    "17": "schedule2_line3_tax",
    "20": "schedule3_nonrefundable_credits",
    "23": "schedule2_total_tax",
    "26": "estimated_payments",
    "31": "schedule3_other_payments",
}


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

# --- Provenance-integrity verification (Security / Review enhancement, step 3) ---
# Reconstruct the audit trail from trusted typed records and tool contracts. Do
# not accept a provenance entry just because it has a plausible-looking source.
DOCUMENT_BOXES = {
    "1z": "1", "2a": "8", "2b": "1", "3a": "1b", "3b": "1a",
    "4a": "1", "4b": "2a", "5a": "1", "5b": "2a", "6a": "5",
    "25a": "2", "25b": {"1099-INT": "4", "1099-DIV": "4", "1099-R": "4", "SSA-1099": "6"},
}
DERIVED_DEPENDENCIES = {
    "6b": ["6a", "2a", "10", *SOCIAL_SECURITY_OTHER_INCOME],
    "9": [*SOCIAL_SECURITY_OTHER_INCOME, "6b"],
    "11a": ["9", "10"],
    "12e": [],
    "13b": ["11a"],
    "14": ["12e", "13b"],
    "15": ["11a", "14"],
    "16": ["15"],
    "18": ["16", "17"],
    "21": ["20"],
    "22": ["18", "21"],
    "24": ["22", "23"],
    "25d": ["25a", "25b"],
    "32": ["31"],
    "33": ["25d", "26", "32"],
    "34": ["33", "24"],
    "37": ["24", "33"],
}
SUM_DEPENDENCIES = {"9", "14", "18", "21", "24", "25d", "32", "33"}
SUBTRACT_DEPENDENCIES = {
    "11a": "subtract", "15": "subtract_floor_zero", "22": "subtract_floor_zero",
    "34": "subtract_floor_zero", "37": "subtract_floor_zero",
}
RULE_PROVENANCE = {
    "6b": "social_security_base",
    "12e": "age_blind_boxes",
    "13b": "senior_deduction_count",
}


def _same_evidence(actual, expected):
    """Compare typed/JSON-round-tripped evidence without floating-point math.

    JSON checkpoints may turn Decimals into strings. Numeric strings are only
    tolerated when the expected value is numeric, not for booleans or IDs.
    """
    if isinstance(expected, Decimal):
        if isinstance(actual, bool) or not isinstance(actual, (Decimal, str, int)):
            return False
        try:
            return Decimal(str(actual)) == expected
        except InvalidOperation:
            return False
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _same_evidence(a, b) for a, b in zip(actual, expected)
        )
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            _same_evidence(actual[key], value) for key, value in expected.items()
        )
    return type(actual) is type(expected) and actual == expected


def _selected_document_records(line, documents):
    """Mirror source selection ORDER (especially 25b) without using draft evidence."""
    form_types, field, ira_flag = SOURCE_DOCUMENT_LINES[line]
    records = list(documents.values())
    if line == "25b":
        # Computation combines these groups, not the raw upload/inventory order.
        groups = (("1099-INT", None), ("1099-DIV", None),
                  ("1099-R", True), ("1099-R", False), ("SSA-1099", None))
        selected = [r for form_type, ira in groups for r in records
                    if r.form_type == form_type
                    and (ira is None or r.ira_sep_simple == ira)
                    and getattr(r, field) is not None]
    else:
        selected = [r for r in records if r.form_type in form_types
                    and (ira_flag is None or r.ira_sep_simple == ira_flag)
                    and getattr(r, field) is not None]
    return selected


def _expected_tool_inputs(line, state, lines, answers):
    """Return trusted tool name and arguments, or None if prerequisite state is missing."""
    if line in SOURCE_DOCUMENT_LINES:
        documents = state.get("documents", {})
        if any(isinstance(r, StateWriteConflict) for r in documents.values()):
            return None
        field = SOURCE_DOCUMENT_LINES[line][1]
        return "sum", {"values": [getattr(r, field) for r in _selected_document_records(line, documents)]}
    deps = DERIVED_DEPENDENCIES.get(line)
    if deps is None or any(d not in lines for d in deps):
        return None
    if line in SUM_DEPENDENCIES:
        return "sum", {"values": [lines[d].amount for d in deps]}
    if line in SUBTRACT_DEPENDENCIES:
        a, b = deps
        return SUBTRACT_DEPENDENCIES[line], {"a": lines[a].amount, "b": lines[b].amount}
    filing = answers.get("filing_status")
    if filing is None:
        return None
    filing_status = filing.value
    decisions = state.get("rule_decisions", {})
    if line == "6b":
        decision = decisions.get("social_security_base")
        if decision is None or not isinstance(decision.outcome, dict) or "mfs_lived_with_spouse" not in decision.outcome:
            return None
        return "taxable_social_security", {
            "filing_status": filing_status, "benefits": lines["6a"].amount,
            "other_income": [lines[d].amount for d in SOCIAL_SECURITY_OTHER_INCOME],
            "tax_exempt_interest": lines["2a"].amount,
            "adjustments": lines["10"].amount,
            "lived_with_spouse": decision.outcome["mfs_lived_with_spouse"],
        }
    if line == "12e":
        decision = decisions.get("age_blind_boxes")
        if decision is None or not isinstance(decision.outcome, dict) or "count" not in decision.outcome:
            return None
        return "standard_deduction", {"filing_status": filing_status, "boxes": decision.outcome["count"]}
    if line == "13b":
        decision = decisions.get("senior_deduction_count")
        if decision is None:
            return None
        return "senior_deduction", {
            "filing_status": filing_status, "magi": lines["11a"].amount,
            "qualifying_people": decision.outcome,
        }
    if line == "16":
        return "tax_from_schedule", {"filing_status": filing_status, "taxable_income": lines["15"].amount}
    return None


def check_provenance_integrity(state: SilverFileState) -> list[RevisionRequest]:
    """Verify source identities, captured values, computation steps and dependencies.

    Audit never mutates draft data. A mismatch returns only safe, field-level
    reasons, not original amounts, taxpayer identifiers or document contents.
    """
    problems: list[RevisionRequest] = []
    lines = state.get("lines", {})
    documents = state.get("documents", {})
    answers = current_answers(state)
    decisions = state.get("rule_decisions", {})

    def flag(line, reason, target="computation", field=None):
        problems.append(RevisionRequest(target=target, line=line, field=field, reason=reason))

    for line, entry in lines.items():
        steps = entry.provenance
        doc_steps = [p for p in steps if p.kind == "document"]
        user_steps = [p for p in steps if p.kind == "user_input"]
        tool_steps = [p for p in steps if p.kind == "tool"]
        rule_steps = [p for p in steps if p.kind == "rule"]

        if line in SOURCE_DOCUMENT_LINES:
            field = SOURCE_DOCUMENT_LINES[line][1]
            selected = []
            if not any(isinstance(r, StateWriteConflict) for r in documents.values()):
                selected = _selected_document_records(line, documents)
            box = DOCUMENT_BOXES[line]
            expected = [(
                r.document_id,
                f"{r.form_type} {r.document_id}, box {box if isinstance(box, str) else box[r.form_type]}",
                getattr(r, field), r.source.model_dump(mode="json"),
                r.source.entered_by, r.source.recorded_at,
            ) for r in selected]
            if len(doc_steps) != len(expected):
                flag(line, "document provenance count does not match source records")
            seen = set()
            for item in doc_steps:
                doc_id = item.inputs.get("document_id")
                # A provenance link may not be invented, repeated, or borrowed
                # from another document, form, or tax line.
                matches = [e for e in expected if e[0] == doc_id]
                if doc_id in seen or len(matches) != 1:
                    flag(line, "document provenance contains an unknown or duplicate source reference")
                    continue
                seen.add(doc_id)
                _, name, value, record_source, entered_by, recorded_at = matches[0]
                if (item.source != name or item.inputs.get("field") != field
                    or not _same_evidence(item.value, value)
                    or not _same_evidence(item.inputs.get("record_source"), record_source)
                    or item.entered_by != entered_by or item.recorded_at != recorded_at):
                    flag(line, "document provenance conflicts with confirmed source evidence")
            if user_steps or rule_steps:
                flag(line, "unexpected evidence type on document-backed line")

        elif line in SOURCE_INTAKE_LINES:
            field = SOURCE_INTAKE_LINES[line]
            answer = answers.get(field)
            if answer is None or len(user_steps) != 1:
                flag(line, "missing or duplicate intake provenance", "intake", field)
            else:
                item = user_steps[0]
                if (item.source != f"intake: {field}"
                    or not _same_evidence(item.value, answer.value)
                    or item.entered_by != answer.entered_by
                    or item.recorded_at != answer.answered_at):
                    flag(line, "intake provenance does not match the latest confirmed answer")
            if doc_steps or rule_steps or tool_steps:
                flag(line, "unexpected evidence type on intake-backed line")

        elif line in DERIVED_DEPENDENCIES:
            if doc_steps or user_steps:
                flag(line, "derived line includes an unexpected direct source")
            rule_id = RULE_PROVENANCE.get(line)
            if rule_id is not None:
                decision = decisions.get(rule_id)
                if decision is None:
                    flag(line, "rule decision required to audit provenance is missing", "rules", rule_id)
                    flag(line, "recompute line after rule decision is restored")
                elif len(rule_steps) != 1:
                    # The calculation agent writes the line's provenance, not
                    # Rules. Repairing Rules alone would leave the draft stale.
                    flag(line, "missing or duplicated rule provenance")
                else:
                    item = rule_steps[0]
                    if (item.source != decision.rule_id or item.citation != decision.citation
                        or not _same_evidence(item.value, decision.outcome)):
                        flag(line, "rule provenance does not match the current policy decision")
            elif rule_steps:
                flag(line, "unexpected rule provenance on derived line")
        else:
            flag(line, "unrecognized form line cannot be audited")
            continue

        expected_deps = DERIVED_DEPENDENCIES.get(line, [])
        if entry.depends_on != expected_deps:
            flag(line, "line dependency record does not match required calculation inputs")

        # Inputs are independently reconstructed from authoritative state. A
        # forged self-consistent tool entry must not be enough to pass review.
        if line in SOURCE_INTAKE_LINES:
            continue
        if len(tool_steps) != 1:
            flag(line, "expected exactly one deterministic tool provenance step")
            continue
        expected_tool = _expected_tool_inputs(line, state, lines, answers)
        if expected_tool is None:
            flag(line, "cannot reconstruct deterministic tool evidence for this line")
            continue
        name, inputs = expected_tool
        item = tool_steps[0]
        if item.source != f"tax_math.{name}" or not _same_evidence(item.inputs, inputs):
            flag(line, "recorded tool identity or arguments differ from confirmed evidence")
            continue
        try:
            recalculated, verified_step = call_tool(name, **inputs)
        except (ValueError, TypeError, KeyError):
            flag(line, "deterministic tool evidence could not be verified")
            continue
        if (item.via != verified_step.via
            or not _same_evidence(item.value, recalculated)
            or not _same_evidence(entry.amount, recalculated)):
            flag(line, "tool result provenance does not match verified calculation")

    return problems

def consolidate_revision_requests(requests: list[RevisionRequest]) -> list[RevisionRequest]:
    """Combine findings that require the same repair while preserving audit detail.

    Review may detect one defect through several independent checks. Routing all
    of those findings separately makes the queue noisy even though the owning
    agent repairs them together. Keep the first-seen action order, retain every
    distinct safe reason, and never combine different targets, fields, documents
    or form lines.
    """
    grouped: dict[tuple, tuple[RevisionRequest, list[str]]] = {}
    order: list[tuple] = []
    for request in requests:
        key = (request.target, request.field, request.document_id, request.line, request.raised_by)
        if key not in grouped:
            grouped[key] = (request, [request.reason])
            order.append(key)
        elif request.reason not in grouped[key][1]:
            grouped[key][1].append(request.reason)

    consolidated = []
    for key in order:
        request, reasons = grouped[key]
        if len(reasons) == 1:
            consolidated.append(request)
        else:
            consolidated.append(request.model_copy(
                update={"reason": "Multiple audit findings: " + "; ".join(reasons)}
            ))
    return consolidated


def find_problems(state: SilverFileState) -> list[RevisionRequest]:
    lines = state.get("lines", {})
    problems: list[RevisionRequest] = []

    def problem(line, reason, target="computation"):
        problems.append(RevisionRequest(target=target, line=line, reason=reason))

    missing = [line for line in FORM_LINES if line not in lines]
    for line in missing:
        problem(line, "line missing from the draft")
    if missing:
        return consolidate_revision_requests(problems)

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
            problem(line, "total does not recompute from required component lines")
    for line, (tool, a, b) in SUBTRACT_CHECKS.items():
        expected, _ = call_tool(tool, a=lines[a].amount, b=lines[b].amount)
        if lines[line].amount != expected:
            problem(line, "total does not recompute from required component lines")

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
    problems.extend(check_provenance_integrity(state))

    scope = state.get("rule_decisions", {}).get("scope")
    escalations = state.get("escalations", {})
    if scope is None:
        problem(None, "scope was never checked", target="rules")
    else:
        for ticket_id in scope.outcome["issues"]:
            ticket = escalations.get(ticket_id)
            if ticket is None or ticket.status != "resolved":
                problem(None, f"out-of-scope item {ticket_id} not resolved by a human", target="rules")
    return consolidate_revision_requests(problems)


def review(state: SilverFileState) -> dict:
    problems = find_problems(state)
    return {
        "revision_requests": problems,
        "review_status": "failed" if problems else "passed",
        "review_passes": state.get("review_passes", 0) + 1,
        "last_agent": "review",
    }
