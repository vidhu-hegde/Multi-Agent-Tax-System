"""Shared data contracts. Every agent reads and writes these types, so change them here and nowhere else.

Money is always Decimal (never float). Every amount on the draft is a LineValue, and a LineValue
cannot exist without at least one Provenance record explaining where the amount came from.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from src.security import (
    SSNValidationError,
    TEST_SSN_PATTERN,
    validate_test_ssn,
)


_timestamp_lock = Lock()
_last_timestamp = datetime.min.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    """Return a process-local UTC timestamp that is strictly increasing.

    Some platforms can return the same wall-clock value for several rapid
    calls. SilverFile uses timestamps to identify and order immutable events,
    so ties would make a legitimate correction look like a conflicting replay.
    """
    global _last_timestamp

    with _timestamp_lock:
        current = datetime.now(timezone.utc)
        if current <= _last_timestamp:
            current = _last_timestamp + timedelta(microseconds=1)
        _last_timestamp = current
        return current


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, revalidate_instances="always")


# Only IRS test-range SSNs (900-999 prefix) are accepted, so a real SSN can never be entered.
# Backward-compatible schema name; the security module is authoritative.
SSN_PATTERN = TEST_SSN_PATTERN
SSN = Annotated[str, StringConstraints(pattern=SSN_PATTERN)]
EIN = Annotated[str, StringConstraints(pattern=r"^\d{2}-\d{7}$")]
Money = Annotated[Decimal, Field(ge=0)]

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

AgentName = Literal["orchestrator", "intake", "extraction", "rules", "computation", "review", "human"]

# The 1040-SR lines SilverFile fills, in form order.
FORM_LINES: dict[str, str] = {
    "1z": "Total wages",
    "2a": "Tax-exempt interest",
    "2b": "Taxable interest",
    "3a": "Qualified dividends",
    "3b": "Ordinary dividends",
    "4a": "IRA distributions",
    "4b": "IRA distributions, taxable amount",
    "5a": "Pensions and annuities",
    "5b": "Pensions and annuities, taxable amount",
    "6a": "Social Security benefits",
    "6b": "Social Security benefits, taxable amount",
    "9": "Total income",
    "10": "Adjustments to income",
    "11a": "Adjusted gross income",
    "12e": "Standard deduction",
    "13b": "Additional deductions from Schedule 1-A",
    "14": "Total deductions",
    "15": "Taxable income",
    "16": "Tax",
    "17": "Additional tax from Schedule 2, line 3",
    "18": "Tax before credits",
    "20": "Credits from Schedule 3, line 8",
    "21": "Total credits",
    "22": "Tax after credits",
    "23": "Other taxes from Schedule 2, line 21",
    "24": "Total tax",
    "25a": "Federal income tax withheld from W-2",
    "25b": "Federal income tax withheld from 1099",
    "25d": "Total federal income tax withheld",
    "26": "Estimated tax payments",
    "31": "Other payments from Schedule 3, line 15",
    "32": "Total other payments and credits",
    "33": "Total payments",
    "34": "Overpayment",
    "37": "Amount you owe",
}


# --- Provenance -------------------------------------------------------------


class Provenance(Contract):
    """One step in how an amount was obtained. A line's provenance list reads like a calculation."""

    kind: Literal["document", "user_input", "tool", "rule"]
    source: NonEmpty  # "W-2 w2-1, box 1", "intake: estimated_payments", "tax_math.sum", "policy.md#standard-deduction"
    value: Any = None
    inputs: dict[str, Any] = Field(default_factory=dict)  # tool arguments, or extra context
    citation: str | None = None  # policy.md section, for rule steps
    entered_by: NonEmpty | None = None  # for user input: "taxpayer", "case file", staff id
    recorded_at: datetime = Field(default_factory=_now)
    stub: bool = False  # True while a placeholder stands in for the real tool or agent
    via: str | None = None  # tool steps: the tax_math MCP server URL, or None when computed in-process


class LineValue(Contract):
    line: NonEmpty
    amount: Decimal
    provenance: list[Provenance] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)  # other lines this one was computed from

    @property
    def label(self) -> str:
        return FORM_LINES.get(self.line, self.line)

    @property
    def is_stub(self) -> bool:
        return any(p.stub for p in self.provenance)


# --- Intake ------------------------------------------------------------------


