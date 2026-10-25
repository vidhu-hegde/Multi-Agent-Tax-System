"""One-question Intake, using the shared contracts and the existing human handoff.

Each accepted interactive answer returns a state update before asking the next question.
Case-file answers can be loaded together. Intake records inputs; Rules and Computation
own interpretation and arithmetic. No language model is needed for structured replies.
"""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import get_args

from langgraph.types import interrupt
from pydantic import TypeAdapter

from src.escalation import escalate
from src.memory import invoke_model, redact_ssns
from src.schemas import Dependent, DocumentRef, FormType, IntakeAnswer, RevisionRequest, SSN
from src.state import SilverFileState, current_answers

FILING_STATUSES = {
    "single": "single",
    "mfj": "mfj",
    "married filing jointly": "mfj",
    "mfs": "mfs",
    "married filing separately": "mfs",
    "hoh": "hoh",
    "head of household": "hoh",
    "qss": "qss",
    "qualifying surviving spouse": "qss",
}
NOT_APPLICABLE = {"none", "no", "n/a", "na"}
UNKNOWN = {"not sure", "unsure", "don't know", "dont know", "i don't know", "i dont know"}


def parse_filing_status(raw):
    value = str(raw).strip().lower()
    if value not in FILING_STATUSES:
        raise ValueError("Choose a listed filing status")
    return FILING_STATUSES[value]


def parse_date(raw):
    value = raw if type(raw) is date else date.fromisoformat(str(raw).strip())
    if value > date(2025, 12, 31):
        raise ValueError("Birth date must be no later than the tax year")
    return value


def parse_yes_no(raw):
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"yes", "y", "true"}:
        return True
    if value in {"no", "n", "false"}:
        return False
    raise ValueError("Please type yes or no")


