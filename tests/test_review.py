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