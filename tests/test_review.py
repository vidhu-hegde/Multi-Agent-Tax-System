"""Safety-gate tests for Qiyan's Review/Audit responsibilities."""

import pytest
from decimal import Decimal

from src.agents.review import check_source_lines, find_problems, review
from src.schemas import (
    FORM_LINES, LineValue, Provenance, RuleDecision, IntakeAnswer,
    W2Record, Interest1099, Dividend1099, Retirement1099R, SSA1099, DocumentRef,
)
from tests.conftest import SKELETON_CASE
from src.tools import TOOLS
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

    corrected_state = complete_zero_state()
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
