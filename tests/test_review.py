"""Safety-gate tests for Qiyan's Review/Audit responsibilities."""

import pytest
from decimal import Decimal

from src.agents.review import check_source_lines, check_tax_rules, find_problems, review
from src.schemas import (
    FORM_LINES, LineValue, Provenance, RuleDecision, IntakeAnswer,
    W2Record, Interest1099, Dividend1099, Retirement1099R, SSA1099, DocumentRef,
)
from tests.conftest import SKELETON_CASE
from src.tools import TOOLS, call_tool
from src.agents.computation import computation


def complete_zero_state(*, stub_line: str | None = None) -> dict:
    """Complete, consistent draft with one optional placeholder line."""

    lines = {
        line: LineValue(
            line=line,
            amount=Decimal("0"),
            provenance=[
                Provenance(
                    kind="tool",
                    source=f"tax_math.test_{line}",
                    value=Decimal("0"),
                    stub=line == stub_line,
                )
            ],
        )
        for line in FORM_LINES
    }

    return {
        "lines": lines,
        "documents": {},
        "answers": [
            IntakeAnswer(field="adjustments", value="0"),
            IntakeAnswer(field="estimated_payments", value="0"),
        ],
        "rule_decisions": {
            "scope": RuleDecision(
                rule_id="scope",
                outcome={"issues": []},
                explanation="Test fixture has no out-of-scope items.",
                citation="policy.md#scope",
            )
        },
        "escalations": {},
        "review_passes": 0,
    }


def set_amount(state: dict, line: str, amount: str) -> None:
    state["lines"][line] = state["lines"][line].model_copy(
        update={"amount": Decimal(amount)}
    )


def test_review_rejects_stubbed_tax_value_and_sends_it_back_to_computation():
    state = complete_zero_state(stub_line="16")

    problems = find_problems(state)

    assert any(
        problem.target == "computation"
        and problem.line == "16"
        and "stub" in problem.reason.lower()
        for problem in problems
    )
    assert review(state)["review_status"] == "failed"


@pytest.mark.production_stubs
def test_production_placeholder_tools_cannot_reach_draft_ready(make_graph, monkeypatch):
    for name in (
        "taxable_social_security",
        "standard_deduction",
        "senior_deduction",
        "tax_from_schedule",
    ):
        function, _ = TOOLS[name]
        monkeypatch.setitem(
            TOOLS,
            name,
            (function, True),
        )

    result = make_graph().invoke(
        {"case_path": SKELETON_CASE},
        {"configurable": {"thread_id": "production-stub-gate"}},
    )

    [interrupt_value] = [
        item.value for item in result["__interrupt__"]
    ]
    requests = interrupt_value["evidence"]["open_requests"]

    assert result["status"] == "waiting_on_human"
    assert result["review_status"] == "failed"
    assert interrupt_value["reason"] == "review_limit"

    assert {
        request["line"] for request in requests
    } == {"6b", "12e", "13b", "16"}

    assert all(
        "stub" in request["reason"].lower()
        for request in requests
    )


@pytest.mark.parametrize(
    ("taxable_line", "total_line"),
    [
        ("3a", "3b"),
        ("4b", "4a"),
        ("5b", "5a"),
        ("6b", "6a"),
    ],
)
def test_review_detects_taxable_amount_above_its_total(
    taxable_line,
    total_line,
):
    state = complete_zero_state()
    set_amount(state, taxable_line, "2")
    set_amount(state, total_line, "1")

    problems = find_problems(state)

    assert any(
        problem.target == "computation"
        and problem.line == taxable_line
        and total_line in problem.reason
        for problem in problems
    )


def test_review_rejects_refund_and_amount_owed_both_positive():
    state = complete_zero_state()
    set_amount(state, "34", "10")
    set_amount(state, "37", "5")

    problems = find_problems(state)

    assert any(
        problem.target == "computation"
        and problem.line == "34"
        and "both positive" in problem.reason
        for problem in problems
    )


def test_review_detects_incorrect_total_income():
    state = complete_zero_state()
    set_amount(state, "9", "1")

    problems = find_problems(state)

    assert any(
        problem.line == "9"
        and "recompute" in problem.reason
        for problem in problems
    )


