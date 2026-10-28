"""tax_math values over MCP. Amounts travel as strings, so no cent is lost to a JSON float.

The client encodes every Decimal as a string; the server turns money arguments back into Decimal.
Lists, booleans, ints and None pass through unchanged. Floats are sent as floats, so the rules
refuse them exactly as they do in-process.

Rule errors cross as `ToolError("<ExceptionName>: <message>")`; the client raises the same class.
"""

from decimal import Decimal, InvalidOperation

MONEY_ARGUMENTS = {
    "values", "a", "b", "magi", "benefits", "other_income", "tax_exempt_interest", "adjustments", "taxable_income",
}

# The exception classes call_tool() callers can see from a tool, in-process or over MCP.
RULE_ERRORS = {"ValueError": ValueError, "TypeError": TypeError, "InvalidOperation": InvalidOperation}


def encode(value):
    """Client side: Decimal -> str, recursively."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(name, value):
    """Server side: money strings -> Decimal. Anything that does not parse is left for the rule to reject."""
    if name not in MONEY_ARGUMENTS:
        return value
    if isinstance(value, list):
        return [decode(name, v) for v in value]
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


def rule_error(exc: Exception) -> str:
    """The marker the server puts on a rule error."""
    return f"{type(exc).__name__}: {exc}"


def raise_rule_error(tool: str, text: str) -> None:
    """Client side: re-raise a marked rule error; return if `text` carries no marker.

    The SDK reports a ToolError as "Error executing tool <tool>: <message>" (pinned by a test).
    """
    prefix = f"Error executing tool {tool}: "
    body = text[len(prefix):] if text.startswith(prefix) else text
    for name, cls in RULE_ERRORS.items():
        if body.startswith(f"{name}: "):
            raise cls(body[len(name) + 2:])
