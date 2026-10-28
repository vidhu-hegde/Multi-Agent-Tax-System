# Implementation notes

## Topology

Hub-and-spoke (supervisor). Every agent returns to the **orchestrator**, which reads state and picks the
next hop. We chose this over a fixed pipeline because the next step genuinely depends on state:
escalations can appear at any point, review can send work back to different agents, and a resumed
session can be anywhere in the process. A single router also gives one place to enforce the loop bounds.

The orchestrator never extracts, computes or talks to the user. It only applies the routing table below
(`decide()` in `src/agents/orchestrator.py`).

## Routing table

First matching row wins.

| # | State condition | Next hop | Reason recorded |
|---|---|---|---|
| 1 | Any escalation ticket is open | `human` (interrupt) | `escalation <ticket_id>` |
| 2 | A human resolved a ticket with `stop` | END, status `stopped` | `stopped by a human` |
| 3 | `intake_complete` is not set | `intake` | `intake incomplete` |
| 4 | In-scope documents without a record | `extract_document` × N (parallel `Send`) → `aggregate_documents` | `N document(s) to extract` |
| 5 | No `scope` rule decision yet | `rules` | `rules not evaluated` |
| 6 | Revision requests pending and `review_passes >= SILVERFILE_MAX_REVIEW_PASSES` | `human` (new `review_limit` ticket) | `review limit reached` |
| 7 | Revision requests pending | the request's `target` agent | `revision: line X: <reason>` |
| 8 | No lines computed | `computation` | `lines not computed` |
| 9 | `review_status` is not `passed` | `review` | `draft not reviewed` |
| 10 | Otherwise | END, status `draft_ready` | `draft ready` |

## Documents that can't be read

When Extraction can't read a document (an image it can't transcribe, or typed values that don't fit the
form), it raises an `uncertain` ticket with `needs_document_values` and the form's `required_fields`.
The fields staff must type for each form are defined in code, in `STAFF_ENTRY_FIELDS` (`src/agents/extraction.py`):
every field that feeds a 1040-SR line, plus the W-2 values that should escalate. Every listed field must be
present. An explicit `0`, `false`, `null` or `[]` is fine, but a missing field is rejected, so nothing silently
defaults (for example, a missing `federal_withheld` can't become $0).
The document is **never left out**: row 4 keeps it pending until it has a record, so a draft can't be
produced with it missing. Staff resolve the ticket in one of two ways:

- **Type the values from the document:** `{"action": "continue", "values": {...}}`, or
  `sessions.resolve(..., values={...})`, or `python run.py --resolve ... --values '{...}'`. The values
  become a record with provenance "direct user input", the staff member's id and the time (§4.2).
- **Stop the session.**

Plain `continue` asks again. Invalid values are asked for again too, naming only the fields that need
checking, never the typed values. The ticket's resolution records which document was entered, but the
values themselves live only in the record.

## Parallel extraction

Row 4 fans out one `extract_document` branch per document with `Send`. The branches write to
`documents`, a dict merged by `merge_documents`, keyed by `document_id`. Disjoint writes merge in either
order and identical retries are idempotent. Competing writes are preserved in `StateWriteConflict`;
the orchestrator turns them into a human escalation before any consumer runs
(`tests/test_merge_order.py`). `aggregate_documents` is the join. Staff select one numbered candidate
or stop; a selected document queues fresh Rules, Computation and Review work.
Rules and computed lines use `merge_dicts` for sequential revision; same-key replacement there is
explicitly order-dependent and must not be used for competing parallel writes.

## Social Security ordering

Line 6b needs every other income line and line 10, and lines 9 and 11a need 6b. The graph guarantees all
documents are extracted (row 4) before computation runs (row 8), and `computation.py` computes lines in
dependency order: other income → 10 → 6b → 9 → 11a (`test_social_security_runs_after_other_income`).

## Line 16 and rounding

Line 16 uses the 2025 tax rate schedule because the brief's line table specifies it, not the IRS Tax
Table. On the clean case (line 15 = $6,445) the Tax Table would give $643 instead of $644.50. Every
tool result is rounded to cents, half up, once in `call_tool()` (`src/tools.py`); the rule functions in
`src/tax_math/rules.py` stay exact. This supersedes the whole-dollar recommendation in
`docs/tax_math_rules_spec.md` section 4.

## tax_math MCP server

`call_tool()` (`src/tools.py`) runs the seven tools of `src/tax_math/registry.py` (`sum`, `subtract`,
`subtract_floor_zero` and the four rules) in-process when `TAX_MATH_MCP_URL` is empty, and on the MCP server
(`python -m src.tax_math.server`, streamable HTTP at `/mcp`, port 8001) when it is set. The URL is read once
per process from `.env`; `run.py`, the dashboard and `python -m evals.run_evals` all go through `call_tool()`,
so they all follow it. Both paths share one implementation and return the same `(Decimal, Provenance)`:

- Amounts travel as strings (`src/tax_math/wire.py`); the server turns money arguments back into `Decimal`.
  Its tool arguments are typed `Any`, so it never coerces a value (`True` into `1`) that the rules refuse.
- The server returns the exact result; `call_tool()` rounds it to cents, half up, as in-process.
- A tool step's `Provenance.via` is the server URL, or `None` in-process. `inputs` are the caller's own
  values on both paths, so the draft view is the same.
- A rule error crosses as `ToolError("ValueError: ...")` (also `TypeError`, `InvalidOperation`) and is raised
  again as that class, so callers that catch `ValueError` behave the same on both paths.
- If the server cannot answer, `call_tool()` raises `TaxMathUnavailable`, a `RuntimeError` and deliberately
  not a `ValueError` (the dashboard shows a `ValueError` as bad form input). There is one reconnect, since
  the tools are pure, and never a fallback to in-process math. `run.py` and the dashboard lifespan call
  `check_server()` at startup, so a missing server stops them before a return is half computed.
- `call_tool()` stays synchronous. Each MCP call runs on one event loop in a daemon thread, so it works from
  `run.py`, the dashboard's threadpool, and inside a running loop (the dashboard's `async def resolve`). The
  server is stateless, so each call opens a short MCP session; about 5 ms per call on localhost.