def test_review_detects_missing_provenance():
    state = complete_zero_state()

    # Deliberately bypass Pydantic validation to simulate corrupted state.
    state["lines"]["16"] = LineValue.model_construct(
        line="16",
        amount=Decimal("0"),
        provenance=[],
        depends_on=[],
    )

    problems = find_problems(state)

    assert any(
        problem.line == "16"
        and problem.reason == "no provenance record"
        for problem in problems
    )


def test_review_detects_unresolved_scope_issue_and_routes_to_rules():
    state = complete_zero_state()

    state["rule_decisions"]["scope"] = RuleDecision(
        rule_id="scope",
        outcome={"issues": ["out_of_scope:nec-1"]},
        explanation="Unsupported document found.",
        citation="policy.md#scope",
    )

    problems = find_problems(state)

    assert any(
        problem.target == "rules"
        and problem.line is None
        and "out_of_scope:nec-1" in problem.reason
        for problem in problems
    )


def test_review_does_not_modify_lines():
    state = complete_zero_state(stub_line="16")
    before = {
        line: value.model_dump(mode="json")
        for line, value in state["lines"].items()
    }

    update = review(state)

    after = {
        line: value.model_dump(mode="json")
        for line, value in state["lines"].items()
    }

    assert after == before
    assert "lines" not in update
    assert update["revision_requests"]


def test_corrected_return_is_reviewed_again_and_can_pass():
    first_state = complete_zero_state(stub_line="16")

    first_review = review(first_state)

    assert first_review["review_status"] == "failed"
    assert first_review["review_passes"] == 1

    corrected_state = _source_state()
    corrected_state["review_passes"] = first_review["review_passes"]

    second_review = review(corrected_state)

    assert second_review["review_status"] == "passed"
    assert second_review["revision_requests"] == []
    assert second_review["review_passes"] == 2

# --- Source-to-line validation (Security / Review enhancement, step 1) ---


def _source_state() -> dict:
    """Real documents/answers and lines produced by the existing computation code."""
    origin = Provenance(kind="document", source="test fixture", value="typed case data")
    documents = {
        "w2-1": W2Record(document_id="w2-1", source=origin, employer_name="Test Employer A",
                         wages="18000", federal_withheld="1500"),
        "w2-2": W2Record(document_id="w2-2", source=origin, employer_name="Test Employer B",
                         wages="2000", federal_withheld="200"),
        "int-1": Interest1099(document_id="int-1", source=origin, payer_name="Test Bank",
                              interest="420", tax_exempt_interest="80", federal_withheld="10"),
        "div-1": Dividend1099(document_id="div-1", source=origin, payer_name="Test Broker",
                              ordinary_dividends="500", qualified_dividends="200", federal_withheld="20"),
        "ira-1": Retirement1099R(document_id="ira-1", source=origin, payer_name="Test IRA",
                                 gross_distribution="6000", taxable_amount="6000", ira_sep_simple=True,
                                 federal_withheld="600"),
        "pension-1": Retirement1099R(document_id="pension-1", source=origin, payer_name="Test Pension",
                                     gross_distribution="1000", taxable_amount="900", ira_sep_simple=False,
                                     federal_withheld="50"),
        "ssa-1": SSA1099(document_id="ssa-1", source=origin,
                         net_benefits="22000", federal_withheld="30"),
    }
    state = {
        "documents": documents,
        "answers": [
            IntakeAnswer(field="filing_status", value="single"),
            IntakeAnswer(field="taxpayer_dob", value="1957-05-01"),
            IntakeAnswer(field="adjustments", value="0"),
            IntakeAnswer(field="estimated_payments", value="1000"),
        ],
        "rule_decisions": {
            "scope": RuleDecision(rule_id="scope", outcome={"issues": []},
                                  explanation="All documents in scope", citation="policy.md#scope"),
            "age_blind_boxes": RuleDecision(rule_id="age_blind_boxes", outcome={"count": 1},
                                            explanation="Age 65+", citation="policy.md#standard-deduction"),
            "senior_deduction_count": RuleDecision(rule_id="senior_deduction_count", outcome=1,
                                                   explanation="Senior qualifies", citation="policy.md#senior-deduction"),
            "social_security_base": RuleDecision(rule_id="social_security_base",
                                                outcome={"mfs_lived_with_spouse": False},
                                                explanation="Single filer", citation="policy.md#social-security"),
        },
        "escalations": {},
        "review_passes": 0,
    }
    state["lines"] = computation(state)["lines"]
    return state


