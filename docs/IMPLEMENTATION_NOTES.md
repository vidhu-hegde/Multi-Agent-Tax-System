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
| 4 | In-scope documents not yet extracted | `extract_document` × N (parallel `Send`) → `aggregate_documents` | `N document(s) to extract` |
| 5 | No `scope` rule decision yet | `rules` | `rules not evaluated` |
| 6 | Revision requests pending and `review_passes >= SILVERFILE_MAX_REVIEW_PASSES` | `human` (new `review_limit` ticket) | `review limit reached` |
| 7 | Revision requests pending | the request's `target` agent | `revision: line X: <reason>` |
| 8 | No lines computed | `computation` | `lines not computed` |
| 9 | `review_status` is not `passed` | `review` | `draft not reviewed` |
| 10 | Otherwise | END, status `draft_ready` | `draft ready` |

## Parallel extraction

Row 4 fans out one `extract_document` branch per document with `Send`. The branches write to
`documents`, a dict merged by `merge_dicts`, keyed by `document_id`, so concurrent writes never collide and
the result does not depend on arrival order (`tests/test_merge_order.py`). `aggregate_documents` is the join.

## Social Security ordering

Line 6b needs every other income line and line 10, and lines 9 and 11a need 6b. The graph guarantees all
documents are extracted (row 4) before computation runs (row 8), and `computation.py` computes lines in
dependency order: other income → 10 → 6b → 9 → 11a (`test_social_security_runs_after_other_income`).

## Review → revise bound

Review increments `review_passes` on every run and returns `RevisionRequest`s; it never edits lines.
After `SILVERFILE_MAX_REVIEW_PASSES` (default 3) failing passes, the orchestrator escalates with a
`review_limit` ticket instead of routing back again (`test_review_loop_is_bounded_then_escalates`).
Resolving the ticket with `continue` resets the counter.

## Loop guard

Every routing decision is recorded as a `Handoff(from_agent, to_agent, reason)`. Before routing, the
orchestrator counts identical handoffs since `guard_window_start`; if this one has already happened
`SILVERFILE_LOOP_GUARD_REPEATS` times (default 3), it raises a `loop_guard` ticket and routes to a human
instead. Resolving the ticket moves the window forward. The review loop cannot trip it by accident, because
the review bound (row 6) is checked first. Test: `test_loop_guard_breaks_a_pathological_cycle`, using an
Intake agent that never finishes.

## Human-in-the-loop

`human` calls `interrupt()` once per open ticket. Resume with `Command(resume=...)`: a string (`stop`, or
any note meaning continue) or a dict `{"action": "continue" | "stop", "note": ..., "resolved_by": ...}`,
which is what the dashboard will send. Resolved tickets are never reopened (`merge_escalations`).

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

**Stub detection:** Intake's `classify_reply()` uses keyword lists. The LLM Intake agent replaces that one
function with a model call; the escalation path stays the same. Data for eval case 2 is in
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

## Stubs still in place

| Piece | Current behaviour | Replaced by |
|---|---|---|
| `tools.py` tax rules | `standard_deduction`, `senior_deduction`, `taxable_social_security`, `tax_from_schedule` return 0 and mark provenance `stub=True` | tax_math MCP server |
| Intake | Fixed questions, case file answers, keyword `classify_reply()` | LLM Intake agent |
| Extraction | Typed-in values only; images escalate as `uncertain` | Claude vision W-2 extraction |
| Rules citations | Placeholder `policy.md#...` ids | `data/policy.md` |
| `run_batch` | Not implemented | Context-window strategy + `docs/metrics.md` |
