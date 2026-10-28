"""Client side of the tax_math tools. Computation and Review get every number through call_tool().

For now the tools run locally: the plain sums here, and the four tax rules from src/tax_math/rules.py.
Step 3 swaps this file for calls to the tax_math MCP server; agents do not change.
The rule functions stay exact; call_tool() rounds each result to cents, half up, once.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from src.schemas import Provenance
from src.tax_math import rules


def _sum(values):
    return sum((Decimal(v) for v in values), Decimal("0"))


def _subtract(a, b):
    return Decimal(a) - Decimal(b)


def _subtract_floor_zero(a, b):
    return max(Decimal("0"), Decimal(a) - Decimal(b))


CENT = Decimal("0.01")


class ToolInputError(ValueError):
    """A sanitized tool failure containing field names, never rejected values."""

    def __init__(self, tool: str, fields: tuple[str, ...]):
        self.tool = tool
        self.fields = fields
        named = ", ".join(fields) if fields else "input"
        super().__init__(
            f"tax_math.{tool} rejected invalid field(s): {named}"
        )


def _invalid_fields(message: str, inputs: dict) -> tuple[str, ...]:
    """Identify likely fields from an error without retaining its raw text."""

    normalized = message.lower().replace("_", " ")
    matched = tuple(
        sorted(
            name
            for name in inputs
            if name.lower().replace("_", " ") in normalized
        )
    )
    return matched or tuple(sorted(inputs))


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
    try:
        result = fn(**inputs).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    except (ValueError, InvalidOperation, TypeError) as exc:
        fields = _invalid_fields(str(exc), inputs)
        raise ToolInputError(name, fields) from None

    return result, Provenance(
        kind="tool",
        source=f"tax_math.{name}",
        value=result,
        inputs=inputs,
        stub=is_stub,
    )