def test_source_lines_pass_for_multiple_real_documents_and_intake():
    state = _source_state()

    assert check_source_lines(state) == []
    assert find_problems(state) == []
    assert review(state)["review_status"] == "passed"
    assert state["lines"]["1z"].amount == Decimal("20000.00")
    assert state["lines"]["25b"].amount == Decimal("710.00")


@pytest.mark.parametrize(
    ("document_id", "field", "line"),
    [
        ("w2-1", "wages", "1z"),
        ("int-1", "tax_exempt_interest", "2a"),
        ("int-1", "interest", "2b"),
        ("div-1", "qualified_dividends", "3a"),
        ("div-1", "ordinary_dividends", "3b"),
        ("ira-1", "gross_distribution", "4a"),
        ("ira-1", "taxable_amount", "4b"),
        ("pension-1", "gross_distribution", "5a"),
        ("pension-1", "taxable_amount", "5b"),
        ("ssa-1", "net_benefits", "6a"),
        ("w2-1", "federal_withheld", "25a"),
        ("ssa-1", "federal_withheld", "25b"),
    ],
)
def test_review_detects_stale_line_after_source_record_changes(document_id, field, line):
    state = _source_state()
    # Keep *all* draft lines internally consistent: only the source record changes.
    # The old Review passed this; the independent source check must reject it.
    original = state["documents"][document_id]
    state["documents"][document_id] = original.model_copy(
        update={field: getattr(original, field) + Decimal("25")}
    )
    before = {key: value.model_dump(mode="json") for key, value in state["lines"].items()}

    problems = find_problems(state)
    assert any(p.target == "computation" and p.line == line
               and "source documents" in p.reason for p in problems)
    assert review(state)["review_status"] == "failed"
    assert before == {key: value.model_dump(mode="json") for key, value in state["lines"].items()}


@pytest.mark.parametrize(("field", "line"), [("adjustments", "10"), ("estimated_payments", "26")])
def test_review_checks_latest_confirmed_intake_amount(field, line):
    state = _source_state()
    state["answers"].append(IntakeAnswer(field=field, value="2222"))
    problems = check_source_lines(state)
    assert any(p.target == "computation" and p.line == line for p in problems)


def test_review_requests_missing_intake_evidence_instead_of_passing():
    state = _source_state()
    state["answers"] = [a for a in state["answers"] if a.field != "estimated_payments"]
    problems = check_source_lines(state)
    assert any(p.target == "intake" and p.field == "estimated_payments" for p in problems)


def test_review_requests_missing_source_ledger_instead_of_assuming_zero():
    state = _source_state()
    del state["documents"]
    problems = check_source_lines(state)
    assert any(p.target == "intake" and p.field == "document_inventory" for p in problems)


def test_review_allows_explicitly_empty_document_inventory():
    state = complete_zero_state()
    del state["documents"]
    state["document_inventory"] = []
    assert check_source_lines(state) == []


def test_review_rejects_document_listed_but_not_extracted():
    state = _source_state()
    state["document_inventory"] = [DocumentRef(document_id="w2-missing", form_type="W-2")]
    problems = check_source_lines(state)
    assert any(p.target == "extraction" and p.document_id == "w2-missing" for p in problems)


# --- Deterministic independent tax-rule checks (Security / Review step 2) ---


