"""Safety-gate tests for Qiyan's Review/Audit responsibilities."""

import pytest
from decimal import Decimal

from src.agents.review import find_problems, review
from src.schemas import FORM_LINES, LineValue, Provenance, RuleDecision
from tests.conftest import SKELETON_CASE
from src.tools import TOOLS


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