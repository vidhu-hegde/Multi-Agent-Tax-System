"""The four 2025 Form 1040-SR tax rules, as pure functions. Source: docs/tax_math_rules_spec.md.

All money is Decimal. Invalid input raises ValueError instead of returning a guess, so a bad value
surfaces as an escalation rather than a silent zero. Results are not rounded.
"""

from decimal import Decimal

FILING_STATUSES = ("single", "mfj", "mfs", "hoh", "qss")

ZERO = Decimal("0")

# Standard deduction chart, Form 1040-SR page 4: status -> amount for 1, 2, 3, 4 boxes checked on line 12d.
STANDARD_DEDUCTION_CHART = {
    "single": (Decimal("17750"), Decimal("19750")),
    "mfj": (Decimal("33100"), Decimal("34700"), Decimal("36300"), Decimal("37900")),
    "qss": (Decimal("33100"), Decimal("34700")),
    "hoh": (Decimal("25625"), Decimal("27625")),
    "mfs": (Decimal("17350"), Decimal("18950"), Decimal("20550"), Decimal("22150")),
}

# Schedule 1-A Part V.
SENIOR_AMOUNT = Decimal("6000")
SENIOR_PHASEOUT_RATE = Decimal("0.06")

# Rev. Proc. 2024-40 section 2.01: status -> [(bracket lower bound, base tax, rate)].
_RATES = (Decimal("0.10"), Decimal("0.12"), Decimal("0.22"), Decimal("0.24"),
          Decimal("0.32"), Decimal("0.35"), Decimal("0.37"))


def _schedule(bounds, bases):
    return tuple(zip((Decimal(b) for b in bounds), (Decimal(b) for b in bases), _RATES))


_JOINT_SCHEDULE = _schedule(
    ("0", "23850", "96950", "206700", "394600", "501050", "751600"),
    ("0", "2385", "11157", "35302", "80398", "114462", "202154.50"),
)
TAX_RATE_SCHEDULES = {
    "single": _schedule(
        ("0", "11925", "48475", "103350", "197300", "250525", "626350"),
        ("0", "1192.50", "5578.50", "17651", "40199", "57231", "188769.75"),
    ),
    "mfj": _JOINT_SCHEDULE,
    "qss": _JOINT_SCHEDULE,
    "hoh": _schedule(
        ("0", "17000", "64850", "103350", "197300", "250500", "626350"),
        ("0", "1700", "7442", "15912", "38460", "55484", "187031.50"),
    ),
    "mfs": _schedule(
        ("0", "11925", "48475", "103350", "197300", "250525", "375800"),
        ("0", "1192.50", "5578.50", "17651", "40199", "57231", "101077.25"),
    ),
}


def _status(filing_status):
    if filing_status not in FILING_STATUSES:
        raise ValueError(f"unknown filing status {filing_status!r}; expected one of {', '.join(FILING_STATUSES)}")
    return filing_status


def _count(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    return value


def _money(name, value, allow_negative=False):
    """Decimal from Decimal, int or str. Floats are refused: they cannot hold cents exactly."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError(f"{name} must be a Decimal, int or str amount, got {value!r}")
    try:
        amount = Decimal(value)
    except ArithmeticError:
        raise ValueError(f"{name} is not a valid amount: {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"{name} must be a finite amount, got {value!r}")
    if amount < 0 and not allow_negative:
        raise ValueError(f"{name} cannot be negative, got {amount}")
    return amount


def standard_deduction(filing_status, boxes):
    """Form 1040-SR line 12e from the page 4 chart. `boxes` is the line 12d count (1 or more)."""
    row = STANDARD_DEDUCTION_CHART[_status(filing_status)]
    boxes = _count("boxes", boxes)
    if not 1 <= boxes <= len(row):
        raise ValueError(f"{boxes} boxes is not possible for {filing_status}; the chart allows 1 to {len(row)}")
    return row[boxes - 1]


def senior_deduction(filing_status, magi, qualifying_people):
    """Schedule 1-A Part V, lines 31-37 -> Form 1040-SR line 13b. Counting people is the Rules agent's job."""
    _status(filing_status)
    magi = _money("magi", magi, allow_negative=True)
    qualifying_people = _count("qualifying_people", qualifying_people)
    most = 2 if filing_status == "mfj" else 0 if filing_status == "mfs" else 1
    if not 0 <= qualifying_people <= most:
        raise ValueError(f"{qualifying_people} qualifying people is not possible for {filing_status}; "
                         f"the most is {most}")
    threshold = Decimal("150000") if filing_status == "mfj" else Decimal("75000")  # line 32
    excess = max(ZERO, magi - threshold)  # line 33
    per_person = max(ZERO, SENIOR_AMOUNT - SENIOR_PHASEOUT_RATE * excess)  # lines 34-35
    return per_person * qualifying_people  # lines 36a, 36b, 37


def taxable_social_security(filing_status, benefits, other_income, tax_exempt_interest, adjustments,
                            lived_with_spouse=None):
    """Publication 915 Worksheet 1 -> Form 1040-SR line 6b.

    `other_income` holds lines 1z, 2b, 3b, 4b and 5b. `lived_with_spouse` matters only for `mfs`: True
    means no base amount, False uses the $25,000 base, and None raises ValueError when there are benefits.
    """
    _status(filing_status)
    benefits = _money("benefits", benefits)
    other = sum((_money("other_income", v) for v in other_income), ZERO)
    tax_exempt_interest = _money("tax_exempt_interest", tax_exempt_interest)
    adjustments = _money("adjustments", adjustments)
    if benefits == 0:
        return ZERO
    if filing_status == "mfs" and lived_with_spouse is None:
        raise ValueError("mfs needs lived_with_spouse to choose the base amount")

    half = benefits / 2  # line 2
    cap = Decimal("0.85") * benefits  # line 18
    line6 = half + other + tax_exempt_interest  # lines 3-6
    if adjustments >= line6:  # lines 7-8
        return ZERO
    line8 = line6 - adjustments
    # MFS filers who lived with their spouse at any time in 2025 have no base amount (Pub. 915).
    if filing_status == "mfs" and lived_with_spouse is True:
        return min(Decimal("0.85") * line8, cap)

    joint = filing_status == "mfj"
    line10 = line8 - (Decimal("32000") if joint else Decimal("25000"))  # lines 9-10
    if line10 <= 0:
        return ZERO
    tier = Decimal("12000") if joint else Decimal("9000")  # line 11
    line12 = max(ZERO, line10 - tier)
    line13 = min(line10, tier)
    line15 = min(half, line13 / 2)  # lines 14-15
    line17 = line15 + Decimal("0.85") * line12  # lines 16-17
    return min(line17, cap)  # line 19


def tax_from_schedule(filing_status, taxable_income):
    """Form 1040-SR line 16 from the 2025 tax rate schedules: base + rate * (income - lower bound).

    Exact to the cent; whether to round to whole dollars, or to use the Tax Table under $100,000, is
    still an open decision (spec section 4).
    """
    schedule = TAX_RATE_SCHEDULES[_status(filing_status)]
    income = _money("taxable_income", taxable_income)
    lower, base, rate = next(row for row in reversed(schedule) if income >= row[0])
    return base + rate * (income - lower)
