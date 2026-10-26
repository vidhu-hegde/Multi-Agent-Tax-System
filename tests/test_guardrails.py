"""Guardrails and ethics (owner: Juee). Policy: data/policy.md.

1. A labelled set of taxpayer replies: every reply must get the expected escalation reason, including
   ordinary answers that the old keyword lists wrongly flagged.
2. Rules escalates when the Standard Deduction Chart does not apply, and on W-2 scope signals.
3. policy.md stays in step with the code: every citation and escalation reason has a section.
"""

import json
import re
import typing
from pathlib import Path

import pytest
from langgraph.types import Command

from src.guardrails import classify_reply, explain
from src.schemas import EscalationReason
from tests.conftest import SKELETON_CASE

POLICY = Path("data/policy.md").read_text()


def config(thread_id="g"):
    return {"configurable": {"thread_id": thread_id}}


def paused_on(result):
    interrupts = result.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None


# 1. Labelled replies ------------------------------------------------------------------------------

ORDINARY_ANSWERS = [
    "single", "married filing separately", "widowed", "none", "no", "0", "2000", "1950-02-03",
    "Synthetic Child", "go back to filing status", "change filing status to married filing jointly",
    "I was walking my dog earlier", "This question is beyond me",
    # Wrongly flagged by the old keyword lists:
    "My 1099-R is from a Roth IRA",            # "roth" alone is not advice; Roth distributions are in scope
    "Should I type the date with dashes?",     # a question about the form is not tax advice
    "We file separately",                      # an answer, not a question
    "I do not have foreign income",            # a denial is not a disclosure
    "I don't have any rental income",
    "no crypto, no business income",
    "I'm answering for my mother, I have power of attorney",  # stated authority
]

LABELLED = {
    "advice_request": [
        "Should I file separately so I pay less tax?",          # brief 2
        "Would I pay less if we filed separately?",             # brief 2
        "Can I deduct my medications?",                         # brief 2
        "Should I convert my IRA to a Roth?",                   # brief 2
        "What's the best way to get a bigger refund?",
        "Is it better to take the standard deduction or not?",
        "How can I lower my taxes this year?",
        "Do you recommend we file jointly?",
        "what would you do if you were me",
    ],
    "exploitation_concern": [
        "My nephew told me to say single and send the refund to his account",
        "My son handles my money, he said to put his account for the refund",
        "I don't know whose account that is, my caregiver gave me the number",
        "That's not my account, it's my grandson's",
        "Deposit the refund into my neighbor's account",
        "I'm answering for my mother, she can't come to the phone",
        "She won't let me see the bank statements",
        "Someone called me and said I owe the IRS and must pay with gift cards",
    ],
    "out_of_scope": [
        "I have foreign income", "I have a foreign bank account", "I have some bitcoin",
        "I received a 1099-NEC", "I do freelance work on the side", "I have rental income",
        "I sold some stock last year", "I want itemized deductions", "I need an amended return",
        "I need a state return",
    ],
    "1099r_taxable_not_determined": [
        "My 1099-R says taxable amount not determined",
        "My 1099-R has box 2b checked",
    ],
    "uncertain": [
        "I'm not sure, my eye doctor never said", "no idea, can't remember", "I don’t know",
    ],
}


@pytest.mark.parametrize("reply", ORDINARY_ANSWERS)
def test_ordinary_answers_are_not_escalated(reply):
    assert classify_reply(reply) is None, explain(reply)


@pytest.mark.parametrize("expected, reply", [(r, t) for r, texts in LABELLED.items() for t in texts])
def test_replies_get_the_expected_escalation(expected, reply):
    assert classify_reply(reply) == expected, explain(reply)


def test_exploitation_outranks_advice():
    # Safety first (policy.md#exploitation): both signs present, the exploitation ticket wins.
    reply = "My son says I should file jointly so the refund goes to his account"
    assert classify_reply(reply) == "exploitation_concern"


def test_refund_routing_is_flagged_even_with_a_stated_authority():
    reply = "I have power of attorney, send the refund to my account instead of hers"
    assert classify_reply(reply) == "exploitation_concern"


def test_every_guardrail_reason_is_a_shared_escalation_reason():
    reasons = set(typing.get_args(EscalationReason))
    assert set(LABELLED) <= reasons


