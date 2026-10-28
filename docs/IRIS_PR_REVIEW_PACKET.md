# Iris offline follow-up: PR and independent review packet

Use this packet to find the source and tests behind the PR. Test results do not establish a grade.
The current scope and status are in
[IRIS_HANDOFF.md](IRIS_HANDOFF.md); the report contribution is [IRIS_REPORT.md](IRIS_REPORT.md).

## PR title and description

Base: `main` (`5c441003e7ba8d59b6ede46568915ec7437bf1d0` when checked).
Head: `Iris-agent-memory`.

Title: **Persist partial Intake imports and harden offline memory evaluation**

```markdown
Partial case-file imports could pause for a missing answer before saving the answers already
provided. Intake now checkpoints those imports before asking the next question. The benchmark
also checks whether classifier output was valid, so malformed JSON and unsupported reasons no
longer count as correct through the `uncertain` fallback. Intake still flags a volunteer.

Adds eight shared offline eval cases and checks their confirmed answers and handoff evidence.
Tests cover five-process SQLite restarts, recap, correction history, recalculation, current and
archived provenance, thread isolation and staff recovery. Both benchmark CLI modes test context
boundaries and reject invalid outcomes or missing usage. Fault tests confirm that lost inputs
and unrelated uncertainty pauses fail the readiness evals. Iris's report, disclosure draft and
demo instructions have been edited with Humanizer; teammate attribution is preserved.

Validation (offline, 2026-10-28):

- 532 pytest tests passed with 7 existing PyMuPDF/SWIG warnings.
- 24/24 shared evals passed; the diff whitespace check is clean.
- The guardrail development set passed 42/42; keyboard/click provenance and 390px layout passed.
- The checkpoint and invalid-output regressions failed before their fixes. Fault controls exposed
  the earlier readiness-assertion gap. Current origin/main separately passed 504 tests/7 warnings.
- PR #11 overlaps five files and has no textual merge conflict at its tested head `c6aafeb`.
  A temporary combined snapshot passed 574 tests/7 warnings after this PR's restart test was
  updated to check the displayed question through the production formatter. Neither branch
  contains the other's unmerged work.

No live API calls or context-token measurements were made. Synthetic usage checks logging only.
Four readiness cases verify staff pauses; dependent and nonzero Schedule 2/3 output remains
incomplete. Model/batch wiring, all-call usage accounting, live context evaluation, MCP transport,
Security/Review integration and container verification still need their owners. Current Review
can miss coherently wrong tax values. Iris still needs to approve her report/disclosure and record
her segment; the team must complete its final report, disclosures and 5-to-10-minute video.

Runtime edits are confined to Iris's Intake/classifier and memory benchmark. Shared changes extend
offline eval assertions. Schemas, extraction/rendering, graph, policy, tax rules and dashboard remain
attributed to their owners. The ten-item assessment and owner findings are in `docs/IRIS_HANDOFF.md`.
```

The original commits `760483f`, `f7e2545` and `5902794` remain in history. Audit fixes are in
`d5d1c06`, the audit documentation is in `805c742`, and the typed-question test adjustment is in
`d702319`. The review-preparation step fast-forwards Iris's existing `Iris-agent-memory` branch and
removes the redundant local branch name. Publishing this branch creates no second Iris branch and
does not change main or the head of PR #11. PR #6 is merged and PR #5 is closed.

## Open PR compatibility (2026-10-28)

[Security/Review PR #11](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/11) was the only
open PR before this follow-up. Its tested head is `c6aafeb82dd6d5f25735275633f8473bb7d9652e`.
The overlapping files are `evals/cases.json`, `src/agents/intake.py`, `src/memory.py`,
`tests/test_intake.py` and `tests/test_memory.py`. `git merge-tree --write-tree` reports a clean merge.

The first combined snapshot passed 573 tests and failed the new restart regression because #11
changes question interrupts from strings to typed objects. The regression now uses the production
formatter to inspect the question shown to the taxpayer. The adjusted snapshot passes 574 tests
with the same seven warnings. Both working branches remain separate. This check covers the tested
commits; whichever PR merges second still needs to update against main and rerun its checks.

## Evidence map against the professor's rubric

The professor's brief defines the graded requirements. The ten-item Iris checklist records the
team's additional acceptance criteria.

| Rubric area | Evidence to inspect/run | Limits and uncompleted requirements |
|---|---|---|
| **A. Memory/state (15 pts)** | `src/state.py`, `src/memory.py`, `src/agents/intake.py`; `tests/test_merge_order.py` (both merge orders/conflicts/delayed retries); `tests/test_memory.py::test_multiple_real_process_restarts_and_thread_isolation`; new `tests/test_iris_integration.py::test_restart_correction_recomputes_and_preserves_audit_and_isolation` | Single-writer answer history; no arbitrary multi-writer guarantee. Container restart/persistent mount is not established by Python-process tests. |
| **B. Orchestration (15 pts)** | Existing `src/graph.py`, `src/agents/orchestrator.py`; `tests/test_graph.py::test_extraction_fans_out_one_branch_per_document`, `test_review_loop_is_bounded_then_escalates`, `test_loop_guard_breaks_a_pathological_cycle`; README graph | Existing team-owned behavior exercised by the suite, not newly implemented by this PR. Actual MCP transport remains incomplete. |
| **C. Engineering/reproducibility (15 pts)** | Full pytest suite; existing requirements; `git diff --check`; strict checkpoint serialization in `tests/conftest.py`; literal expected payment amounts/provenance in new integration tests | Runtime DBs/artifacts live under ignored output/temp paths. Seven PyMuPDF/SWIG warnings also occur on the freshly tested baseline. Passing tests does not prove full correctness: current Review misses a coherently corrupted tax result; #11 is unmerged. |
| **D. Evaluation (20 pts)** | `evals/cases.json` and `python -m evals.run_evals`; the eight `iris-...` cases; new cross-process test for actual restart evidence; `evals/README.md` for the team's recorded live W-2 check | Four new readiness-gate cases pass by pausing, not by completing the required dependent/schedule outputs. Live W-2 results are teammate-reported earlier evidence, not repeated here. §4.5 context table/curve has no actual measurements. |
| **E. Demo (5 pts)** | `demo/iris_memory_accessibility.md`, its action sequence/narration and the automated integration evidence | Rehearsal and tests are not the required 5-to-10 minute recorded team video. |
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

## Assignment source and remaining submission work

The audit findings are at the top of [IRIS_HANDOFF.md](IRIS_HANDOFF.md), including
negative controls and the ten-row completion assessment. Sections dated October 27 and October 25
below it are prior/historical evidence, not the latest status. The test results leave the submission requirements below open.

For this local workspace, the original supplied assignment/checklist is available at
`/Users/irisli0926/Downloads/SilverFile_Codex_Handoff_Iris_Checklist_v2.md`. That personal Downloads path
is not a repository dependency; external reviewers need the instructor's original brief supplied to
them. The professor's §5.2 clean/HITL fixtures, dashboard/image extraction and filled draft, §5.3
individual disclosures and required 5-to-10 minute recording must be checked in the final integrated team
submission. The optional five-page report and Docker/dashboard stretch deliverables are team work;
this Iris report contribution alone does not complete them.
