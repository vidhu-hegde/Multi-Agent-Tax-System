"""Staff dashboard: the HITL queue, every return's status, and the controls to resolve an escalation.

    python -m src.dashboard              # http://127.0.0.1:8000, same SQLite file as run.py
    python -m src.dashboard --demo       # a separate demo database seeded from the eval cases

The dashboard talks only to src/sessions.py. Every staff decision goes through Sessions.resolve(), so the
rules there (a candidate for a conflict, typed values for an unreadable document, a written reason for
out-of-scope) apply here exactly as they do on the command line. It is a local staff tool: it binds to
127.0.0.1 and refuses form posts from other sites.
"""

import json
import re
import typing
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.agents.extraction import RECORD_TYPES
from src.agents.human import REASON_REQUIRED
from src.config import ROOT
from src.render import render_draft
from src.sessions import STATUSES, Sessions, StaleEscalation, open_sessions
from src.state import current_answers
from src.tools import check_server

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
BOX12_ROWS = 4
TEXT_FIELDS = {"employer_name", "payer_name", "distribution_code"}  # everything else typed is an amount
SSN_SHAPE = re.compile(r"(?<!\d)\d{3}-?\d{2}-?(\d{4})(?!\d)")

STATUS_LABELS = {
    "waiting_on_human": "Waiting on staff",
    "waiting_on_taxpayer": "Waiting on taxpayer",
    "in_progress": "In progress",
    "draft_ready": "Draft ready",
    "stopped": "Stopped",
}
REASON_LABELS = {
    "out_of_scope": "Outside what SilverFile prepares",
    "document_conflict": "Taxpayer's answer disagrees with a document",
    "1099r_taxable_not_determined": "1099-R taxable amount not determined (box 2b)",
    "advice_request": "Taxpayer asked for tax advice",
    "filing_status_ambiguity": "Filing status needs a decision",
    "exploitation_concern": "Possible exploitation or third-party pressure",
    "review_limit": "Review could not settle the draft",
    "loop_guard": "Workflow kept repeating",
    "uncertain": "Needs a volunteer's help",
    "tool_input_invalid": "Tax calculation input needs correction",
}
FIELD_LABELS = {
    "employer_name": "Employer name (box c)",
    "payer_name": "Payer name",
    "wages": "Wages, tips, other compensation (box 1)",
    "medicare_wages": "Medicare wages and tips (box 5)",
    "allocated_tips": "Allocated tips (box 8)",
    "dependent_care_benefits": "Dependent care benefits (box 10)",
    "box12": "Box 12 codes and amounts",
    "statutory_employee": "Statutory employee (box 13)",
    "interest": "Interest income (box 1)",
    "tax_exempt_interest": "Tax-exempt interest (box 8)",
    "ordinary_dividends": "Total ordinary dividends (box 1a)",
    "qualified_dividends": "Qualified dividends (box 1b)",
    "gross_distribution": "Gross distribution (box 1)",
    "taxable_amount": "Taxable amount (box 2a)",
    "taxable_not_determined": "Taxable amount not determined (box 2b)",
    "distribution_code": "Distribution code (box 7)",
    "ira_sep_simple": "IRA/SEP/SIMPLE (box 7)",
    "net_benefits": "Net benefits (box 5)",
}
WITHHELD_BOX = {"W-2": "box 2", "1099-INT": "box 4", "1099-DIV": "box 4", "1099-R": "box 4", "SSA-1099": "box 6"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
# Shown on the answers table elsewhere (documents) or not useful to staff as raw values.
HIDDEN_ANSWERS = {"document_inventory"}
# Shown in the staff form only, never on the taxpayer's screen.
STAFF_GUIDANCE = {
    "exploitation_concern": "Speak with the taxpayer privately before deciding. Do not repeat the concern in front of "
                            "anyone helping them.",
    "out_of_scope": "SilverFile does not prepare this return. Stop the session, or continue only with a written reason "
                    "(for example, a false alarm).",
    "advice_request": "SilverFile never gives tax advice. Note what was asked so a volunteer can follow up.",
    "tool_input_invalid": (
        "The tax calculation rejected an input. "
        "The rejected value was not retained. "
        "Stop the session, correct the source data, "
        "and start a new return."
    ),
}


def mask(value):
    """Mask anything SSN-shaped to its last four digits, for display."""
    if isinstance(value, str):
        return SSN_SHAPE.sub(lambda m: f"***-**-{m.group(1)}", value)
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask(v) for v in value]
    return value