- A missing or unexpected argument is a `TypeError` on both paths: `call_tool()` binds the arguments to the
  tool's signature before sending, because the server would otherwise ignore an extra (misspelled) one.
- On `127.0.0.1` the SDK checks the Host header (DNS rebinding protection). `TAX_MATH_MCP_HOST=0.0.0.0`, for
  Docker, turns that check off.

Tests force `TAX_MATH_MCP_URL` empty (`tests/conftest.py`). `tests/test_tax_math_mcp.py` starts the server in
a thread on a free port and checks every tool and every rule error against the in-process path, a call from
inside a running loop, concurrent calls, the unreachable case (run.py and the dashboard refuse to start) and
a whole graph run.

## Docker

`Dockerfile` builds one image (`python:3.11-slim-bookworm`, `requirements.txt` only, about 850 MB, mostly the
pip layer). `docker-compose.yml` runs it three ways: `tax-math` (the MCP server), `dashboard` (port 8000,
published on the host's 127.0.0.1 only) and `app` (`run.py`, evals, tests; `cli` profile, so `up` does not
start it). The README's "Getting started with Docker" has the commands.

- **Secrets.** `.dockerignore` keeps `.env` out of the build context; compose passes it at run time with
  `env_file` (optional, so the offline paths need none). A build with a fake key in `.env` left no trace of it
  in the image or in `docker history`.
- **Addresses.** Compose sets `TAX_MATH_MCP_URL=http://tax-math:8001/mcp` and `SILVERFILE_DB_PATH` in
  `environment`, which wins over `.env` (whose `localhost` and `data/` values are for running outside Docker).
  tax-math listens on `0.0.0.0` (`TAX_MATH_MCP_HOST`): on 127.0.0.1 the SDK's Host-header check refuses
  `Host: tax-math:8001` with 421. On 0.0.0.0 the SDK does no Host check; port 8001 is not published, so only
  the compose network reaches it. The dashboard binds 0.0.0.0 with its existing `--host` flag; no code changed.
- **Readiness.** tax-math's healthcheck is a plain TCP connect (no curl in the image, and `GET /mcp` opens a
  stream that never closes). app and dashboard wait for it (`service_healthy`), and their own
  `check_server()` then confirms the MCP tools answer.
