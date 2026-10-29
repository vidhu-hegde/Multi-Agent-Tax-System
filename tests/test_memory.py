"""Memory boundaries: opaque workflow identity, selective disclosure and restart persistence."""

import json

import pytest

from src import memory

# The benchmark file, in run order; offline providers below answer each turn's expected label.
CONTEXT_TURNS = [turn for item in memory.load_context_items()["items"] for turn in item["turns"]]
EXPECTED = {turn["reply"]: turn["expected"] for turn in CONTEXT_TURNS}


def expected_answer(messages):
    return json.dumps({"reason": EXPECTED[json.loads(messages[-1].content)["reply"]]})


def question_text(value):
    if (
        isinstance(value, dict)
        and value.get("type") == "intake_question"
    ):
        return value["prompt"]

    return str(value)


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
def question_text(value):
    if isinstance(value, dict) and value.get("type") == "intake_question":
        return value["prompt"]
    return str(value)
with open_checkpointer(load_settings()) as saver:
    graph = build_graph(load_settings(), saver)
    config = thread_config(sys.argv[1])
    before = graph.get_state(config)
    result = graph.invoke(None if before.values else {}, config)
    for reply in json.loads(sys.argv[2]):
        result = graph.invoke(Command(resume=reply), config)
    snapshot = graph.get_state(config)
    print(json.dumps({'answers': {k: str(v.value) for k, v in current_answers(snapshot.values).items()},
                      'question': question_text(snapshot.interrupts[0].value),
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
    assert "So far:" not in third["question"]  # the CLI adds a recap only when a session resumes


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
        assert "spouse who died" in question_text(
            result["__interrupt__"][0].value
        )
        assert current_answers(result)["filing_status"].value == "single"
        result = graph.invoke(Command(resume="none"), config)
        assert "date of birth" in question_text(
            result["__interrupt__"][0].value
        )


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
                content=expected_answer(messages),
                usage_metadata={"input_tokens": count, "output_tokens": 5, "total_tokens": count + 5},
            )

    with memory.open_checkpointer(settings) as saver:
        on = memory.run_context_benchmark(Provider(), saver, "strategy-on", True)
        off = memory.run_context_benchmark(Provider(), saver, "strategy-off", False)
        assert len(on) == len(off) == 10
        assert all(row["correct"] and row["model_calls"] == 3 for row in on + off)
        # ON: 2 messages per call, 3 calls per item. OFF: call k sends 2k messages, so item i = 144 + 18i.
        assert [r["input_tokens"] for r in on] == [156] * 10
        assert [r["input_tokens"] for r in off] == list(range(162, 325, 18))
        assert len(list(saver.list(memory.thread_config("strategy-on")))) > 10
        with pytest.raises(ValueError, match="fresh thread"):
            memory.run_context_benchmark(Provider(), saver, "strategy-on", True)


@pytest.mark.parametrize("enabled", [True, False])
def test_benchmark_cli_writes_comparable_runs_without_sampling_parameters(settings, monkeypatch, tmp_path, enabled):
    """Review coverage for PR #13; all usage below is synthetic, not benchmark evidence."""
    import json
    from dataclasses import replace

    from langchain_core.messages import AIMessage

    import langchain_anthropic
    import src.config

    class OfflineProvider:
        def __init__(self, **kwargs):
            assert not {"temperature", "top_p", "top_k"} & kwargs.keys()
            assert kwargs["max_retries"] == 0
            assert kwargs["model"] == "offline-provider-double"
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            turn = CONTEXT_TURNS[self.calls - 1]
            assert json.loads(messages[-1].content) == {"question": turn["question"], "reply": turn["reply"]}
            status = "mfs" if self.calls > 27 else "single"  # item 10 (calls 28-30) seeds mfs
            assert f'"filing_status": "{status}"' in messages[0].content
            assert len(messages) == (2 if enabled else 2 * self.calls)
            count = 100 + len(messages)
            return AIMessage(content=expected_answer(messages), usage_metadata={
                "input_tokens": count, "output_tokens": 1, "total_tokens": count + 1,
            })

    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", OfflineProvider)
    monkeypatch.setattr(src.config, "load_settings", lambda: replace(
        settings, anthropic_api_key="offline-test-double", model="offline-provider-double",
    ))
    output = tmp_path / "synthetic-usage.json"
    args = ["--batch", "--thread-id", f"cli-strategy-{enabled}", "--output", str(output)]
    if not enabled:
        args.append("--no-context-strategy")
    memory.main(args)
    result = json.loads(output.read_text())
    assert result["strategy_enabled"] is enabled
    assert result["model"] == "offline-provider-double"
    assert result["thread_id"] == f"cli-strategy-{enabled}"
    assert [row["item"] for row in result["items"]] == list(range(1, 11))
    assert all(row["correct"] and row["model_calls"] == 3 for row in result["items"])
    assert [row["input_tokens"] for row in result["items"]] == (
        [306] * 10 if enabled else list(range(312, 475, 18))
    )


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("failure", ["wrong_outcome", "missing_usage", "malformed_output", "unsupported_reason"])
def test_benchmark_cli_rejects_invalid_evidence(settings, monkeypatch, tmp_path, enabled, failure):
    import json
    from dataclasses import replace
    from langchain_core.messages import AIMessage
    import langchain_anthropic
    import src.config

    class OfflineProvider:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            content = {
                "malformed_output": "not valid JSON",
                "unsupported_reason": '{"reason":"invented_reason"}',
            }.get(failure, '{"reason":null}')
            return AIMessage(content=content, usage_metadata=None if failure == "missing_usage" else {
                "input_tokens": 10, "output_tokens": 1, "total_tokens": 11,
            })

    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", OfflineProvider)
    monkeypatch.setattr(src.config, "load_settings", lambda: replace(settings, anthropic_api_key="offline-double"))
    output = tmp_path / "invalid-evidence.json"
    args = ["--batch", "--thread-id", "invalid-evidence", "--output", str(output)]
    if not enabled:
        args.append("--no-context-strategy")
    if failure == "missing_usage":
        with pytest.raises(ValueError, match="actual input-token usage"):
            memory.main(args)
        assert not output.exists()
    else:
        with pytest.raises(SystemExit, match="Outcome validation failed"):
            memory.main(args)
        rows = json.loads(output.read_text())["items"]
        assert len(rows) == 10 and all(not row["correct"] for row in rows)
        if failure == "wrong_outcome":
            # A fixed null is right for the 15 re-ask turns, but every item has a turn that needs a label.
            assert sum(turn["correct"] for row in rows for turn in row["turns"]) == 15