def test_ordinary_roth_answer_is_asked_again_not_escalated(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="My 1099-R is from a Roth IRA"), config())
    assert isinstance(paused_on(result), str)          # Intake simply asks again
    assert "Which filing status" in paused_on(result)
    assert not result.get("escalations")


# 2. Rules scope checks ----------------------------------------------------------------------------

@pytest.fixture
def case(tmp_path):
    def make(answers=None, w2=None):
        data = json.loads(open(SKELETON_CASE).read())
        data["answers"].update(answers or {})
        data["documents"][0]["values"].update(w2 or {})
        path = tmp_path / "case.json"
        path.write_text(json.dumps(data))
        return str(path)

    return make


@pytest.mark.parametrize("answers, ticket_id", [
    ({"taxpayer_claimed_dependent": True}, "out_of_scope:taxpayer_is_a_dependent"),
    ({"dual_status_alien": True}, "out_of_scope:dual_status_alien"),
    ({"filing_status": "mfs", "spouse_itemizes": True}, "out_of_scope:mfs_spouse_itemizes"),
])
def test_chart_exceptions_escalate_as_out_of_scope(make_graph, case, answers, ticket_id):
    result = make_graph().invoke({"case_path": case(answers)}, config())
    ticket = paused_on(result)
    assert ticket["ticket_id"] == ticket_id
    assert ticket["reason"] == "out_of_scope"
    assert ticket["evidence"]["policy"] == "policy.md#standard-deduction-exceptions"
    assert result["rule_decisions"]["standard_deduction_chart_applies"].outcome is False


def test_stopping_a_chart_exception_ends_without_a_draft(make_graph, case):
    graph = make_graph()
    graph.invoke({"case_path": case({"dual_status_alien": True})}, config())
    result = graph.invoke(Command(resume="stop"), config())
    assert result["status"] == "stopped"


def test_no_chart_exception_means_the_chart_applies(make_graph, case):
    result = make_graph().invoke({"case_path": case()}, config())
    assert result["status"] == "draft_ready"
    assert result["rule_decisions"]["standard_deduction_chart_applies"].outcome is True


@pytest.mark.parametrize("w2, ticket_id, reason", [
    ({"statutory_employee": True}, "out_of_scope:w2-1:statutory_employee", "out_of_scope"),
    ({"allocated_tips": "300"}, "out_of_scope:w2-1:allocated_tips", "out_of_scope"),
    ({"dependent_care_benefits": "1200"}, "out_of_scope:w2-1:dependent_care_benefits", "out_of_scope"),
    ({"box12": [{"code": "W", "amount": "1000"}]}, "out_of_scope:w2-1:box12_W", "out_of_scope"),
    ({"box12": [{"code": "XX", "amount": "50"}]}, "uncertain:w2-1:box12_XX", "uncertain"),
])
def test_w2_scope_signals_escalate(make_graph, case, w2, ticket_id, reason):
    result = make_graph().invoke({"case_path": case(w2=w2)}, config())
    ticket = paused_on(result)
    assert ticket["ticket_id"] == ticket_id
    assert ticket["reason"] == reason


def test_ordinary_box12_codes_need_no_human(make_graph, case):
    w2 = {"box12": [{"code": "D", "amount": "1000"}, {"code": "DD", "amount": "4000"}], "retirement_plan": True}
    result = make_graph().invoke({"case_path": case(w2=w2)}, config())
    assert result["status"] == "draft_ready"


# 3. policy.md is in step with the code ------------------------------------------------------------

def policy_ids():
    return set(re.findall(r'<a id="([^"]+)"></a>', POLICY))


def test_every_rules_citation_has_a_policy_section():
    cited = set(re.findall(r"policy\.md#([\w-]+)", Path("src/agents/rules.py").read_text()))
    assert cited, "Rules should cite policy.md"
    assert cited <= policy_ids(), cited - policy_ids()


def test_every_escalation_reason_is_documented_in_policy():
    for reason in typing.get_args(EscalationReason):
        assert f"`{reason}`" in POLICY, reason


def test_policy_states_the_2025_figures_from_the_brief():
    for figure in ["$15,750", "$31,500", "$23,625", "$2,000", "$1,600", "$6,000", "$75,000", "$150,000",
                   "6%", "2 January 1961", "$25,000", "$32,000", "$34,000", "$44,000", "900–999"]:
        assert figure in POLICY, figure
