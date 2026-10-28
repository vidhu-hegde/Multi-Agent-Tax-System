"""SilverFile entry point.

Taxpayer session:
    python run.py                        # start a new intake session
    python run.py --thread-id abc123     # resume a saved session
    python run.py --case data/fixtures/skeleton_case.json
    python run.py --batch [--no-context-strategy]

Staff (the same actions the dashboard offers):
    python run.py --sessions                                 # list sessions and open escalations
    python run.py --resolve abc123 TICKET_ID --note "..."    # resolve and let the session continue (out_of_scope needs a reason)
    python run.py --resolve abc123 TICKET_ID --stop          # resolve by stopping the session
    python run.py --resolve abc123 TICKET_ID --values '{"employer_name": "...", "wages": "..."}'  # unreadable document

When the graph pauses with interrupt(), the taxpayer session shows the question or escalation,
reads a reply from the terminal and resumes with Command(resume=reply).
"""

import argparse
import json
import logging
import sys

from src.config import load_settings
from src.security import SSNValidationError, protect_resume_input

log = logging.getLogger("silverfile")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="SilverFile: Form 1040-SR preparation aid")
    parser.add_argument("--thread-id", help="resume a saved session (never use an SSN as the id)")
    parser.add_argument("--case", help="JSON case file with answers and documents, e.g. data/fixtures/skeleton_case.json")
    parser.add_argument("--batch", action="store_true", help="run the batch scenario for docs/metrics.md")
    parser.add_argument(
        "--no-context-strategy",
        action="store_true",
        help="disable the context-window strategy (for the metrics comparison)",
    )
    parser.add_argument("--html", help="write an accessible HTML draft with provenance")
    staff = parser.add_argument_group("staff")
    staff.add_argument("--sessions", action="store_true", help="list sessions and their open escalations")
    staff.add_argument("--resolve", nargs=2, metavar=("THREAD_ID", "TICKET_ID"), help="resolve an escalation")
    staff.add_argument("--stop", action="store_true", help="with --resolve: stop the session instead of continuing")
    staff.add_argument("--note", default="", help="with --resolve: note recorded on the ticket")
    staff.add_argument("--staff-id", default="staff", help="with --resolve: who is resolving")
    staff.add_argument("--choice", type=int, help="with --resolve: select a conflicting record, numbered from 1")
    staff.add_argument(
        "--taxable-amount",
        help=(
            "with --resolve: confirmed 1099-R "
            "taxable amount for box 2a"
        ),
    )
    staff.add_argument(
        "--values",
        help=(
            "with --resolve: JSON values typed from an unreadable "
            "document"
        ),
    )
    return parser.parse_args(argv)


def format_interrupt(value):
    """Format structured Intake questions and human escalations."""

    if isinstance(value, dict) and value.get("type") == "intake_question":
        return str(value["prompt"])

    if not isinstance(value, dict):
        return str(value)

    said = value.get("evidence", {}).get("said_to_taxpayer")
    if value.get("reason") == "exploitation_concern":
        # policy.md#exploitation: notice and stop, never accuse. The person steering the return may be
        # reading this screen, so the taxpayer sees only the neutral message; staff see the full ticket
        # with python run.py --sessions or in the dashboard.
        return f"{said or 'Thank you.'}\n\n[Paused: a member of staff will continue this with you.]"
    lead = f"{said}\n" if said else ""

    if value.get("evidence", {}).get("state_write"):
        for number, candidate in enumerate(
            value["evidence"]["candidates"],
            1,
        ):
            lead += (
                f"Candidate {number}: "
                f"{json.dumps(candidate, sort_keys=True)}\n"
            )

    return (
        f"{lead}\n"
        f"[Escalation: {value['reason']}] {value['detail']}\n"
        f"{value['how_to_resolve']}"
    )


