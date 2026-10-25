"""Memory boundaries: opaque workflow identity, selective disclosure and restart persistence."""

import pytest

from src import memory


def test_thread_identity_is_opaque_stable_and_rejects_ssns():
    a, b = memory.thread_config(), memory.thread_config()
    assert a != b
    identifier = a["configurable"]["thread_id"]
    assert memory.thread_config(identifier) == a
    for value in ("901-12-3456", "123456789", "return-901-12-3456"):
        with pytest.raises(ValueError, match="thread"):
            memory.thread_config(value)


def test_sqlite_boundary_rejects_ssn_identifiers(settings):
    with memory.open_checkpointer(settings) as saver:
        with pytest.raises(ValueError, match="thread"):
            saver.get_tuple({"configurable": {"thread_id": "901-12-3456"}})


def test_multiple_real_process_restarts_and_thread_isolation(settings):
    import json
    import os
    import subprocess
    import sys

    script = """
import json, sys
from langgraph.types import Command
from src.config import load_settings
from src.graph import build_graph
from src.memory import open_checkpointer, thread_config
from src.state import current_answers
with open_checkpointer(load_settings()) as saver:
    graph = build_graph(load_settings(), saver)
    config = thread_config(sys.argv[1])
    before = graph.get_state(config)
    result = graph.invoke(None if before.values else {}, config)
    for reply in json.loads(sys.argv[2]):
        result = graph.invoke(Command(resume=reply), config)
    snapshot = graph.get_state(config)
    print(json.dumps({'answers': {k: str(v.value) for k, v in current_answers(snapshot.values).items()},
                      'question': snapshot.interrupts[0].value,
                      'count': len(snapshot.values.get('answers', []))}))
"""
    env = {**os.environ, "SILVERFILE_DB_PATH": str(settings.db_path)}

    def process(thread, replies):
        result = subprocess.run(
            [sys.executable, "-c", script, thread, json.dumps(replies)],
            env=env,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    first = process("return-a", ["single", "none", "1950-02-03"])
    assert first["answers"]["taxpayer_dob"] == "1950-02-03"
    assert "legally blind" in first["question"]
    second = process("return-a", ["no", "no"])
    assert second["answers"]["filing_status"] == "single"
    assert "dual-status" in second["question"]
    third = process("return-a", [])
    assert third == second  # another interruption/restart, no duplicate effective writes
    other = process("return-b", [])
    assert other["answers"] == {}
    assert "So far:" not in other["question"]
    assert "So far:" in third["question"]


def test_uncertainty_pause_survives_restart_and_staff_resolution(settings, make_graph):
    from langgraph.types import Command
    from src.state import current_answers

    config = memory.thread_config("uncertainty-return")
    with memory.open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        graph.invoke({}, config)
        graph.invoke(Command(resume="single"), config)
        result = graph.invoke(Command(resume="I'm not sure"), config)
        assert result["__interrupt__"][0].value["reason"] == "uncertain"
    with memory.open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        result = graph.invoke(Command(resume={"action": "continue", "resolved_by": "staff-test"}), config)
        assert "spouse pass away" in result["__interrupt__"][0].value
        assert current_answers(result)["filing_status"].value == "single"
        result = graph.invoke(Command(resume="none"), config)
        assert "date of birth" in result["__interrupt__"][0].value


def test_selective_recall_excludes_old_dialogue_and_sensitive_answers():
    from langchain_core.messages import HumanMessage
    from src.schemas import IntakeAnswer

    state = {
        "messages": [HumanMessage(content="old-topic-1"), HumanMessage(content="old-topic-2")],
        "answers": [
            IntakeAnswer(field="filing_status", value="single"),
            IntakeAnswer(field="dependent_1_ssn", value="901-12-3456"),
        ],
    }
    on = memory.model_context(state, "current-item", use_context_strategy=True)
    off = memory.model_context(state, "current-item", use_context_strategy=False)
    assert "old-topic-1" not in str(on)
    assert "old-topic-1" in str(off)
    assert "single" in str(on)
    assert "current-item" in str(on)
    assert "901-12-3456" not in str(on) + str(off)


def test_model_boundary_records_provider_usage_and_rejects_missing_measurements():
    from langchain_core.messages import AIMessage

    class Provider:
        def __init__(self, usage):
            self.usage = usage

        def invoke(self, messages):
            return AIMessage(content='{"reason":"uncertain"}', usage_metadata=self.usage)

    response, update = memory.invoke_model(
        Provider({"input_tokens": 31, "output_tokens": 7, "total_tokens": 38}), {}, "current"
    )
    assert response.content == '{"reason":"uncertain"}'
    assert sum(update["input_token_usage"].values()) == 31
    with pytest.raises(ValueError, match="input.token"):
        memory.invoke_model(Provider(None), {}, "current")


def test_benchmark_runs_ten_sequential_items_in_separate_persistent_threads(settings):
    from langchain_core.messages import AIMessage

    class Provider:
        def invoke(self, messages):
            # Synthetic usage values test plumbing only; these are not measurements.
            count = 50 + len(messages)
            return AIMessage(
                content='{"reason":"uncertain"}',
                usage_metadata={"input_tokens": count, "output_tokens": 5, "total_tokens": count + 5},
            )

    with memory.open_checkpointer(settings) as saver:
        on = memory.run_context_benchmark(Provider(), saver, "strategy-on", True)
        off = memory.run_context_benchmark(Provider(), saver, "strategy-off", False)
        assert len(on) == len(off) == 10
        assert all(row["correct"] and row["model_calls"] == 1 for row in on + off)
        assert [r["input_tokens"] for r in on] == [52] * 10
        assert [r["input_tokens"] for r in off] == list(range(52, 72, 2))
        assert len(list(saver.list(memory.thread_config("strategy-on")))) > 10
        with pytest.raises(ValueError, match="fresh thread"):
            memory.run_context_benchmark(Provider(), saver, "strategy-on", True)
