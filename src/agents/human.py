"""Human-in-the-loop node. Pauses the graph with interrupt() once per open escalation ticket.

Resume with Command(resume=...) where the value is either a string ("stop", or any note meaning
continue) or a dict {"action": "continue" | "stop", "note": str, "resolved_by": str}.
Conflicting state writes additionally require a one-based "choice". A document that could not be read
(evidence "needs_document_values") requires "values": the fields typed from the document. The CLI accepts
JSON for both. Plain "continue" is not enough for either, so nothing is chosen or left out silently.
An out_of_scope ticket can be continued only with a written reason in "note" (policy.md#scope): SilverFile
does not prepare that return, so going on is a staff override that must say why.
"""

import json
from datetime import datetime, timezone

from langgraph.types import Overwrite, interrupt
from pydantic import TypeAdapter

from src.agents.extraction import StaffEntryError, staff_entered_record
from src.evidence import invalidate_evidence
from src.resolution import (
    validate_1099r_correction_target,
    validate_resolution_corrections,
)
from src.schemas import (
    EscalationTicket,
    Provenance,
    RevisionRequest,
    TaxDocument,
)
from src.state import SilverFileState


# Escalations that "continue" may pass only with a written reason. Box 2b is handled with a corrected amount.
REASON_REQUIRED = {"out_of_scope"}
_NOT_A_REASON = {"", "continue", "c", "ok", "okay", "yes", "y", "go on", "carry on", "fine"}


def has_written_reason(note) -> bool:
    return str(note or "").strip().lower().rstrip(".!") not in _NOT_A_REASON


def normalize_resolution(answer) -> dict:
    if isinstance(answer, dict):
        return {"action": "continue", **answer}
    text = str(answer).strip()
    return {"action": "stop" if text.lower() == "stop" else "continue", "note": text}


