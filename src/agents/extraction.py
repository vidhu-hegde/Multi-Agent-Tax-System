"""Document Extraction agent (STUB). Turns one DocumentRef into a typed record; never decides meaning.

Runs once per document in parallel (the orchestrator fans out with Send). Typed-in values are
validated now; W-2 image extraction with Claude vision replaces the escalation below.
"""

from pydantic import TypeAdapter, ValidationError

from src.escalation import escalate
from src.schemas import DocumentRef, Provenance, TaxDocument

_records = TypeAdapter(TaxDocument)


def extraction_ticket_id(document_id: str) -> str:
    return f"uncertain:extract:{document_id}"


def _cannot_extract(ref: DocumentRef, detail: str) -> dict:
    return escalate(
        "uncertain", raised_by="extraction", key=f"extract:{ref.document_id}", detail=detail,
        evidence={"document_id": ref.document_id, "form_type": ref.form_type, "image_path": ref.image_path},
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
