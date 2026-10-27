"""Seed a demo database with returns in every state, from the eval cases in evals/cases.json.

Each return runs the taxpayer's scripted replies and stops at the first escalation, so staff have real
tickets to resolve in the dashboard. Seeding is offline (no API key) and skips returns already there.
"""

import json
from pathlib import Path

from langgraph.types import Command

from evals.run_evals import build_case_file, load_cases

# (thread id, eval case id, whether to send the case's scripted taxpayer replies)
DEMO_RETURNS = [
    ("demo-clean-return", "eval-case-1-clean-run", True),
    ("demo-wage-conflict", "eval-case-2-wage-conflict", True),
    ("demo-out-of-scope-1099-nec", "hitl-out-of-scope-document", True),
    ("demo-unreadable-w2", "unreadable-w2-staff-types-values", True),
    ("demo-1099r-box-2b", "hitl-1099r-box-2b", True),
    ("demo-spouse-died-2025", "hitl-spouse-died-2025", True),
    ("demo-third-party-pressure", "hitl-third-party-pressure", True),
    ("demo-waiting-on-taxpayer", "hitl-advice-request", False),
]


def seed(sessions, case_folder: Path) -> list[str]:
    """Start each demo return that isn't in the database yet. Returns the thread ids it started."""
    cases = {case["id"]: case for case in load_cases()}
    existing = set(sessions.thread_ids())
    case_folder.mkdir(parents=True, exist_ok=True)  # kept: Intake re-reads the case file when it revisits
    started = []
    for thread_id, case_id, send_replies in DEMO_RETURNS:
        if thread_id in existing:
            continue
        case = cases[case_id]
        replies = list(case.get("replies", [])) if send_replies else []
        config = {"configurable": {"thread_id": thread_id}}
        result = sessions.graph.invoke({"case_path": build_case_file(case, case_folder)}, config)
        while replies:
            pending = result.get("__interrupt__") or []
            if not pending or (isinstance(pending[0].value, dict) and "ticket_id" in pending[0].value):
                break  # paused on staff: leave it for the dashboard
            result = sessions.graph.invoke(Command(resume=replies.pop(0)), config)
        started.append(thread_id)
    return started


if __name__ == "__main__":
    from dataclasses import replace

    from src.config import ROOT, load_settings
    from src.sessions import open_sessions

    settings = replace(load_settings(), anthropic_api_key="", db_path=ROOT / "output" / "demo.sqlite")
    with open_sessions(settings) as sessions:
        print(json.dumps(seed(sessions, ROOT / "output" / "demo_cases"), indent=2))
