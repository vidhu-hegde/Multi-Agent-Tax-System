# SilverFile

A multi-agent system, built for Kushim, that helps prepare a draft **Form 1040-SR (U.S. Tax Return for Seniors), tax year 2025**.

SilverFile collects information from the taxpayer, reads their tax documents, and produces:

1. A **draft 1040-SR**, where every dollar amount shows where it came from (its provenance).
2. A **"superuser" dashboard** that Kushim employees use to track returns and resolve human-in-the-loop (HITL) escalations.

> SilverFile helps prepare a return. It is not a tax preparer or a tax advisor. It **never files anything**, **never gives tax advice**, **never shows a dollar amount it cannot source**, and **always hands off to a human** when it hits an escalation condition.

---

## Quick start (Docker)

You need Docker Desktop (or another Docker engine) with Compose 2.24 or newer.

```bash
git clone https://github.com/vidhu-hegde/Multi-Agent-Tax-System.git
cd Multi-Agent-Tax-System
cp .env.example .env            # add your ANTHROPIC_API_KEY; only run.py needs it
docker compose up -d --build    # starts the tax_math MCP server and the dashboard
```

Then:

- **Dashboard:** open http://127.0.0.1:8000.
- **Demo dashboard**, with returns in every state and no key needed: see [Demo dashboard](#demo-dashboard).
- **A taxpayer session:** `docker compose run --rm app python run.py --case data/fixtures/skeleton_case.json`
- **The eval cases:** `docker compose run --rm app python -m evals.run_evals`

No Docker? See [Running without Docker](#running-without-docker).

---

## For graders

| What is graded | Where to look |
|---|---|
| Clean run from our eval case 1 data | [`demo/eval_case_1.md`](demo/eval_case_1.md): the commands, the expected draft and a hand check of every number |
| W-2 amounts read from the image | Eval case 1 reads [`demo/w2_image_1.jpg`](demo/w2_image_1.jpg) with Claude. The dashboard shows the image and the W-2 record's source. `python -m evals.live_vision_check` checks both W-2 images field by field |
| A HITL event from our eval case 2 data, resolved | [`demo/eval_case_2.md`](demo/eval_case_2.md): a wage conflict, then resolved on the dashboard or from the terminal |
| A clean run with your own data | [Make up your own return](#make-up-your-own-return) |
| Dashboard: returns in progress and submitted, HITL resolved by clicking | [Staff dashboard](#staff-dashboard) and the [demo dashboard](#demo-dashboard) |
| Docker | [Quick start](#quick-start-docker) and the [Docker reference](#docker-reference) |
| Tests and offline evals | [Tests and evals](#tests-and-evals): 688 tests, 26 of 26 eval cases |

---

## What SilverFile handles

- **Documents:** W-2 (typed values or a photo, read by Claude), SSA-1099, 1099-R, 1099-INT and 1099-DIV.
- **Filing statuses:** all five.
- **Deductions:** the standard deduction only, plus the Schedule 1-A senior deduction.
- **Schedules 1, 2 and 3:** the taxpayer types the totals in directly.

Anything else stops for a person rather than being guessed, for example itemized deductions, self-employment
income, capital gains, digital assets, foreign income, or a return with dependents. The full policy, with the
2025 figures and a citation for every rule, is in [`data/policy.md`](data/policy.md).

> **Test SSNs only:** the system accepts only SSNs in the 900–999 range (e.g. `901-XX-XXXX`), so a real SSN can never be entered.

---

## Agents

| Agent | Responsibility | Constraint |
|---|---|---|
| **Orchestrator** | Decides which agent acts next and when the run ends | Does not extract data, compute amounts, or talk to the user |
| **Intake** | The only agent that talks to the taxpayer: filing status, age, blindness, dependents, documents, estimated payments | Does no arithmetic and does not interpret tax rules |
| **Document Extraction** | Turns tax documents (W-2 images) into typed, structured records | Does not decide what a value means for the return |
| **Eligibility & Rules** | 1040-SR eligibility, filing-status checks, box counts, which schedules apply, scope checks | Grounded in `data/policy.md`; must cite it |
| **Computation** | Fills in every derived line | All arithmetic goes through deterministic MCP tool calls |
| **Review / Audit** | Tries to find problems in the assembled return and sends work back | Never fixes things itself |

## Orchestration

Hub-and-spoke: every agent returns to the orchestrator, which picks the next hop from state.
The full routing table and design notes are in [`docs/IMPLEMENTATION_NOTES.md`](docs/IMPLEMENTATION_NOTES.md).

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

- **Conditional routing:** the orchestrator applies a routing table to the current state.
- **Parallel branch:** one extraction branch per document (`Send`), joined at *Aggregate documents*; the `documents` reducer merges concurrent writes.
- **Review → revise cycle:** bounded at `SILVERFILE_MAX_REVIEW_PASSES` (default 3), then escalates.
- **Loop guard:** the same handoff (from, to, reason) repeated `SILVERFILE_LOOP_GUARD_REPEATS` times escalates to a human.

## Human-in-the-loop escalation

LangGraph interrupts fire for:

1. Any out-of-scope item (itemized deductions, Schedule C/E/D, 1099-NEC, digital assets, foreign income, amended or prior-year returns, state returns)
2. An unresolved conflict between what the user says and what a document shows
3. A 1099-R with box 2b "taxable amount not determined" checked
4. A request for tax advice, planning, or optimization
5. Ambiguous filing status, such as a spouse who died during the tax year
6. Signs of financial exploitation or third-party pressure

They also fire when SilverFile can't go on safely by itself: a document it could not read (staff type the
values in), an answer the taxpayer isn't sure about, a tax calculation that rejects an input, and the review
limit or loop guard above. Every reason, with its policy section, is listed in
[`data/policy.md`](data/policy.md#escalation).

---

## Running without Docker

You need Python 3.11 or newer.

```bash
git clone https://github.com/vidhu-hegde/Multi-Agent-Tax-System.git
cd Multi-Agent-Tax-System
python -m venv .venv
source .venv/bin/activate                          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt  # the exact versions we tested
cp .env.example .env                               # then add your ANTHROPIC_API_KEY
```

Every amount on the draft comes from a tax_math tool call (`call_tool()` in `src/tools.py`). `.env.example`
sets `TAX_MATH_MCP_URL=http://localhost:8001/mcp`, so the tools run on the MCP server. Start it in its own
terminal and leave it running:

```bash
python -m src.tax_math.server              # terminal 1: http://127.0.0.1:8001/mcp
```

Then use a second terminal for everything else:

```bash
python -m src.dashboard                    # terminal 2: the dashboard at http://127.0.0.1:8000
python run.py --case data/fixtures/skeleton_case.json
```

`run.py` and the dashboard check the server at startup. If it isn't answering, they stop with a message
instead of failing partway through a return. To run the same tools in-process with no server, comment
`TAX_MATH_MCP_URL` out of `.env`, or prefix a command with `TAX_MATH_MCP_URL=`. There is never a silent
fallback from one to the other. To use another port, start the server with `--port 8002` and change
`TAX_MATH_MCP_URL` to match.

---

## Using SilverFile

Commands are shown without Docker. With Docker, put `docker compose run --rm app` in front of `python ...`.

### Taxpayer session

`run.py` needs `ANTHROPIC_API_KEY` in `.env`.

```bash
python run.py --case data/fixtures/skeleton_case.json    # run a case file
python run.py --case demo/anupama_vision_case.json       # the same return, with the W-2 read from its photo
python run.py                                            # answer every question yourself
python run.py --thread-id <session id>                   # pick up a saved session
python run.py --case <file> --html output/draft.html     # also write the draft with its sources
```

Intake asks only for what the case file doesn't already answer. Press **Ctrl-D** at any question to save the
session and leave. `--thread-id` continues it later, and staff see it on the dashboard.

### Make up your own return

Copy [`data/fixtures/skeleton_case.json`](data/fixtures/skeleton_case.json), change the answers and the
document values, and run it with `--case`. Leave an answer out and Intake asks for it. With Docker, mount the
folder that holds your file (see [Docker reference](#docker-reference)).

A document named only in the chat (by typing "W-2" when Intake asks) has no values yet, so the return pauses for
staff to type them in on the dashboard. That's the unreadable-document escalation. For a clean run, put the
values (or an `image_path` to a W-2 photo) in the case file.

### Staff dashboard

```bash
python -m src.dashboard           # http://127.0.0.1:8000, the same sessions as run.py
python -m src.dashboard --demo    # a separate demo database with returns in every state
```

- **Needs a decision:** every return waiting on staff, oldest first. Open one to see the evidence, the
  uploaded image of an unreadable W-2, and what the taxpayer was told.
- **Resolve:** continue (with a note, a chosen record, a corrected amount, or the values typed from the
  document) or stop the session. The decision, note and staff ID are recorded on the ticket.
- **All returns:** filter by status: In progress, Waiting on taxpayer, Waiting on staff, Draft ready,
  Submitted, Stopped.
- **Draft with sources:** each draft opens with the source of every amount: the document box, the answer, or
  the tax_math call.
- **Mark as submitted:** once a reviewed draft has been filed, staff record it. The return shows who
  submitted it and when.
- **Resume:** a return that stopped partway (the tax_math server went down) can be resumed once the server
  is back.

`--demo` seeds `output/demo.sqlite` from the eval cases, offline, and never touches the real database. Delete
that file to start the demo fresh.

### Staff commands

The same actions the dashboard offers, from the terminal:

```bash
python run.py --sessions                                   # list sessions and open escalations
python run.py --resolve <session id> <ticket id> --note "Checked with client" --staff-id staff-7
python run.py --resolve <session id> <ticket id> --stop    # end the session instead
python run.py --resolve <session id> <ticket id> --values '{"employer_name": "...", "wages": "..."}'  # a document that couldn't be read
python run.py --submit <session id> --staff-id staff-7     # record that a finished return was filed
```

### Draft view without a key

```bash
python -m src.render --case data/fixtures/skeleton_case.json --output output/draft_1040sr.html
```

Open the HTML file and click or keyboard-activate an amount to see its sources and calculation. Amounts that
aren't complete or verified are withheld rather than shown. The design is in
[Anupama's handoff](docs/ANUPAMA_HANDOFF.md).

**Finished runs to look at.** [`traces/`](traces/) holds both graded walkthroughs, run offline with no key and
with the tax math on the MCP server. Each `_state.json` is the final saved state: answers, documents, rule
decisions with citations, every line with its provenance (each tool step's `via` is the server URL) and
the agent handoffs. Each `_draft.html` is the finished draft, opened like the one above.

| File | Shows |
|---|---|
| `demo_eval-case-1-clean-run_state.json`, `_draft.html` | The clean return (typed W-2): `draft_ready`, refund $2,455.50 |
| `demo_eval-case-2-wage-conflict_ticket.json` | The escalation staff saw: stated wages $24,000 against the W-2's $26,450.00 |
| `demo_eval-case-2-wage-conflict_state.json`, `_draft.html` | The same return after staff chose Continue: the resolved ticket and a refund of $1,460.25 |

No full SSN appears: case 2's W-2 keeps only the last four digits of the fixture's test SSN. To regenerate
(timestamps change; everything else is the same):

```bash
python -m src.tax_math.server &   # stop it afterwards
TAX_MATH_MCP_URL=http://localhost:8001/mcp python -m evals.run_evals --case eval-case-1-clean-run --trace traces
TAX_MATH_MCP_URL=http://localhost:8001/mcp python -m evals.run_evals --case eval-case-2-wage-conflict --trace traces
```

### Tests and evals

```bash
python -m pytest -q                           # the tests, always in-process
TAX_MATH_MCP_URL= python -m evals.run_evals   # the eval cases, offline, tax math in-process
python -m evals.run_evals                     # the same, through the tax_math server (start it first)
python -m evals.live_vision_check             # reads both W-2 images with Claude (needs the key)
```

The eval cases are in [`evals/cases.json`](evals/cases.json) (format: [`evals/README.md`](evals/README.md)), and
every case also runs in `pytest`. `tests/test_tax_math_mcp.py` starts its own server on a free port.

### Context-window strategy measurement

```bash
python run.py --batch                        # strategy enabled
python run.py --batch --no-context-strategy  # strategy disabled
```

Results are recorded in [`docs/metrics.md`](docs/metrics.md).

---

## Docker reference

One image runs everything (`Dockerfile`). `docker-compose.yml` starts the tax_math MCP server (`tax-math`) and
the staff dashboard, and runs `run.py`, the evals and the tests on demand (`app`).

| Task | Command |
|---|---|
| Staff dashboard | http://127.0.0.1:8000 (published on this machine only) |
| Evals (through tax-math) | `docker compose run --rm app python -m evals.run_evals` |
| Evals, tax math in-process | `docker compose run --rm -e TAX_MATH_MCP_URL= app python -m evals.run_evals` |
| Tests | `docker compose run --rm app python -m pytest -q -p no:cacheprovider` |
| Taxpayer session (needs the key) | `docker compose run --rm app python run.py --case data/fixtures/skeleton_case.json` |
| Resume a session | `docker compose run --rm app python run.py --thread-id <session id>` |
| List sessions | `docker compose run --rm app python run.py --sessions` |
| Logs | `docker compose logs -f dashboard tax-math` |
| Stop (keeps sessions) | `docker compose down` |
| Stop and delete all sessions | `docker compose down -v` |

### Demo dashboard

The demo uses the same port, so stop the normal dashboard first:

```bash
docker compose stop dashboard
docker compose run --rm --service-ports dashboard python -m src.dashboard --demo --host 0.0.0.0
# Ctrl-C to stop it, then: docker compose start dashboard
```

Without Docker: `python -m src.dashboard --demo`.

**What persists.** Sessions live in `/app/state/silverfile.sqlite` on the `state` volume, which `app` and the
dashboard share. The demo database, its case files and HTML drafts (`run.py --html output/draft.html`) live
in `/app/output` on the `output` volume. Both survive `docker compose down` and are deleted only by
`down -v`. `data/` (policy.md, fixtures) comes from the image and is never a volume.

**Restart check, no key needed:**

1. Start the demo dashboard (above). It prints `Demo database: /app/output/demo.sqlite (9 new returns)`.
2. Open http://127.0.0.1:8000, open *demo-wage-conflict*, enter a staff ID and choose Continue.
3. Ctrl-C, then `docker compose down` (no `-v`) and `docker compose up -d`.
4. Start the demo again: it prints `(0 new returns)`, and *demo-wage-conflict* shows your decision under
   "Decisions so far".

With a key, the same works for a taxpayer session: start one with `run.py --case ...`, note the session id,
press Ctrl-D (the session is saved), `down`, `up -d`, then `run.py --thread-id <session id>`.

**Notes.**

- `.env` is read at run time (`env_file`) and never copied into the image (`.dockerignore`). Compose sets
  `TAX_MATH_MCP_URL=http://tax-math:8001/mcp` and the database path itself, overriding the `localhost` and
  `data/` values in `.env`, which are for running outside Docker.
- Port 8001 is not published: only the containers reach tax-math.
- `constraints.txt` pins the image to the exact versions we tested (`pip install -r requirements.txt -c
  constraints.txt`). After changing `requirements.txt`, regenerate it inside the container, not on your Mac
  (some packages differ by platform): `docker compose build`, then
  `docker compose run --rm --no-deps -T app pip freeze > constraints.txt` (`-T`: without it the TTY adds `\r` to every line).
- The code in the image is read-only to the app (it runs as user `silverfile`, uid 1000); only `/app/state`
  and `/app/output` are writable. To run your own case file, mount it read-only, for example
  `docker compose run --rm -v "$PWD/cases:/app/cases:ro" app python run.py --case cases/mine.json`, and mount it
  again at the same path to resume.
- If run.py or the dashboard says the tax_math server is unreachable, check `docker compose ps`: tax-math
  should be `healthy`. A `421 Invalid Host header` means it is listening on 127.0.0.1 instead of 0.0.0.0.
- Port 8000 already in use (a local dashboard, say): stop that, or change `127.0.0.1:8000:8000` to
  `127.0.0.1:8080:8000` and open http://127.0.0.1:8080.

---

## Repository layout

```
.
├── run.py                  # taxpayer sessions, staff commands, --batch
├── Dockerfile, docker-compose.yml, constraints.txt, requirements.txt, .env.example
├── src/
│   ├── graph.py            # the LangGraph graph and the orchestrator's routing
│   ├── state.py, schemas.py, communication.py   # shared state and the typed contracts between agents
│   ├── agents/             # orchestrator, intake, extraction, rules, computation, review, human
│   ├── tools.py            # call_tool(): in-process, or the tax_math MCP server
│   ├── tax_math/           # rules.py, registry.py, server.py (python -m src.tax_math.server)
│   ├── sessions.py         # the staff API the dashboard and run.py use
│   ├── dashboard/          # FastAPI app, templates, --demo seeding
│   ├── render.py           # the draft with sources, as HTML
│   ├── memory.py           # checkpointer and the context-window strategy
│   └── guardrails.py, security.py, escalation.py, resolution.py, evidence.py, config.py
├── data/
│   ├── policy.md           # the 2025 rules every decision cites
│   ├── generate_fixtures.py
│   └── fixtures/           # case files, W-2 PDFs and their expected records
├── evals/                  # cases.json, run_evals.py, live_vision_check.py, guardrail_eval.py
├── tests/
├── demo/                   # eval_case_1.md, eval_case_2.md, W-2 images, the vision case file
├── docs/
└── traces/
```

## Documentation

- [`docs/TEAM_REPORT.md`](docs/TEAM_REPORT.md): the team report, with Mermaid diagrams
- [`docs/IMPLEMENTATION_NOTES.md`](docs/IMPLEMENTATION_NOTES.md): design decisions, routing, and how each part was built and checked
- [`data/policy.md`](data/policy.md): the tax rules, scope and escalation reasons
- [`docs/GUARDRAILS_AND_ETHICS.md`](docs/GUARDRAILS_AND_ETHICS.md) and [`docs/guardrail_eval.md`](docs/guardrail_eval.md): guardrails and how they were measured
- [`docs/SECURITY_AND_PII.md`](docs/SECURITY_AND_PII.md): security boundaries and PII handling
- [`docs/tax_math_rules_spec.md`](docs/tax_math_rules_spec.md): the tax_math tools
- [`docs/metrics.md`](docs/metrics.md): the context-window strategy measurement
- [`docs/AI_DISCLOSURE.md`](docs/AI_DISCLOSURE.md): how we used AI tools
- Handoffs and report sections: [`docs/ANUPAMA_HANDOFF.md`](docs/ANUPAMA_HANDOFF.md), [`docs/ANUPAMA_REPORT.md`](docs/ANUPAMA_REPORT.md), [`docs/IRIS_HANDOFF.md`](docs/IRIS_HANDOFF.md), [`docs/IRIS_REPORT.md`](docs/IRIS_REPORT.md)

---

## Team

| Focus area | Team member assigned |
|---|---|
| Agent memory | Iris |
| Inter-agent communication | Anupama |
| Task division and management | Vidhatri |
| MLOps/DevOps | Max |
| Guardrails and ethics | Juee |
| Security | Qiyan |

Team members: Vidhatri Hegde, Qiyan Zhai, Max Charles, Iris Li, Juee Patil, Lakshmi Anupama Tamarapalli
