"""run.py --batch drives Iris's context benchmark; src.metrics_table turns its results into the docs/metrics.md table.

Offline: a fake provider stands in for Claude. Its usage numbers are synthetic and test plumbing only;
they are not measurements (docs/metrics.md).
"""

import json
from dataclasses import replace

import langchain_anthropic
import pytest
from langchain_core.messages import AIMessage

import run
import src.config
from src.config import load_settings
from src.metrics_table import HEADER, main as metrics_table
from tests.conftest import benchmark_answer


class FakeClaude:
    """Answers every turn as expected and reports 50 + 2 tokens per message it was sent."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, messages):
        count = 50 + 2 * len(messages)
        return AIMessage(content=benchmark_answer(messages[-1].content),
                         usage_metadata={"input_tokens": count, "output_tokens": 5, "total_tokens": count + 5})


@pytest.fixture
def offline_benchmark(monkeypatch, tmp_path):
    settings = replace(load_settings(), anthropic_api_key="test-key", db_path=tmp_path / "silverfile.sqlite")
    monkeypatch.setattr(run, "load_settings", lambda: settings)
    monkeypatch.setattr(src.config, "load_settings", lambda: settings)  # src.memory.main imports it at call time
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeClaude)
    monkeypatch.chdir(tmp_path)  # the benchmark writes output/context_{on,off}.json relative to the cwd
    return tmp_path


def test_run_py_batch_runs_the_context_benchmark_both_ways(offline_benchmark):
    run.main(["--batch"])
    run.main(["--batch", "--no-context-strategy"])
    on = json.loads((offline_benchmark / "output/context_on.json").read_text())
    off = json.loads((offline_benchmark / "output/context_off.json").read_text())

    assert on["strategy_enabled"] is True and off["strategy_enabled"] is False
    assert on["thread_id"] != off["thread_id"]
    for result in (on, off):
        assert [row["item"] for row in result["items"]] == list(range(1, 11))
        assert all(row["model_calls"] == 3 and row["correct"] for row in result["items"])
    # ON sends a fixed context every item; OFF adds the earlier dialogue, so --no-context-strategy reached it.
    assert len({row["input_tokens"] for row in on["items"]}) == 1
    tokens = [row["input_tokens"] for row in off["items"]]
    assert tokens == sorted(tokens) and tokens[-1] > tokens[0]


def test_run_py_batch_passes_the_thread_id(offline_benchmark):
    run.main(["--batch", "--thread-id", "metrics-on-1"])
    assert json.loads((offline_benchmark / "output/context_on.json").read_text())["thread_id"] == "metrics-on-1"


def result(strategy_enabled, tokens, correct=None, model="claude-test"):
    correct = correct or [True] * len(tokens)
    return {
        "thread_id": f"t-{'on' if strategy_enabled else 'off'}",
        "strategy_enabled": strategy_enabled,
        "model": model,
        "measured_at": "2026-10-28T00:00:00+00:00",
        "items": [{"item": i, "input_tokens": t, "model_calls": 1, "correct": c}
                  for i, (t, c) in enumerate(zip(tokens, correct), start=1)],
    }


@pytest.fixture
def result_files(tmp_path):
    def write(on, off):
        paths = tmp_path / "context_on.json", tmp_path / "context_off.json"
        for path, data in zip(paths, (on, off)):
            path.write_text(json.dumps(data))
        return [str(p) for p in paths]

    return write


def test_table_rows_outcomes_and_growth(result_files, capsys, tmp_path):
    on_tokens = [100] * 10
    off_tokens = [100 + 150 * i for i in range(10)]  # 100 ... 1,450
    files = result_files(result(True, on_tokens), result(False, off_tokens, correct=[True] * 9 + [False]))

    metrics_table([*files, "--out", str(tmp_path / "docs/metrics")])
    lines = capsys.readouterr().out.splitlines()

    assert "\n".join(lines[:2]) == HEADER
    assert lines[2] == "| 1 | 100 | 100 | ON correct, OFF correct |"
    assert lines[11] == "| 10 | 100 | 1,450 | ON correct, OFF incorrect |"
    assert len([line for line in lines if line.startswith("| ") and line[2].isdigit()]) == 10
    assert lines[13] == ("First to last item. ON: 100 → 100 input tokens (+0, +0%); "
                         "OFF: 100 → 1,450 input tokens (+1,350, +1350%).")
    assert lines[14].startswith("Model claude-test. ON thread t-on")
    chart = lines[lines.index("```mermaid"):]
    assert chart[1] == "xychart-beta"
    assert '    y-axis "Input tokens" 0 --> 1450' in chart
    assert chart[5:7] == ["    line [100, 100, 100, 100, 100, 100, 100, 100, 100, 100]",
                          "    line [100, 250, 400, 550, 700, 850, 1000, 1150, 1300, 1450]"]
    for name in ("context_on.json", "context_off.json"):
        assert (tmp_path / "docs/metrics" / name).read_text() == (tmp_path / name).read_text()


@pytest.mark.parametrize("on, off, message", [
    (result(False, [1] * 10), result(False, [1] * 10), "not a strategy ON run"),
    (result(True, [1] * 9), result(False, [1] * 10), "must hold items 1-10"),
    (result(True, [1] * 10), result(False, [1] * 10, model="other"), "different models"),
])
def test_table_refuses_mismatched_runs(result_files, on, off, message):
    with pytest.raises(SystemExit, match=message):
        metrics_table(result_files(on, off))
