"""Client side of the tax_math tools. Computation and Review get every number through call_tool().

For now the tools run locally: the plain sums here, and the four tax rules from src/tax_math/rules.py.
Step 3 swaps this file for calls to the tax_math MCP server; agents do not change.
"""

from decimal import Decimal

from src.schemas import Provenance
from src.tax_math import rules


def _sum(values):
    return sum((Decimal(v) for v in values), Decimal("0"))


def _subtract(a, b):
    return Decimal(a) - Decimal(b)


def _subtract_floor_zero(a, b):
    return max(Decimal("0"), Decimal(a) - Decimal(b))


# name -> (function, is_stub)
TOOLS = {
    "sum": (_sum, False),
    "subtract": (_subtract, False),
    "subtract_floor_zero": (_subtract_floor_zero, False),
    "standard_deduction": (rules.standard_deduction, False),
    "senior_deduction": (rules.senior_deduction, False),
    "taxable_social_security": (rules.taxable_social_security, False),
    "tax_from_schedule": (rules.tax_from_schedule, False),
}


def call_tool(name: str, **inputs) -> tuple[Decimal, Provenance]:
    fn, is_stub = TOOLS[name]
    result = fn(**inputs)
    return result, Provenance(kind="tool", source=f"tax_math.{name}", value=result, inputs=inputs, stub=is_stub)
