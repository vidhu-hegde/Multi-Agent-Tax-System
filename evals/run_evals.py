"""Run the end-to-end eval cases in evals/cases.json through the real graph.

    python -m evals.run_evals                 # every case
    python -m evals.run_evals --case eval-case-2-wage-conflict

Each case starts from a case file, optionally changes answers or documents, scripts the taxpayer's
replies to any questions and the staff decisions for any escalations, then checks what comes out.
Evals run offline: no API key is used, so they are repeatable and free. The format is described in
evals/README.md.

Every case is also checked against invariants that must always hold, whatever the case expects:
a finished draft has a record for every in-scope document and a source for every line, and no SSN
outside the 900-999 test range appears anywhere in the saved state.
"""

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases.json"
MAX_STEPS = 100
REAL_LOOKING_SSN = re.compile(r"(?<!\d)(?!9)\d{3}-\d{2}-\d{4}(?!\d)")


def _faults():
    """Named faults a case can inject, to exercise the loop bounds end to end."""
    from src.agents.computation import computation

    def computation_6b_too_large(state):
        update = computation(state)
        update["lines"]["6b"] = update["lines"]["6b"].model_copy(update={"amount": Decimal("999999")})
        return update

    def intake_never_finishes(state):
        return {}

    return {
        "computation_6b_too_large": ("computation", computation_6b_too_large),
        "intake_never_finishes": ("intake", intake_never_finishes),
    }


@dataclass
class Outcome:
    case_id: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    status: str | None = None
    escalations: list[str] = field(default_factory=list)


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text())["cases"]


def build_case_file(case: dict, folder: Path) -> str:
    """Start from case["case_file"], then apply answers, remove_answers, documents, document_values, add_documents."""
    data = json.loads((ROOT / case["case_file"]).read_text())
    data["answers"].update(case.get("answers", {}))
    for field_name in case.get("remove_answers", []):
        data["answers"].pop(field_name, None)
    if "documents" in case:
        data["documents"] = case["documents"]
    for ref in data.get("documents", []):
        if ref["document_id"] in case.get("document_values", {}):
            changes = case["document_values"][ref["document_id"]]
            if changes is None:
                ref.pop("values", None)  # e.g. an image-only W-2 with nothing typed in
            else:
                ref["values"] = {**ref.get("values", {}), **changes}
    data["documents"] = data.get("documents", []) + case.get("add_documents", [])
    path = folder / f"{case['id']}.json"
    path.write_text(json.dumps(data))
    return str(path)


def make_graph(case: dict):
    from src.config import load_settings
    from src.graph import build_graph
    from src.memory import serializer

    agents = {}
    if case.get("fault"):
        node, fn = _faults()[case["fault"]]
        agents[node] = fn
    settings = replace(load_settings(), anthropic_api_key="")  # evals are offline and repeatable
    return build_graph(settings, InMemorySaver(serde=serializer()), agents=agents)


def _check_invariants(state: dict) -> list[str]:
    problems = []
    if state.get("status") == "draft_ready":
        documents = state.get("documents", {})
        for ref in state.get("document_inventory", []):
            if ref.form_type != "other" and ref.document_id not in documents:
                problems.append(f"draft finished without a record for document {ref.document_id}")
        for line, value in state.get("lines", {}).items():
            if not value.provenance:
                problems.append(f"line {line} has no provenance")
    dump = json.dumps({k: v for k, v in state.items() if k != "case_path"}, default=str)
    if REAL_LOOKING_SSN.search(dump):
        problems.append("a non-test SSN appears in the saved state")
    return problems


def run_case(case: dict) -> Outcome:
    outcome = Outcome(case_id=case["id"], passed=False)
    replies = list(case.get("replies", []))
    staff = list(case.get("staff", []))
    graph = make_graph(case)
    config = {"configurable": {"thread_id": f"eval-{case['id']}"}}

    with tempfile.TemporaryDirectory() as folder:
        payload = {"case_path": build_case_file(case, Path(folder))}
        for _ in range(MAX_STEPS):
            result = graph.invoke(payload, config)
            interrupts = result.get("__interrupt__") or []
            if not interrupts:
                break
            value = interrupts[0].value
            if isinstance(value, dict) and "ticket_id" in value:
                outcome.escalations.append(value["reason"])
                if not staff:
                    break  # paused on a human; the case may expect exactly that
                decision = staff.pop(0)
                if decision.get("reason") and decision["reason"] != value["reason"]:
                    outcome.problems.append(
                        f"expected escalation {decision['reason']} next, got {value['reason']}")
                    break
                payload = Command(resume={k: v for k, v in decision.items() if k != "reason"})
            else:
                if not replies:
                    outcome.problems.append(f"unexpected question with no scripted reply: {str(value)[:80]}")
                    break
                payload = Command(resume=replies.pop(0))
        else:
            outcome.problems.append(f"did not settle within {MAX_STEPS} steps")

        state = graph.get_state(config).values
        paused = graph.get_state(config).interrupts
        outcome.status = "waiting_on_human" if paused and isinstance(paused[0].value, dict) else state.get("status")

    expect = case.get("expect", {})
    if "status" in expect and outcome.status != expect["status"]:
        outcome.problems.append(f"status {outcome.status}, expected {expect['status']}")
    if "escalations" in expect and outcome.escalations != expect["escalations"]:
        outcome.problems.append(f"escalations {outcome.escalations}, expected {expect['escalations']}")
    for line, amount in expect.get("lines", {}).items():
        value = state.get("lines", {}).get(line)
        if value is None or value.amount != Decimal(amount):
            outcome.problems.append(f"line {line} is {value and value.amount}, expected {amount}")
    if "hops" in expect:
        hops = [h.to_agent for h in state.get("handoffs", [])]
        if hops != expect["hops"]:
            outcome.problems.append(f"route {hops}, expected {expect['hops']}")
    for name, value in expect.get("state", {}).items():
        if state.get(name) != value:
            outcome.problems.append(f"{name} is {state.get(name)!r}, expected {value!r}")
    if replies:
        outcome.problems.append(f"{len(replies)} scripted reply(s) never used")
    if staff:
        outcome.problems.append(f"{len(staff)} staff decision(s) never used")
    outcome.problems += _check_invariants(state)
    outcome.passed = not outcome.problems
    return outcome


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run SilverFile eval cases")
    parser.add_argument("--case", help="run one case by id")
    args = parser.parse_args(argv)
    cases = [c for c in load_cases() if args.case in (None, c["id"])]
    if not cases:
        print(f"No case with id {args.case!r}")
        return 1
    outcomes = [run_case(c) for c in cases]
    width = max(len(o.case_id) for o in outcomes)
    for o in outcomes:
        print(f"{'PASS' if o.passed else 'FAIL'}  {o.case_id:<{width}}  {o.status or '-':<17} {', '.join(o.escalations) or '-'}")
        for problem in o.problems:
            print(f"      - {problem}")
    failed = sum(not o.passed for o in outcomes)
    print(f"\n{len(outcomes) - failed} of {len(outcomes)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
