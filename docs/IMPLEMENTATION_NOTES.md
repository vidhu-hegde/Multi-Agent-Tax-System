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

## Stubs still in place

| Piece | Current behaviour | Replaced by |
|---|---|---|
| `tools.py` tax rules | `standard_deduction`, `senior_deduction`, `taxable_social_security`, `tax_from_schedule` return 0 and mark provenance `stub=True` | tax_math MCP server |
| Intake | Fixed questions, case file answers | LLM Intake agent |
| Extraction | Typed-in values only; images escalate as `uncertain` | Claude vision W-2 extraction |
| Rules citations | Placeholder `policy.md#...` ids | `data/policy.md` |
| `run_batch` | Not implemented | Context-window strategy + `docs/metrics.md` |
