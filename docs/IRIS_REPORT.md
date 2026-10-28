# Agent Memory and accessible Intake (Iris)

This contribution describes PR #15 integrated with main at `1bfd9e8` on 2026-10-28.
Verification details are in [IRIS_HANDOFF.md](IRIS_HANDOFF.md).

## Memory and state

Each return has an opaque thread ID that cannot contain an SSN. SQLite stores typed LangGraph state,
and the taxpayer driver and staff session API share the configured database. Intake saves accepted
answers before asking the next question. Partial case-file imports also checkpoint their validated
answers before pausing for a missing field, so another process can resume with those answers in its
recap. The Docker configuration now mounts the shared database on a persistent volume.

Intake keeps answer history and derives the current value of each field by confirmation time.
Replaying an old answer cannot undo a newer correction. An unchanged answer adds no effective change;
contradictory confirmations at the same time fail explicitly. This assumes a single Intake writer.
Parallel extraction branches merge documents by ID. Disjoint writes survive either merge order;
conflicting versions remain available for staff to choose between.

Corrections use Anupama's revision/evidence contracts and Vidhatri's routing. A changed input archives
prior work, clears stale results and requests fresh Rules and Computation work before Review checks
the replacement draft. Inventory replacement uses the shared retraction interface. Intake records
facts without calculating tax, choosing tax rules or offering advice. The process-restart test checks
literal recalculated tax/refund values, payment provenance, archived amounts and another return's
isolation. Finished-return corrections are available through the graph API; dashboard correction
controls remain separate work.

## Accessibility and dignity

| Choice from brief section 4.3 | Behavior and demonstration |
|---|---|
| One question at a time | Dependent name, relationship and required synthetic SSN use separate prompts. Dependent output is still incomplete, so the collection case pauses afterward. |
| Plain language | Filing-status choices use full names; Schedule/payment prompts include short explanations. Dialogue tests check length, jargon and internal-name leakage. Juee owns final wording decisions. |
| Repetition and drift | An unrelated reply returns to the pending question. Go-back preserves other fields; a correction retains history and requests fresh calculation. |
| Resumability | Restarting with the same ID gives one short recap and continues at the unanswered question. Ordinary retries do not repeat the recap. |
| Honest uncertainty | Uncertainty creates a volunteer ticket. Staff resolve it through the shared API, and the taxpayer returns to the original question with earlier answers preserved. |
| Minimize PII | Intake never asks for the taxpayer's SSN. Dependent SSNs use only the assignment's test range. Recaps omit DOB values and SSNs, and model summaries omit typed dependent/DOB/document records. |

The [rehearsal](../demo/iris_memory_accessibility.md) exercises these choices without model credits.
Keyboard/click provenance and narrow-screen checks supplement the dialogue tests. Screen-reader
compatibility has not been validated.

## Context strategy

Selective recall sends the current classifier item and a small allowlisted session summary. The OFF
baseline also sends earlier classifier dialogue. Both paths redact SSNs and record provider-reported
input usage by call ID; missing usage fails instead of using an estimate. Separate fresh ON/OFF
threads each hold ten sequential synthetic Intake items, with outcome validity checked per item.

Malformed or unsupported model output formerly counted as correct through the `uncertain` fallback.
The follow-up keeps the safe volunteer handoff but records whether output was valid, so invalid
output fails the benchmark. Provider-double tokens verify logging only. Iris made no live model
calls or token measurements.

Vidhatri recorded ten Intake items per return thread as the team's working interpretation of the
brief's ambiguous invoice wording, proposed multi-turn items and offered to run the live comparison.
Max has proposed batch wiring and a results-table generator in [PR #21](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/21). Those changes and
the multi-turn refinement still need integration; the normal graph currently uses deterministic
Intake. The team must record actual per-item counts, outcomes and a curve in `metrics.md`. This
classifier-only harness makes no claim to measure W-2 extraction or full-return usage.

## Verification and limits

Current main passed 649 tests. Combining it with the old #15 exposed nine failures: three Schedule
cases still expected pauses, and six fault-test instances relied on them. The repaired revision passes
674 tests with seven existing PyMuPDF/SWIG warnings and all 25 shared evals, in-process and through a
real local MCP server. The pinned Docker image also builds and passes 674 tests and all 25 MCP
evals. An isolated container-recreation check preserves partial imports, one resume recap and a
dashboard staff decision; it completes the typed clean return with a $2,455.50 refund without a model
key. Three new fault checks ensure that zeroed nonzero Schedule inputs fail the
evaluation even when the altered draft passes Review.

The eight Iris evals now cover corrections, go-back, drift/repetition, scope disclosure, dependent
collection and completed Schedule 2/3 outcomes. Only the dependent case retains a missing-output
pause. The SQLite regression uses five real Python processes; staff recovery uses the production
session interface after reopening the database.

MCP transport, Docker, Security/Review and Schedule 2/3 are now merged teammate contributions.
Vidhatri's #17 review records the keyed container restart Iris requested. Dependent output/credits,
line 17 and other direct-input/QCD contracts remain software or policy limits. Security tests cover
recognized SSN shapes and ingress boundaries; they do not establish production authentication,
encrypted storage or provider-side trace privacy.

The [team report](TEAM_REPORT.md) includes this material with team attribution and editable
Mermaid diagrams.