def show(value) -> str:
    """One evidence or answer value as readable text."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in value]
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None or value == []:
        return "none"
    if isinstance(value, (dict, list)):
        return json.dumps(mask(value), indent=2, sort_keys=True, default=str)
    return mask(str(value))


def when(value) -> str:
    if not value:
        return ""
    moment = datetime.fromisoformat(str(value)) if not isinstance(value, datetime) else value
    return moment.strftime("%d %b %Y, %H:%M UTC")


def field_kind(form_type: str, name: str) -> str:
    """How the staff form asks for one field: yes/no, box 12 rows, optional (blank = none), or required text."""
    annotation = RECORD_TYPES[form_type].model_fields[name].annotation
    if annotation is bool:
        return "bool"
    if typing.get_origin(annotation) is list:
        return "box12"
    if type(None) in typing.get_args(annotation):
        return "optional"
    return "text"


def entry_fields(ticket) -> list[dict]:
    form_type = ticket.evidence["form_type"]
    labels = {**FIELD_LABELS, "federal_withheld": f"Federal income tax withheld ({WITHHELD_BOX[form_type]})"}
    return [{"name": name, "label": labels.get(name, name.replace("_", " ").capitalize()),
             "kind": field_kind(form_type, name)} for name in ticket.evidence["required_fields"]]


def document_image(state: dict, document_id: str) -> Path | None:
    """The image file of a document in this return's inventory, only if it is an image inside the project."""
    ref = next((r for r in state.get("document_inventory", []) if r.document_id == document_id), None)
    if ref is None or not ref.image_path:
        return None
    path = (ROOT / ref.image_path).resolve()
    if not path.is_relative_to(ROOT) or path.suffix.lower() not in IMAGE_TYPES or not path.is_file():
        return None
    return path


def amount(text: str) -> str:
    return text.strip().replace("$", "").replace(",", "")  # "$26,450.00" as typed from the form


def typed_values(form, fields: list[dict]) -> dict:
    """The staff form's values in the shape staff_entered_record() expects. Blank optional fields are null."""
    values = {}
    for field in fields:
        name, kind = field["name"], field["kind"]
        if kind == "box12":
            rows = [(form.get(f"v_box12_code_{i}", "").strip().upper(), amount(form.get(f"v_box12_amount_{i}", "")))
                    for i in range(BOX12_ROWS)]
            values[name] = [{"code": code, "amount": amount} for code, amount in rows if code or amount]
        elif kind == "bool":
            choice = form.get(f"v_{name}", "")
            values[name] = {"yes": True, "no": False}.get(choice, choice)
        else:
            text = form.get(f"v_{name}", "").strip()
            if name not in TEXT_FIELDS:
                text = amount(text)
            values[name] = None if kind == "optional" and not text else text
    return values


