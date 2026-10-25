"""Shared data contracts. Every agent reads and writes these types, so change them here and nowhere else.

Money is always Decimal (never float). Every amount on the draft is a LineValue, and a LineValue
cannot exist without at least one Provenance record explaining where the amount came from.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# Only IRS test-range SSNs (900-999 prefix) are accepted, so a real SSN can never be entered.
SSN = Annotated[str, StringConstraints(pattern=r"^9\d{2}-\d{2}-\d{4}$")]
Money = Annotated[Decimal, Field(ge=0)]

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]
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
    "24": "Total tax",
    "25a": "Federal income tax withheld from W-2",
    "25b": "Federal income tax withheld from 1099",
    "25d": "Total federal income tax withheld",
    "26": "Estimated tax payments",
    "33": "Total payments",
    "34": "Overpayment",
    "37": "Amount you owe",
}


# --- Provenance -------------------------------------------------------------


class Provenance(Contract):
    """One step in how an amount was obtained. A line's provenance list reads like a calculation."""

    kind: Literal["document", "user_input", "tool", "rule"]
    source: str  # "W-2 w2-1, box 1", "intake: estimated_payments", "tax_math.sum", "policy.md#standard-deduction"
    value: Any = None
    inputs: dict[str, Any] = Field(default_factory=dict)  # tool arguments, or extra context
    citation: str | None = None  # policy.md section, for rule steps
    entered_by: str | None = None  # for user input: "taxpayer", "case file", staff id
    recorded_at: datetime = Field(default_factory=_now)
    stub: bool = False  # True while a placeholder stands in for the real tool or agent


class LineValue(Contract):
    line: str
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

    field: str  # "filing_status", "taxpayer_dob", ...
    value: Any
    raw_text: str | None = None
    entered_by: str = "taxpayer"
    answered_at: datetime = Field(default_factory=_now)


class Dependent(Contract):
    name: str
    ssn: SSN
    relationship: str


# --- Documents ---------------------------------------------------------------

FormType = Literal["W-2", "1099-INT", "1099-DIV", "1099-R", "SSA-1099"]


class DocumentRef(Contract):
    """A document the taxpayer has. Either an image to extract, or values typed in by the user."""

    document_id: str
    form_type: FormType | Literal["other"]
    image_path: str | None = None
    values: dict[str, Any] | None = None
    description: str = ""  # e.g. "1099-NEC from consulting work" for an out-of-scope document


class _Record(Contract):
    document_id: str
    source: Provenance  # where the record came from: image extraction or user entry


class W2Record(_Record):
    form_type: Literal["W-2"] = "W-2"
    employer_name: str
    wages: Money  # box 1
    federal_withheld: Money = Decimal("0")  # box 2


class Interest1099(_Record):
    form_type: Literal["1099-INT"] = "1099-INT"
    payer_name: str
    interest: Money = Decimal("0")  # box 1
    tax_exempt_interest: Money = Decimal("0")  # box 8
    federal_withheld: Money = Decimal("0")  # box 4


class Dividend1099(_Record):
    form_type: Literal["1099-DIV"] = "1099-DIV"
    payer_name: str
    ordinary_dividends: Money = Decimal("0")  # box 1a
    qualified_dividends: Money = Decimal("0")  # box 1b
    federal_withheld: Money = Decimal("0")  # box 4


class Retirement1099R(_Record):
    form_type: Literal["1099-R"] = "1099-R"
    payer_name: str
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
    rule_id: str  # "eligibility_1040sr", "age_blind_boxes", "senior_deduction_count", "scope"
    outcome: Any
    explanation: str
    citation: str = Field(min_length=1)  # policy.md section id; every rule decision must cite


class RevisionRequest(Contract):
    """Review sends work back with one of these. It never fixes anything itself."""

    target: AgentName
    reason: str
    line: str | None = None
    raised_by: AgentName = "review"


EscalationReason = Literal[
    "out_of_scope",
    "document_conflict",
    "1099r_taxable_not_determined",
    "advice_request",
    "filing_status_ambiguity",
    "exploitation_concern",
    "review_limit",
    "loop_guard",
    "uncertain",
]


class EscalationTicket(Contract):
    """A human-in-the-loop item. Shown in the dashboard; the graph waits until it is resolved."""

    ticket_id: str  # deterministic, so the same issue is never raised twice
    reason: EscalationReason
    raised_by: AgentName
    detail: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "resolved"] = "open"
    resolution: dict[str, Any] | None = None  # {"action": "continue" | "stop", "note": ...}
    resolved_by: str | None = None
    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None


class Handoff(Contract):
    """One orchestrator routing decision. The loop guard compares these."""

    from_agent: str
    to_agent: str
    reason: str
