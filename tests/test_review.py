"""Safety-gate tests for Qiyan's Review/Audit responsibilities."""

import pytest
from decimal import Decimal

from src.agents.review import find_problems, review
from src.schemas import FORM_LINES, LineValue, Provenance, RuleDecision
from tests.conftest import SKELETON_CASE


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
def test_production_placeholder_tools_cannot_reach_draft_ready(make_graph):
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