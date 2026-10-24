"""Smoke tests for the project setup: config loads and run.py can drive a graph through an interrupt."""

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

import run
from src.config import load_settings


def test_settings_load():
    settings = load_settings()
    assert settings.max_review_passes >= 1
    assert settings.db_path.is_absolute()


def test_cli_flags():
    args = run.parse_args(["--batch", "--no-context-strategy"])
    assert args.batch and args.no_context_strategy


def test_drive_resumes_after_interrupt():
    class State(TypedDict, total=False):
        answer: str

    def ask_status(state):
        return {"answer": interrupt("What is your filing status?")}

    builder = StateGraph(State)
    builder.add_node("ask_status", ask_status)
    builder.add_edge(START, "ask_status")
    builder.add_edge("ask_status", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    shown = []
    result = run.drive(graph, "t1", {}, ask=lambda _: "Single", say=shown.append)

    assert shown == ["What is your filing status?"]
    assert result["answer"] == "Single"
