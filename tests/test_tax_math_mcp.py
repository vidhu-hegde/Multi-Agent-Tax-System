"""The tax_math MCP server against the in-process path. Offline: the server runs in a thread on 127.0.0.1."""

import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal, InvalidOperation

import pytest
import uvicorn
from fastapi.testclient import TestClient

import run
import src.tools as tools
from src.config import load_settings
from src.dashboard.app import create_app as create_dashboard
from src.tax_math.server import PATH, create_app
from src.tools import TOOLS, TaxMathUnavailable, call_tool, check_server
from tests.conftest import SKELETON_CASE

D = Decimal


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "tax_math server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}{PATH}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def via_server(monkeypatch, server_url):
    """Route call_tool() to the server, as TAX_MATH_MCP_URL would."""
    monkeypatch.setattr(tools, "_url", server_url)
    return server_url


def in_process(monkeypatch):
    monkeypatch.setattr(tools, "_url", "")


TOOL_CALLS = [
    ("sum", dict(values=[D("1.005"), D("2"), 3])),
    ("sum", dict(values=[])),
    ("subtract", dict(a=D("10"), b=D("12.345"))),
    ("subtract_floor_zero", dict(a=D("10"), b=D("12.345"))),
    ("standard_deduction", dict(filing_status="mfj", boxes=2)),
    ("senior_deduction", dict(filing_status="single", magi=D("80000"), qualifying_people=1)),
    ("taxable_social_security", dict(filing_status="single", benefits=D("22013.33"), other_income=[D("24420.17")],
                                     tax_exempt_interest=D("80"), adjustments=D("0"))),
    ("taxable_social_security", dict(filing_status="mfs", benefits=D("20000"), other_income=[D("20000")],
                                     tax_exempt_interest=D("0"), adjustments=D("0"), lived_with_spouse=True)),
    ("taxable_social_security", dict(filing_status="mfs", benefits=D("0"), other_income=[D("500000")],
                                     tax_exempt_interest=D("0"), adjustments=D("0"), lived_with_spouse=None)),
    ("tax_from_schedule", dict(filing_status="single", taxable_income=D("37327.67"))),
    ("tax_from_schedule", dict(filing_status="single", taxable_income="10000.05")),
]

BAD_CALLS = [
    ("taxable_social_security", dict(filing_status="mfs", benefits=D("20000"), other_income=[D("20000")],
                                     tax_exempt_interest=D("0"), adjustments=D("0"), lived_with_spouse=None)),
    ("standard_deduction", dict(filing_status="single", boxes=True)),  # the server must not coerce True to 1
    ("standard_deduction", dict(filing_status="widowed", boxes=0)),
    ("senior_deduction", dict(filing_status="single", magi=80000.5, qualifying_people=1)),  # floats are refused
    ("senior_deduction", dict(filing_status="mfs", magi=D("50000"), qualifying_people=1)),
    ("tax_from_schedule", dict(filing_status="single", taxable_income="not money")),
    ("sum", dict(values=["abc"])),  # InvalidOperation, as in-process
]


def test_server_lists_every_tool(server_url):
    check_server(server_url)
    assert set(TOOLS) == set(tools.FUNCTIONS)


@pytest.mark.parametrize("name, inputs", TOOL_CALLS, ids=[c[0] for c in TOOL_CALLS])
def test_every_tool_matches_in_process(monkeypatch, via_server, name, inputs):
    remote, remote_step = call_tool(name, **inputs)
    in_process(monkeypatch)
    local, local_step = call_tool(name, **inputs)
    assert remote == local and str(remote) == str(local)
    assert remote_step.value == local_step.value and remote_step.inputs == local_step.inputs == inputs
    assert remote_step.via == via_server and local_step.via is None


@pytest.mark.parametrize("name, inputs", BAD_CALLS, ids=[c[0] for c in BAD_CALLS])
def test_rule_errors_arrive_as_the_same_exception(monkeypatch, via_server, name, inputs):
    # Also pins the SDK's "Error executing tool <name>: " prefix: if it changes, this raises TaxMathUnavailable.
    with pytest.raises((ValueError, TypeError, InvalidOperation)) as remote:
        call_tool(name, **inputs)
    in_process(monkeypatch)
    with pytest.raises((ValueError, TypeError, InvalidOperation)) as local:
        call_tool(name, **inputs)
    assert type(remote.value) is type(local.value)
    assert str(remote.value) == str(local.value)


