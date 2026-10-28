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


def test_resume_recap_is_shown_once(make_graph):
    from langgraph.types import Command

    graph = make_graph()
    config = {"configurable": {"thread_id": "resume-recap"}}
    graph.invoke({}, config)
    result = graph.invoke(Command(resume="single"), config)
    assert "So far:" not in result["__interrupt__"][0].value
    replies = iter(["none", "1950-02-03"])
    shown = []

    def ask(_):
        try:
            return next(replies)
        except StopIteration:
            raise EOFError

    run.drive(graph, "resume-recap", None, ask=ask, say=shown.append)
    assert shown[0].startswith("So far: filing status: single.")
    question = result["__interrupt__"][0].value
    assert question["type"] == "intake_question"
    assert "So far:" not in question["prompt"]


def test_cli_new_session_uses_safe_id(settings, monkeypatch):
    import uuid
    from dataclasses import replace

    from src.memory import thread_config

    monkeypatch.setattr(run, "load_settings", lambda: replace(settings, anthropic_api_key="test"))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("12345678901212345678901234567890"))
    seen = []

    def drive(graph, thread_id, first_input):
        config = thread_config(thread_id)  # the old truncated hex id fails here
        result = graph.invoke(first_input, config)
        seen.append(result)

    monkeypatch.setattr(run, "drive", drive)
    run.main([])
    assert len(seen) == 1
