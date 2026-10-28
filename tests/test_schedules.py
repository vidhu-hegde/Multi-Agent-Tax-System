"""Schedule 2 and 3 totals typed in at Intake flow into lines 20-24 and 31-33 through tax_math."""

import json
from decimal import Decimal

import pytest

from tests.conftest import SKELETON_CASE


def run_case(make_graph, tmp_path, **answers):
    case = json.loads(open(SKELETON_CASE).read())
    case["answers"].update(answers)
    path = tmp_path / "schedules.json"
    path.write_text(json.dumps(case))
    return make_graph().invoke({"case_path": str(path)}, {"configurable": {"thread_id": "schedules"}})


def amounts(result, *lines):
    return {line: result["lines"][line].amount for line in lines}


# The skeleton return has tax $644.50 (line 16) and payments $2,100 withheld + $1,000 estimated.
@pytest.mark.parametrize(
    "schedule2,credits,other_payments,expected",
    [
        # Every part nonzero: credits reduce tax, other taxes add to it, other payments add to payments.
        ("150", "100", "200", {"18": "644.50", "21": "100", "22": "544.50", "24": "694.50",
                               "32": "200", "33": "3300", "34": "2605.50", "37": "0"}),
        # Nonrefundable credits larger than the tax stop at zero; they never create a refund.
        ("0", "1000", "0", {"18": "644.50", "21": "1000", "22": "0", "24": "0",
                            "32": "0", "33": "3100", "34": "3100", "37": "0"}),
        # Schedule 2 tax large enough to turn the refund into an amount owed.
        ("4000", "0", "0", {"18": "644.50", "21": "0", "22": "644.50", "24": "4644.50",
                            "32": "0", "33": "3100", "34": "0", "37": "1544.50"}),
    ],
)
def test_schedule_totals_flow_into_the_draft(make_graph, tmp_path, schedule2, credits, other_payments, expected):
    result = run_case(
        make_graph, tmp_path,
        schedule2_total_tax=schedule2,
        schedule3_nonrefundable_credits=credits,
        schedule3_other_payments=other_payments,
    )
    assert result["status"] == "draft_ready"
    assert not result.get("escalations")
    assert result["review_status"] == "passed"
    assert amounts(result, "20", "23", "31") == {
        "20": Decimal(credits), "23": Decimal(schedule2), "31": Decimal(other_payments),
    }
    assert amounts(result, *expected) == {line: Decimal(value) for line, value in expected.items()}


def test_schedule_lines_cite_the_intake_answer_and_derived_lines_cite_a_tool(make_graph, tmp_path):
    result = run_case(make_graph, tmp_path, schedule2_total_tax="150", schedule3_nonrefundable_credits="100",
                      schedule3_other_payments="200")
    for line, field in (("20", "schedule3_nonrefundable_credits"), ("23", "schedule2_total_tax"),
                        ("31", "schedule3_other_payments")):
        [step] = result["lines"][line].provenance
        assert step.kind == "user_input"
        assert step.source == f"intake: {field}"
        assert step.entered_by == "case file"
    for line, tool, depends_on in (("22", "tax_math.subtract_floor_zero", ["18", "21"]),
                                   ("24", "tax_math.sum", ["22", "23"]),
                                   ("33", "tax_math.sum", ["25d", "26", "32"])):
        assert result["lines"][line].depends_on == depends_on
        assert [p.source for p in result["lines"][line].provenance if p.kind == "tool"] == [tool]


def test_review_sends_a_schedule_line_back_when_it_disagrees_with_intake(make_graph, tmp_path):
    from src.agents.review import find_problems

    result = run_case(make_graph, tmp_path, schedule2_total_tax="150")
    state = dict(result)
    state["lines"] = {**result["lines"], "23": result["lines"]["23"].model_copy(update={"amount": Decimal("15")})}
    problems = find_problems(state)
    assert any(p.target == "computation" and p.line == "23" for p in problems)
    assert any(p.line == "24" and "recompute" in p.reason for p in problems)
