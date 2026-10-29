"""The context benchmark's items (evals/context_items.json) and how the harness scores them.

Offline: providers here are doubles, and their token counts are synthetic plumbing values, not
measurements (docs/metrics.md).
"""

import json
import re

import pytest
from langchain_core.messages import AIMessage

from src import memory
from src.agents.intake import ESCALATION_DETAIL, QUESTIONS
from src.guardrails import classify_reply

DATA = memory.load_context_items()
TURNS = [(item["id"], n, turn) for item in DATA["items"] for n, turn in enumerate(item["turns"], start=1)]
PARSERS = {field: parse for field, _, parse, _ in QUESTIONS}
QUESTION_TEXT = {field: text for field, text, _, _ in QUESTIONS}
# The two reply commands Intake handles itself, without the model (src/agents/intake.py, _intake).
GO_BACK = re.compile(r"go back(?: to)? (.+)", flags=re.I)
CHANGE = re.compile(r"change (.+?) (?:to|=) (.+)", flags=re.I)


def test_ten_items_of_three_turns_with_one_known_label_each():
    assert len(DATA["items"]) == 10 and len(TURNS) == 30
    assert len({item["id"] for item in DATA["items"]}) == 10
    assert len({turn["reply"] for _, _, turn in TURNS}) == 30  # the offline doubles look turns up by reply
    assert all(turn["expected"] in (*ESCALATION_DETAIL, None) for _, _, turn in TURNS)
    assert DATA["seed_answers"] == {"filing_status": "single"}


def test_no_real_looking_ssn():
    for number in re.findall(r"(?<!\d)(\d{3})-?\d{2}-?\d{4}(?!\d)", json.dumps(DATA)):
        assert 900 <= int(number) <= 999, "only the assignment's synthetic 900-999 range may appear"


@pytest.mark.parametrize("item, n, turn", TURNS, ids=[f"{i}-{n}" for i, n, _ in TURNS])
def test_every_turn_reaches_the_model_in_production(item, n, turn):
    """In real Intake a reply reaches the classifier only if no guardrail, command or parser handles it."""
    reply = turn["reply"]
    assert turn["question"] == QUESTION_TEXT[turn["field"]], "the question must be Intake's own text"
    assert classify_reply(reply) is None, "a guardrail rule would decide this turn without the model"
    assert not GO_BACK.fullmatch(reply) and not CHANGE.fullmatch(reply), "Intake would treat this as a command"
    with pytest.raises((ValueError, TypeError)):
        PARSERS[turn["field"]](reply)  # a reply the field accepts is never sent to the model


class ScriptedProvider:
    """Answers each turn's expected label (except `wrong`) and reports distinct synthetic usage per call."""

    def __init__(self, wrong=()):
        self.wrong, self.calls, self.seen = set(wrong), 0, []

    def invoke(self, messages):
        self.calls += 1
        self.seen.append(messages)
        reply = json.loads(messages[-1].content)["reply"]
        expected = next(turn["expected"] for _, _, turn in TURNS if turn["reply"] == reply)
        reason = "advice_request" if reply in self.wrong else expected  # `wrong` turns never expect advice
        tokens = 10 * self.calls  # synthetic
        return AIMessage(content=json.dumps({"reason": reason}),
                         usage_metadata={"input_tokens": tokens, "output_tokens": 1, "total_tokens": tokens + 1})


def item_seed(item):
    return {**DATA["seed_answers"], **item.get("seed_answers", {})}


def test_items_1_to_9_seed_single_and_item_10_seeds_mfs():
    assert [item_seed(item)["filing_status"] for item in DATA["items"]] == ["single"] * 9 + ["mfs"]
    assert DATA["items"][9]["turns"][0]["field"] == "mfs_lived_with_spouse"  # Intake asks it only of mfs filers


