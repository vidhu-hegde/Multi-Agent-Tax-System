"""Every tax_math tool by name. src/tools.py (in-process) and src/tax_math/server.py (MCP) share these functions."""

from decimal import Decimal

from src.tax_math import rules


def _sum(values):
    return sum((Decimal(v) for v in values), Decimal("0"))


def _subtract(a, b):
    return Decimal(a) - Decimal(b)


def _subtract_floor_zero(a, b):
    return max(Decimal("0"), Decimal(a) - Decimal(b))


FUNCTIONS = {
    "sum": _sum,
    "subtract": _subtract,
    "subtract_floor_zero": _subtract_floor_zero,
    "standard_deduction": rules.standard_deduction,
    "senior_deduction": rules.senior_deduction,
    "taxable_social_security": rules.taxable_social_security,
    "tax_from_schedule": rules.tax_from_schedule,
}