- **Persistence.** The `state` volume holds `/app/state/silverfile.sqlite`, shared by app and dashboard. The
  `output` volume holds `/app/output` (the demo database, `demo_cases/`, which demo sessions re-read, and HTML
  drafts). Nothing is mounted over `/app/data`, which holds policy.md and the fixtures. Named volumes live in
  Docker's Linux VM, where SQLite locking is reliable; do not bind-mount the database to a macOS folder.
- **Pinned versions.** `constraints.txt` pins all 83 installed packages to the versions tested in the image;
  the Dockerfile installs `requirements.txt` with `-c constraints.txt`, so a rebuild cannot drift.
  `requirements.txt` keeps the ranges. After changing it, regenerate the pins the same way, inside the
  container (`docker compose build`, then `docker compose run --rm --no-deps -T app pip freeze >
  constraints.txt`): a Mac venv resolves differently (on 2026-10-28 it had `anthropic` 1.17.0 to the image's
  2.3.0, plus leftover streamlit packages).
- **Permissions.** The code is owned by root and read-only to the app, which runs as `silverfile` (uid 1000);
  only `/app/state` and `/app/output` are writable. A named volume takes its owner from the image the first
  time it is mounted. Run the tests with `-p no:cacheprovider` (pytest cannot write `.pytest_cache`).
- **Verified (2026-10-28, Docker 29.9.2, Compose v5.6.1):** tax-math healthy, dashboard 200, port 8001
  unreachable from the host; evals 16 of 16 through tax-math (1,872 MCP requests, 4 per tool call); 532 tests
  in the container; the demo restart check (resolve over HTTP, `down`, `up -d`, `0 new returns`, ticket still
  resolved).

## Review → revise bound

Review increments `review_passes` on every run and returns `RevisionRequest`s; it never edits lines.
After `SILVERFILE_MAX_REVIEW_PASSES` (default 3) failing passes, the orchestrator escalates with a
`review_limit` ticket instead of routing back again (`test_review_loop_is_bounded_then_escalates`).
Resolving the ticket with `continue` resets the counter.

## Loop guard

Every routing decision is recorded as a `Handoff(from_agent, to_agent, reason)`. Before routing, the
orchestrator counts identical handoffs since `guard_window_start`; if this one has already happened
`SILVERFILE_LOOP_GUARD_REPEATS` times (default 3), it raises a `loop_guard` ticket and routes to a human
instead. The orchestrator advances the window when the deduplicated confirmed-answer history grows;
Intake never resets it, including after model-assisted re-asks. Resolving a guard ticket also moves the
window forward. The review loop cannot trip it by accident, because
the review bound (row 6) is checked first. Test: `test_loop_guard_breaks_a_pathological_cycle`, using an
Intake agent that never finishes.

## Human-in-the-loop

`human` calls `interrupt()` once per open ticket. Resume with `Command(resume=...)`: a string (`stop`, or
any note meaning continue) or a dict `{"action": "continue" | "stop", "note": ..., "resolved_by": ...}`,
which is what the dashboard will send. Resolved tickets are never reopened (`merge_escalations`).

An `out_of_scope` ticket can always be stopped, but "continue" needs a written reason in `note`
(for example "Client confirms the 1099-NEC was issued in error"). Plain `continue`, an empty note or
"ok" asks again, and `Sessions.resolve` / `run.py --resolve` refuse it before touching the session.
SilverFile does not prepare those returns, so continuing is a staff override, and the reason stays on
the ticket's `resolution` for the reviewer. False alarms (for example a guardrail match on a reply)
are the expected reason to continue.

Agents raise tickets only through `escalate()` / `ticket()` in `src/escalation.py`. The ticket id is
`<reason>:<key>`, where the key identifies the occurrence, so raising the same issue twice is harmless.

### The six escalation conditions

