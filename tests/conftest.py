import json
import os
from dataclasses import replace

# Fail loudly if a state type is missing from the serializer allow-list (src/memory.py).
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
# Tests are offline and free even when a developer's .env holds a key (load_dotenv never overrides this).
# The live W-2 check is python -m evals.live_vision_check.
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

import src.agents.computation as computation_module
from src.config import load_settings  # noqa: E402
from src.graph import build_graph  # noqa: E402
from src.memory import serializer  # noqa: E402
from src.tools import call_tool as production_call_tool

SKELETON_CASE = "data/fixtures/skeleton_case.json"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "production_stubs: run with real placeholder tax tools so Review must fail closed",
    )


@pytest.fixture(autouse=True)
def verified_test_tools(request, monkeypatch):
    """Use verified tool provenance in tests unrelated to placeholder safety."""

    if request.node.get_closest_marker("production_stubs"):
        return

    def call_verified_tool(name, **inputs):
        result, provenance = production_call_tool(name, **inputs)
        return result, provenance.model_copy(update={"stub": False})

    monkeypatch.setattr(
        computation_module,
        "call_tool",
        call_verified_tool,
    )


@pytest.fixture
def settings(tmp_path):
    return replace(load_settings(), db_path=tmp_path / "silverfile.sqlite")


@pytest.fixture
def make_graph(settings):
    def make(agents=None, checkpointer=None):
        return build_graph(settings, checkpointer or InMemorySaver(serde=serializer()), agents=agents)

    return make


@pytest.fixture
def make_case(tmp_path):
    """Write a variant of the skeleton case: make_case(r1_2b=True, other_document=True)."""

    def make(name="case", r1_2b=False, other_document=False):
        case = json.loads(open(SKELETON_CASE).read())
        if r1_2b:
            case["documents"][2]["values"]["taxable_not_determined"] = True
        if other_document:
            case["documents"].append(
                {"document_id": "nec-1", "form_type": "other", "description": "1099-NEC for consulting work"}
            )
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(case))
        return str(path)

    return make
