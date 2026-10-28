"""Client side of the tax_math tools. Computation, Rules and Review get every number through call_tool().

With TAX_MATH_MCP_URL empty the tools run in-process, from src/tax_math/registry.py. With it set, every call
goes to the tax_math MCP server (python -m src.tax_math.server). If that server cannot answer, call_tool()
raises TaxMathUnavailable; it never falls back to in-process math. A rule error on the server raises the
same ValueError (or TypeError, InvalidOperation) the in-process call would.
The rule functions stay exact; call_tool() rounds each result to cents, half up, once.
"""

import asyncio
import inspect
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from decimal import ROUND_HALF_UP, Decimal

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from src.config import load_settings
from src.schemas import Provenance
from src.tax_math.registry import FUNCTIONS
from src.tax_math.wire import encode, raise_rule_error

CENT = Decimal("0.01")
TIMEOUT = 10  # seconds for one MCP attempt

# name -> (function, is_stub)
TOOLS = {name: (fn, False) for name, fn in FUNCTIONS.items()}


class TaxMathUnavailable(RuntimeError):
    """TAX_MATH_MCP_URL is set but the server there could not answer. Not a ValueError: it is not bad input."""


def call_tool(name: str, **inputs) -> tuple[Decimal, Provenance]:
    fn, is_stub = TOOLS[name]
    url = mcp_url()
    result = _exact(name, fn, inputs, url).quantize(CENT, rounding=ROUND_HALF_UP)
    return result, Provenance(kind="tool", source=f"tax_math.{name}", value=result, inputs=inputs, stub=is_stub,
                              via=url or None)


def _exact(name, fn, inputs, url):
    if not url:
        return fn(**inputs)
    # A missing or extra argument is a TypeError, as in-process; the server would silently drop an extra one.
    inspect.signature(fn).bind(**inputs)
    result = _on_server_loop(url, lambda session: session.call_tool(name, {k: encode(v) for k, v in inputs.items()}))
    text = "".join(getattr(part, "text", "") for part in result.content)
    if result.is_error:
        raise_rule_error(name, text)
        raise TaxMathUnavailable(f"tax_math.{name} failed on the MCP server at {url}: {text}")
    return Decimal((result.structured_content or {}).get("result", text))


def check_server(url: str | None = None) -> None:
    """Startup check for run.py and the dashboard: the configured server answers and has every tool."""
    url = url or mcp_url()
    if not url:
        return
    listed = _on_server_loop(url, lambda session: session.list_tools())
    missing = sorted(set(TOOLS) - {tool.name for tool in listed.tools})
    if missing:
        raise TaxMathUnavailable(f"The tax_math MCP server at {url} is missing tools: {', '.join(missing)}")


# Resolved once per process from TAX_MATH_MCP_URL; "" means in-process.
_url: str | None = None


def mcp_url() -> str:
    global _url
    if _url is None:
        _url = load_settings().tax_math_mcp_url
    return _url


# One event loop on a daemon thread. call_tool() hands its MCP request to this loop and waits, so it stays
# a plain sync call from run.py, from the dashboard's threadpool, and from inside a running event loop
# (the dashboard's async handlers), without ever touching the caller's loop.
_loop: asyncio.AbstractEventLoop | None = None
_loop_pid: int | None = None
_loop_lock = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_pid
    with _loop_lock:
        if _loop is None or _loop_pid != os.getpid():  # a forked child does not inherit the thread
            _loop, _loop_pid = asyncio.new_event_loop(), os.getpid()
            threading.Thread(target=_loop.run_forever, name="tax-math-mcp", daemon=True).start()
    return _loop


def _on_server_loop(url, request):
    future = asyncio.run_coroutine_threadsafe(_with_reconnect(url, request), _background_loop())
    try:
        return future.result(timeout=2 * TIMEOUT + 1)
    except FutureTimeout:
        future.cancel()
        raise TaxMathUnavailable(f"The tax_math MCP server at {url} did not answer in time.") from None


async def _with_reconnect(url, request):
    """One short MCP session per call (the server is stateless), and one reconnect. Tools are pure, so a
    retry is safe; there is never a fallback to in-process math."""
    for _ in range(2):
        try:
            return await asyncio.wait_for(_session(url, request), TIMEOUT)
        except Exception as exc:  # connection refused, timeout, a dropped stream
            failure = exc
    raise TaxMathUnavailable(
        f"The tax_math MCP server at {url} is unreachable ({type(failure).__name__}). Start it with "
        "python -m src.tax_math.server, or unset TAX_MATH_MCP_URL to run the tax math in-process."
    ) from failure


async def _session(url, request):
    async with streamable_http_client(url) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await request(session)