| # | Condition (brief §4.4) | Raised by | Ticket id | How it's detected now | Test |
|---|---|---|---|---|---|
| 1 | Out-of-scope item | Rules | `out_of_scope:<document id>` or `out_of_scope:not_1040sr_eligible` | Document type `other`; nobody born before 2 Jan 1961 | `test_out_of_scope_document_escalates` |
| 2 | User statement conflicts with a document | Rules | `document_conflict:wages` | Intake asks about wages when there's a W-2; Rules compares that answer with the W-2 box 1 total, and a difference over $500 escalates. "Not sure" is a valid answer and skips the check | `test_stated_wages_that_disagree_with_the_w2_escalate` |
| 3 | 1099-R box 2b checked | Rules | `1099r_taxable_not_determined:<document id>` | `taxable_not_determined` on the record | `test_1099r_box_2b_escalates_and_resolves` |
| 4 | Tax advice, planning or optimisation | Intake | `advice_request:<field>:<reply hash>` | Reply that isn't a valid answer and asks for advice | `test_advice_request_escalates_then_intake_carries_on` |
| 5 | Filing-status ambiguity | Rules | `filing_status_ambiguity:spouse_death` | Intake asks MFJ/QSS filers whether their spouse died; died in 2025, QSS without a 2023/2024 death, or MFJ with a death all escalate | `test_spouse_death_makes_filing_status_a_human_decision` |
| 6 | Exploitation or third-party pressure | Intake | `exploitation_concern:<field>:<reply hash>` | Reply mentions someone else directing the return or refund | `test_third_party_steering_the_refund_escalates` |
| — | Honest uncertainty (§4.3) | Intake | `uncertain:<field>:<reply hash>` | "I'm not sure" where a definite answer is needed | `test_not_sure_escalates_as_uncertain` |

When Intake escalates, it stops at the current question, keeps the answers it already has, and picks up
at the same question once staff resolve the ticket. If the person repeats a reply that was already
escalated, Intake says so and asks again instead of raising a second ticket. The ticket's evidence holds
the question, the reply, and what was said to the taxpayer (`said_to_taxpayer`).

**Reply detection:** Intake's default `classify_reply()` uses Juee's named rules in `src/guardrails.py`.
The optional `make_intake(model,
use_context_strategy=True)` adds a model fallback for unparseable replies, accepting only the approved
escalation reason or null. The escalation path stays the same. Data for eval case 2 is in
`data/fixtures/conflict_case.json`.

## Dashboard hook (`src/sessions.py`)

The dashboard talks to sessions only through `open_sessions()`; it never touches the graph or the
checkpointer directly.

```python
from src.sessions import open_sessions, StaleEscalation

with open_sessions() as sessions:
    sessions.list_sessions()                # SessionSummary for every session, newest first
    sessions.list_sessions("waiting_on_human")
    sessions.open_escalations()             # [(thread_id, EscalationTicket)]: the HITL queue
    sessions.state(thread_id)               # full state for the detail view: lines, provenance, answers
    sessions.resolve(thread_id, ticket_id, action="continue", note="...", resolved_by="staff-7")
```

| Session status | Meaning |
|---|---|
| `in_progress` | The graph is between steps |
| `waiting_on_taxpayer` | Intake asked a question (`pending_question`) |
| `waiting_on_human` | Paused on an escalation (`awaiting_ticket_id`) |
| `draft_ready` | Reviewed draft produced |
| `stopped` | A staff member resolved a ticket with `stop` |

`resolve()` checks that the session is paused on that exact ticket, resumes that interrupt by id, and
returns the new summary. The session may finish, pause on its next ticket, or go back to waiting on the
taxpayer. A ticket that was already resolved raises `StaleEscalation`, so two staff members cannot both
act on it. Resolutions are recorded on the ticket (`resolution`, `resolved_by`, `resolved_at`).

The same actions are on the command line for graders and for testing without the dashboard:
`python run.py --sessions` and `python run.py --resolve THREAD_ID TICKET_ID [--stop] [--note ...]`.

## Dashboard (`src/dashboard/`)

`python -m src.dashboard` serves a FastAPI app with server-rendered Jinja templates (autoescaped, no
JavaScript). It reads and resolves sessions only through `Sessions`, so every rule in `resolve()` applies
exactly as it does on the command line.

| Page | What staff see and do |
|---|---|
| `/` | The queue of open escalations across returns (oldest first) and every return, filterable by status |
| `/sessions/{id}` | The ticket the return is paused on: reason, detail, evidence, which guardrail rule fired, staff-only guidance. A form that matches the ticket: a note, a reason (required for `out_of_scope`), a candidate (state-write conflict), or the document's fields with its image (unreadable document). Also the decisions so far, the documents and the taxpayer's answers |
| `/sessions/{id}/draft` | Anupama's provenance view (`render_draft`) |

