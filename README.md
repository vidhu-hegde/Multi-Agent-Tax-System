# SilverFile

A multi-agent system, built for Kushim, that helps prepare a draft **Form 1040-SR (U.S. Tax Return for Seniors),
tax year 2025**. It talks with the taxpayer, reads their tax documents, and produces:

1. A **draft 1040-SR** where every dollar amount shows where it came from.
2. A **staff dashboard** where Kushim employees track returns and resolve human-in-the-loop (HITL) escalations.

> SilverFile **never files anything**, **never gives tax advice**, **never shows an amount it can't source**, and
> **hands off to a person** whenever it hits an escalation condition. It accepts only test SSNs (900–999).

## Quick start (Docker)

Needs Docker Desktop with Compose 2.24 or newer.

```bash
git clone https://github.com/vidhu-hegde/Multi-Agent-Tax-System.git
cd Multi-Agent-Tax-System
cp .env.example .env            # add your ANTHROPIC_API_KEY (only run.py needs it)
docker compose up -d --build    # starts the tax-math server and the dashboard
```

- **Dashboard:** http://127.0.0.1:8000
- **A return:** `docker compose run --rm app python run.py --case data/fixtures/skeleton_case.json`
- **The eval cases:** `docker compose run --rm app python -m evals.run_evals`

More Docker commands, the demo dashboard and troubleshooting: [`docs/DOCKER.md`](docs/DOCKER.md).

### Without Docker

Needs Python 3.11 or newer, and two terminals.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
cp .env.example .env                  # add your ANTHROPIC_API_KEY

python -m src.tax_math.server         # terminal 1: the tax-math server; leave it running
python -m src.dashboard               # terminal 2: the dashboard at http://127.0.0.1:8000
```

## For graders

| What is graded | Where to look |
|---|---|
| Clean run from eval case 1, W-2 read from its image | [`demo/eval_case_1.md`](demo/eval_case_1.md): commands, expected draft, and a hand check of every number |
| HITL event from eval case 2, resolved | [`demo/eval_case_2.md`](demo/eval_case_2.md): a wage conflict, resolved on the dashboard |
| A clean run with your own data | Copy [`data/fixtures/skeleton_case.json`](data/fixtures/skeleton_case.json), change the answers and document values, and run `python run.py --case <your file>`. Leave an answer out and Intake asks for it |
| Dashboard | `python -m src.dashboard --demo` opens returns in every state, no key needed (in Docker: [demo dashboard](docs/DOCKER.md#demo-dashboard)) |
| Finished runs, no key needed | [`traces/`](traces/README.md): both eval cases' drafts and saved state |
| Context-window measurement | [`docs/metrics.md`](docs/metrics.md) |
| The report | [`docs/TEAM_REPORT.md`](docs/TEAM_REPORT.md) |

## How it works

Six agents plus a human-in-the-loop step. Every agent returns to the orchestrator, which picks the next step from
the current state.

| Agent | Job | Never |
|---|---|---|
| **Orchestrator** | Decides which agent acts next, and when the return is done | Extracts, computes, or talks to the taxpayer |
| **Intake** | The only agent that talks to the taxpayer, one question at a time | Does arithmetic or interprets tax rules |
| **Document Extraction** | Turns tax documents, including W-2 photos, into typed records | Decides what a value means for the return |
| **Eligibility & Rules** | Eligibility, filing status, deduction boxes, scope; cites [`data/policy.md`](data/policy.md) | Decides anything without citing the policy |
| **Computation** | Fills in every calculated line | Does arithmetic itself: every number is an MCP tool call |
| **Review / Audit** | Rechecks the whole return and sends problems back | Fixes anything itself |

```mermaid
flowchart TD
    START([Start]) --> O{Orchestrator}
    O -->|intake incomplete| I[Intake]
    O -->|documents pending| E1[Extract doc 1]
    O -->|documents pending| E2[Extract doc 2]
    O -->|documents pending| EN[Extract doc N]
    E1 --> AGG[Aggregate documents]
    E2 --> AGG
    EN --> AGG
    O -->|rules not evaluated| R[Eligibility & Rules]
    O -->|lines not computed| C[Computation]
    O -->|not reviewed| V[Review / Audit]
    O -->|open escalation, review limit or loop guard| H[[Human-in-the-loop interrupt]]
    I --> O
    AGG --> O
    R --> O
    C --> O
    V -->|revision requests| O
    H --> O
    O -->|draft ready or stopped| END([Draft 1040-SR + provenance])
```

- **Conditional routing:** the next step depends on the state, not a fixed order.
- **Parallel branch:** documents are read in parallel and merged by a reducer.
- **Bounded review loop:** Review can send work back up to 3 times (`SILVERFILE_MAX_REVIEW_PASSES`), then a person
  decides.
- **Loop guard:** the same handoff repeated 3 times (`SILVERFILE_LOOP_GUARD_REPEATS`) stops for a person.

**A person is asked** when there is an out-of-scope item, a conflict between the taxpayer and a document, a 1099-R
with box 2b checked, a request for tax advice, an unclear filing status, or any sign of financial exploitation. It
also happens when a document can't be read or the taxpayer isn't sure of an answer. Every reason is listed in
[`data/policy.md`](data/policy.md#escalation).

**In scope:** W-2, SSA-1099, 1099-R, 1099-INT and 1099-DIV; all five filing statuses; the standard deduction and the
senior deduction; Schedule 1, 2 and 3 totals typed in directly. Everything else goes to a person.

## Commands

Add `docker compose run --rm app` in front of these to run them in Docker.

```bash
python run.py --case data/fixtures/skeleton_case.json     # a return from a case file
python run.py --case demo/anupama_vision_case.json        # the same return, W-2 read from its photo
python run.py                                             # answer every question yourself
python run.py --thread-id <session id>                    # resume a saved return (Ctrl-D saves and leaves)
python run.py --sessions                                  # list returns and open escalations
python run.py --resolve <session id> <ticket id> --staff-id staff-7   # resolve from the terminal (--stop to stop)
python run.py --submit <session id> --staff-id staff-7    # mark a finished return as submitted
python -m src.render --case data/fixtures/skeleton_case.json --output output/draft.html   # draft, no key

python -m pytest -q                                       # tests
TAX_MATH_MCP_URL= python -m evals.run_evals               # eval cases, offline, no server needed
python run.py --batch [--no-context-strategy]             # context-window measurement (needs the key)
```

## Documentation

- [`docs/TEAM_REPORT.md`](docs/TEAM_REPORT.md): the report
- [`docs/IMPLEMENTATION_NOTES.md`](docs/IMPLEMENTATION_NOTES.md): design decisions and the full routing table
- [`docs/metrics.md`](docs/metrics.md): context-window measurement
- [`docs/AI_DISCLOSURE.md`](docs/AI_DISCLOSURE.md): how we used AI
- [`data/policy.md`](data/policy.md): the tax rules, scope and escalation reasons
- [`docs/GUARDRAILS_AND_ETHICS.md`](docs/GUARDRAILS_AND_ETHICS.md), [`docs/SECURITY_AND_PII.md`](docs/SECURITY_AND_PII.md):
  guardrails and security
- [`docs/DOCKER.md`](docs/DOCKER.md): Docker in detail
- [`evals/README.md`](evals/README.md): how the eval cases work

## Team

| Focus area | Team member |
|---|---|
| Agent memory | Iris Li |
| Inter-agent communication | Lakshmi Anupama Tamarapalli |
| Task division and management | Vidhatri Hegde |
| MLOps/DevOps | Max Charles |
| Guardrails and ethics | Juee Patil |
| Security | Qiyan Zhai |
