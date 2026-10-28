# Agent Memory and accessible Intake (Iris)

This report contribution was checked on 2026-10-28 against merged `main` at `5c44100` and the
follow-up now on `Iris-agent-memory`. Iris still needs to review it personally before the team uses
it in the final report. Test evidence and owner dependencies are in [IRIS_HANDOFF.md](IRIS_HANDOFF.md).

## Memory and state

Each return has an opaque thread ID that cannot contain an SSN. SQLite stores the typed LangGraph state,
and the taxpayer driver and staff session API can use the same configured database path. Intake
saves accepted answers before asking the next question. The partial case-file fix extends that
behavior to imported answers: if a case is missing a field, its validated answers are saved before
Intake pauses to ask for it. Another process can then resume with those answers in its recap.

Intake records answer history and derives the current value of each field. It orders confirmations
by time before collapsing repeated values, so retrying an old answer cannot undo a later correction.
An unchanged answer adds no effective change. Contradictory values confirmed at the same time fail
explicitly. This history assumes a single Intake writer; concurrent answer editing has no general
guarantee.

Parallel extraction branches merge documents by ID. Disjoint writes survive in either order, and
conflicting records remain available for staff to choose between. An identical retry cannot reopen
a resolved escalation. Tests cover both merge orders and conflicts.

Corrections use Anupama's shared revision and evidence contracts with Vidhatri's routing. Changing a
confirmed input archives prior work, clears stale results and requests fresh Rules and Computation
work before Review checks the replacement draft. Inventory changes use the existing retraction
interface. Intake records inputs without doing tax arithmetic, selecting tax rules or giving advice.
The process-restart test checks updated line-26 provenance and total payments, archived old amounts,
persistence after another exit, and isolation from a second return.

## Accessibility and dignity

| Choice from brief §4.3 | Behavior and demonstration |
|---|---|
| One question at a time | Dependent name, relationship and required synthetic SSN are separate turns. The dependent eval pauses when collection finishes because downstream output is incomplete. |
| Plain language | Filing-status choices use full names. Schedule and payment prompts include short explanations. Dialogue tests check length, jargon and internal-name leakage. Juee owns policy and wording decisions. |
| Repetition and drift | An unrelated reply returns to the unfinished question. `go back to adjustments` preserves other inputs. A correction keeps history and triggers fresh calculations. |
| Resumability | Reopening the same thread after a process exit gives one short recap and continues at the unanswered question. Ordinary retries do not repeat the recap. |
| Honest uncertainty | "I'm not sure" creates a typed volunteer ticket. Staff resolve it through the session API, and the taxpayer returns to the original question with earlier answers preserved. |
| Minimize unnecessary PII | Intake never asks for the taxpayer's SSN. Required dependent SSNs use the assignment's synthetic range. Recaps omit birth-date values and SSNs; model summaries exclude typed dependent, DOB and document records. |

The [demo rehearsal](../demo/iris_memory_accessibility.md) exercises these choices without model
credentials. Browser smoke checks cover keyboard disclosure, visible source details and the HTML
draft at a narrow viewport. Screen-reader compatibility still needs human review. The team's required
5-to-10-minute video must show at least four of the choices above.

## Context strategy

Selective recall sends the current classifier item and a small allowlisted summary. The OFF baseline
also sends earlier classifier dialogue. Both paths redact SSNs and record provider-reported input
usage by call ID. A response without usage fails instead of substituting a token estimate.

The harness processes ten sequential synthetic Intake items in one persisted thread, with separate
fresh threads for ON and OFF. It checks the expected outcome for each item. Offline tests cover the
context boundary, usage propagation, thread separation and both CLI modes, including rejection of
unsupported sampling parameters.

The audit found that malformed or unsupported model output could count as correct because Intake
converted it to the expected `uncertain` fallback. The fix preserves the volunteer handoff and
records whether the model output was valid. Invalid output now fails the benchmark's outcome check,
as do wrong classifications and missing usage. Token values from test doubles check this plumbing.
No live token measurements or measured curve improvement are available.

Vidhatri and Max still need to connect the normal graph and batch path and account for other model
calls. The team also needs to resolve the assignment's invoice/item ambiguity. A team member with
available credits must then run the live comparison; Iris has exhausted her API allowance.

## Verification and remaining work

Fresh execution of the merged baseline passed 504 tests. The incoming follow-up passed 516; after
the audit fixes, 532 tests pass with the same seven PyMuPDF/SWIG warnings. All 24 shared offline evals
pass, including eight Iris cases. The four readiness cases check retained answers and the relevant
handoff fields. Fault tests confirm that lost inputs and unrelated pauses cause them to fail.

Removing the partial-import guard reproduced the missing saved answer, and restoring it passed.
Invalid-output benchmark regressions also failed before their fix. The restart/correction test uses
five separate Python processes with SQLite. The staff-recovery test reopens the database and graph
through the production session interface. All inputs are synthetic; no live model request was made.

Dependent rendering and nonzero Schedule 2/3 consumers remain incomplete. Their evals verify a staff
pause; correct finished returns still need the owners' implementation. QCD, line 25c and other direct
inputs, plus the brief's limited adjustment set, need schema and policy decisions. Max owns the actual
MCP transport and Docker volume/restart verification; the merged tax functions currently run locally.

Qiyan's ingress and checkpoint protections are in unmerged PR #11. Intake redaction alone cannot
establish that raw resume payloads or external traces are free of PII. A fault probe also showed that
current Review accepts a coherent $1 corruption of tax, total tax and refund. Its total checks do
not validate every tax result or source. Qiyan and Vidhatri own that gap. These limits need to remain
visible in the team's account of system completion.
