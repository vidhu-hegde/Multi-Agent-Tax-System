"""Human-in-the-loop node. Pauses the graph with interrupt() once per open escalation ticket.

Resume with Command(resume=...) where the value is either a string ("stop", or any note meaning
continue) or a dict {"action": "continue" | "stop", "note": str, "resolved_by": str}.
Conflicting state writes additionally require a one-based "choice". The CLI accepts JSON for these.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from langgraph.types import Overwrite, interrupt
from pydantic import TypeAdapter

from src.resolution import validate_resolution_corrections
from src.schemas import (
    EscalationTicket,
    Provenance,
    RevisionRequest,
    TaxDocument,
)
from src.state import SilverFileState


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
        prompt = {
            "ticket_id": ticket.ticket_id,
            "reason": ticket.reason,
            "detail": ticket.detail,
            "evidence": ticket.evidence,
            "how_to_resolve": "Reply 'continue' (with an optional note) to carry on, or 'stop' to end the session.",
        }
        if ticket.reason == "1099r_taxable_not_determined":
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
        while True:
            answer = interrupt(prompt)
            expects_json = (
                    bool(channel)
                    or ticket.reason
                    == "1099r_taxable_not_determined"
            )

            if expects_json and isinstance(answer, str):
                try:
                    answer = json.loads(answer)
                except ValueError:
                    pass
            resolution = normalize_resolution(answer)
            validated_corrections = validate_resolution_corrections(
                ticket.reason,
                resolution.get("action", "continue"),
                resolution.get("corrections"),
            )

            if validated_corrections:
                resolution["corrections"] = validated_corrections
            else:
                resolution.pop("corrections", None)

            choice = resolution.get("choice")
            if not channel or resolution.get("action") == "stop":
                break
            if type(choice) is int and 1 <= choice <= len(ticket.evidence["candidates"]):
                record = ticket.evidence["candidates"][choice - 1]
                key = ticket.evidence["key"]
                if channel == "documents":
                    documents[key] = TypeAdapter(TaxDocument).validate_python(record)
                    update["documents"] = Overwrite(documents)
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
            document_id = ticket.evidence.get(
                "document_id"
            )
            record = documents.get(document_id)

            if (
                record is None
                or getattr(record, "form_type", None)
                != "1099-R"
            ):
                raise ValueError(
                    "The 1099-R correction target "
                    "is unavailable."
                )

            taxable_amount = Decimal(
                resolution["corrections"][
                    "taxable_amount"
                ]
            )

            if (
                taxable_amount
                > record.gross_distribution
            ):
                raise ValueError(
                    "The corrected taxable amount "
                    "cannot exceed the gross "
                    "distribution."
                )

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