def parse_money(raw):
    try:
        value = Decimal(str(raw).strip().replace("$", "").replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("Please enter an amount") from exc
    if not value.is_finite() or value < 0:
        raise ValueError("Please enter a finite, nonnegative amount")
    return value


def parse_money_or_unknown(raw):
    if raw is None or str(raw).strip().lower() in UNKNOWN:
        return None
    return parse_money(raw)


def parse_year_or_none(raw):
    if raw is None or str(raw).strip().lower() in NOT_APPLICABLE:
        return None
    year = int(str(raw).strip())
    if not 1900 <= year <= 2025:
        raise ValueError("Please enter a year no later than 2025")
    return year


def parse_count(raw):
    count = int(str(raw).strip())
    if count < 0:
        raise ValueError("Please enter zero or a positive whole number")
    return count


def parse_name(raw):
    value = str(raw).strip()
    if not value:
        raise ValueError("Please enter a value")
    return value


def parse_test_ssn(raw):
    return TypeAdapter(SSN).validate_python(str(raw).strip())


def parse_inventory(raw):
    if isinstance(raw, str):
        if raw.strip().lower() in NOT_APPLICABLE:
            return []
        if raw.lstrip().startswith("["):
            raw = json.loads(raw)
        else:
            raw = [
                dict(document_id=f"doc-{i}", form_type=kind.strip().upper()) for i, kind in enumerate(raw.split(","), 1)
            ]
            for ref in raw:
                if ref["form_type"] not in get_args(FormType):
                    ref["description"] = ref["form_type"]
                    ref["form_type"] = "other"
    refs = [DocumentRef.model_validate(ref) for ref in raw]
    if len({ref.document_id for ref in refs}) != len(refs):
        raise ValueError("Each document needs a different id")
    return refs


def _is_joint(known, inventory):
    return known.get("filing_status") is not None and known["filing_status"].value == "mfj"


def _has_w2(known, inventory):
    return any(ref.form_type == "W-2" for ref in inventory)


# One field per question. These are inputs, never eligibility conclusions.
QUESTIONS = [
    (
        "filing_status",
        "Which filing status are you using? Choose single, married filing jointly (mfj), married filing separately (mfs), head of household (hoh), or qualifying surviving spouse (qss).",
        parse_filing_status,
        None,
    ),
    (
        "spouse_died_year",
        "In what year did your spouse pass away? Type none if this does not apply.",
        parse_year_or_none,
        None,
    ),
    ("taxpayer_dob", "What is your date of birth? Please type it as YYYY-MM-DD.", parse_date, None),
    ("taxpayer_blind", "Are you legally blind? Please type yes or no.", parse_yes_no, None),
    ("spouse_dob", "What is your spouse's date of birth? Please type it as YYYY-MM-DD.", parse_date, _is_joint),
    ("spouse_blind", "Is your spouse legally blind? Please type yes or no.", parse_yes_no, _is_joint),
    (
        "taxpayer_claimed_dependent",
        "Can someone else claim you as a dependent on their tax return? Please type yes or no, or say you're not sure.",
        parse_yes_no,
        None,
    ),
    (
        "spouse_itemizes",
        "Is your separately filing spouse listing individual deductions instead of taking the standard deduction? Type yes or no.",
        parse_yes_no,
        lambda k, i: k["filing_status"].value == "mfs",
    ),
    (
        "dual_status_alien",
        "Were you a dual-status alien in 2025 (a resident for only part of the year for federal tax purposes)? Type yes or no, or not sure.",
        parse_yes_no,
        None,
    ),
    (
        "document_inventory",
        "Which tax documents do you have for 2025? Type form names separated by commas, such as W-2, SSA-1099; type none if there are none.",
        parse_inventory,
        None,
    ),
    ("dependent_count", "How many dependents will you list on this return? Type 0 if none.", parse_count, None),
    (
        "stated_wages",
        "About how much did you earn from jobs in 2025, before tax? Type not sure if you don't know.",
        parse_money_or_unknown,
        _has_w2,
    ),
    (
        "adjustments",
        "What is the total on Schedule 1, line 26 (adjustments to income)? Type 0 if you don't have one.",
        parse_money,
        None,
    ),
    (
        "schedule2_total_tax",
        "What is the total additional tax on Schedule 2, line 21? Type 0 if you don't have one.",
        parse_money,
        None,
    ),
    (
        "schedule3_nonrefundable_credits",
        "What is the total on Schedule 3, line 8 (credits that reduce tax)? Type 0 if you don't have one.",
        parse_money,
        None,
    ),
    (
        "schedule3_other_payments",
        "What is the total on Schedule 3, line 15 (other payments and refundable credits)? Type 0 if you don't have one.",
        parse_money,
        None,
    ),
    (
        "estimated_payments",
        "How much did you pay in estimated tax for 2025 (tax payments you sent during the year)? Type 0 if none.",
        parse_money,
        None,
    ),
]

# These inputs are collected here but their owner modules do not consume them yet.
# Remove each gate only alongside its downstream integration and end-to-end tests.
PENDING_DOWNSTREAM_FIELDS = (
    "taxpayer_claimed_dependent",
    "spouse_itemizes",
    "dual_status_alien",
    "dependent_count",
    "schedule2_total_tax",
    "schedule3_nonrefundable_credits",
    "schedule3_other_payments",
)

ADVICE_PHRASES = [
    "should i",
    "would i pay less",
    "can i deduct",
    "is it better",
    "roth",
    "lower my tax",
    "save on tax",
    "file separately",
    "pay less tax",
]
EXPLOITATION_PHRASES = [
    "send the refund",
    "refund to his",
    "refund to her",
    "refund to their",
    "refund to my son",
    "refund to my daughter",
    "not my account",
    "whose account",
    "answering for",
    "on her behalf",
    "on his behalf",
    "told me to say",
    "said i have to",
]
UNCERTAIN_PHRASES = ["not sure", "unsure", "don't know", "dont know", "no idea", "can't remember", "cannot remember"]

# Disclosure vocabulary from assignment §3.3, routed through the shared out_of_scope
# catalogue entry. This notices what the person says; Rules still decides eligibility.
SCOPE_DISCLOSURES = re.compile(
    r"\b(?:foreign (?:income|accounts?)|digital assets?|1099[- ]?NEC|"
    r"self[- ]employment(?: income)?|business income|rental income|capital gains|"
    r"schedule [ACDE]|itemi[sz]ed deductions?|amended (?:tax )?returns?|"
    r"prior[- ]year (?:tax )?returns?|state (?:tax )?returns?)\b", re.I
)


def scope_disclosure(text: str) -> bool:
    for match in SCOPE_DISCLOSURES.finditer(text):
        prefix = text[:match.start()]
        if not re.search(r"\b(?:no|without|(?:do not|don't|did not|didn't) have)(?: any)?\s*$", prefix, re.I):
            return True
    return False


def classify_reply(text: str) -> str | None:
    lowered = str(text).lower()
    if any(p in lowered for p in EXPLOITATION_PHRASES):
        return "exploitation_concern"
    if any(p in lowered for p in ADVICE_PHRASES):
        return "advice_request"
    if scope_disclosure(lowered):
        return "out_of_scope"
    if any(p in lowered for p in UNCERTAIN_PHRASES):
        return "uncertain"
    return None


def classify_with_model(model, state, text, use_context_strategy=True):
    """Optional model fallback for unclear replies, constrained to the shared escalation catalogue."""
    response, update = invoke_model(model, state, text, use_context_strategy)
    content = response.content
    if isinstance(content, list):
        content = "".join(block.get("text", "") for block in content if isinstance(block, dict))
    try:
        payload = json.loads(content)
        reason = payload["reason"]
        if reason not in (*ESCALATION_DETAIL, None):
            reason = "uncertain"
    except (ValueError, TypeError, KeyError):
        reason = "uncertain"
    # Keep only the validated classification, never model-generated advice or extra text.
    update["messages"][-1] = response.model_copy(update={"content": json.dumps({"reason": reason})})
    return reason, update


ESCALATION_DETAIL = {
    "out_of_scope": "The taxpayer disclosed an item outside SilverFile's supported scope. A volunteer must review it.",
    "advice_request": "The taxpayer asked for tax advice. Noted for a volunteer preparer.",
    "exploitation_concern": "The reply suggests a third party may be directing the return or refund.",
    "uncertain": "The taxpayer was not sure how to answer. Flagged for a volunteer.",
}
SAID_TO_TAXPAYER = {
    "out_of_scope": "That needs a volunteer's help. I've flagged it before we go on.",
    "advice_request": "That's a question for a volunteer preparer. I can't give tax advice, but I've noted it so they can help.",
    "exploitation_concern": "Thank you. I've asked a member of staff to look at this before we go on.",
    "uncertain": "I'm not sure; let me flag this for a volunteer.",
}


def load_case(case_path: str | None) -> dict:
    return json.loads(Path(case_path).read_text()) if case_path else {}


def question_list(known):
    questions = list(QUESTIONS)
    count = known.get("dependent_count")
    for i in range(1, (count.value if count else 0) + 1):
        questions.extend(
            [
                (f"dependent_{i}_name", f"What is dependent {i}'s name?", parse_name, None),
                (f"dependent_{i}_relationship", f"How is dependent {i} related to you?", parse_name, None),
                (
                    f"dependent_{i}_ssn",
                    f"What is dependent {i}'s test Social Security number? Use only a made-up number beginning with 900 through 999, formatted 901-12-3456.",
                    parse_test_ssn,
                    None,
                ),
            ]
        )
    return questions


def recap(known):
    covered = []
    if "filing_status" in known:
        covered.append("filing status: " + known["filing_status"].value)
    for field, label in [
        ("taxpayer_dob", "your birth date"),
        ("taxpayer_blind", "your blindness answer"),
        ("dependent_count", "dependent count"),
        ("document_inventory", "document list"),
        ("adjustments", "adjustments"),
        ("estimated_payments", "estimated payments"),
    ]:
        if field in known:
            covered.append(label + " recorded")
    return "So far: " + "; ".join(covered) + ". " if covered else ""


def _field_name(text):
    return str(text).strip().lower().replace(" ", "_")


def make_intake(model, use_context_strategy=True):
    """Plug into build_graph(..., agents={'intake': make_intake(model, enabled)})."""

    def node(state: SilverFileState):
        return _intake(state, model=model, use_context_strategy=use_context_strategy)

    return node


def intake(state: SilverFileState) -> dict:
    return _intake(state)


def _intake(state: SilverFileState, model=None, use_context_strategy=True) -> dict:
    case = load_case(state.get("case_path"))
    supplied = dict(case.get("answers", {}))
    if "documents" in case:
        supplied["document_inventory"] = case["documents"]
    inventory = state.get("document_inventory", [])
    known = current_answers(state)
    update = {"answers": [], "last_agent": "intake", "intake_complete": False}
    revisit = state.get("intake_revisit")
    questions = question_list(known)
    pending = next((q for q in questions if q[0] == revisit), None) if revisit else None
    if revisit and pending is None:
        raise ValueError("Unknown Intake field to revisit")

    while True:
        if pending is None:
            questions = question_list(known)
            pending = next(
                (q for q in questions if q[0] not in known and (q[3] is None or q[3](known, inventory))), None
            )
        if pending is None:
            count = known["dependent_count"].value
            dependents = [
                Dependent(
                    name=known[f"dependent_{i}_name"].value,
                    relationship=known[f"dependent_{i}_relationship"].value,
                    ssn=known[f"dependent_{i}_ssn"].value,
                )
                for i in range(1, count + 1)
            ]
            update["answers"].append(IntakeAnswer(field="dependents", value=dependents, entered_by="intake"))
            unsupported = [field for field in PENDING_DOWNSTREAM_FIELDS if field in known and known[field].value]
            if unsupported:
                fingerprint = hashlib.sha256(str([(f, known[f].value) for f in unsupported]).encode()).hexdigest()[:12]
                update.update(
                    escalate(
                        "uncertain",
                        raised_by="intake",
                        key=f"downstream-integration:{fingerprint}",
                        detail="These recorded inputs still need downstream integration before a draft can be prepared.",
                        evidence={"fields": unsupported, "said_to_taxpayer": SAID_TO_TAXPAYER["uncertain"]},
                    )
                )
                update["intake_revisit"] = unsupported[0]
                return update
            update["intake_complete"] = True
            return update
        field, question, parse, _ = pending
        # Case imports validate through exactly the same parsers as interactive answers.
        from_case = field in supplied and not revisit
        raw = supplied.get(field)
        if from_case:
            try:
                value = parse(raw)
            except (ValueError, TypeError):
                from_case = False
        if not from_case:
            prompt = recap(known) + question
            while True:
                reply = interrupt(prompt)
                model_called = False
                safe = redact_ssns(reply)
                # Safety disclosures apply to the whole turn, even while another field
                # is requested or a structured reply includes a separate disclosure.
                turn_reason = classify_reply(str(safe))
                if turn_reason == "uncertain":
                    turn_reason = None  # retain the field-specific unknown-wages contract
                command = re.fullmatch(r"go back(?: to)? (.+)", str(safe), flags=re.I)
                correction = re.fullmatch(r"change (.+?) (?:to|=) (.+)", str(safe), flags=re.I)
                if turn_reason:
                    raw = safe
                elif command or correction or isinstance(safe, dict):
                    target = (
                        _field_name(safe.get("field", ""))
                        if isinstance(safe, dict)
                        else _field_name((command or correction)[1])
                    )
                    target_question = next((q for q in questions if q[0] == target), None)
                    if target_question is None:
                        prompt = "That field is not available here. " + question
                        continue
                    if command:
                        update["intake_revisit"] = target
                        return update
                    field, question, parse, _ = target_question
                    if isinstance(safe, dict):
                        raw = reply.get("value") if field.endswith("_ssn") else safe.get("value")
                    else:
                        raw = correction[2]
                else:
                    raw = reply if field.endswith("_ssn") else safe
                reason = turn_reason or classify_reply(str(raw))
                # An explicitly unknown wage estimate is allowed by the existing Rules contract.
                if reason == "uncertain" and parse is parse_money_or_unknown and str(raw).strip().lower() in UNKNOWN:
                    reason = None
                if reason is None:
                    try:
                        value = parse(raw)
                        break
                    except (ValueError, TypeError):
                        if model is None:
                            prompt = "Sorry, I didn't understand that. " + question
                            continue
                        reason, model_update = classify_with_model(
                            model,
                            {**state, "answers": list(known.values())},
                            json.dumps({"question": question, "reply": safe}),
                            use_context_strategy,
                        )
                        model_called = True
                        update.update(model_update)
                        if reason is None:
                            # Commit the model result before asking again: interrupt replay must
                            # not repeat a completed, billed model call on the next resume.
                            update["guard_window_start"] = len(state.get("handoffs", []))
                            return update
                if reason:
                    key = f"{field}:{hashlib.sha256(str(safe).encode()).hexdigest()[:12]}"
                    if f"{reason}:{key}" in state.get("escalations", {}):
                        if model_called:
                            update["guard_window_start"] = len(state.get("handoffs", []))
                            return update
                        prompt = "I've already passed that on to a member of staff. " + question
                        continue
                    update.update(
                        escalate(
                            reason,
                            raised_by="intake",
                            key=key,
                            detail=ESCALATION_DETAIL[reason],
                            evidence={
                                "question": question,
                                "reply": safe,
                                "said_to_taxpayer": SAID_TO_TAXPAYER[reason],
                            },
                        )
                    )
                    return update
        previous = known.get(field)
        if (
            field == "document_inventory"
            and previous is not None
            and previous.value != value
            and state.get("documents")
        ):
            # The graph has no retraction interface for extracted records yet. Do not compute
            # against a mixture of the new inventory and old records while awaiting that hook.
            update.update(
                escalate(
                    "uncertain",
                    raised_by="intake",
                    key="inventory-retraction",
                    detail="Changing extracted documents needs staff coordination before this return can continue.",
                    evidence={"field": field, "said_to_taxpayer": SAID_TO_TAXPAYER["uncertain"]},
                )
            )
            return update
        answer = IntakeAnswer(
            field=field,
            value=value,
            raw_text=None if field.endswith("_ssn") else str(redact_ssns(raw)),
            entered_by="case file" if from_case else "taxpayer",
        )
        update["answers"].append(answer)
        known[field] = answer
        if field == "document_inventory":
            inventory = value
            update["document_inventory"] = value
        if previous is not None and previous.value != value:
            # Use the existing routing contract; do not replace the orchestrator or compute locally.
            requests = list(state.get("revision_requests", []))
            for target in ("rules", "computation"):
                request = RevisionRequest(target=target, reason=f"Intake corrected {field}", raised_by="intake")
                if request not in requests:
                    requests.append(request)
            update.update(revision_requests=requests, review_status="pending", review_passes=0, status="in_progress")
        if not from_case:
            update["intake_revisit"] = None
            # A confirmed reply is progress, unlike a pathological handoff loop.
            update["guard_window_start"] = len(state.get("handoffs", []))
            return update
        pending = None