Choices made for staff safety:

- It binds to 127.0.0.1 and refuses form posts whose `Origin`/`Referer` is another site, so a page open
  in the staff member's browser can't resolve tickets.
- SSN-shaped values are masked to the last four digits wherever the dashboard displays state.
- A document image is served only if it is that return's inventory image, an image type, and inside the project.
- Error messages name fields by their form labels and never repeat typed values; the form keeps them so
  staff can correct them.
- The exploitation guidance is shown only on the staff page. The taxpayer's screen stays neutral (`run.py`).
- Staff must give an ID; it is remembered in an HTTP-only cookie for the next decision.

`python -m src.dashboard --demo` seeds `output/demo.sqlite` from eval cases, offline, with returns that
are draft-ready, waiting on the taxpayer, and paused on each kind of escalation. Tests: `tests/test_dashboard.py`.

## Persistence

`src/memory.py` opens the SQLite checkpointer (`SILVERFILE_DB_PATH`) for every process: the taxpayer
session, the dashboard and the tests. Our Pydantic types are registered with LangGraph's serializer.
Without that, a future LangGraph version refuses to load them, and today an unregistered type comes back
as a plain dict. The tests run with `LANGGRAPH_STRICT_MSGPACK=true`, so a new state type that isn't
registered fails the tests instead of passing silently.

## W-2 record fields

Rule: a field goes on `W2Record` only if the system uses it or it helps catch a misread image.

| W-2 box | Field | Decision |
|---|---|---|
| 1, 2 | `wages`, `federal_withheld` | Required/kept: feed lines 1z and 25a |
| c | `employer_name` | Kept: shown in provenance |
| b | `employer_ein` | Optional, format `NN-NNNNNNN`. Not personal data; detects the same W-2 uploaded twice |
| e | `employee_name` | Optional. Says whose W-2 it is on a joint return |
| a | `employee_ssn_last4` | Only the last four digits are stored. Extraction passes the full number as `employee_ssn`; the record rejects anything outside the 900–999 test range, then discards all but the last four. A full SSN never reaches state, logs, traces or prompts |
| 3–6 | `social_security_wages`, `social_security_withheld`, `medicare_wages`, `medicare_withheld` | Optional. Not on the 1040-SR, but they let Review catch vision misreads (box 4 = 6.2% of box 3, box 6 = 1.45% of box 5) |
| 8, 10, 12, 13 | `allocated_tips`, `dependent_care_benefits`, `box12` (code + amount), `statutory_employee`, `retirement_plan`, `third_party_sick_pay` | Kept as **scope signals**. They aren't used in the arithmetic, but some values mean the return is out of scope (see below) |
| 7, 9, 11, 14 | — | Left out: informational only (box 7 tips and box 11 amounts are already in box 1; box 9 is always blank) |
| 15–20 | — | Left out: state and local only, and state returns are out of scope |

### W-2 values that should escalate (for the Rules agent)

These fields are captured now, but the Rules agent does not act on them yet. Before relying on this list, check
each code against the IRS *2025 General Instructions for Forms W-2 and W-3* and record it in `policy.md`
with a section id the Rules agent can cite.

| Field | Escalate when | Why |
|---|---|---|
| `statutory_employee` | checked | Statutory employee wages go on Schedule C |
| `allocated_tips` | > 0 | Form 4137 |
| `dependent_care_benefits` | > 0 | Form 2441 (line 1e) |
| `medicare_wages` | > 200,000 | Additional Medicare Tax, Form 8959 (line 25c) |
| `box12` code A, B, M, N | present | Uncollected Social Security/Medicare tax, Schedule 2 |
| `box12` code K, Z | present | Excise or additional tax (golden parachute, 409A) |
| `box12` code Q | present | Nontaxable combat pay election (line 1i) |
| `box12` code R, W | present | Archer MSA / HSA (Forms 8853, 8889) |
| `box12` code T | present | Adoption benefits, Form 8839 (line 1f) |
| `box12` code H, FF, GG, HH, II | present | Need forms or judgement outside our scope |
| `box12` any code not listed here | present | Unknown means "not sure": escalate as `uncertain` |