def _same_origin(request: Request) -> bool:
    """Refuse a form post made from another site (a page in the staff member's browser posting to localhost)."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    return origin is None or urlparse(origin).netloc == request.url.netloc


def create_app(sessions: Sessions | None = None, settings=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        check_server()  # with TAX_MATH_MCP_URL set, refuse to start rather than fail on the first resolve
        if sessions is not None:
            app.state.sessions = sessions
            yield
            return
        with open_sessions(settings) as opened:
            app.state.sessions = opened
            yield

    app = FastAPI(title="SilverFile staff dashboard", lifespan=lifespan, docs_url=None, redoc_url=None)

    def page(request, name, status_code=200, **context):
        context.update(status_labels=STATUS_LABELS, reason_labels=REASON_LABELS, when=when, show=show)
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status_code)

    def known(thread_id: str):
        store = app.state.sessions
        if thread_id not in store.thread_ids():
            raise HTTPException(status_code=404, detail="No session with that id.")
        return store

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, status: str | None = None):
        store = app.state.sessions
        everything = store.list_sessions()
        counts = {s: sum(1 for x in everything if x.status == s) for s in STATUSES}
        shown = [s for s in everything if status in (None, "") or s.status == status]
        queue = sorted(((s.thread_id, t) for s in everything for t in s.open_tickets), key=lambda item: item[1].created_at)
        return page(request, "index.html", sessions=shown, counts=counts, statuses=STATUSES, status=status,
                    queue=queue, awaiting={s.thread_id: s.awaiting_ticket_id for s in everything})

    def session_page(request, thread_id, status_code=200, error=None, form=None):
        store = known(thread_id)
        summary = store.summary(thread_id)
        state = store.state(thread_id)
        tickets = state.get("escalations", {})
        awaiting = tickets.get(summary.awaiting_ticket_id) if summary.awaiting_ticket_id else None
        answers = current_answers(state) if state.get("answers") else {}
        return page(
            request, "session.html", status_code=status_code, summary=summary, state=state, awaiting=awaiting,
            queued=[t for t in summary.open_tickets if awaiting is None or t.ticket_id != awaiting.ticket_id],
            resolved=sorted((t for t in tickets.values() if t.status == "resolved"), key=lambda t: t.resolved_at,
                            reverse=True),
            answers=sorted((k, v) for k, v in answers.items() if k not in HIDDEN_ANSWERS),
            inventory=state.get("document_inventory", []), documents=state.get("documents", {}),
            images={r.document_id for r in state.get("document_inventory", []) if document_image(state, r.document_id)},
            fields=entry_fields(awaiting) if awaiting and awaiting.evidence.get("needs_document_values") else [],
            reason_required=bool(awaiting and awaiting.reason in REASON_REQUIRED),
            stop_only=bool(
                awaiting
                and awaiting.reason == "tool_input_invalid"
            ),
            guidance=STAFF_GUIDANCE.get(awaiting.reason) if awaiting else None,
            box12_rows=BOX12_ROWS, error=error, form=form or {},
            staff_id=(form or {}).get("staff_id") or request.cookies.get("staff_id", ""),
            done=request.query_params.get("done"), has_draft=bool(state.get("lines")),
        )

    @app.get("/sessions/{thread_id}", response_class=HTMLResponse)
    def session(request: Request, thread_id: str):
        return session_page(request, thread_id)

    @app.post("/sessions/{thread_id}/tickets/{ticket_id}", response_class=HTMLResponse)
    async def resolve(request: Request, thread_id: str, ticket_id: str):
        if not _same_origin(request):
            raise HTTPException(status_code=403, detail="Form posts are accepted only from this dashboard.")
        store = known(thread_id)
        form = dict(await request.form())
        action = "stop" if form.get("action") == "stop" else "continue"
        staff_id = form.get("staff_id", "").strip()
        if not staff_id:
            return session_page(request, thread_id, 400, "Enter your staff ID so the decision is recorded.", form)
        ticket = store.state(thread_id).get("escalations", {}).get(ticket_id)
        choice = form.get("choice")

        values = None
        if ticket is not None and ticket.evidence.get("needs_document_values") and action == "continue":
            values = typed_values(form, entry_fields(ticket))

        corrections = None
        if (
                ticket is not None
                and ticket.reason == "1099r_taxable_not_determined"
                and action == "continue"
        ):
            corrections = {
                "taxable_amount": amount(form.get("taxable_amount", ""))
            }

        try:
            store.resolve(
                thread_id,
                ticket_id,
                action,
                note=form.get("note", "").strip(),
                resolved_by=staff_id,
                choice=int(choice) if choice and choice.isdigit() else None,
                corrections=corrections,
                values=values,
            )
        except StaleEscalation as exc:
            return session_page(request, thread_id, 409, f"{exc} Someone may have resolved it already.")
        except ValueError as exc:
            message = str(exc)
            if values is not None:  # name fields as the form labels them; the message never holds typed values
                for field in sorted(entry_fields(ticket), key=lambda f: -len(f["name"])):
                    message = re.sub(rf"\b{field['name']}\b", field["label"], message)
            return session_page(request, thread_id, 400, message, form)
        response = RedirectResponse(f"/sessions/{quote(thread_id)}?done={quote(ticket_id)}", status_code=303)
        response.set_cookie("staff_id", staff_id, httponly=True, samesite="strict")
        return response

    @app.get("/sessions/{thread_id}/documents/{document_id}/image")
    def image(thread_id: str, document_id: str):
        path = document_image(known(thread_id).state(thread_id), document_id)
        if path is None:
            raise HTTPException(status_code=404, detail="No image for that document.")
        return FileResponse(path, media_type=IMAGE_TYPES[path.suffix.lower()])

    @app.get("/sessions/{thread_id}/draft", response_class=HTMLResponse)
    def draft(thread_id: str):
        state = known(thread_id).state(thread_id)
        if not state.get("lines"):
            raise HTTPException(status_code=404, detail="This return has no draft yet.")
        return HTMLResponse(render_draft(state))

    return app
