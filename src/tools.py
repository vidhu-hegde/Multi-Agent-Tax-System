"""Client side of the tax_math tools. Computation and Review get every number through call_tool().

For now the tools run locally: the plain sums are real, and the four tax rules are STUBS that return 0
and mark their provenance stub=True. Step 3 swaps this file for calls to the tax_math MCP server;
agents do not change.
"""

from decimal import Decimal

from src.schemas import Provenance


def _sum(values):
    return sum((Decimal(v) for v in values), Decimal("0"))


def _subtract(a, b):
    return Decimal(a) - Decimal(b)


def _subtract_floor_zero(a, b):
    return max(Decimal("0"), Decimal(a) - Decimal(b))


def _stub(**_):
    return Decimal("0")


# name -> (function, is_stub)
TOOLS = {
    "sum": (_sum, False),
    "subtract": (_subtract, False),
    "subtract_floor_zero": (_subtract_floor_zero, False),
    "standard_deduction": (_stub, True),
    "senior_deduction": (_stub, True),
    "taxable_social_security": (_stub, True),
    "tax_from_schedule": (_stub, True),
}


def call_tool(name: str, **inputs) -> tuple[Decimal, Provenance]:
    fn, is_stub = TOOLS[name]
    result = fn(**inputs)
    return result, Provenance(kind="tool", source=f"tax_math.{name}", value=result, inputs=inputs, stub=is_stub)
