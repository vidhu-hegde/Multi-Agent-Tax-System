"""Document Extraction agent (STUB). Turns one DocumentRef into a typed record; never decides meaning.

Runs once per document in parallel (the orchestrator fans out with Send). Typed-in values are
validated now; W-2 image extraction with Claude vision replaces the escalation below.

A document that cannot be read escalates with `needs_document_values`: staff must type the values from
the document (staff_entered_record) or stop the session. It is never silently left out of the return.
"""

from datetime import datetime, timezone

from pydantic import TypeAdapter, ValidationError

from src.escalation import escalate
from src.schemas import (
    SSA1099,
    Dividend1099,
    DocumentRef,
    Interest1099,
    Provenance,
    Retirement1099R,
    TaxDocument,
    W2Record,
)

_records = TypeAdapter(TaxDocument)
RECORD_TYPES = {"W-2": W2Record, "1099-INT": Interest1099, "1099-DIV": Dividend1099,
                "1099-R": Retirement1099R, "SSA-1099": SSA1099}


# What staff must type when a document can't be read. Every field listed must be present: an explicit
# 0, false, null or [] is accepted, but an omitted field is rejected, so nothing silently defaults.
# Listed: every field that feeds a 1040-SR line, plus W-2 values that should escalate (IMPLEMENTATION_NOTES).
STAFF_ENTRY_FIELDS = {
    "W-2": ["employer_name", "wages", "federal_withheld", "medicare_wages", "allocated_tips",
            "dependent_care_benefits", "box12", "statutory_employee"],
    "1099-INT": ["payer_name", "interest", "tax_exempt_interest", "federal_withheld"],
    "1099-DIV": ["payer_name", "ordinary_dividends", "qualified_dividends", "federal_withheld"],
    "1099-R": ["payer_name", "gross_distribution", "taxable_amount", "taxable_not_determined",
               "federal_withheld", "distribution_code", "ira_sep_simple"],
    "SSA-1099": ["net_benefits", "federal_withheld"],
}


class StaffEntryError(ValueError):
    """Staff-typed values that can't be used. The message names fields only, never the typed values."""


def required_fields(form_type: str) -> list[str]:
    """Fields staff must type for this form when it cannot be read."""
    return list(STAFF_ENTRY_FIELDS[form_type])


def invalid_fields(exc: ValidationError) -> str:
    """Field names from a validation error, for messages that must not echo the typed values."""
    names = set()
    for error in exc.errors():
        loc = [part for part in error["loc"] if part not in RECORD_TYPES]  # drop the form-type union tag
        names.add(str(loc[0]) if loc else "the record")
    return ", ".join(sorted(names)) or "the record"


def staff_entered_record(document_id: str, form_type: str, values: dict, entered_by: str):
    """A record typed in by staff from the document. Raises StaffEntryError if a field is missing or invalid."""
    missing = [name for name in STAFF_ENTRY_FIELDS[form_type] if name not in values]
    if missing:
        raise StaffEntryError("Missing values for: " + ", ".join(missing) + " (type 0, false or null if blank).")
    source = Provenance(
        kind="user_input",
        source=f"direct user input: {form_type} {document_id} (typed by staff from the document)",
        entered_by=entered_by,
        recorded_at=datetime.now(timezone.utc),
    )
    try:
        return _records.validate_python({**values, "document_id": document_id, "form_type": form_type, "source": source})
    except ValidationError as exc:
        raise StaffEntryError("Some values need checking: " + invalid_fields(exc) + ".") from None


def extraction_ticket_id(document_id: str) -> str:
    return f"uncertain:extract:{document_id}"


def _cannot_extract(ref: DocumentRef, detail: str) -> dict:
    return escalate(
        "uncertain", raised_by="extraction", key=f"extract:{ref.document_id}", detail=detail,
        evidence={
            "document_id": ref.document_id, "form_type": ref.form_type, "image_path": ref.image_path,
            "needs_document_values": True, "required_fields": required_fields(ref.form_type),
        },
    )


def extract_document(payload: dict) -> dict:
    ref: DocumentRef = payload["doc"]
    if ref.values is None:
        return _cannot_extract(ref, f"Reading {ref.form_type} images is not implemented yet ({ref.document_id}).")

    source = Provenance(
        kind="user_input",
        source=f"{ref.form_type} {ref.document_id} (values entered by user)",
        entered_by="case file",
    )
    try:
        record = _records.validate_python(
            {**ref.values, "document_id": ref.document_id, "form_type": ref.form_type, "source": source}
        )
    except ValidationError as exc:
        return _cannot_extract(ref, f"{ref.form_type} {ref.document_id} has values I can't read: {exc.errors()[0]['msg']}")
    return {"documents": {ref.document_id: record}}


def aggregate_documents(state: dict) -> dict:
    """Join point after the parallel extraction branches. The reducer has already merged their writes."""
    return {"last_agent": "extraction"}
