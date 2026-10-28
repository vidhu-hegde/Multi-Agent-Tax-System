"""Accessibility and dignity in the Intake dialogue (brief 4.3; owner: Juee). Policy: data/policy.md#dignity.

These check every sentence Intake says to a taxpayer, so a future wording change can't quietly break them.
"""

from types import SimpleNamespace

import pytest

from src.agents import intake

QUESTIONS = [q[1] for q in intake.question_list({"dependent_count": SimpleNamespace(value=1)})]
SAID = list(intake.SAID_TO_TAXPAYER.values())
RETRY_PREFIXES = ["Sorry, I didn't understand that. ", "I've already passed that on to a member of staff. "]

# Terms the brief says should be glossed or, ideally, never appear (brief 4.3, plain language).
JARGON = ["modified adjusted gross income", "magi", "provisional income", "agi ", "adjusted gross income"]
# Internal names that must never reach a taxpayer.
INTERNAL = ["ticket", "escalat", "agent", "orchestrator", "_", "reason code", "interrupt"]


@pytest.mark.parametrize("question", QUESTIONS)
def test_one_question_at_a_time(question):
    assert question.count("?") == 1, question
    assert " and what " not in question.lower() and " also " not in question.lower(), question


@pytest.mark.parametrize("question", QUESTIONS)
def test_questions_are_short(question):
    assert len(question.split()) <= 30, question


@pytest.mark.parametrize("text", QUESTIONS + SAID + RETRY_PREFIXES)
def test_no_tax_jargon(text):
    for term in JARGON:
        assert term not in text.lower(), (term, text)


@pytest.mark.parametrize("text", QUESTIONS + SAID + RETRY_PREFIXES)
def test_no_internal_names_reach_the_taxpayer(text):
    for term in INTERNAL:
        assert term not in text.lower(), (term, text)


def test_yes_no_questions_say_how_to_answer():
    for question in QUESTIONS:
        if question.startswith(("Are you", "Is your", "Can someone", "Were you")):
            assert "yes or no" in question, question


def test_uncertain_answers_are_always_allowed_where_people_often_do_not_know():
    asks = {q[0]: q[1] for q in intake.QUESTIONS}
    for field in ["taxpayer_claimed_dependent", "dual_status_alien", "stated_wages"]:
        assert "not sure" in asks[field], field


def test_retry_messages_do_not_blame_the_person():
    for text in RETRY_PREFIXES:
        for word in ["invalid", "wrong", "error", "incorrect", "failed"]:
            assert word not in text.lower(), (word, text)


def test_advice_reply_declines_without_giving_advice():
    said = intake.SAID_TO_TAXPAYER["advice_request"]
    assert "can't give tax advice" in said
    assert "noted" in said
    for word in ["you should", "better", "recommend", "save", "lower"]:
        assert word not in said.lower(), word


def test_exploitation_reply_does_not_accuse_anyone():
    said = intake.SAID_TO_TAXPAYER["exploitation_concern"]
    for word in ["abuse", "fraud", "scam", "exploit", "suspicious", "pressure", "refund", "account"]:
        assert word not in said.lower(), word


def test_honest_uncertainty_uses_the_brief_wording():
    assert "let me flag this for a volunteer" in intake.SAID_TO_TAXPAYER["uncertain"]


def test_only_test_ssns_are_requested():
    ssn_questions = [q for q in QUESTIONS if "Social Security number" in q]
    assert ssn_questions, "dependents need an SSN question"
    for question in ssn_questions:
        assert "900 through 999" in question and "made-up" in question
    assert not any("your social security number" in q.lower() for q in QUESTIONS), "never ask for the taxpayer's own SSN"
