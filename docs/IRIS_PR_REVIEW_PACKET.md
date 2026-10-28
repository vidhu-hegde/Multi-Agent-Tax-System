# Iris offline follow-up: PR and independent review packet

This packet helps reviewers locate evidence. It is not an independent audit or a grade prediction.
Verify claims against the source, tests and professor's assignment. The current scope/status is in
[IRIS_HANDOFF.md](IRIS_HANDOFF.md); the report contribution is [IRIS_REPORT.md](IRIS_REPORT.md).

## Proposed PR

Base: `main` (`5c441003e7ba8d59b6ede46568915ec7437bf1d0` when checked).
Head: `codex/iris-offline-verification`.

Title: **Persist partial Intake imports before prompting and add offline memory evidence**

Suggested description:

> A partial case file could reach its first unanswered question before Intake returned the imported
> answers to the checkpointer. After process restart those answers were absent from the saved state
> and resume recap. Intake now saves the accumulated imports before asking for the missing answer.
>
> Adds a regression using five separate Python processes to verify the checkpoint, one resume recap,
> corrections, updated payment provenance, archived prior values and thread isolation. Also adds
> staff-recovery integration coverage, both benchmark CLI modes with provider doubles, and eight
> shared offline eval cases. Updates Iris's handoff, report/disclosure contribution and demo notes
> against the merged interfaces. Runtime changes are confined to three added lines in Intake.
>
> Validation: **516 tests passed** with seven existing PyMuPDF/SWIG warnings; **24/24 offline evals**.
> Browser smoke checks passed for Enter/Space/click provenance controls and a 390px viewport.
> No live API calls or token measurements were made. Dependent/Schedule 2/3 cases deliberately expect
> a staff pause until the downstream consumers land. Default model/batch wiring, live context
> measurement, actual MCP transport, Security PR #11 and Docker verification remain team dependencies.
>
> Evidence and ownership: `docs/IRIS_HANDOFF.md`. Report/disclosure drafts still require Iris's final
> proofreading, and the team still needs its recorded demo.

The bug regression failed on the merged baseline before the fix (saved `adjustments` was missing),
then passed with the checkpoint guard. The branch's implementation/test and documentation commits
retain Iris's configured author attribution. This packet is an additional documentation commit.

## Evidence map against the professor's rubric

The supplied handoff includes the professor's text and a separate ten-item Iris checklist. Treat the
professor's brief as authoritative; don't silently turn the team's checklist into extra graded rules.

| Rubric area | Evidence to inspect/run | Limits and uncompleted requirements |
|---|---|---|
| **A. Memory/state (15 pts)** | `src/state.py`, `src/memory.py`, `src/agents/intake.py`; `tests/test_merge_order.py` (both merge orders/conflicts/delayed retries); `tests/test_memory.py::test_multiple_real_process_restarts_and_thread_isolation`; new `tests/test_iris_integration.py::test_restart_correction_recomputes_and_preserves_audit_and_isolation` | Single-writer answer history; no arbitrary multi-writer guarantee. Container restart/persistent mount is not established by Python-process tests. |
| **B. Orchestration (15 pts)** | Existing `src/graph.py`, `src/agents/orchestrator.py`; `tests/test_graph.py::test_extraction_fans_out_one_branch_per_document`, `test_review_loop_is_bounded_then_escalates`, `test_loop_guard_breaks_a_pathological_cycle`; README graph | Existing team-owned behavior exercised by the suite, not newly implemented by this PR. Actual MCP transport remains incomplete. |
| **C. Engineering/reproducibility (15 pts)** | Full pytest suite; existing requirements; `git diff --check`; strict checkpoint serialization in `tests/conftest.py`; literal expected payment amounts/provenance in new integration tests | Runtime DBs/artifacts live under ignored output/temp paths. Seven existing PyMuPDF/SWIG warnings remain. Passing tests does not prove all security properties; #11 is unmerged. |
| **D. Evaluation (20 pts)** | `evals/cases.json` and `python -m evals.run_evals`; the eight `iris-...` cases; new cross-process test for actual restart evidence; `evals/README.md` for the team's recorded live W-2 check | Four new readiness-gate cases pass by pausing, not by completing the required dependent/schedule outputs. Live W-2 results are teammate-reported earlier evidence, not repeated here. §4.5 context table/curve has no actual measurements. |
| **E. Demo (5 pts)** | `demo/iris_memory_accessibility.md`, its action sequence/narration and the automated integration evidence | Rehearsal and tests are not the required 5–10 minute recorded team video. |
| **§4.3 Accessibility/dignity** | Six choices mapped in `docs/IRIS_REPORT.md`; `tests/test_dialogue_dignity.py`; recap/drift/correction/staff-recovery tests; browser smoke check | At least four choices still need to be shown in the team video. Keyboard/mobile checks are not a screen-reader audit. Known guardrail false alarms are recorded for Juee. |
| **§4.5 Context strategy** | `src/memory.py::model_context`, `invoke_model`, `run_context_benchmark`, `main`; selective-context/provider-usage/ten-item tests and both CLI modes in `tests/test_memory.py` | Provider-double usage is synthetic. `run_batch` still raises `SystemExit`; the default graph does not wire model-backed Intake. Extraction model usage is not aggregated by the Intake-only harness. Team must agree invoice/item interpretation and run the actual measured comparison using someone else's available credits. |
| **§5.3 AI disclosure** | Iris draft in `docs/AI_DISCLOSURE.md` | Iris's personal proofreading and team consolidation remain. A generated draft does not establish personal approval. |

## Reproduce offline

From the repository root with its existing requirements installed:

```bash
.venv/bin/python -m pytest -q
ANTHROPIC_API_KEY='' .venv/bin/python -m evals.run_evals
git diff origin/main...HEAD --check
```

Tests force an empty Anthropic key, use temporary state for test runs and never require live credits.
The JSON eval runner uses an in-memory saver. It cannot establish a process restart; that evidence
comes from the subprocess test, which uses a real SQLite database.

Optional integrated HTML/browser reproduction is in `docs/IRIS_HANDOFF.md`. The generated draft,
browser screenshot and rehearsal transcript under ignored `output/` are local conveniences, not
required source artifacts or substitute submissions.

## Suggested prompt for the separate audit chat

Audit `codex/iris-offline-verification` against the professor's original SilverFile assignment and
Iris's separate ten-item checklist. Read this packet only as an index, then inspect the actual
`origin/main...HEAD` diff, implementation, tests and deliverables independently. Rerun the offline
checks. Distinguish Iris's new changes from already-merged teammate work, missing implementation from
legitimate scope escalation, and synthetic model usage from real measurements. Report actionable
findings with file/line evidence and identify anything needed before PR review separately from final
team submission. API access is external to Iris; do not request tokens or make live calls. Begin
read-only and do not alter this branch while reviewing it.

For this local workspace, the original supplied assignment/checklist is available at
`/Users/irisli0926/Downloads/SilverFile_Codex_Handoff_Iris_Checklist_v2.md`. That personal Downloads path
is not a repository dependency; external reviewers need the instructor's original brief supplied to
them. Older claims below the historical boundary in `IRIS_HANDOFF.md` are historical, not the latest
completion status.