def _retotal_after_tax_line_change(state):
    """Keep the draft internally arithmetically consistent despite a seeded error.

    The old Review used only these total relationships, so it would pass the
    manipulated drafts below. Recalculate downstream lines using real tools.
    """
    amounts = {line: value.amount for line, value in state["lines"].items()}

    def set_derived(line, tool, **kwargs):
        result, _ = call_tool(tool, **kwargs)
        set_amount(state, line, str(result))
        amounts[line] = result

    set_derived("9", "sum", values=[amounts[x] for x in ("1z", "2b", "3b", "4b", "5b", "6b")])
    set_derived("11a", "subtract", a=amounts["9"], b=amounts["10"])
    # If the target is the Senior Deduction, do not 'correct' the seeded error.
    set_derived("14", "sum", values=[amounts["12e"], amounts["13b"]])
    set_derived("15", "subtract_floor_zero", a=amounts["11a"], b=amounts["14"])
    set_derived("24", "sum", values=[amounts["16"]])
    set_derived("34", "subtract_floor_zero", a=amounts["33"], b=amounts["24"])
    set_derived("37", "subtract_floor_zero", a=amounts["24"], b=amounts["33"])


@pytest.mark.parametrize("line", ["6b", "12e", "13b", "16"])
def test_rule_recalculation_detects_internally_consistent_wrong_tax_line(line):
    state = _source_state()
    original = state["lines"][line].amount
    # Keep Social Security taxable <= total benefit when tampering.
    changed = original + Decimal("10")
    if line == "6b" and changed > state["lines"]["6a"].amount:
        changed = original - Decimal("10")
    set_amount(state, line, str(changed))
    _retotal_after_tax_line_change(state)

    assert check_source_lines(state) == []  # no source transcription problem
    rule_errors = check_tax_rules(state)
    assert any(r.target == "computation" and r.line == line
               and "tax_math." in r.reason for r in rule_errors)
    assert any(r.line == line for r in find_problems(state))
    assert review(state)["review_status"] == "failed"


def test_tax_rule_check_accepts_valid_derived_values():
    state = _source_state()
    assert check_tax_rules(state) == []
    assert review(state)["review_status"] == "passed"


def test_age_blind_decision_cannot_hide_wrong_count_from_review():
    state = _source_state()
    original = state["rule_decisions"]["age_blind_boxes"]
    forged = {**original.outcome, "count": 2}
    state["rule_decisions"]["age_blind_boxes"] = original.model_copy(update={"outcome": forged})
    # A fraudulent decision also makes the existing amount look plausible.
    set_amount(state, "12e", "19750")
    _retotal_after_tax_line_change(state)
    requests = check_tax_rules(state)
    assert any(r.target == "rules" and r.field == "age_blind_boxes" for r in requests)
    assert any(r.target == "computation" and r.line == "12e" for r in requests)
    assert requests.index(next(r for r in requests if r.target == "rules" and r.field == "age_blind_boxes")) < requests.index(next(r for r in requests if r.target == "computation" and r.line == "12e"))


def test_senior_count_decision_cannot_hide_wrong_count_from_review():
    state = _source_state()
    original = state["rule_decisions"]["senior_deduction_count"]
    state["rule_decisions"]["senior_deduction_count"] = original.model_copy(update={"outcome": 0})
    set_amount(state, "13b", "0")
    _retotal_after_tax_line_change(state)
    requests = check_tax_rules(state)
    assert any(r.target == "rules" and r.field == "senior_deduction_count" for r in requests)
    assert any(r.target == "computation" and r.line == "13b" for r in requests)


@pytest.mark.parametrize("rule_name,line", [
    ("social_security_base", "6b"),
    ("age_blind_boxes", "12e"),
    ("senior_deduction_count", "13b"),
])
def test_review_rejects_missing_tax_rule_decision(rule_name, line):
    state = _source_state()
    del state["rule_decisions"][rule_name]
    requests = check_tax_rules(state)
    assert any(r.target == "rules" and r.line == line for r in requests)
    assert any(r.target == "computation" and r.line == line for r in requests)


def test_missing_filing_status_requests_intake_not_tool_arithmetic():
    state = _source_state()
    state["answers"] = [a for a in state["answers"] if a.field != "filing_status"]
    requests = check_tax_rules(state)
    assert any(r.target == "intake" and r.field == "filing_status" for r in requests)


