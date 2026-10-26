# PR #6 review follow-up

Review: vidhu-hegde, 2026-10-25. This note supersedes the historical guard, recap,
conflict-reducer and downstream-resume descriptions in `IRIS_HANDOFF.md`.

| Review item | Disposition |
|---|---|
| 1. Nonzero dependent / Schedule 2 / Schedule 3 loop | Fixed. Intake escalates once per unsupported-value fingerprint, then completes after staff continue. Changed values need fresh approval; stop ends the session. Inputs are retained. Downstream calculations still do not consume them, as the staff prompt explicitly states. |
| 2. Intake resets loop guard | Fixed. Only the orchestrator tracks growth of the deduplicated confirmed-answer history and advances the window for that progress. Intake no longer writes the guard index, including after model calls. Repeated re-asks without new answers escalate. |
| 3. Random CLI session-ID rejection | Fixed. New CLI sessions use `thread_config()`; a deterministic all-digit UUID regression exercises the old failure. |
| 4. Recap before every question | Fixed in the CLI driver. A resumed session shows the recap once, on its first Intake question. Ordinary questions and retries omit it. Other frontends should apply the same resume boundary. |
| 5. Spouse-death wording | Changed to “If you had a spouse who died, what year was it? Type none if this does not apply to you.” This avoids presuming a deceased spouse while retaining single-filer disclosure coverage. Juee's final wording approval remains a team dependency. |
| 6. Conflicting reducer writes crash | Fixed. Reducers preserve competing records in `StateWriteConflict`. The orchestrator escalates before consumers run. Staff explicitly select a numbered record or stop. A selected document triggers Rules, Computation and Review again. Pending document conflicts survive a SQLite restart. |
| 7. Live context-window metrics | Still blocked. Both ON and OFF benchmark commands exit because `ANTHROPIC_API_KEY` is not configured. No live token measurements or flat-curve result are claimed. |
| 8. Benchmark fields in shared state | Fixed. The benchmark uses `ContextBenchmarkState`; `context_item` and `context_reason` were removed from `SilverFileState`. |

Staff can resolve a write conflict with
`sessions.resolve(thread_id, ticket_id, choice=1)` or
`python run.py --resolve THREAD_ID TICKET_ID --choice 1`.
The interactive CLI shows the candidates and accepts
`{"action":"continue","choice":1}`. Candidate numbers start at 1;
plain continue cannot silently choose a record.

Validation:

- Baseline: `.venv/bin/python -m pytest -q` — 126 passed.
- After review fixes: `.venv/bin/python -m pytest -q` — 137 passed.
- Both runs have the same seven existing PyMuPDF/SWIG deprecation warnings.
- Regressions cover the reviewer's complete interactive dependent and Schedule 2 flows,
  all seven unsupported-field gates, fresh approval for changed values, progress-aware
  guards, no-progress model cycles, recap frequency, safe CLI identity, reducer ordering,
  conflict restart/selection, recalculation and staff stop/continue selection.
- `git diff --check` — clean.
- ON: `.venv/bin/python -m src.memory --batch --thread-id pr6-context-on` — exit 1, missing API key.
- OFF: `.venv/bin/python -m src.memory --batch --no-context-strategy --thread-id pr6-context-off`
  — exit 1, missing API key.

These changes do not wire the missing tax calculations or replace the team's final policy,
wording, UI and live-measurement reviews.
