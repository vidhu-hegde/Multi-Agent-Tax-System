"""Intake agent (STUB). The only agent that talks to the taxpayer.

Asks one question at a time through interrupt(). Answers already in the case file are used without
asking. To be replaced by the LLM-driven Intake agent; keep the same state outputs.
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from langgraph.types import interrupt

from src.schemas import DocumentRef, IntakeAnswer
from src.state import SilverFileState, current_answers

FILING_STATUSES = {"single", "mfj", "mfs", "hoh", "qss"}


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


def _is_joint(known):
    return known["filing_status"].value == "mfj"


# (field, question, parser, ask_only_if)
QUESTIONS = [
    ("filing_status", "Which filing status are you using? Type one of: single, mfj, mfs, hoh, qss.", parse_filing_status, None),
    ("taxpayer_dob", "What is your date of birth? Please type it as YYYY-MM-DD.", parse_date, None),
    ("taxpayer_blind", "Are you legally blind? Please type yes or no.", parse_yes_no, None),
    ("spouse_dob", "What is your spouse's date of birth? Please type it as YYYY-MM-DD.", parse_date, _is_joint),
    ("spouse_blind", "Is your spouse legally blind? Please type yes or no.", parse_yes_no, _is_joint),
    ("adjustments", "What is the total on Schedule 1, line 26? Type 0 if you don't have one.", parse_money, None),
    ("estimated_payments", "How much did you pay in estimated tax for 2025? Type 0 if none.", parse_money, None),
]


def load_case(case_path: str | None) -> dict:
    if not case_path:
        return {}
    return json.loads(Path(case_path).read_text())


def intake(state: SilverFileState) -> dict:
    case = load_case(state.get("case_path"))
    case_answers = case.get("answers", {})
    known = current_answers(state)
    new_answers: list[IntakeAnswer] = []

    for field, question, parse, ask_only_if in QUESTIONS:
        if field in known or (ask_only_if and not ask_only_if(known)):
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
            raw = interrupt(prompt)
            try:
                answer = IntakeAnswer(field=field, value=parse(raw), raw_text=str(raw))
            except ValueError:
                prompt = f"Sorry, I didn't understand that. {question}"
        new_answers.append(answer)
        known[field] = answer

    update = {"answers": new_answers, "intake_complete": True, "last_agent": "intake"}
    if not state.get("document_inventory"):
        update["document_inventory"] = [DocumentRef.model_validate(d) for d in case.get("documents", [])]
    return update
