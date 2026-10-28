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


@pytest.mark.parametrize("enabled", [True, False])
def test_turns_use_the_production_input_and_fixed_seeds(settings, enabled):
    provider = ScriptedProvider()
    with memory.open_checkpointer(settings) as saver:
        memory.run_context_benchmark(provider, saver, f"shape-{enabled}", enabled)
    assert provider.calls == 30
    for messages, (_, _, turn) in zip(provider.seen, TURNS):
        # Byte for byte what Intake sends: json.dumps({"question": question, "reply": safe}).
        assert messages[-1].content == json.dumps({"question": turn["question"], "reply": turn["reply"]})
    # The seeded summary is the same in every call of both modes, so only the dialogue differs.
    assert {messages[0].content for messages in provider.seen} == {provider.seen[0][0].content}
    assert '"filing_status": "single"' in provider.seen[0][0].content


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