@pytest.mark.parametrize("inputs", [dict(values=[D("1")], extra=1), dict()], ids=["extra", "missing"])
def test_wrong_arguments_are_a_type_error_on_both_paths(monkeypatch, via_server, inputs):
    with pytest.raises(TypeError):
        call_tool("sum", **inputs)  # the server alone would silently drop `extra`
    in_process(monkeypatch)
    with pytest.raises(TypeError):
        call_tool("sum", **inputs)


def test_mfs_unknown_lived_with_spouse_raises_value_error_over_mcp(via_server):
    with pytest.raises(ValueError, match="lived_with_spouse"):
        call_tool("taxable_social_security", filing_status="mfs", benefits=D("100"), other_income=[],
                  tax_exempt_interest=D("0"), adjustments=D("0"))


def test_call_tool_works_inside_a_running_event_loop(via_server):
    async def handler():  # like the dashboard's async resolve(), which runs the graph on its loop
        return call_tool("sum", values=[D("1"), D("2")])

    result, step = asyncio.run(handler())
    assert result == D("3.00") and step.via == via_server


def test_concurrent_calls_from_threads(via_server):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: call_tool("sum", values=[D(n), D("0.005")])[0], range(16)))
    assert results == [D(n) + D("0.01") for n in range(16)]


def test_unreachable_server_raises_and_never_falls_back(monkeypatch):
    dead = f"http://127.0.0.1:{free_port()}{PATH}"
    monkeypatch.setattr(tools, "_url", dead)
    started = time.monotonic()
    with pytest.raises(TaxMathUnavailable, match="unreachable") as error:
        call_tool("sum", values=[D("1")])
    assert not isinstance(error.value, ValueError)  # the dashboard shows a ValueError as bad form input
    assert dead in str(error.value)
    assert time.monotonic() - started < 10
    with pytest.raises(TaxMathUnavailable):
        check_server()


def test_dashboard_refuses_to_start_when_the_server_is_down(monkeypatch):
    monkeypatch.setattr(tools, "_url", f"http://127.0.0.1:{free_port()}{PATH}")
    with pytest.raises(TaxMathUnavailable):
        with TestClient(create_dashboard(sessions=object())):
            pass


def test_dashboard_demo_exits_before_seeding_when_the_server_is_down(monkeypatch):
    import src.dashboard.__main__ as dashboard_main

    monkeypatch.setattr(tools, "_url", f"http://127.0.0.1:{free_port()}{PATH}")
    monkeypatch.setattr(dashboard_main, "seed", lambda *args: pytest.fail("seeded with the server down"))
    with pytest.raises(SystemExit, match="unreachable"):
        dashboard_main.main(["--demo"])


def test_run_py_exits_when_the_server_is_down(monkeypatch):
    monkeypatch.setattr(tools, "_url", f"http://127.0.0.1:{free_port()}{PATH}")
    monkeypatch.setattr(run, "load_settings", lambda: replace(load_settings(), anthropic_api_key="test-key"))
    with pytest.raises(SystemExit, match="unreachable"):
        run.main(["--case", SKELETON_CASE])


def test_graph_through_the_server_matches_in_process(monkeypatch, make_graph, via_server):
    remote = make_graph().invoke({"case_path": SKELETON_CASE}, {"configurable": {"thread_id": "mcp"}})
    in_process(monkeypatch)
    local = make_graph().invoke({"case_path": SKELETON_CASE}, {"configurable": {"thread_id": "local"}})
    assert remote["status"] == local["status"] == "draft_ready"
    assert {k: v.amount for k, v in remote["lines"].items()} == {k: v.amount for k, v in local["lines"].items()}
    tool_steps = [p for line in remote["lines"].values() for p in line.provenance if p.kind == "tool"]
    assert tool_steps and all(p.via == via_server for p in tool_steps)