def print_draft(state):
    from src.schemas import FORM_LINES

    print(f"\nDraft 1040-SR ({state.get('status')})")
    for line, label in FORM_LINES.items():
        value = state.get("lines", {}).get(line)
        if value is not None:
            flag = "  (placeholder)" if value.is_stub else ""
            print(f"  {line:>4}  {label:<42} {value.amount:>12,.2f}{flag}")


def print_summary(summary):
    print(f"{summary.thread_id:<14} {summary.status:<20} {summary.updated_at[:19]}")
    for ticket in summary.open_tickets:
        marker = "*" if ticket.ticket_id == summary.awaiting_ticket_id else " "
        print(f"   {marker} {ticket.ticket_id:<45} {ticket.detail}")


def drive(graph, thread_id, first_input, ask=input, say=print):
    """Run the graph on one thread, pausing for the user at every interrupt."""
    from langgraph.types import Command
    from src.agents.intake import recap
    from src.memory import thread_config
    from src.state import current_answers

    config = thread_config(thread_id)
    payload = first_input
    show_recap = first_input is None
    while True:
        result = graph.invoke(payload, config)
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if not interrupts:
            return result
        input_type = "text"

        for item in interrupts:
            prompt = format_interrupt(item.value)

            if (
                    isinstance(item.value, dict)
                    and item.value.get("type") == "intake_question"
            ):
                input_type = item.value["input_type"]

                if show_recap:
                    prompt = recap(current_answers(result)) + prompt
                    show_recap = False

            say(prompt)

        while True:
            try:
                reply = ask("> ")
                protected_reply = protect_resume_input(
                    reply,
                    input_type=input_type,
                )
                payload = Command(resume=protected_reply)
                break
            except SSNValidationError as exc:
                # The validation error is deliberately safe and never echoes the value.
                say(str(exc))
            except (EOFError, KeyboardInterrupt):
                say(
                    f"\nSession saved. Resume with: "
                    f"python run.py --thread-id {thread_id}"
                )
                return None


def run_staff_command(args, settings):
    from src.sessions import StaleEscalation, open_sessions

    with open_sessions(settings) as sessions:
        if args.resolve:
            thread_id, ticket_id = args.resolve
            action = "stop" if args.stop else "continue"
            corrections = None
            if args.taxable_amount is not None:
                corrections = {
                    "taxable_amount": (
                        args.taxable_amount
                    ),
                }

            try:
                values = json.loads(args.values) if args.values else None
                summary = sessions.resolve(
                    thread_id,
                    ticket_id,
                    action,
                    note=args.note,
                    resolved_by=args.staff_id,
                    choice=args.choice,
                    corrections=corrections,
                    values=values,
                )
            except (StaleEscalation, ValueError) as exc:
                sys.exit(str(exc))
            print(f"Resolved {ticket_id} ({action}). Session is now:")
            print_summary(summary)
            return
        summaries = sessions.list_sessions()
        if not summaries:
            print("No sessions yet.")
        for summary in summaries:
            print_summary(summary)


def main(argv=None):
    args = parse_args(argv)
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    if args.sessions:
        run_staff_command(args, settings)
        return

    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    if args.resolve:
        run_staff_command(args, settings)
        return

    from src.graph import build_graph, run_batch
    from src.memory import open_checkpointer, thread_config

    use_context_strategy = not args.no_context_strategy

    with open_checkpointer(settings) as checkpointer:
        graph = build_graph(settings, checkpointer, use_context_strategy=use_context_strategy)

        if args.batch:
            run_batch(graph, use_context_strategy=use_context_strategy)
            return

        if args.thread_id:
            thread_id, first_input = args.thread_id, None  # None resumes from the checkpoint
        else:
            thread_id = thread_config()["configurable"]["thread_id"]
            first_input = {"case_path": args.case} if args.case else {}
            print(f"Session id: {thread_id}")

        result = drive(graph, thread_id, first_input)
        if result is not None:
            print_draft(result)
            if args.html:
                from pathlib import Path
                from src.render import render_draft
                target = Path(args.html)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_draft(result), encoding="utf-8")


if __name__ == "__main__":
    main()
