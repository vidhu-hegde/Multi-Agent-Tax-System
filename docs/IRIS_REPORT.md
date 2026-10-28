# Report contribution: Agent Memory and accessible Intake (Iris)

Draft for Iris's personal review, independently audited on **2026-10-28** against merged `main` at
`5c44100` and the offline follow-up on `codex/iris-offline-verification`. This is material for the
team's report, not a claim that the full report or recorded demo is complete. Evidence and dependencies are in
[IRIS_HANDOFF.md](IRIS_HANDOFF.md).

## Memory and state

SilverFile identifies each return with an opaque, non-SSN thread ID and persists typed LangGraph
state with SQLite. The configured database path can be shared by the taxpayer driver and the staff
session API. Committing accepted answers before the next question lets another process resume the
same return. The offline follow-up also fixes partial case-file imports: validated imported answers
are saved before Intake interrupts to request the first missing field. Without that checkpoint, a
restart could not summarize the answers already supplied by the fixture.

Intake keeps confirmed answer history and derives a current value for each field. Confirmation time
orders events before repeated effective values are collapsed, so an old retried event cannot reverse
a newer correction. Repeating the same effective answer does not create another effective change.
Contradictory events with the same confirmation time fail explicitly. Intake has one answer writer;
this is not a claim of arbitrary concurrent answer editing.

Independent extraction branches merge documents by ID without dropping disjoint writes. Competing
records are retained as conflict candidates for explicit staff selection. A resolved escalation is
not reopened by an identical retry. These choices preserve evidence rather than silently selecting
whichever concurrent write arrives last. Tests execute disjoint and conflicting merges in both orders.

Corrections use Anupama's shared revision/evidence contracts and Vidhatri's existing routing. A changed
confirmed input archives prior work, clears stale results and requests Rules/Computation again before
Review passes the replacement draft. Inventory edits use the integrated retraction interface. Intake
records inputs; it performs no tax arithmetic, chooses no tax rules and gives no advice. The new
real-process test verifies updated line-26 provenance and total payments, old amounts retained in the
audit archive, persistence after another process exit, and isolation of another return.

## Accessibility and dignity

| Deliberate choice from brief §4.3 | Behavior and demonstration |
|---|---|
| One question at a time | Dependent name, relationship and required synthetic SSN are separate turns. The shared dependent eval ends at the honest downstream-integration pause. |
| Plain language | Filing-status choices include full names; schedule/payment prompts include short explanations. Dialogue tests check length, jargon and internal-name leakage. Juee owns policy/wording decisions. |
| Repetition and drift | An unrelated reply returns to the unfinished question. `go back to adjustments` preserves other inputs; a correction retains history and triggers fresh calculations. |
| Resumability | Close the taxpayer process, reopen the same thread, hear one concise recap and continue at the unanswered question. Ordinary retries do not repeat that recap. |
| Honest uncertainty | “I'm not sure” raises a typed volunteer ticket. Staff resolve it through the existing session API; the taxpayer resumes the original question with earlier answers preserved. |
| Minimize unnecessary PII | There is no taxpayer SSN question. Required dependent SSNs must use the assignment's synthetic range. Recaps omit actual birth dates and SSNs; model summaries exclude typed dependent/DOB/document records. |

The [demo rehearsal](../demo/iris_memory_accessibility.md) makes these choices reproducible without
model credentials. Browser smoke checks also verify keyboard disclosure, visible source details and
a narrow viewport on the integrated HTML draft. Automated checks are not a screen-reader audit and
do not replace showing at least four choices in the required 5–10 minute team video.

## Context strategy

Selective recall supplies the current classifier item and a small allowlisted summary. The OFF
baseline additionally includes earlier classifier dialogue. Both paths redact SSNs and record actual
provider-reported input usage by call ID; missing usage fails rather than substituting a token estimate.
The existing harness processes ten sequential synthetic Intake items in one persisted thread per
run, with separate fresh threads for ON/OFF and an expected-outcome check for every item.

Offline tests verify the context boundary, usage propagation, separate threads, both benchmark CLI
modes and rejection of unsupported sampling parameters. The audit also found and fixed a false-positive
outcome check: malformed or unsupported model output still safely flags a volunteer, but now counts
as an incorrect benchmark classification. Wrong outcomes and missing usage fail the CLI. Test-double
token values are synthetic plumbing checks. **No live token measurements or materially flatter measured curve are claimed.**
Normal graph/batch integration, complete accounting of other model calls and the assignment's
ambiguous invoice/item unit require team coordination. A team member with available credits must
perform live execution; Iris's exhausted API allowance is not an unfinished coding task.

## Verification and remaining limits

Fresh execution of the merged baseline passed **504 tests**; the incoming follow-up passed **516**.
After this audit, **532 tests pass**, with the same seven PyMuPDF/SWIG warnings, and **24/24 shared
offline eval cases** pass, including eight Iris-owned additions. The four readiness cases now assert
retained confirmed values and the relevant handoff fields; fault injection verifies they reject data
loss and unrelated pauses. The partial-import regression independently failed with its guard removed
and passed after restoration. Invalid-output benchmark regressions also failed before their fix.
The new restart/correction test uses five separate Python processes with SQLite; a separate staff-recovery test reopens the
database/graph through the production session interface. All inputs are synthetic and no live model
request was made.

Dependent rendering and nonzero Schedule 2/3 consumers remain incomplete; the new evals expect a staff
pause, not a correct finished dependent/schedule return. QCD, line 25c/other direct-input contracts and
the brief's limited adjustment set need the relevant schema/policy owners. Real tax functions are
merged, but the actual MCP transport is still Max's work. Docker volume/restart verification is also
external to this contribution. Qiyan's ingress and checkpoint protections are in unmerged PR #11;
Intake-level redaction alone cannot establish that raw resume payloads or external traces are free
of PII. A read-only fault probe also showed that current Review accepts a coherent $1 corruption of
tax/total tax/refund; its total checks do not prove every tax result or source is correct. Qiyan and
Vidhatri own closing that gap. The report must retain these limits when describing overall completion.