No action needed (already reflected in box 1, or informational): box 12 codes C, D, E, F, G, S, AA, BB, DD,
EE, J, L, P, V, Y, and the `retirement_plan` and `third_party_sick_pay` checkboxes.

The ground truth for the sample images (`data/fixtures/w2_N_expected.json`) has exactly the `W2Record`
input fields, so an extraction test can compare its output directly.

## Integration status (audited 2026-10-28)

| Piece | Current behaviour | Remaining work |
|---|---|---|
| Intake model hookup | Checkpointed structured dialogue; optional model classifier via `make_intake` | Vidhatri/Max connect the factory to the default entry point |
| Extraction | Typed direct entries plus Claude W-2 vision (#7/#13); unreadable documents require staff fields or stop | Further live quality evidence belongs to the extraction owner; no API needed for offline Intake work |
| Rules citations | Juee's `data/policy.md` and centralized guardrails are merged (#9) | Policy/wording follow-ups belong to Juee |
| Staff dashboard | FastAPI/Jinja queue, return details, resolution and provenance draft are merged (#13) | Finished-return correction controls and final accessibility review |
| Context benchmark | `python run.py --batch [--no-context-strategy]` runs Iris's `src.memory` benchmark; `python -m src.metrics_table` writes the results table (#21) | Live ON/OFF run needs an API key (`docs/metrics.md`) |

## Iris: memory and state

Intake saves each accepted interactive answer before asking the next question. Case-file imports may
commit several validated fields together. They return a checkpoint update before interrupting for a
missing interactive answer, so a partial case's imported values survive restart and appear in the
resume recap. `answers` uses `merge_answers`: `(field, answered_at,
entered_by)` identifies an event. The reducer orders events by confirmation time before collapsing repeated
effective values, so replaying an old suppressed answer cannot undo a newer correction. Contradictory
values at the same confirmation time fail explicitly. `current_answers()` uses the same ordering,
including for legacy checkpoints whose history was written in arrival order.
Intake is the single answer writer; this history is not a commutative multi-writer CRDT.

`IntakeAnswer`, `Dependent`, `DocumentRef`, `SSN`, `RevisionRequest`, and `EscalationTicket` remain the
existing contracts in `src/schemas.py`. `StateWriteConflict` preserves competing document or escalation
writes until staff choose one. Shared records and pending conflicts round-trip through the serializer.
Escalations preserve a resolved ticket over an identical open retry; changed identities or contradictory
resolutions become an `uncertain` staff ticket. Candidate order and deduplication are deterministic.
The CLI displays the candidates and accepts `{"action":"continue","choice":1}` or `stop`.
Staff API callers use `sessions.resolve(..., choice=1)`; staff CLI callers add `--choice 1`.

`thread_config()` generates opaque return ids and rejects SSN-shaped supplied ids. The SQLite saver
enforces that boundary for existing entry points too. Each id identifies a single return workflow. It carries no SSN and does not identify a person across
tax years. `SILVERFILE_DB_PATH` remains configurable. The tests start three separate
Python processes with one database and return id, then a separate return id, verifying answers,
recap, pending question, retry idempotency and isolation. A different SQLite connection alone is not
our process-restart evidence. The DB is ignored by Git; no real taxpayer data was used.

Corrections during a question accept `change filing status to married filing jointly`,
`go back to filing status`, or `{"field": "estimated_payments", "value": "2000"}`. A changed confirmed
field queues the existing `RevisionRequest` contract for Rules and Computation, marks Review pending,
and resets its pass count. The existing graph performs those reruns. The orchestrator tracks new
confirmed answers with `guard_answer_count` and advances `guard_window_start` when that count grows.
Pathological Intake and model re-ask cycles with no new answers still trip the guard.
A finished return can be reopened through the existing graph API
with `{"intake_complete": false, "intake_revisit": "estimated_payments"}`; finished-return correction controls are not wired into Vidhatri's dashboard.

Review-to-Intake requests first use the integrated `RevisionRequest.field` (#7), then the existing
line bindings: `10` asks for `adjustments`, `20` for `schedule3_nonrefundable_credits`,
`23` for `schedule2_total_tax`, `26` for `estimated_payments`, and `31` for
`schedule3_other_payments`; an explicit
`intake_revisit` also supplies a target. The request remains
pending until that field is confirmed. Go-back to another field does not consume a line-targeted
request. A confirmation with no change marks Review pending without resetting its bounded pass count.
Unknown/unavailable targets are explicitly handed off as `uncertain` and removed from the routing
queue; other requests remain. Named-field targeting itself is no longer a missing interface.

The integrated `src/evidence.py` contract from #7 archives prior documents/lines/rules, retracts
removed or replaced inventory records, increments an evidence epoch and clears stale results before
fresh Rules/Computation/Review. Changed evidence gets fresh rule-ticket identities, preserving prior
approvals as history without applying them to the new occurrence. Competing writes still require
explicit staff selection. These interfaces handle retraction and versioning for the supported paths.

Nonzero inputs awaiting downstream integration create one uncertainty ticket for their fingerprint.
Staff `continue` lets Intake finish without re-asking the same field; `stop` ends the workflow.
Changed unsupported values create a fresh ticket. This approval does not implement dependent
calculations: the escalation explicitly discloses that those inputs remain unused. Schedule 2/3 totals
are no longer gated: Computation uses them for lines 20, 23 and 31 (see below).

## Iris: accessibility and dignity

The tests below exercise the dialogue choices. Use `demo/iris_memory_accessibility.md` to record
them in the required 5-to-10-minute team video; that recording remains to be made.

| Brief §4.3 choice | Behavior | Verification |
|---|---|---|
| One question at a time | Each prompt asks for one field. Dependent name, relationship and requested test SSN are separate turns. | `test_interactive_intake_asks_one_question_at_a_time`, `test_dependents_are_collected_as_separate_questions` |
| Plain language | Filing statuses have full names; estimated payments and schedule totals have short explanations. The spouse-death question begins "If you had a spouse who died" and offers none, including for single filers. | Full interactive test plus explicit question text; Juee still needs to sign off on wording. |
| Repetition and drift | Invalid unrelated replies re-ask; repeated effective answers deduplicate; corrections and go-back preserve previous fields and history. | Correction, repetition and go-back tests in `tests/test_intake.py` |
| Minimize PII | No taxpayer SSN prompt. Only dependent records request required test SSNs via the existing 900-series schema. Recaps omit names, birth-date values and SSNs. Model summaries exclude typed DOB/dependent/document records. | Dependent, unsolicited-SSN and selective-context tests |
| Resumability | The CLI shows a recap once, on the first question after resuming. Ordinary questions and retries omit it. Other frontends should use the same resume boundary. | `test_resume_recap_is_shown_once`, process-restart tests |
| Honest uncertainty | "I'm not sure; let me flag this for a volunteer" creates the existing typed ticket, and the existing human node interrupts. Staff resolution returns to the unfinished question. | `test_uncertainty_pause_survives_restart_and_staff_resolution`, existing escalation tests |

Intake sanitizes unsolicited SSNs before storing answers, tickets or model context, including the
baseline. Qiyan's merged #11 also validates/redacts replies before `Command(resume=...)`, using the
question's input type, and validates staff decisions through `Sessions.resolve()`. This matters because
LangGraph can save the raw resume payload before Intake runs. Requested test dependent SSNs remain
in typed records because the assignment requires them. External provider traces, encryption, production
authentication and retention are not established by these tests; see `SECURITY_AND_PII.md`.

## Iris: model context and measurement interface

`make_intake(model, use_context_strategy=...)` uses `src.memory.invoke_model()` for unclear replies.
ON sends the current question/reply and a small allowlisted summary of confirmed session inputs. OFF
sends the same summary plus accumulated classifier dialogue. Both redact SSNs. The model returns an
escalation classification only; invalid output becomes `uncertain`, and arbitrary generated prose is
not passed to the taxpayer. A boolean `silverfile_classification_valid` in response metadata
distinguishes valid output from the safety fallback. Benchmark correctness requires a valid expected
classification; malformed JSON and unsupported reasons fail that check. Intake commits a completed
model call before the next interrupt to prevent
normal resume replay from billing the same call again. A crash between provider response and checkpoint
commit still has an at-least-once delivery risk; no exactly-once remote-call guarantee is claimed.

Actual `AIMessage.usage_metadata.input_tokens` is recorded by call id in `input_token_usage`. Missing
usage raises an error; text length is never substituted. The benchmark sums all new call entries per
item, verifies outcomes, and persists ten sequential items in a single fresh thread for each run.
It calls the same classifier as Intake, using synthetic unclear replies. Its small evaluation graph
uses its own `ContextBenchmarkState`. Its fields `context_item`, `context_reason` and
`context_classification_valid` are absent from `SilverFileState`. See `docs/metrics.md` for commands and blockers.

The default `run.py` graph still uses deterministic Intake. Vidhatri/Max can opt into the tested model
path without replacing the graph:

```python
from langchain_anthropic import ChatAnthropic
from src.agents.intake import make_intake

model = ChatAnthropic(model=settings.model, api_key=settings.anthropic_api_key,
                      max_retries=0)
graph = build_graph(settings, checkpointer,
                    agents={"intake": make_intake(model, use_context_strategy)})
```

`build_graph(use_context_strategy=...)` alone currently does not configure any model. Its owner must
wire this factory and the existing `run.py --batch` hook. The Iris-owned measurement entry point is
`python -m src.memory --batch [--no-context-strategy]`. Live measurements were blocked by the missing
API key in the historical attempt. Live execution now remains an external team dependency because
Iris has no credits. No further key/token request or live call was made. Production-wide token
reduction and the completed invoice evaluation remain unmeasured.

New downstream inputs have an explicit readiness gate (`PENDING_DOWNSTREAM_FIELDS`), now limited to
a positive dependent count. Standard-deduction scope exceptions are recorded by Intake and escalated
by Rules, with policy citations. Schedule 2/3 totals left the gate once Computation consumed them: Schedule 3 line 8
fills line 20, Schedule 2 line 21 fills line 23 and Schedule 3 line 15 fills line 31, and lines 18, 21,
22, 24, 32 and 33 are derived through `tax_math` (`tests/test_schedules.py`, eval
`schedules-2-and-3-typed-totals`). Line 17 and line 19 are not supported, so lines 18 and 21 each have
one part. Staff continue does not implement dependent output. Preserve truthful answers and stop
unsupported dependent workflows until their owner integration is complete. This gate checks missing software support; Intake
does not determine tax eligibility or compute amounts. Remove each gate only with downstream tests.

## Iris: per-turn disclosure and field-aware PII fixes

A per-turn pre-check delegates to Juee's centralized `src/guardrails.py` (#9) before accepting an answer
or applying a structured correction. It reuses the shared reasons and `escalate()` helper. The checks
notice disclosures independently of the field being requested and record the named matching rule
for staff. They do not interpret tax rules. Wording/false-alarm follow-ups reproduced during Iris's
offline review are recorded in `docs/IRIS_HANDOFF.md`.

Only a complete valid monetary literal in a requested monetary field bypasses generic SSN redaction
for field validation. Thus `123456789` can be an amount; labelled identifiers and dashed SSNs cannot
parse as money. The same applies to corrections targeting a monetary field. A separately redacted turn
is still used for model context and escalation evidence, and the raw-text copy is generically redacted.
Unsolicited nine-digit integers in structured metadata are redacted too. Requested dependent SSNs still
use the shared 900-series schema and have no raw-text copy. The merged security ingress reuses this
field-aware distinction before resume commands; external trace handling still requires deployment
review. See `docs/IRIS_HANDOFF.md` for regression results and
all ten updated checklist statuses. Live context measurements remain unavailable.


## Communication/extraction integration update (Anupama, 2026-10-25)

[ANUPAMA_HANDOFF.md](ANUPAMA_HANDOFF.md) supersedes earlier descriptions of extraction as a typed-values-only
stub, missing generic revision-field targeting, and blocked inventory retraction. It documents the
Claude vision interface, audited manual records, graph message validation, evidence epochs/archives
and the HTML provenance view. The later status table above supersedes historical dependency claims:
live W-2 testing, real tax functions, policy and the dashboard landed in #9/#10/#13/#14. Normal Intake
model/batch wiring and actual MCP transport remain open. This update changes no tax policy.
