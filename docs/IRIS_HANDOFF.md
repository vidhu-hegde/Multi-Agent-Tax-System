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

| # | Checklist item / status | Files touched and verified behavior | Evidence / remaining coordination |
|---|---|---|---|
| 1 | Shared state — **done** | `src/state.py`, `tests/test_merge_order.py`: existing shared contracts retained; parallel documents merge both ways; conflicting document/ticket keys fail; retries deduplicate; sequential derived-line updates remain supported. | Merge tests plus existing all-agent graph and strict serializer tests pass. No competing schema module. Answer history is single-writer, not a parallel CRDT. |
| 2 | SQLite / identity — **partial** | `src/memory.py`, `tests/test_memory.py`: configurable existing SQLite saver reused, opaque ids, SSN-shaped ids rejected at saver boundaries, same-return restart and thread isolation verified. | Three actual Python subprocess restarts pass. **Max** must mount a persistent Docker directory and keep `SILVERFILE_DB_PATH` inside it; Docker was not edited/tested. |
| 3 | Prompts / wording — **partial** | `src/agents/intake.py`, `tests/test_intake.py`, `tests/test_graph.py`: one field per prompt, full filing-status names, short explanations, no MAGI jargon, separate dependent questions. | Interactive and dependent tests pass. **Juee** must supply/sign off on policy wording; no `data/policy.md` exists on this base. Screen-reader/UI behavior and the final video remain unverified. |
| 4 | Intake fields — **partial** | `src/agents/intake.py`, both existing synthetic case JSON files, focused tests: filing status, spouse death, taxpayer/spouse DOB and blindness, dependency/scope inputs, dependent records, inventory, wages estimate, Schedule 1/2/3 direct totals and estimated payments are collected/validated. | Field and full graph tests pass. **Max/Juee/Anupama** must consume the new Schedule 2/3, dependent and scope fields; current downstream stubs do not. Nonzero/positive unintegrated inputs now pause safely instead of generating a draft that ignores them. The professor's “limited set” of adjustments is undefined; team confirmation remains required. |
| 5 | Corrections / go-back — **partial** | `src/agents/intake.py`, `src/state.py`, Intake/reducer tests: latest confirmed values plus history, repeated-answer deduplication, go-back, and typed Rules/Computation revision requests. | Finished-return payment correction re-runs Rules, Computation and Review and yields the corrected line. **Vidhatri/Anupama** must add extraction retraction/versioning and issue epochs. Post-extraction inventory edits currently pause safely without applying them. |
| 6 | Resume / recap — **done** | `src/agents/intake.py`, `tests/test_memory.py`, `tests/test_graph.py`: each accepted reply checkpoints before the next prompt; recap is built from confirmed values. | Multiple actual process stops/restarts retain values, preserve pending question, avoid duplicate history and isolate another thread. |
| 7 | Honest uncertainty — **done** | `src/agents/intake.py`, Intake/memory tests: existing `uncertain` ticket schema/catalogue/helper reused; volunteer wording; existing orchestrator/human node pauses and staff resumes. | Both existing escalation suite and persisted uncertainty pause/restart/resolution tests pass. Staff routing was not duplicated. Live classification quality remains unmeasured. |
| 8 | Context-window strategy — **partial; live measurement blocked** | `src/memory.py`, `src/state.py`, `src/agents/intake.py`, context tests, `docs/metrics.md`: optional actual model boundary with selective recall, OFF history baseline, provider usage logging, ten sequential persisted items per run, outcome checks. | Offline behavior tests pass. Both live commands exit 1: **no API key**. **Max/Vidhatri** must connect default model/batch hooks and obtain configured credentials/model access. Team must settle the brief's “invoices” ambiguity. **No real token counts or flatter-curve claim.** |
| 9 | Merge / focused tests — **done** | `tests/test_merge_order.py`, `tests/test_intake.py`, `tests/test_memory.py`, existing Intake portions of `tests/test_graph.py` updated for explicit new questions. | Full suite: **87 passed**, 7 pre-existing PyMuPDF SWIG deprecation warnings. Both orders explicitly exercised for disjoint typed documents and conflicts. Corrections, isolation, real restart, recap, uncertainty recovery and retry behavior pass. |
| 10 | Documentation / accessibility demo / disclosure — **partial** | `docs/IMPLEMENTATION_NOTES.md`, `docs/metrics.md`, this report and `demo/iris_memory_accessibility.md`: six deliberate §4.3 choices, evidence, demo commands, limitations and disclosure contribution. | **Max/Vidhatri/Juee** must integrate and record the 5–10 minute team demo. The **team report/document owner** must incorporate the Memory/Accessibility sections and disclosure below. No final report/video or live UI accessibility audit is claimed. |

## Verified environment and commands

The repository requirements installed successfully into the ignored `.venv` with Python 3.13.2.
Relevant installed versions: LangGraph 1.2.17, langgraph-checkpoint-sqlite 3.1.2, Pydantic 2.14.1,
pytest 9.1.1 and PyMuPDF 2.0. No dependency constraints were changed.

- Baseline before implementation: `.venv/bin/python -m pytest -q` → **47 passed**, 7 warnings.
- Final implementation suite: `.venv/bin/python -m pytest -q` → **87 passed**, 7 warnings.
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
alone remains a no-op. Review-to-Intake revisions without a named field are not a complete repair API.

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
escalation catalogue and keeps advice/exploitation detection. Current default detection is keyword-based;
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

**Team / instructor clarification:** §4.5 says “invoices” in a tax-return assignment and references a
scenario absent from §4.2. The implemented harness explicitly uses synthetic Intake classifier items.
Agree on the graded item and run the actual complete model-calling path once integration is ready.
Also clarify the “limited set” of Schedule 1 adjustments rather than inventing tax policy.

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
