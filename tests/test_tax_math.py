"""Tax rules from docs/tax_math_rules_spec.md, section 5 test vectors."""

from decimal import Decimal

import pytest

from src.tax_math.rules import (
    STANDARD_DEDUCTION_CHART,
    TAX_RATE_SCHEDULES,
    senior_deduction,
    standard_deduction,
    tax_from_schedule,
    taxable_social_security,
)
from src.tools import call_tool

D = Decimal


@pytest.mark.parametrize(
    "status, boxes, expected",
    [("single", 1, "17750"), ("mfj", 2, "34700"), ("hoh", 1, "25625"), ("mfs", 4, "22150")],
)
def test_standard_deduction(status, boxes, expected):
    assert standard_deduction(status, boxes) == D(expected)


@pytest.mark.parametrize("status, boxes", [("single", 3), ("single", 0), ("mfj", 5), ("qss", 3), ("hoh", -1)])
def test_standard_deduction_rejects_impossible_box_counts(status, boxes):
    with pytest.raises(ValueError):
        standard_deduction(status, boxes)


def test_standard_deduction_chart_is_base_plus_boxes_times_per_box_addition():
    # data/policy.md base amounts and per-box additions (spec section 6.4)
    policy = {
        "single": (D("15750"), D("2000")),
        "hoh": (D("23625"), D("2000")),
        "mfj": (D("31500"), D("1600")),
        "qss": (D("31500"), D("1600")),
        "mfs": (D("15750"), D("1600")),
    }
    assert set(STANDARD_DEDUCTION_CHART) == set(policy)
    for status, row in STANDARD_DEDUCTION_CHART.items():
        base, per_box = policy[status]
        for boxes, amount in enumerate(row, start=1):
            assert amount == base + boxes * per_box, (status, boxes)


@pytest.mark.parametrize(
    "status, magi, people, expected",
    [
        ("single", "75000", 1, "6000"),
        ("single", "85000", 1, "5400"),
        ("single", "100000", 1, "4500"),
        ("single", "175000", 1, "0"),
        ("mfj", "150000", 2, "12000"),
        ("mfj", "160000", 2, "10800"),
        ("mfs", "50000", 0, "0"),
        ("mfs", "500000", 0, "0"),
    ],
)
def test_senior_deduction(status, magi, people, expected):
    assert senior_deduction(status, D(magi), people) == D(expected)


@pytest.mark.parametrize("status, people", [("mfs", 1), ("single", 2), ("mfj", 3), ("hoh", -1)])
def test_senior_deduction_rejects_impossible_counts(status, people):
    with pytest.raises(ValueError):
        senior_deduction(status, D("50000"), people)


@pytest.mark.parametrize(
    "benefits, other_income, expected",
    [
        ("5980", ["28990"], "2990"),  # Pub. 915 Example 1
        ("10000", ["15000"], "0"),
        ("20000", ["40000"], "17000"),  # the 85% cap binds
    ],
)
def test_taxable_social_security(benefits, other_income, expected):
    result = taxable_social_security("single", D(benefits), [D(v) for v in other_income], D("0"), D("0"))
    assert result == D(expected)


@pytest.mark.parametrize("lived_with_spouse", [False])
def test_taxable_social_security_mfs_not_lived_with_spouse_uses_the_25000_base(lived_with_spouse):
    # l8 = 10,000 + 20,000 = 30,000; l10 = 5,000; l13 = 5,000; l15 = min(10,000, 2,500) = 2,500
    result = taxable_social_security("mfs", D("20000"), [D("20000")], D("0"), D("0"),
                                     lived_with_spouse=lived_with_spouse)
    assert result == D("2500")
    assert result == taxable_social_security("single", D("20000"), [D("20000")], D("0"), D("0"))


def test_taxable_social_security_mfs_without_lived_with_spouse_raises():
    with pytest.raises(ValueError, match="lived_with_spouse"):
        taxable_social_security("mfs", D("20000"), [D("20000")], D("0"), D("0"), lived_with_spouse=None)


def test_taxable_social_security_mfs_lived_with_spouse_has_no_base_amount():
    # l8 = 10,000 + 20,000 = 30,000; 0.85 * 30,000 = 25,500, capped at 0.85 * 20,000 = 17,000
    assert taxable_social_security("mfs", D("20000"), [D("20000")], D("0"), D("0"), lived_with_spouse=True) \
        == D("17000")
    # l8 = 5,000 + 2,000 = 7,000; 0.85 * 7,000 = 5,950, below the 8,500 cap
    assert taxable_social_security("mfs", D("10000"), [D("2000")], D("0"), D("0"), lived_with_spouse=True) \
        == D("5950")


@pytest.mark.parametrize("status", ["single", "mfj", "hoh", "qss"])
@pytest.mark.parametrize("lived_with_spouse", [True, False])
def test_taxable_social_security_ignores_lived_with_spouse_outside_mfs(status, lived_with_spouse):
    args = (status, D("20000"), [D("40000")], D("0"), D("0"))
    assert taxable_social_security(*args, lived_with_spouse=lived_with_spouse) == taxable_social_security(*args)


@pytest.mark.parametrize("status", ["single", "mfs"])
def test_taxable_social_security_is_zero_without_benefits(status):
    assert taxable_social_security(status, D("0"), [D("500000")], D("0"), D("0"), lived_with_spouse=True) == D("0")


@pytest.mark.parametrize(
    "status, income, expected",
    [
        ("single", "11925", "1192.50"),
        ("single", "50000", "5914.00"),
        ("hoh", "17000", "1700"),
        ("mfj", "100000", "11828"),
        ("mfs", "400000", "110031.25"),
    ],
)
def test_tax_from_schedule(status, income, expected):
    assert tax_from_schedule(status, D(income)) == D(expected)


def test_tax_rate_schedule_base_amounts_are_continuous():
    for status, schedule in TAX_RATE_SCHEDULES.items():
        for (lower, base, rate), (next_lower, next_base, _) in zip(schedule, schedule[1:]):
            assert base + rate * (next_lower - lower) == next_base, (status, next_lower)


@pytest.mark.parametrize(
    "call",
    [
        lambda: standard_deduction("widowed", 1),
        lambda: standard_deduction("single", True),
        lambda: senior_deduction("single", 85000.0, 1),
        lambda: taxable_social_security("single", D("-1"), [], D("0"), D("0")),
        lambda: tax_from_schedule("single", D("-1")),
        lambda: tax_from_schedule("single", "abc"),
    ],
)
def test_invalid_input_raises(call):
    with pytest.raises(ValueError):
        call()


def test_call_tool_reports_real_tax_rules():
    result, provenance = call_tool("standard_deduction", filing_status="single", boxes=1)
    assert result == D("17750")
    assert provenance.stub is False
    assert provenance.source == "tax_math.standard_deduction"
