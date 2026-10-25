# Iris Agent Memory / Intake completion and coordination report

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