def test_review_tax_rule_check_does_not_mutate_amounts_or_decisions():
    state = _source_state()
    set_amount(state, "16", "1234")
    before_lines = {k: v.model_dump(mode="json") for k, v in state["lines"].items()}
    before_rules = {k: v.model_dump(mode="json") for k, v in state["rule_decisions"].items()}
    check_tax_rules(state)
    assert before_lines == {k: v.model_dump(mode="json") for k, v in state["lines"].items()}
    assert before_rules == {k: v.model_dump(mode="json") for k, v in state["rule_decisions"].items()}


def test_joint_filers_both_seniors_are_recalculated_with_two_eligible_people():
    state = _source_state()
    state["answers"] = [
        a for a in state["answers"] if a.field != "filing_status"
    ] + [
        IntakeAnswer(field="filing_status", value="mfj"),
        IntakeAnswer(field="spouse_dob", value="1959-04-20"),
    ]
    first = state["rule_decisions"]["age_blind_boxes"]
    state["rule_decisions"]["age_blind_boxes"] = first.model_copy(
        update={"outcome": {"count": 2, "taxpayer_65": True, "spouse_65": True}}
    )
    second = state["rule_decisions"]["senior_deduction_count"]
    state["rule_decisions"]["senior_deduction_count"] = second.model_copy(update={"outcome": 2})
    state["lines"] = computation(state)["lines"]
    assert state["lines"]["12e"].amount == Decimal("34700.00")
    assert state["lines"]["13b"].amount == Decimal("12000.00")
    assert check_tax_rules(state) == []


def test_mfs_social_security_uses_correct_residence_case():
    state = _source_state()
    state["answers"] = [a for a in state["answers"] if a.field != "filing_status"] + [
        IntakeAnswer(field="filing_status", value="mfs"),
        IntakeAnswer(field="mfs_lived_with_spouse", value=True),
    ]
    seniors = state["rule_decisions"]["senior_deduction_count"]
    state["rule_decisions"]["senior_deduction_count"] = seniors.model_copy(update={"outcome": 0})
    base = state["rule_decisions"]["social_security_base"]
    state["rule_decisions"]["social_security_base"] = base.model_copy(
        update={"outcome": {"case": "mfs_lived_with_spouse", "mfs_lived_with_spouse": True}}
    )
    state["lines"] = computation(state)["lines"]
    assert check_tax_rules(state) == []
    state["rule_decisions"]["social_security_base"] = base.model_copy(
        update={"outcome": {"case": "standard", "mfs_lived_with_spouse": False}}
    )
    requests = check_tax_rules(state)
    assert any(r.line == "6b" and r.target == "rules" and r.field == "social_security_base" for r in requests)
    assert any(r.line == "6b" and r.target == "computation" for r in requests)

# --- Provenance integrity verification (Security / Review enhancement, step 3) ---


def _replace_provenance(state, line, index, **changes):
    record = state["lines"][line]
    evidence = list(record.provenance)
    evidence[index] = evidence[index].model_copy(update=changes)
    state["lines"][line] = record.model_copy(update={"provenance": evidence})


def test_provenance_audit_passes_real_source_and_tool_evidence():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    assert check_provenance_integrity(state) == []
    assert find_problems(state) == []


@pytest.mark.parametrize("alteration", ["unknown_id", "wrong_field", "wrong_amount", "wrong_snapshot",
                                       "wrong_timestamp", "wrong_source_label"])
def test_provenance_audit_rejects_forged_document_evidence(alteration):
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    source = state["lines"]["1z"].provenance[0]
    changes = {
        "unknown_id": {"inputs": {**source.inputs, "document_id": "unknown-document"}},
        "wrong_field": {"inputs": {**source.inputs, "field": "federal_withheld"}},
        "wrong_amount": {"value": Decimal("999.00")},
        "wrong_snapshot": {"inputs": {**source.inputs, "record_source": {"forged": True}}},
        "wrong_timestamp": {"recorded_at": source.recorded_at.replace(year=2020)},
        "wrong_source_label": {"source": "W-2 w2-1, box 2"},
    }[alteration]
    _replace_provenance(state, "1z", 0, **changes)

    assert any(r.target == "computation" and r.line == "1z"
               for r in check_provenance_integrity(state))
    assert review(state)["review_status"] == "failed"


