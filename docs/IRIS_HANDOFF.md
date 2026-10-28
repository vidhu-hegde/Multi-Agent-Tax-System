# Iris Agent Memory / Intake completion and coordination report

## Current independent audit (2026-10-28)

The audit checked the assignment and all ten Iris checklist items against source, the full diff and
fresh offline runs. The results below supersede the two earlier reports. Iris still needs to approve
the generated disclosure personally; test results do not establish a grade.

### Branch, attribution and remote review

The audit started with a clean tree on `codex/iris-offline-verification`, at `5902794`. `git fetch origin
--prune` left `origin/main` at `5c441003e7ba8d59b6ede46568915ec7437bf1d0`. The original local commits
`760483f`, `f7e2545`, and `5902794` are preserved. The audit made no changes to main and did not
push, open a PR or contact teammates. The later review-preparation step reuses `Iris-agent-memory`
as Iris's only local and remote branch. It fast-forwards that branch to the audited commits and
removes the redundant local branch name; all commits remain in history.

PR #6 contains the earlier Iris implementation. Shared contracts/evidence/rendering (#7), graph and
staff interfaces (#8/#12/#13), guardrails (#9), tax rules (#10) and cents rounding (#14) are already
merged contributions, not new implementation in this follow-up. The original follow-up added the
partial-import guard, eight eval cases, integration/benchmark tests and Iris documentation. This audit
also changes the Intake classifier's validity metadata, benchmark outcome validation and eval
assertions. It does not modify teammate orchestration, schemas, computation, policy, security or deployment.

The GitHub connector could not access this repository; authenticated local `gh` supplied read-only
PR metadata. Latest open Security PR #11 is at `c6aafeb82dd6d5f25735275633f8473bb7d9652e`; GitHub
reports MERGEABLE / CLEAN. Its newest commit merges #14's rounding.
There are no additional Intake/memory changes between the previously inspected `4a11024` and that
head. Its description and test count are older than its code. It remains unmerged. The compatibility
check in [IRIS_PR_REVIEW_PACKET.md](IRIS_PR_REVIEW_PACKET.md) uses a temporary combined tree; it
does not change either working branch. Qiyan still owns integration and verification.

### Prioritized findings and disposition

1. P1: the partial-import guard saves progress before the next question.
   Removing the three-line guard in `src/agents/intake.py` makes the real-process test fail because
   saved `adjustments` is missing. Restoring it passes. Imported inventory/answers are committed
   before the first interactive interrupt. Five process launches verify recap, history, isolation,
   archived old line 26 and new source identity/time. Assertions now also check the adjustment's
   downstream worksheet, income, taxable income, tax and refund against literal expected amounts.
2. P2: invalid classifier output no longer counts as correct. `classify_with_model()` safely maps bad
   JSON/unknown reasons to `uncertain`; the harness previously counted that as correct on every item.
   Four new ON/OFF regression instances failed before the fix. Validity is now recorded as a boolean
   in sanitized response metadata; `correct` requires valid output and the expected reason. Safe
   taxpayer handoff is retained. Both CLI modes reject wrong outcomes, invalid output and missing
   usage. Happy-path doubles inspect item order, context size, session summary and model configuration.
3. P2: readiness evals now check the saved answers and handoff fields. The four shared gate cases formerly
   checked only a generic uncertainty pause. New `expect.answers` and `expect.escalation_evidence`
   checks require retained confirmed values and the relevant missing-consumer fields. Eight injected
   data-loss/wrong-ticket variants fail with these assertions; disabling the assertions makes all
   eight broken variants pass. Correction/drift cases also check confirmed values. The staff test
   now accepts the next real answer after recovery and verifies progress to DOB.
4. P2: the current documentation has been corrected. Current status no longer repeats #11's obsolete conflict
   claim or limits runtime changes to three lines. Report/disclosure/demo and PR text distinguish
   fresh checks, prior history, generated drafts and external measurements.

### Cross-owner findings retained for team review

- P1: required in-scope outputs remain incomplete (Anupama/Max, coordinated by Vidhatri).
  `PENDING_DOWNSTREAM_FIELDS` and Computation show that dependent output and nonzero Schedule 2/3
  consumers are absent. A staff `continue` permits a draft that still ignores those fields; the
  four gate cases deliberately stop before that. These fields are in scope, and the missing consumers remain a software limitation. Keep it explicit in submission
  material; replace pause expectations with correct-output cases only when owner integration lands.
- P1: Review and security still need integration (Qiyan/Vidhatri). On a copied clean state,
  increasing lines 16 and 24 by $1 and reducing line 34 by $1 leaves
  `src/agents/review.py::find_problems()` returning zero problems: the current checks recompute
  totals but do not independently validate every tax result or source. PR #11 contains additional
  review/ingress protections. Those changes remain outside this branch; the temporary compatibility
  run is recorded in the PR packet. Intake redaction cannot prove raw resume checkpoints/traces are PII-free. Do not infer that guarantee
  from the W-2 schema or a passing suite.
- Vidhatri/Max: `run_batch` still exits unimplemented; the default graph does not wire model-backed
  Intake or apply its strategy switch. Full-path usage aggregation must include extraction calls.
  Team member with credits: perform live ON/OFF runs after integration and agreement on the
  professor's invoice/item ambiguity; record actual per-item counts and curve in `docs/metrics.md`.
  No tokens were requested and no live API calls were made. Synthetic usage is not measurement evidence.
- Max: actual MCP transport is absent (`src/tools.py` calls local functions); Docker persistent
  volume/container restart is not established by Python-process tests. Anupama/Juee/Max: QCD,
  line 25c/other direct-input contracts and the team's limited-adjustment wording need decisions.
  Juee: prior field-sensitive false alarms remain owner decisions, not new Iris policy work.

### Ten-item Iris completion assessment

| # | Status | Implemented and verified evidence | Remaining Iris action / external owner |
|---|---|---|---|
| 1 Shared schema/reducers | **Done within tested scope** | Existing shared contracts, strict checkpoint serialization, both merge orders, collisions and delayed retries pass (`test_merge_order.py`, `test_communication.py`). | Single Intake writer; no arbitrary multi-writer answer guarantee. |
| 2 SQLite/identity | **Partial** | Configurable path, opaque IDs, actual process restarts and separate-return isolation (`test_memory.py`, `test_iris_integration.py`). | Max: persistent volume and container restart. |
| 3 Prompt wording | **Partial** | Single-field prompts, glosses, drift tolerance and dignity checks; offline demo sequence exercised. | Juee: field-sensitive wording/false alarms; human accessibility review. |
| 4 Intake fields | **Partial** | Filing status, applicable DOB/blindness, dependents, inventory and direct totals collected; gate evals now verify retention. | Anupama/Max: downstream dependent/Schedule consumers; schema/policy owners: unresolved field contracts. |
| 5 Corrections/go-back | **Done for supported paths** | Answer history, retries, invalidation, literal recalculation outcomes, current and archived provenance pass. | Max: finished-return correction UI; broader natural-language coverage is finite. |
| 6 Resume/recap | **Done for CLI/API paths** | Real process exits, partial-import checkpoint, one recap and correct question verified. | Iris: show it in the recorded segment. |
| 7 Uncertainty recovery | **Done for tested paths** | Typed ticket, staff identity/note, reopened SQLite and successful next answer (`test_iris_integration.py`). | Team: demonstrate staff UI; Qiyan: ingress/security integration. |
| 8 Context strategy | **Partial; live evaluation external** | Actual classifier boundary, separate persisted ON/OFF threads, ten items, provider usage and failure validation tested offline. | Vidhatri/Max: normal/batch wiring and all-call accounting; team member with credits: live table/curve and outcomes. |
| 9 Focused tests | **Done for this follow-up** | 532 suite tests, 24 shared evals; negative controls expose checkpoint loss, invalid classifier scoring and weak gate assertions. | Not proof of live accuracy, full tax correctness or full credit. |
| 10 Docs/accessibility/disclosure | **Partial** | Report, disclosure draft, handoff, metrics and demo proofread; six design choices mapped; browser/sequence checks reproduced. | Iris: personally approve disclosure/report and record segment; team: consolidate roles/report/disclosures and 5-to-10 minute video. |

### Verification and PR readiness

- `origin/main` exported to a temporary directory: **504 passed, 7 warnings**. Initial follow-up before
  audit edits: **516 passed, 7 warnings**. Final suite: **532 passed, 7 warnings** (PyMuPDF/SWIG).
- `ANTHROPIC_API_KEY='' .venv/bin/python -m evals.run_evals`: **24/24**; eight Iris cases, including
  four readiness pauses rather than completed in-scope outputs.
- `ANTHROPIC_API_KEY='' .venv/bin/python -m evals.guardrail_eval`: **42/42** on the existing tuned
  development set, not independent accuracy evidence.
- Offline render plus browser smoke check: Enter/Space/click provenance and **390px** layout pass.
  The documented dialogue/staff/dependent sequence was scripted with SQLite reopenings in a temporary
  database. Separate subprocess tests establish actual process restarts. No video or screen-reader
  certification was produced.
- `git diff --check` and `git diff origin/main...HEAD --check`: clean. No requirements changed.
- Review preparation: the restart test now uses `format_interrupt()` to check the displayed prompt
  with both string interrupts and #11's typed questions. The temporary combined snapshot passes
  574 tests with seven warnings. See the PR packet for the tested head and overlapping files.

Iris's code and proofreading work is ready for a Draft PR. She still needs to review the generated
text personally and record her segment. The team dependencies above also remain open. Ready-to-paste PR title/description and the professor-rubric evidence
map are in [IRIS_PR_REVIEW_PACKET.md](IRIS_PR_REVIEW_PACKET.md). Generated disclosure/report text still
requires Iris's personal review; this audit does not represent it as approved.

## Prior offline follow-up — 2026-10-27

> Preserved historical snapshot. Its test counts, PR statuses and ownership blockers reflect that
> review; the 2026-10-28 audit above is the current assessment.

Reviewed against merged `main` at `5c44100` (PRs #6–10 and #12–14), the source and test
inventory, shared evals, policy, dashboard, report/disclosure material, and the supplied ten-item
checklist/professor brief. PR #11 was also inspected as **unmerged** work; its branch contains newer
Security integration than its PR description suggests. Work is on `codex/iris-offline-verification`;
the original `Iris-agent-memory` branch and local `main` are preserved.

| # | Requirement | Current status and evidence | Remaining dependency |
|---|---|---|---|
| 1 | Shared state/reducers | **Done within Iris scope.** Disjoint writes survive both orders; conflicting documents/tickets preserve candidates; delayed answer retries cannot undo corrections. Existing strict-serialization and reducer tests pass. | Single-writer answer history is not a parallel CRDT. |
| 2 | SQLite/identity | **Partial.** Actual process exits/restarts preserve confirmed answers, corrections, provenance and separate-return isolation. | **Max:** persistent container volume and real container restart verification. |
| 3 | Plain, single-question Intake | **Partial.** Existing dialogue/dignity tests pass; recap appears once on resume and omits DOB values/SSNs. Guardrails from Juee are integrated. | **Juee:** follow-up wording/false-alarm decisions below; human screen-reader review remains unverified. |
| 4 | Intake fields | **Partial.** Filing status, applicable DOB/blindness, inventory, dependents, adjustments/payments and schedule totals are collected/validated. New shared cases preserve nonzero unintegrated inputs and stop at staff. | **Anupama/Max:** dependent output and Schedule 2/3 consumers. **Anupama/Juee:** QCD, 25c/other direct-line contracts and the brief's limited adjustment set. No new tax semantics are invented here. |
| 5 | Corrections/drift/go-back | **Done for supported fields.** Named revisions, evidence archives, retraction and fresh review from #7 are integrated. New evals verify reviewed corrected values. A real-process test checks old line 26 is archived and new payments/provenance persist. | A finished-return correction UI is not present in the staff dashboard; graph/API reopening is available. |
| 6 | Resume/recap | **Done for CLI/API.** Fixed partial case-file imports losing the checkpoint/recap before the first unanswered question. New integration test uses five separate Python processes. | Final team recording remains separate from automated evidence. |
| 7 | Honest uncertainty/handoff | **Done for tested paths.** Existing staff session API sees the ticket, records volunteer identity/note and returns to the same question after reopening SQLite. Scope disclosure at a payment question has a shared eval. | Guardrail language coverage is finite. Security/Box-2b corrections remain in unmerged #11. |
| 8 | Context strategy | **Partial; live evaluation external.** Existing ON/OFF context/usage tests and new benchmark-CLI tests pass with explicit provider doubles. #13's removal of sampling parameters is covered. | **Vidhatri/Max:** default Intake/batch wiring and full-path usage accounting. **Team member with credits:** live ON/OFF measurements, agreed evaluation unit, table/curve. Iris is not expected to obtain more API tokens. |
| 9 | Focused regressions/integration | **Done for this offline change.** Baseline **504 passed**; final **516 passed**, same seven PyMuPDF/SWIG warnings. Shared evals **24/24**, including eight Iris-owned cases. | Passing offline checks does not establish live model quality or complete tax correctness. |
| 10 | Documentation/accessibility/disclosure | **Partial.** Current handoff, [report contribution](IRIS_REPORT.md), Iris disclosure draft, corrected implementation notes and [demo rehearsal](../demo/iris_memory_accessibility.md) are ready. Keyboard/visible-provenance/mobile browser smoke check passed. | **Iris:** personally proofread the disclosure/report and perform the demo segment. **Team:** assemble and record the 5–10 minute video; final human accessibility review. |

### What changed, why, and how it was verified

- **Checkpoint before asking.** Partial case-file imports accumulated validated answers locally, then
  called `interrupt()` before returning them. A restart therefore had no saved answers to recap.
  `src/agents/intake.py` now returns those imports before the interactive pause. The regression first
  failed with a missing saved `adjustments` answer, then passed after the three-line guard/comment.
- **Verify the result of a correction.** Eight additions to `evals/cases.json` use the existing real
  graph/runner. The real-process test in `tests/test_iris_integration.py` checks correction history,
  a single recap after resume, line-26 source identity/time, archived old calculations, recalculated
  total payments and thread isolation. No production graph or tax module was replaced.
- **Exercise the benchmark entry point offline.** Two tests in `tests/test_memory.py` run both CLI
  modes using a provider double that rejects sampling parameters. Outputs go to temporary files.
  Synthetic usage checks verify plumbing only; nothing is copied into `docs/metrics.md` as a result.
- **Staff recovery uses the existing interface.** A second integration test opens a new SQLite
  connection/graph, resolves uncertainty through `Sessions.resolve()` and verifies the unfinished
  question and confirmed filing status. This is API integration evidence, not another process test.

Verification commands:

```bash
.venv/bin/python -m pytest -q
ANTHROPIC_API_KEY='' .venv/bin/python -m evals.run_evals
ANTHROPIC_API_KEY='' .venv/bin/python -m evals.guardrail_eval
ANTHROPIC_API_KEY='' .venv/bin/python -m src.render --case data/fixtures/skeleton_case.json --output output/iris-offline-draft.html
SILVERFILE_BROWSER='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' .venv/bin/python tests/check_draft_browser.py output/iris-offline-draft.html
```

The guardrail development set remains **42/42**, a reused/tuned set rather than a new independent
accuracy estimate. The browser check verifies Enter/Space/click disclosure, visible provenance and
390px layout; it does not certify screen-reader accessibility. The first baseline attempt lacked
FastAPI; installing the existing requirements with `uv pip install --python .venv/bin/python -r
requirements.txt` resolved collection. No dependency specifications changed. No live API was called.

### Proofreading and owner follow-ups

Read-only probes against current `src/guardrails.py` reproduced these existing #9 review points:

| Reply | Observed result | Decision needed |
|---|---|---|
| `No, I don't think my son is going to claim me` | `advice_request`, rule `decision_about_tax` | **Juee:** false-alarm handling. Intake's yes/no parser also currently requires a short `no`; removing the guardrail match alone would still re-ask. |
| `Yes, she itemizes` | `out_of_scope`, rule `itemized` | **Juee:** coordinate field-aware handling so the answer can be recorded and Rules can make the policy escalation once. |
| `He can't talk right now, I'm his wife` | `exploitation_concern`, rule `cant_come_to_phone` | **Juee:** decide/document how joint filers and stated authority should be handled. This probe does not adjudicate authority. |

Iris can review #13's narrow `memory.py` change locally: both benchmark CLI modes are now covered
against accidental reintroduction of sampling parameters. No GitHub review/comment or teammate
message was posted. The #9 review request is still a human follow-up, even though #9 already merged.

PR #11's latest inspected branch (`4a11024`) contains field-aware ingress, staff recovery and tax-error
boundaries, but is unmerged and GitHub reports conflicts. **Qiyan** owns resolving/integrating those
changes; Iris should not recreate them. **Max** explicitly reports work on the actual MCP server in
#14's discussion. The current tools still call local Python functions. Docker runtime files are absent
from merged `main`. These are concrete team follow-ups, not additional Iris feature work.

## Historical implementation report — 2026-10-25

> Historical report from before PR #6 review. Current review dispositions and verification are in
> the current review above and [PR6_REVIEW_FIXES.md](PR6_REVIEW_FIXES.md). Statements below about
> local-only commits, absent policy/vision/retraction, stubs and older test counts are historical.

Date: **2026-10-25**. The user authorized following the supplied Iris handoff; its team checklist was
kept separate from the professor's assignment text. The assignment defines acceptance, including its
no-advice/no-filing constraints. This report does not claim that all professor deliverables are complete.

The initial checkout was clean on `main` at `aa2168c`. Remote refs were refreshed, then the absent
`feat/iris-agent-memory` branch was created from `origin/main` at `5a1ca95` **before any source edits**.
All changes and local commits are on the feature branch. Local `main` was not modified, committed,
pushed or merged. Nothing was pushed. No teammate source module was rewritten.

## Ten-item completion report

Existing behavior counts below only where exercised. `partial` means the local contribution works but
an explicit acceptance/integration/demo requirement remains; it does not mean a complete tax system.

| # | Checklist item / status | Verified contribution after the four-defect fixes | Remaining dependency |
|---|---|---|---|
| 1 | Shared state — **done within Iris scope** | Existing shared schemas retained; disjoint document merges and conflicts tested. `merge_answers` orders confirmations before deduplication, so replay of a previously suppressed `single` cannot undo newer `mfj`. Equal-time contradictory confirmations fail explicitly. `current_answers` also handles legacy unordered history. | Answers still have one writer; this is not a parallel CRDT. No teammate schema was changed. |
| 2 | SQLite / identity — **partial** | Existing configurable SQLite persistence, opaque ids, strict serialization, real process restart and separate-thread isolation remain passing. | **Max:** persistent Docker mount and real container-restart verification. |
| 3 | Prompts / wording — **partial** | One field per question, plain filing-status names/glosses, separate dependent questions, drift handling and recap remain verified. Per-turn disclosure checks run before accepting a field or structured correction. | **Juee:** wording/policy approval; final UI accessibility and recorded demo remain unverified. |
| 4 | Intake fields — **partial** | Existing filing status, DOB/blindness, dependent, inventory, adjustments and payment collection retained. A complete valid `123456789` payment now passes, including text/structured corrections; labelled identifiers and dashed SSNs fail monetary validation. Requested SSNs still use the shared 900-series validator. | **Max/Anupama/Juee:** downstream Schedule 2/3, dependent and scope-field consumers. Positive unsupported values still pause. Full remaining direct-input coverage, including QCD/25c contracts, and the brief's limited adjustment set remain unresolved; no new fields were added in this fix pass. |
| 5 | Corrections / go-back / revisions — **partial** | Delayed retries no longer supersede corrections. Review requests for lines 10/26 or an existing explicit `intake_revisit` target re-ask the field and are consumed only after confirmation. Going back to another field preserves the original line request. Unsupported targets are removed from the routing queue and handed off as typed uncertainty with the dependency recorded, not looped. Unchanged confirmations preserve the review bound. | **Vidhatri/Anupama:** generic typed revision-field targeting, extraction retraction/versioning, and issue epochs. Post-extraction inventory edits still pause safely. |
| 6 | Resume / recap — **done** | Existing multi-process restart, retained confirmed answers, recap, correct pending question, retry behavior and thread-isolation tests still pass. | No new memory/resume blocker identified for these four fixes. |
| 7 | Honest uncertainty / disclosure handoff — **done for tested paths** | Existing uncertainty/staff recovery retained. Foreign income/accounts, listed unsupported topics, and explicit 1099-R box-2b disclosures route through the existing `out_of_scope` / `1099r_taxable_not_determined` catalogue entries and `escalate()` helper, independently of the requested field. A simple explicit denial does not count as an affirmative disclosure. | No separate Juee scope-catalogue implementation exists in this checkout. The lexical notices mirror assignment §3.3 and do not evaluate tax rules. **Juee** still owns authoritative policy/wording and broader natural-language validation; live classifier quality is unmeasured. |
| 8 | Context-window strategy — **partial; live measurement blocked** | Existing selective-recall boundary, OFF baseline, actual provider-usage logging and ten-item persisted-thread harness remain tested with provider doubles. Only the classifier's allowed shared escalation names were updated in this pass. | **Max/Vidhatri:** normal model/batch wiring; external credentials/model access; team agreement on the invoice/item ambiguity. **No live token measurements, flat-curve result or complete end-to-end benchmark.** |
| 9 | Merge / focused regressions — **done** | **74 focused tests pass**, covering all **39 additional regression instances** plus existing Intake/reducer tests. Complete suite: **126 passed**, 7 existing warnings. Restart, resume, corrections, escalations, isolation, pathological loop guard and bounded review remain passing. | No failing tests remain in the current suite. Provider-double usage is not benchmark evidence. |
| 10 | Documentation / accessibility / disclosure — **partial** | This ten-row report and Iris implementation notes reflect the four fixes, revision targeting and the field-aware security boundary. Existing demo rehearsal and disclosure contribution remain available. | **Team report owner/Max/Vidhatri/Juee:** incorporate material and record/verify the required 5–10 minute team demo. No final video/report or UI audit claimed. |

## Verified environment and commands

The repository requirements installed successfully into the ignored `.venv` with Python 3.13.2.
Relevant installed versions: LangGraph 1.2.17, langgraph-checkpoint-sqlite 3.1.2, Pydantic 2.14.1,
pytest 9.1.1 and PyMuPDF 2.0. No dependency constraints were changed.

- Baseline before implementation: `.venv/bin/python -m pytest -q` → **47 passed**, 7 warnings.
- Prior contribution suite before this fix pass: **87 passed**, 7 warnings.
- All focused Intake/reducer tests: `.venv/bin/python -m pytest tests/test_merge_order.py tests/test_intake.py -q` → **74 passed** (includes all 39 new regression instances).
- Complete suite after fixes: `.venv/bin/python -m pytest -q` → **126 passed**, 7 pre-existing warnings.
- New behaviors were exercised as failing tests before implementation and rerun after fixes.
- `git diff --check` → no whitespace errors.
- ON attempt: `.venv/bin/python -m src.memory --batch --thread-id iris-context-on` → **exit 1, missing API key**.
- OFF attempt: `.venv/bin/python -m src.memory --batch --no-context-strategy --thread-id iris-context-off` → **exit 1, missing API key**.

The fixture edits add explicit intake answers only. Existing document amounts, images and ground truth
were preserved. The seven PyMuPDF SWIG warnings were also present in the unmodified baseline.

## Concrete teammate interfaces and blockers

**Anupama:** retain `IntakeAnswer` / `Dependent` / `DocumentRef` and the existing provenance contracts.
New effective answers are available through `current_answers(state)`: `dependent_count`, `dependents`
(a list of shared `Dependent` models), `taxpayer_claimed_dependent`, `dual_status_alien`, `spouse_itemizes`
(asked for MFS), `schedule2_total_tax`, `schedule3_nonrefundable_credits`, and `schedule3_other_payments`.
Every answer records `entered_by` and `answered_at`; downstream direct-value provenance must use them,
as the existing computation already does for adjustments and estimated payments. Map dependents to the
form and agree with Vidhatri on safe extracted-record replacement/retraction. No schemas were changed.

**Vidhatri:** keep the existing router, six agents, join, bounded review cycle and staff resume hook.
Intake advances `guard_window_start` only after a confirmed reply or committed model-assisted re-ask;
the pathological loop-guard test still passes. Corrections queue existing `RevisionRequest`s for
Rules and Computation, set `review_status=pending`, `review_passes=0` and `status=in_progress`.
Confirm this progress contract. Add an input/document version or issue epoch so new evidence does not
inherit an old human approval; add safe retraction when an extracted document is removed/replaced.
Until that exists, inventory changes after extraction pause and preserve the old inventory. Wire the
`make_intake` factory through the existing graph override; the current `use_context_strategy` argument
alone remains a no-op. Review-to-Intake now supports `line="10"` → `adjustments`, `line="26"` →
`estimated_payments`, or an explicit existing `intake_revisit` field. The request remains pending until
that field is confirmed; a different go-back answer does not consume a line-targeted request. An
unchanged confirmation marks Review pending without resetting its pass count. Unknown/ambiguous targets
create an `uncertain` ticket with dependency `RevisionRequest.field / Intake targeting contract` and
are removed from the routing queue; unrelated requests are preserved. Staff resolution still uses the
existing human node. A staff continue is not an implementation of the missing targeting interface.
Agree a generic typed field contract with **Anupama** before expanding this mapping.

**Max:** mount, for example, a persistent `/data` volume and configure
`SILVERFILE_DB_PATH=/data/silverfile.sqlite`; verify real container restart. Wire `run.py --batch` to the
benchmark, configure the optional model factory with `not args.no_context_strategy`, and add a configured
API key/model through the team's secret mechanism. The default CLI currently requires a key even for
structured Intake/staff resolution; direct API demo commands work without it. The benchmark CLI is
available now under `python -m src.memory --batch`. Computation must source and include the new Schedule
2/3 amounts before any nonzero cases can count as correct; remove the matching `PENDING_DOWNSTREAM_FIELDS` gate only with integration tests. The current tax_math functions return stub
zeros, marked `stub=True`; passing memory tests is not evidence of tax correctness. Connect the finished-
return reopen interface and stale-review status to the dashboard. UI should not display pending stale
lines as a new approved draft.

**Juee:** provide `data/policy.md`, approved phrasing and final scope checks for the newly collected
`taxpayer_claimed_dependent`, `spouse_itemizes`, `dual_status_alien`, dependent and schedule inputs.
Intake records those answers without deriving boxes, eligibility or deductions. Positive unsupported scope inputs pause on an uncertainty ticket pending your integration; replace the matching readiness gates only with tested owner logic. It reuses the existing
shared escalation reason catalogue (`src/schemas.py`) and helper (`src/escalation.py`) and keeps
advice/exploitation detection. No separate scope catalogue/policy file is available to import here.
The new per-turn lexical check notices the assignment's unsupported-topic disclosures, including foreign
income/bank accounts and explicit 1099-R taxable-not-determined statements. It routes to the existing
human handoff before field parsing; it does not calculate tax, choose schedules, or decide eligibility.
Juee should supply the authoritative policy/vocabulary interface for future coverage. Default detection
remains lexical;
the optional model fallback's live recall/precision has not been evaluated. Existing Rules uses a $500
wage-conflict tolerance while the brief says unresolved conflicts escalate; reconcile that policy.
Review the existing ability to “continue” past a 1099-R box-2b escalation without actually making the
return in scope. Those are existing teammate-owned behaviors, not fixed by this contribution.

**Qiyan (Zhai Qiyan):** the shared 900-series SSN type is reused for requested dependent fields. Intake
sanitizes unsolicited SSNs from its own answers/tickets/model context and omits typed dependent/DOB
records from model summaries. However, LangGraph may persist raw resume commands **before Intake
sanitizes them**. Provide ingress validation/redaction and trace policy; Max must apply it before
`Command(resume=...)`. No claim is made that SQLite pending writes or all external logs are PII-free.
The SQLite checkpointer is not an authentication or encryption boundary.

Field-aware input contract for Qiyan: only a **complete, valid monetary literal in a monetary field**
is interpreted as money even when it contains nine digits (`123456789`, numeric or string). The same
applies to a recognized correction targeting a money field. Bare digits alone cannot reveal whether a
person intended an SSN; context is explicit here. `123-45-6789`, `My SSN is 123456789`, and similar
labelled/dashed identifiers do not parse as money and remain redacted in Intake-owned payloads.
Unsolicited nine-digit integer values in structured turns are now redacted too. Requested dependent
SSNs continue through the existing 900-series schema, with no raw-text copy. A separately redacted turn
is always used for escalation evidence/model context; generic redaction itself was not relaxed for
monetary strings. The typed monetary value remains available for provenance and computation, while
its SSN-shaped raw-text copy may be redacted. Qiyan/Max must preserve this field-aware distinction when
adding ingress protection before `Command(resume=...)`; their modules were not modified.

**Team / instructor clarification:** §4.5 says “invoices” in a tax-return assignment and references a
scenario absent from §4.2. The implemented harness explicitly uses synthetic Intake classifier items.
Agree on the graded item and run the actual complete model-calling path once integration is ready.
Also clarify the “limited set” of Schedule 1 adjustments rather than inventing tax policy.

## Four-defect fix verification

1. **Delayed retry:** exact `single`, repeated `single`, newer `mfj`, delayed old replay sequence stays
   `mfj`; late-arriving history is ordered; contradictory same-time confirmations are rejected.
2. **Disclosure:** assignment-listed unsupported topics stop at filing status; a foreign-income reply
   cannot be accepted as a dependent's name; disclosures in structured metadata are checked before the
   proposed field answer. Explicit 1099-R uncertainty uses its existing specific reason.
3. **Revision:** line-targeted and explicitly named revisions are confirmed/consumed, unrelated requests
   survive, unknown/ambiguous targets produce an explicit human handoff instead of `loop_guard`, and
   repeated unchanged confirmations reach the existing review limit. Go-back does not complete a
   different pending line request.
4. **Money/PII:** large valid amounts survive field validation and retain direct-input provenance;
   labelled/dashed SSNs are rejected as amounts, numeric unsolicited IDs are redacted, and existing
   fake-SSN/schema, restart, resume and isolation tests still pass.

Only Iris-owned state, memory, Intake, their tests, and Iris documentation were changed in this pass.
All commits remain local to `feat/iris-agent-memory`; no push, merge or edit to `main` occurred.
Live context-window evaluation remains incomplete.

## AI-use disclosure contribution for the report owner

Iris used OpenAI Codex to inspect the existing SilverFile repository and supplied assignment, identify
reusable schemas, checkpointing and orchestration interfaces, and implement changes to shared memory
reducers and Intake. Codex generated and revised focused tests for parallel writes, answer history,
corrections, SQLite process restarts, uncertainty handoff, selective context and token-usage plumbing,
and ran the complete test suite. It also drafted the Memory/Accessibility notes, benchmark instructions
and this handoff. The work preserved teammate-owned agent/orchestration modules and used synthetic data.
The optional model classifier and benchmark were tested with explicit provider doubles; no live model
token measurements were obtained because credentials were not configured. Tax computations, policy
citations, production security, Docker deployment and the final team demo still require their owners'
implementation or review. The team should review and adapt this paragraph before including it in the
shared disclosure/report; no teammate's review or authorship is asserted here.
