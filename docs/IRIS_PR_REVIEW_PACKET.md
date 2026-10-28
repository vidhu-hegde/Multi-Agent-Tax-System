# Iris offline follow-up: PR and independent review packet

This packet helps reviewers locate evidence. It is not an independent audit or a grade prediction.
Verify claims against the source, tests and professor's assignment. The current scope/status is in
[IRIS_HANDOFF.md](IRIS_HANDOFF.md); the report contribution is [IRIS_REPORT.md](IRIS_REPORT.md).

## Proposed PR

Base: `main` (`5c441003e7ba8d59b6ede46568915ec7437bf1d0` when checked).
Head: `codex/iris-offline-verification`.

Title: **Persist partial Intake imports and harden offline memory evaluation**

Ready-to-paste description:

```markdown
Partial case-file imports could reach an unanswered question before imported answers were
checkpointed, losing saved progress and the resume recap after restart. Save those imports before
interrupting. Also distinguish valid classifier output from Intake's safe `uncertain` fallback so
malformed or unsupported output cannot count as a correct benchmark result.

Add eight shared offline eval cases and strengthen their confirmed-answer and handoff assertions.
Regression coverage checks five-process SQLite persistence, recap, correction history, downstream
recalculation, current/archived provenance, thread isolation and staff recovery. Both benchmark CLI
modes use provider doubles, test context boundaries and reject invalid outcomes or missing usage.
Fault injection verifies readiness evals fail on lost inputs and unrelated uncertainty pauses.
Update Iris's report/disclosure drafts, handoff, metrics and reproducible demo instructions.

Validation (offline, 2026-10-28):

- `.venv/bin/python -m pytest -q`: 532 passed, 7 existing PyMuPDF/SWIG warnings.
- `ANTHROPIC_API_KEY='' .venv/bin/python -m evals.run_evals`: 24/24 passed.
- `git diff origin/main...HEAD --check`: clean.
- Guardrail development set: 42/42; HTML keyboard/click provenance and 390px smoke check passed.
- Checkpoint and invalid-classifier regressions failed before their fixes; fault controls expose
  the earlier readiness-assertion gap. Current origin/main separately passed 504 tests/7 warnings.

Limitations: no live API calls or context-token measurements; synthetic usage checks plumbing only.
Four readiness cases expect a staff pause, not completed dependent/Schedule 2/3 output. Normal
model/batch wiring, all-call usage accounting, live context evaluation, actual MCP transport,
Security/Review PR #11 integration and container persistence verification remain team dependencies.
Current Review can miss coherently wrong tax values; passing tests do not establish full tax or
security correctness. Iris still needs personal report/disclosure approval and a recorded demo
segment; the team must complete the report, disclosures and 5–10 minute video.

Ownership: new runtime edits are confined to Iris's Intake/classifier and memory benchmark.
Shared changes only extend offline eval assertions. Merged schemas, extraction/rendering, graph,
policy, tax rules and dashboard remain attributed to their owners. Evidence, all ten Iris checklist
statuses and cross-owner findings: `docs/IRIS_HANDOFF.md`.
```

Original commits `760483f`, `f7e2545` and `5902794` are preserved. Audit code/tests are in `d5d1c06`;
the final documentation commit records this package. No push, PR creation or external communication
has been performed. This is ready for a Draft PR, not a claim of completed team submission.

## Evidence map against the professor's rubric

The supplied handoff includes the professor's text and a separate ten-item Iris checklist. Treat the
professor's brief as authoritative; don't silently turn the team's checklist into extra graded rules.

| Rubric area | Evidence to inspect/run | Limits and uncompleted requirements |
|---|---|---|
| **A. Memory/state (15 pts)** | `src/state.py`, `src/memory.py`, `src/agents/intake.py`; `tests/test_merge_order.py` (both merge orders/conflicts/delayed retries); `tests/test_memory.py::test_multiple_real_process_restarts_and_thread_isolation`; new `tests/test_iris_integration.py::test_restart_correction_recomputes_and_preserves_audit_and_isolation` | Single-writer answer history; no arbitrary multi-writer guarantee. Container restart/persistent mount is not established by Python-process tests. |
| **B. Orchestration (15 pts)** | Existing `src/graph.py`, `src/agents/orchestrator.py`; `tests/test_graph.py::test_extraction_fans_out_one_branch_per_document`, `test_review_loop_is_bounded_then_escalates`, `test_loop_guard_breaks_a_pathological_cycle`; README graph | Existing team-owned behavior exercised by the suite, not newly implemented by this PR. Actual MCP transport remains incomplete. |
| **C. Engineering/reproducibility (15 pts)** | Full pytest suite; existing requirements; `git diff --check`; strict checkpoint serialization in `tests/conftest.py`; literal expected payment amounts/provenance in new integration tests | Runtime DBs/artifacts live under ignored output/temp paths. Seven PyMuPDF/SWIG warnings also occur on the freshly tested baseline. Passing tests does not prove full correctness: current Review misses a coherently corrupted tax result; #11 is unmerged. |
| **D. Evaluation (20 pts)** | `evals/cases.json` and `python -m evals.run_evals`; the eight `iris-...` cases; new cross-process test for actual restart evidence; `evals/README.md` for the team's recorded live W-2 check | Four new readiness-gate cases pass by pausing, not by completing the required dependent/schedule outputs. Live W-2 results are teammate-reported earlier evidence, not repeated here. §4.5 context table/curve has no actual measurements. |
| **E. Demo (5 pts)** | `demo/iris_memory_accessibility.md`, its action sequence/narration and the automated integration evidence | Rehearsal and tests are not the required 5–10 minute recorded team video. |
| **§4.3 Accessibility/dignity** | Six choices mapped in `docs/IRIS_REPORT.md`; `tests/test_dialogue_dignity.py`; recap/drift/correction/staff-recovery tests; browser smoke check | At least four choices still need to be shown in the team video. Keyboard/mobile checks are not a screen-reader audit. Known guardrail false alarms are recorded for Juee. |
| **§4.5 Context strategy** | `src/memory.py::model_context`, `invoke_model`, `run_context_benchmark`, `main`; selective-context/provider-usage/ten-item tests and both CLI modes, including invalid-output/missing-usage failures, in `tests/test_memory.py` | Provider-double usage is synthetic. `run_batch` still raises `SystemExit`; the default graph does not wire model-backed Intake. Extraction model usage is not aggregated by the Intake-only harness. Team must agree invoice/item interpretation and run the actual measured comparison using someone else's available credits. |
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

## Audit source and remaining submission evidence

The independent audit is now recorded at the top of [IRIS_HANDOFF.md](IRIS_HANDOFF.md), including
negative controls and the ten-row completion assessment. Sections dated October 27 and October 25
below it are prior/historical evidence, not the latest status. No full-credit prediction is made.

For this local workspace, the original supplied assignment/checklist is available at
`/Users/irisli0926/Downloads/SilverFile_Codex_Handoff_Iris_Checklist_v2.md`. That personal Downloads path
is not a repository dependency; external reviewers need the instructor's original brief supplied to
them. The professor's §5.2 clean/HITL fixtures, dashboard/image extraction and filled draft, §5.3
individual disclosures and required 5–10 minute recording must be checked in the final integrated team
submission. The optional five-page report and Docker/dashboard stretch deliverables are team work;
this Iris report contribution alone does not complete them.