def test_provenance_audit_rejects_duplicate_document_source_even_when_total_matches():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    line = state["lines"]["1z"]
    evidence = [line.provenance[0], line.provenance[0], line.provenance[-1]]
    state["lines"]["1z"] = line.model_copy(update={"provenance": evidence})
    assert any(r.line == "1z" and "document provenance" in r.reason
               for r in check_provenance_integrity(state))


@pytest.mark.parametrize("alteration", ["wrong_source", "wrong_value", "wrong_author", "wrong_timestamp"])
def test_provenance_audit_rejects_forged_intake_evidence(alteration):
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    source = state["lines"]["26"].provenance[0]
    changes = {
        "wrong_source": {"source": "intake: adjustments"},
        "wrong_value": {"value": Decimal("500")},
        "wrong_author": {"entered_by": "forged-staff"},
        "wrong_timestamp": {"recorded_at": source.recorded_at.replace(year=2020)},
    }[alteration]
    _replace_provenance(state, "26", 0, **changes)
    requests = check_provenance_integrity(state)
    assert any(r.line == "26" and r.target == "computation" for r in requests)


@pytest.mark.parametrize("alteration", ["wrong_tool", "wrong_inputs", "wrong_result", "missing_tool"])
def test_provenance_audit_rejects_forged_tool_call(alteration):
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    item = state["lines"]["9"].provenance[0]
    if alteration == "missing_tool":
        state["lines"]["9"] = state["lines"]["9"].model_copy(update={"provenance": []})
    else:
        changes = {
            "wrong_tool": {"source": "tax_math.subtract"},
            "wrong_inputs": {"inputs": {"values": [Decimal("999")]}},
            "wrong_result": {"value": Decimal("999")},
        }[alteration]
        _replace_provenance(state, "9", 0, **changes)
    requests = check_provenance_integrity(state)
    assert any(r.target == "computation" and r.line == "9" for r in requests)
    assert review(state)["review_status"] == "failed"


def test_provenance_audit_rejects_mismatched_rule_citation():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    _replace_provenance(state, "12e", 0, citation="policy.md#forged")
    requests = check_provenance_integrity(state)
    assert any(r.target == "computation" and r.line == "12e" for r in requests)


def test_provenance_audit_rejects_wrong_dependencies_even_if_amounts_are_correct():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    state["lines"]["16"] = state["lines"]["16"].model_copy(update={"depends_on": ["11a"]})
    requests = check_provenance_integrity(state)
    assert any(r.target == "computation" and r.line == "16" and "dependency" in r.reason
               for r in requests)


def test_provenance_audit_read_only_and_revisions_are_sanitized():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    _replace_provenance(state, "1z", 0, value=Decimal("1000000"))
    before = {k: v.model_dump(mode="json") for k, v in state["lines"].items()}
    requests = check_provenance_integrity(state)
    assert requests and all("1000000" not in r.reason for r in requests)
    assert before == {k: v.model_dump(mode="json") for k, v in state["lines"].items()}


def test_provenance_audit_accepts_document_upload_order_different_from_tax_line_order():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    docs = state["documents"]
    # Computation sorts the 1099 withholding groups into 25b in a distinct
    # order. Review must not confuse a valid upload order with fabricated data.
    state["documents"] = {key: docs[key] for key in reversed(list(docs))}
    state["lines"] = computation(state)["lines"]
    assert check_provenance_integrity(state) == []
    assert find_problems(state) == []


def test_provenance_audit_missing_rule_decision_schedules_rules_then_recompute():
    from src.agents.review import check_provenance_integrity

    state = _source_state()
    del state["rule_decisions"]["senior_deduction_count"]
    requests = [r for r in check_provenance_integrity(state) if r.line == "13b"]
    assert requests[0].target == "rules"
    assert any(r.target == "computation" for r in requests[1:])
