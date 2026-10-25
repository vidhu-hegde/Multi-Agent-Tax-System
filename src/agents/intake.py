"""Intake agent (STUB). The only agent that talks to the taxpayer.

Asks one question at a time through interrupt(). Answers already in the case file are used without
asking. A reply that is not a valid answer is classified: a request for advice, a sign of exploitation or
third-party pressure, or "I'm not sure" each escalate to a human; anything else is asked again.

To be replaced by the LLM-driven Intake agent; keep the same state outputs and replace classify_reply().
"""

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from langgraph.types import interrupt

from src.escalation import escalate
from src.schemas import DocumentRef, IntakeAnswer
from src.state import SilverFileState, current_answers

FILING_STATUSES = {"single", "mfj", "mfs", "hoh", "qss"}
NOT_APPLICABLE = {"none", "no", "n/a", "na"}
UNKNOWN = {"not sure", "unsure", "don't know", "dont know", "i don't know", "i dont know"}


def parse_filing_status(raw):
    value = str(raw).strip().lower()
    if value not in FILING_STATUSES:
        raise ValueError(raw)
    return value


def parse_date(raw):
    return raw if isinstance(raw, date) else date.fromisoformat(str(raw).strip())


def parse_yes_no(raw):
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"yes", "y", "true"}:
        return True
    if value in {"no", "n", "false"}:
        return False
    raise ValueError(raw)


def parse_money(raw):
    try:
        value = Decimal(str(raw).strip().replace("$", "").replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(raw) from exc
    if value < 0:
        raise ValueError(raw)
    return value


def parse_money_or_unknown(raw):
    """For estimates the person may not remember: 'not sure' is a valid answer, stored as None."""
    if raw is None or str(raw).strip().lower() in UNKNOWN:
        return None
    return parse_money(raw)


def parse_year_or_none(raw):
    if raw is None or str(raw).strip().lower() in NOT_APPLICABLE:
        return None
    year = int(str(raw).strip())
    if not 1900 <= year <= 2025:
        raise ValueError(raw)
    return year


def _is_joint(known, inventory):
    return known["filing_status"].value == "mfj"


def _may_have_lost_spouse(known, inventory):
    return known["filing_status"].value in {"mfj", "qss"}


def _has_w2(known, inventory):
    return any(ref.form_type == "W-2" for ref in inventory)


# (field, question, parser, ask_only_if)
QUESTIONS = [
    ("filing_status", "Which filing status are you using? Type one of: single, mfj, mfs, hoh, qss.", parse_filing_status, None),
    ("spouse_died_year", "If your spouse has passed away, which year was it? Type none if this does not apply.", parse_year_or_none, _may_have_lost_spouse),
    ("taxpayer_dob", "What is your date of birth? Please type it as YYYY-MM-DD.", parse_date, None),
    ("taxpayer_blind", "Are you legally blind? Please type yes or no.", parse_yes_no, None),
    ("spouse_dob", "What is your spouse's date of birth? Please type it as YYYY-MM-DD.", parse_date, _is_joint),
    ("spouse_blind", "Is your spouse legally blind? Please type yes or no.", parse_yes_no, _is_joint),
    ("stated_wages", "About how much did you earn from jobs in 2025, before tax? Type not sure if you don't know.", parse_money_or_unknown, _has_w2),
    ("adjustments", "What is the total on Schedule 1, line 26? Type 0 if you don't have one.", parse_money, None),
    ("estimated_payments", "How much did you pay in estimated tax for 2025? Type 0 if none.", parse_money, None),
]

# Stub keyword rules. The LLM Intake agent replaces classify_reply() with a model call.
ADVICE_PHRASES = ["should i", "would i pay less", "can i deduct", "is it better", "roth", "lower my tax",
                  "save on tax", "file separately", "pay less tax"]
EXPLOITATION_PHRASES = ["send the refund", "refund to his", "refund to her", "refund to their", "refund to my son",
                        "refund to my daughter", "not my account", "whose account", "answering for",
                        "on her behalf", "on his behalf", "told me to say", "said i have to"]
UNCERTAIN_PHRASES = ["not sure", "unsure", "don't know", "dont know", "no idea", "can't remember", "cannot remember"]


def classify_reply(text: str) -> str | None:
    """Why a reply that isn't a valid answer needs a human: an escalation reason, or None to just ask again."""
    lowered = str(text).lower()
    if any(p in lowered for p in EXPLOITATION_PHRASES):
        return "exploitation_concern"
    if any(p in lowered for p in ADVICE_PHRASES):
        return "advice_request"
    if any(p in lowered for p in UNCERTAIN_PHRASES):
        return "uncertain"
    return None


ESCALATION_DETAIL = {
    "advice_request": "The taxpayer asked for tax advice, which SilverFile does not give. Noted for a volunteer preparer.",
    "exploitation_concern": "The reply suggests a third party may be directing the return or the refund.",
    "uncertain": "The taxpayer was not sure how to answer. Flagged for a volunteer.",
}
SAID_TO_TAXPAYER = {
    "advice_request": "That's a question for a volunteer preparer. I can't give tax advice, but I've noted it so they can help.",
    "exploitation_concern": "Thank you. I've asked a member of staff to look at this before we go on.",
    "uncertain": "That's fine. I'm not sure either, so I've flagged it for a volunteer.",
}


def load_case(case_path: str | None) -> dict:
    if not case_path:
        return {}
    return json.loads(Path(case_path).read_text())


def intake(state: SilverFileState) -> dict:
    case = load_case(state.get("case_path"))
    case_answers = case.get("answers", {})
    inventory = state.get("document_inventory") or [DocumentRef.model_validate(d) for d in case.get("documents", [])]
    raised = state.get("escalations", {})
    known = current_answers(state)
    new_answers: list[IntakeAnswer] = []
    update = {"answers": new_answers, "last_agent": "intake"}
    if not state.get("document_inventory"):
        update["document_inventory"] = inventory

    for field, question, parse, ask_only_if in QUESTIONS:
        if field in known or (ask_only_if and not ask_only_if(known, inventory)):
            continue
        answer = None
        if field in case_answers:
            try:
                raw = case_answers[field]
                answer = IntakeAnswer(field=field, value=parse(raw), raw_text=str(raw), entered_by="case file")
            except ValueError:
                pass  # bad value in the case file: ask the person instead
        prompt = question
        while answer is None:
            reply = interrupt(prompt)
            try:
                answer = IntakeAnswer(field=field, value=parse(reply), raw_text=str(reply))
                break
            except ValueError:
                pass
            reason = classify_reply(reply)
            if reason is None:
                prompt = f"Sorry, I didn't understand that. {question}"
                continue
            key = f"{field}:{hashlib.sha1(str(reply).encode()).hexdigest()[:8]}"
            if f"{reason}:{key}" in raised:
                prompt = f"I've already passed that on to a member of staff. {question}"
                continue
            # Stop here; the human decides, then Intake picks up at this same question.
            update.update(escalate(
                reason, raised_by="intake", key=key, detail=ESCALATION_DETAIL[reason],
                evidence={"question": question, "reply": str(reply), "said_to_taxpayer": SAID_TO_TAXPAYER[reason]},
            ))
            return update
        new_answers.append(answer)
        known[field] = answer

    update["intake_complete"] = True
    return update