def human(state: SilverFileState) -> dict:
    open_tickets = sorted(
        (t for t in state.get("escalations", {}).values() if t.status == "open"), key=lambda t: t.created_at
    )
    update: dict = {"last_agent": "human"}
    resolved = {}
    selected_ticket = False
    documents = dict(state.get("documents", {}))
    for ticket in open_tickets:
        channel = ticket.evidence.get("state_write")
        needs_values = bool(ticket.evidence.get("needs_document_values"))
        needs_reason = ticket.reason in REASON_REQUIRED
        prompt = {
            "ticket_id": ticket.ticket_id,
            "reason": ticket.reason,
            "detail": ticket.detail,
            "evidence": ticket.evidence,
            "how_to_resolve": "Reply 'continue' (with an optional note) to carry on, or 'stop' to end the session.",
        }
        if ticket.reason == "tool_input_invalid":
            prompt["how_to_resolve"] = (
                "The tax calculation rejected an input. "
                "The rejected value was not retained. "
                "Reply 'stop', correct the source data, "
                "and start a new return."
            )
        elif ticket.reason == "1099r_taxable_not_determined":
            prompt["how_to_resolve"] = (
                'Reply with {"action":"continue",'
                '"corrections":{"taxable_amount":"5500"}} '
                "to provide the confirmed taxable amount, "
                'or reply "stop".'
            )
        elif channel:
            prompt["how_to_resolve"] = (
                'Reply with {"action":"continue","choice":1} '
                "to select a candidate (numbered from 1), "
                "or stop."
            )
        if needs_reason:
            prompt["how_to_resolve"] = (
                "This is outside what SilverFile prepares. Reply 'stop' to end the session, or continue only with "
                "a written reason, for example 'Client confirms the 1099-NEC was issued in error'."
            )
        if needs_values:
            example = ", ".join(f'"{name}": ...' for name in ticket.evidence["required_fields"])
            prompt["how_to_resolve"] = (
                'Type the values from the document as {"action":"continue","values":{' + example + "}}, or stop."
            )
        while True:
            answer = interrupt(prompt)
            expects_json = (
                bool(channel)
                or needs_values
                or ticket.reason == "1099r_taxable_not_determined"
            )

            if expects_json and isinstance(answer, str):
                try:
                    answer = json.loads(answer)
                except ValueError:
                    pass
            resolution = normalize_resolution(answer)
            try:
                validated_corrections = validate_resolution_corrections(
                    ticket.reason,
                    resolution.get("action", "continue"),
                    resolution.get("corrections"),
                )
                if (
                    ticket.reason == "1099r_taxable_not_determined"
                    and resolution.get("action") != "stop"
                ):
                    document_id = ticket.evidence.get("document_id")
                    taxable_amount = validate_1099r_correction_target(
                        validated_corrections,
                        documents.get(document_id),
                    )
            except ValueError as exc:
                # Never raise after consuming a resume value: a failed node
                # would replay that value forever on every later resume.
                prompt = {**prompt, "detail": str(exc)}
                continue

            if validated_corrections:
                resolution["corrections"] = validated_corrections
            else:
                resolution.pop("corrections", None)

            choice = resolution.get("choice")
            if resolution.get("action") == "stop" or not (
                channel
                or needs_values
                or needs_reason
                or ticket.reason == "1099r_taxable_not_determined"
            ):
                break
            if ticket.reason == "1099r_taxable_not_determined":
                break
            if needs_reason:
                if has_written_reason(resolution.get("note")):
                    break
                prompt = {**prompt, "detail": "Write why the session can continue, or stop the session."}
                continue
            if needs_values:
                document_id = ticket.evidence["document_id"]
                values = resolution.get("values")
                problem = "Type the document's values before continuing, or stop the session."
                if isinstance(values, dict):
                    try:
                        record = staff_entered_record(
                            document_id, ticket.evidence["form_type"], values, resolution.get("resolved_by", "staff")
                        )
                    except StaffEntryError as exc:
                        problem = str(exc)  # names fields only; never echoes typed values
                    else:
                        documents[document_id] = record
                        update["documents"] = Overwrite(documents)
                        resolution = {k: v for k, v in resolution.items() if k != "values"}
                        resolution["entered_document"] = document_id
                        update["document_readiness"] = {**update.get("document_readiness", {}), document_id: True}
                        break
                prompt = {**prompt, "detail": problem}
                continue
            if type(choice) is int and 1 <= choice <= len(ticket.evidence["candidates"]):
                record = ticket.evidence["candidates"][choice - 1]
                key = ticket.evidence["key"]
                if channel == "documents":
                    documents[key] = TypeAdapter(TaxDocument).validate_python(record)
                    update["documents"] = Overwrite(documents)
                    update.update(invalidate_evidence(state))
                    requests = list(update.get("revision_requests", state.get("revision_requests", [])))
                    requests.extend(
                        RevisionRequest(target=target, reason=f"Staff selected document {key}", raised_by="human")
                        for target in ("rules", "computation")
                    )
                    update.update(revision_requests=requests, review_status="pending", review_passes=0)
                else:
                    resolved[key] = EscalationTicket.model_validate(record)
                    selected_ticket = True
                break
            prompt = {**prompt, "detail": "Select a candidate number before continuing, or stop the session."}

        if (
            ticket.reason
            == "1099r_taxable_not_determined"
            and resolution.get("action") == "continue"
        ):
            document_id = ticket.evidence.get("document_id")
            record = documents[document_id]

            corrected_source = Provenance(
                kind="user_input",
                source=(
                    f"HITL correction: 1099-R "
                    f"{document_id}, box 2a"
                ),
                value=str(taxable_amount),
                inputs={
                    "previous_source": (
                        record.source.model_dump(
                            mode="json"
                        )
                    ),
                },
                entered_by=resolution.get(
                    "resolved_by",
                    "staff",
                ),
            )

            documents[document_id] = (
                record.model_copy(
                    update={
                        "taxable_amount": (
                            taxable_amount
                        ),
                        "taxable_not_determined": (
                            False
                        ),
                        "source": corrected_source,
                    }
                )
            )
            update["documents"] = Overwrite(
                documents
            )

        resolved[ticket.ticket_id] = ticket.model_copy(update={
            "status": "resolved",
            "resolution": resolution,
            "resolved_by": resolution.get("resolved_by", "staff"),
            "resolved_at": datetime.now(timezone.utc),
        })
        if ticket.reason == "review_limit":
            update["review_passes"] = 0
        if ticket.reason == "loop_guard":
            update["guard_window_start"] = len(state.get("handoffs", []))
    # Staff selection explicitly replaces conflicting records; it must bypass the conflict reducer.
    update["escalations"] = (
        Overwrite({**state.get("escalations", {}), **resolved}) if selected_ticket else resolved
    )
    return update