class IntakeAnswer(Contract):
    """One answer from the taxpayer. Answers are appended, never overwritten, so history is kept."""

    field: NonEmpty  # "filing_status", "taxpayer_dob", ...
    value: Any
    raw_text: str | None = None
    entered_by: NonEmpty = "taxpayer"
    answered_at: datetime = Field(default_factory=_now)


class Dependent(Contract):
    name: str
    ssn: SSN
    relationship: str


# --- Documents ---------------------------------------------------------------

FormType = Literal["W-2", "1099-INT", "1099-DIV", "1099-R", "SSA-1099"]


class DocumentRef(Contract):
    """A document the taxpayer has. Either an image to extract, or values typed in by the user."""

    # Typed values can hold an SSN; validation errors must not quote them back.
    model_config = ConfigDict(**Contract.model_config, hide_input_in_errors=True)

    document_id: NonEmpty
    form_type: FormType | Literal["other"]
    image_path: str | None = None
    values: dict[str, Any] | None = None
    entered_by: NonEmpty = "case file"
    entered_at: datetime = Field(default_factory=_now)
    description: str = ""  # e.g. "1099-NEC from consulting work" for an out-of-scope document

    @model_validator(mode="before")
    @classmethod
    def _keep_only_last_four(cls, data):
        """Typed W-2 values may include the employee's SSN. As on W2Record, it must be in the test range and only
        the last four digits are kept, so the full number never reaches state or checkpoints (policy.md#ssn-test-range)."""
        values = data.get("values") if isinstance(data, dict) else None
        if isinstance(values, dict) and values.get("employee_ssn") is not None:
            values = dict(values)
            try:
                ssn = validate_test_ssn(values.pop("employee_ssn"))
            except SSNValidationError:
                raise ValueError("the W-2's SSN is outside the 900-999 test range; only test SSNs are accepted") from None
            data = {**data, "values": {**values, "employee_ssn_last4": ssn[-4:]}}
        return data


class _Record(Contract):
    document_id: NonEmpty
    source: Provenance  # where the record came from: image extraction or user entry


class W2Box12(Contract):
    code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,2}$")]
    amount: Money


class W2Record(_Record):
    """A W-2. Field choices are recorded in docs/IMPLEMENTATION_NOTES.md (W-2 record fields)."""

    model_config = ConfigDict(**Contract.model_config, hide_input_in_errors=True)  # the input can hold an SSN

    form_type: Literal["W-2"] = "W-2"
    employer_name: NonEmpty  # box c, first line
    employer_ein: EIN | None = None  # box b: spots the same W-2 uploaded twice
    employee_name: str | None = None  # box e: whose W-2 this is on a joint return
    employee_ssn_last4: Annotated[str, StringConstraints(pattern=r"^\d{4}$")] | None = None  # box a, masked
    wages: Money  # box 1 -> line 1z
    federal_withheld: Money = Decimal("0")  # box 2 -> line 25a
    # Boxes 3-6 are not on the 1040-SR; they let Review catch misread images (box 4 = 6.2% of box 3, etc.)
    social_security_wages: Money | None = None  # box 3
    social_security_withheld: Money | None = None  # box 4
    medicare_wages: Money | None = None  # box 5
    medicare_withheld: Money | None = None  # box 6
    # Scope signals: not used in arithmetic, but some values mean the return is out of scope (Rules decides).
    allocated_tips: Money | None = None  # box 8 -> Form 4137
    dependent_care_benefits: Money | None = None  # box 10 -> Form 2441
    box12: list[W2Box12] = Field(default_factory=list)  # box 12a-d: code + amount
    statutory_employee: bool = False  # box 13 -> Schedule C
    retirement_plan: bool = False  # box 13
    third_party_sick_pay: bool = False  # box 13

    @model_validator(mode="before")
    @classmethod
    def _keep_only_last_four(cls, data):
        """Extraction passes the SSN it read as `employee_ssn`. It must be in the test range, and only the
        last four digits are kept, so a full SSN never reaches state, logs, traces or prompts."""
        if isinstance(data, dict) and "employee_ssn" in data:
            data = dict(data)
            ssn = data.pop("employee_ssn")
            if ssn is not None:
                try:
                    validated_ssn = validate_test_ssn(ssn)
                except SSNValidationError as exc:
                    raise ValueError(
                        "the W-2 shows an SSN outside the 900-999 test range; "
                        "only test SSNs are accepted"
                    ) from exc

                data["employee_ssn_last4"] = validated_ssn[-4:]
        return data