@pytest.mark.parametrize("enabled", [True, False])
def test_turns_use_the_production_input_and_per_item_seeds(settings, enabled):
    provider = ScriptedProvider()
    with memory.open_checkpointer(settings) as saver:
        rows = memory.run_context_benchmark(provider, saver, f"shape-{enabled}", enabled)
    assert provider.calls == 30
    for messages, (_, _, turn) in zip(provider.seen, TURNS):
        # Byte for byte what Intake sends: json.dumps({"question": question, "reply": safe}).
        assert messages[-1].content == json.dumps({"question": turn["question"], "reply": turn["reply"]})
    # Within an item the seeded summary is the same in every call, so only the dialogue differs; it shows the
    # item's own filing status: single for items 1-9, mfs for item 10, in both modes.
    for number, item in enumerate(DATA["items"]):
        summaries = {messages[0].content for messages in provider.seen[3 * number:3 * number + 3]}
        assert len(summaries) == 1
        assert f'"filing_status": "{item_seed(item)["filing_status"]}"' in summaries.pop()
    assert [row["seed_answers"] for row in rows] == [item_seed(item) for item in DATA["items"]]


def test_a_per_item_seed_is_recorded_before_that_items_first_turn(settings, tmp_path):
    data = json.loads(json.dumps(DATA))
    data["items"][3]["seed_answers"] = {"filing_status": "hoh"}  # item 4 only; item 5 falls back to the file's
    path = tmp_path / "items.json"
    path.write_text(json.dumps(data))
    provider = ScriptedProvider()
    with memory.open_checkpointer(settings) as saver:
        memory.run_context_benchmark(provider, saver, "per-item-seed", True, items_path=path)
        answers = saver.get_tuple(memory.thread_config("per-item-seed")).checkpoint["channel_values"]["answers"]
    status = [json.loads(m[0].content.split("Confirmed session inputs: ")[1])["filing_status"] for m in provider.seen]
    assert status[8] == "single" and status[9:12] == ["hoh"] * 3 and status[12] == "single"
    assert status[27:] == ["mfs"] * 3
    # Appended, never overwritten: every change is a new IntakeAnswer in order.
    seeded = [(a.field, a.value, a.entered_by) for a in answers]
    assert seeded == [("filing_status", v, "synthetic benchmark") for v in ["single", "hoh", "single", "mfs"]]


@pytest.mark.parametrize("seed, message", [
    ({"filing_status": "married"}, "one of the five statuses"),
    ({"favourite_colour": "blue"}, "unknown seed field"),
])
def test_seeds_are_validated(tmp_path, seed, message):
    data = json.loads(json.dumps(DATA))
    data["items"][0]["seed_answers"] = seed
    path = tmp_path / "items.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        memory.load_context_items(path)


def test_item_tokens_sum_its_turns_and_one_wrong_turn_fails_only_its_item(settings):
    wrong = DATA["items"][3]["turns"][1]["reply"]  # item 4, turn 2 (expects null)
    assert DATA["items"][3]["turns"][1]["expected"] is None
    with memory.open_checkpointer(settings) as saver:
        rows = memory.run_context_benchmark(ScriptedProvider(wrong={wrong}), saver, "per-turn", True)

    for number, row in enumerate(rows, start=1):
        assert row["item"] == number and row["id"] == DATA["items"][number - 1]["id"]
        assert [t["input_tokens"] for t in row["turns"]] == [10 * c for c in range(3 * number - 2, 3 * number + 1)]
        assert row["input_tokens"] == sum(t["input_tokens"] for t in row["turns"])
        assert row["model_calls"] == 3 and all(t["model_calls"] == 1 and t["valid"] for t in row["turns"])
        assert [t["expected"] for t in row["turns"]] == [t["expected"] for t in DATA["items"][number - 1]["turns"]]
    assert [row["correct"] for row in rows] == [n != 4 for n in range(1, 11)]
    failed = rows[3]["turns"]
    assert [t["correct"] for t in failed] == [True, False, True]
    assert failed[1]["reply"] == wrong and failed[1]["reason"] != failed[1]["expected"]
