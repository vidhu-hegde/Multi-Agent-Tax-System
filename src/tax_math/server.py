"""tax_math MCP server: the seven tools of src/tax_math/registry.py over streamable HTTP.

    python -m src.tax_math.server [--host 127.0.0.1] [--port 8001]    # serves http://<host>:<port>/mcp

The host defaults to TAX_MATH_MCP_HOST (127.0.0.1); Docker needs 0.0.0.0. On 127.0.0.1 the SDK checks the
Host header against localhost (DNS rebinding protection); on 0.0.0.0 it does not.

Results are exact decimal strings; call_tool() rounds them to cents, as it does in-process. Arguments are
typed Any so the server never coerces a value (True into 1, say) that the rules would refuse in-process.
"""

import argparse
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.config import load_settings
from src.tax_math.registry import FUNCTIONS
from src.tax_math.wire import RULE_ERRORS, decode, rule_error

PATH = "/mcp"
DEFAULT_PORT = 8001

server = MCPServer("tax_math", instructions="Form 1040-SR tax arithmetic for tax year 2025. Amounts are strings.")


def _run(name: str, **arguments) -> str:
    try:
        result = FUNCTIONS[name](**{key: decode(key, value) for key, value in arguments.items()})
    except tuple(RULE_ERRORS.values()) as exc:
        raise ToolError(rule_error(exc)) from None
    return str(result)


@server.tool(name="sum")
def sum_(values: Any) -> str:
    return _run("sum", values=values)


@server.tool()
def subtract(a: Any, b: Any) -> str:
    return _run("subtract", a=a, b=b)


@server.tool()
def subtract_floor_zero(a: Any, b: Any) -> str:
    return _run("subtract_floor_zero", a=a, b=b)


@server.tool()
def standard_deduction(filing_status: Any, boxes: Any) -> str:
    return _run("standard_deduction", filing_status=filing_status, boxes=boxes)


@server.tool()
def senior_deduction(filing_status: Any, magi: Any, qualifying_people: Any) -> str:
    return _run("senior_deduction", filing_status=filing_status, magi=magi, qualifying_people=qualifying_people)


@server.tool()
def taxable_social_security(filing_status: Any, benefits: Any, other_income: Any, tax_exempt_interest: Any,
                            adjustments: Any, lived_with_spouse: Any = None) -> str:
    return _run("taxable_social_security", filing_status=filing_status, benefits=benefits, other_income=other_income,
                tax_exempt_interest=tax_exempt_interest, adjustments=adjustments, lived_with_spouse=lived_with_spouse)


@server.tool()
def tax_from_schedule(filing_status: Any, taxable_income: Any) -> str:
    return _run("tax_from_schedule", filing_status=filing_status, taxable_income=taxable_income)


def create_app(host: str = "127.0.0.1"):
    """The ASGI app. Stateless JSON responses: every tool is a pure function, so there is no session to keep."""
    return server.streamable_http_app(streamable_http_path=PATH, stateless_http=True, json_response=True, host=host)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SilverFile tax_math MCP server")
    parser.add_argument("--host", default=load_settings().tax_math_mcp_host,
                        help="interface to listen on (default: TAX_MATH_MCP_HOST, else 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    print(f"tax_math MCP server: http://{args.host}:{args.port}{PATH}")
    uvicorn.run(create_app(args.host), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