class Interest1099(_Record):
    form_type: Literal["1099-INT"] = "1099-INT"
    payer_name: NonEmpty
    interest: Money = Decimal("0")  # box 1
    tax_exempt_interest: Money = Decimal("0")  # box 8
    federal_withheld: Money = Decimal("0")  # box 4


class Dividend1099(_Record):
    form_type: Literal["1099-DIV"] = "1099-DIV"
    payer_name: NonEmpty
    ordinary_dividends: Money = Decimal("0")  # box 1a
    qualified_dividends: Money = Decimal("0")  # box 1b
    federal_withheld: Money = Decimal("0")  # box 4


class Retirement1099R(_Record):
    form_type: Literal["1099-R"] = "1099-R"
    payer_name: NonEmpty
    gross_distribution: Money  # box 1
    taxable_amount: Money | None = None  # box 2a
    taxable_not_determined: bool = False  # box 2b: always escalates
    federal_withheld: Money = Decimal("0")  # box 4
    distribution_code: str = ""  # box 7
    ira_sep_simple: bool = False  # IRA/SEP/SIMPLE box: line 4 if checked, else line 5


class SSA1099(_Record):
    form_type: Literal["SSA-1099"] = "SSA-1099"
    net_benefits: Decimal  # box 5 (can be negative)
    federal_withheld: Money = Decimal("0")  # box 6


TaxDocument = Annotated[
    Union[W2Record, Interest1099, Dividend1099, Retirement1099R, SSA1099],
    Field(discriminator="form_type"),
]


# --- Agent-to-agent messages -------------------------------------------------


class RuleDecision(Contract):
    rule_id: NonEmpty  # "eligibility_1040sr", "age_blind_boxes", "senior_deduction_count", "scope"
    outcome: Any
    explanation: NonEmpty
    citation: NonEmpty  # policy.md section id; every rule decision must cite


class RevisionRequest(Contract):
    """Review sends work back with one of these. It never fixes anything itself."""

    target: Literal["intake", "extraction", "rules", "computation"]
    field: NonEmpty | None = None
    document_id: NonEmpty | None = None
    reason: NonEmpty
    line: NonEmpty | None = None
    raised_by: AgentName = "review"

    @model_validator(mode="after")
    def _target_document(self):
        if self.target == "extraction" and not self.document_id:
            raise ValueError("Extraction revisions require document_id")
        return self


EscalationReason = Literal[
    "out_of_scope",
    "document_conflict",
    "1099r_taxable_not_determined",
    "advice_request",
    "filing_status_ambiguity",
    "exploitation_concern",
    "review_limit",
    "loop_guard",
    "tool_input_invalid",
    "uncertain",
]


class EscalationTicket(Contract):
    """A human-in-the-loop item. Shown in the dashboard; the graph waits until it is resolved."""

    ticket_id: NonEmpty  # deterministic, so the same issue is never raised twice
    reason: EscalationReason
    raised_by: AgentName
    detail: NonEmpty
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "resolved"] = "open"
    resolution: dict[str, Any] | None = None  # {"action": "continue" | "stop", "note": ...}
    resolved_by: str | None = None
    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def _resolution_action(self):
        if self.resolution is not None and self.resolution.get("action") not in {"continue", "stop"}:
            raise ValueError("Unknown escalation resolution action")
        if self.status == "resolved" and self.resolution is None:
            raise ValueError("Resolved escalations require a resolution")
        return self


class Handoff(Contract):
    """One orchestrator routing decision. The loop guard compares these."""

    from_agent: AgentName | Literal["start"]
    to_agent: AgentName | Literal["end"]
    reason: NonEmpty


class StateWriteConflict(Contract):
    """Keep competing writes until staff explicitly select a record."""

    candidates: list[TaxDocument | EscalationTicket]


class EvidenceSnapshot(Contract):
    """Prior work products retained for audit when evidence changes."""
    epoch: int = Field(ge=0)
    documents: dict[str, TaxDocument | StateWriteConflict]
    lines: dict[str, LineValue]
    rule_decisions: dict[str, RuleDecision]
