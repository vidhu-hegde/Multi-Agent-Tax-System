# Iris: Memory and Intake handoff

Updated 2026-10-28 after integrating `origin/main` at `1bfd9e8` into PR #15.
This replaces the older status reports; their test runs remain in Git history.

## Current result

The integrated revision passes **674 pytest tests** with seven existing PyMuPDF/SWIG warnings and
**25/25 offline evals**, both in-process and through a real local tax-math MCP server. The pinned
Docker image also builds and passes 674 tests and 25/25 MCP evals. No paid model
call or live token measurement was made for this follow-up. These checks cover the stated fixtures
and failure controls; they do not establish complete tax coverage or a grade.

Main now includes Security/Review (#11), MCP transport (#16), Docker (#17), package pins (#18), and
Schedule 2/3 output, outage recovery and the two graded walkthroughs (#19). The earlier notes that
these were absent are obsolete. The remaining dependent pause is intentional: dependent output is
still incomplete. Line 17 and dependent credits on line 19 are also unsupported.

## PR #15 review changes

- Merged current main. Kept `PENDING_DOWNSTREAM_FIELDS = ("dependent_count",)` and Intake's line
  mappings for 20, 23 and 31, together with main's dependent-only readiness tests.
- Resolved the documentation conflict with main's Schedule 2/3 behavior. Corrected the staff-dashboard
  attribution to Vidhatri and updated merged security ingress references in the Iris sections.
- Replaced three obsolete Schedule pause cases with completed-return cases. Each checks the confirmed
  input, affected lines, downstream totals/refund, `intake_complete` and successful Review.
- Retained dependent data-loss/wrong-ticket fault tests. Added three Schedule fault tests: replacing a
  nonzero confirmed total with zero must fail the eval, even if the altered return passes Review.
- Moved `current_answers` to the eval runner's imports. Folded useful review-packet material into this
  handoff and removed `IRIS_PR_REVIEW_PACKET.md`, as suggested by the reviewer.
- Updated the report contribution, disclosure draft, metrics coordination and demo instructions.
  The new five-page team-report draft is a local review artifact and has not been submitted for the team.

The follow-up's runtime behavior remains the partial-import checkpoint guard and classifier-validity
scoring. Computation, graph, Rules, Security, dashboard and deployment changes retain their owners'
attribution; integrating their commits does not transfer authorship to Iris.

## Ten-item completion assessment

| # | Requirement | Status and evidence | Remaining action / owner |
|---|---|---|---|
| 1 | Shared schemas and reducers | Done within tested scope. Existing contracts, strict serialization, both merge orders, disjoint writes, collision preservation and delayed retries pass. | Answer history assumes a single Intake writer. |
| 2 | SQLite and identity | Done for tested CLI/API paths. Opaque non-SSN IDs, configurable database, process restart and return isolation pass. Docker's shared persistent volume is merged. | Current isolated Docker restart and dashboard persistence pass; Vidhatri's keyed image-W-2 restart is recorded in #17. |
| 3 | Single-field, plain prompts | Partial. Dialogue/dignity tests, glosses, separate dependent questions and one recap pass. | Juee: field-sensitive language decisions; human screen-reader review remains. |
| 4 | Intake fields | Partial. Filing status, DOB/blindness, dependents, inventory and direct totals are collected. Schedule 2/3 totals now reach the draft. | Anupama / Vidhatri / Max: dependent output; policy/schema owners: remaining direct-input/QCD contracts. |
| 5 | Correction, repetition, go-back | Done for supported CLI/API paths. History, retry handling, invalidation, recalculation and archived/current provenance pass. | Vidhatri: finished-return correction controls in dashboard, if included. |
| 6 | Resume and recap | Done for tested CLI/API paths. Partial imports save before pausing; five-process regression checks recap and pending question. | Iris: show these actions in the team recording. |
| 7 | Honest uncertainty | Done for tested paths. Typed volunteer ticket, SQLite reopen, staff identity/note and the next taxpayer answer pass. Security ingress is merged. | Team: record the dashboard handoff. Language coverage is finite. |
| 8 | Context strategy | Partial. Actual classifier boundary, fresh separate ON/OFF threads, ten sequential items, provider usage and invalid-output/missing-usage checks pass offline. | Max / Vidhatri: batch/item integration and live table/curve. Iris will not run paid calls. |
| 9 | Focused tests | Done for this follow-up. Full suite 674 passed; shared evals 25/25. Current fault tests check dependent handoff and completed Schedule outcomes. | Preserve the final revision's evidence; extra tests alone cannot complete missing features. |
| 10 | Write-ups and accessibility evidence | Partial. Iris report, disclosure draft, current handoff and rehearsal cover six design choices. | Iris: personal proofreading and recorded segment. Team: five-page report approval, remaining individual disclosures and final 5-to-10-minute video. |

## Evidence to reproduce

```bash
.venv/bin/python -m pytest -q
ANTHROPIC_API_KEY='' TAX_MATH_MCP_URL='' .venv/bin/python -m evals.run_evals
.venv/bin/python -m pytest tests/test_iris_integration.py tests/test_memory.py tests/test_merge_order.py -v
git diff origin/main...HEAD --check
```

The JSON eval runner uses an in-memory saver and cannot prove process restarts. The integration test
`test_restart_correction_recomputes_and_preserves_audit_and_isolation` uses five actual Python
processes and SQLite. It checks imported answers, one resume recap, updated adjustments through Social
Security/tax/refund, estimated-payment provenance, archived prior lines and a second return's isolation.
The staff test reopens the production session interface and accepts the next real taxpayer answer.

Before repair, the temporary combined revision had **9 failures / 668 passes**, and **22/25 evals**:
three outdated Schedule cases plus six fault-test instances depending on them. Fresh main alone had
649 passing tests. After repair, the supported Schedule cases complete with literal expected amounts;
only the dependent case retains the missing-consumer handoff.

The current Docker check used an isolated Compose project and an empty model key. It saved a partial
case before estimated payments, completed a wage-conflict ticket by HTTP on the actual dashboard,
recreated containers without deleting volumes, then resumed the saved return. Imported answers and
one recap survived, the refund was $2,455.50, and the staff ID/note remained. The audit containers and
their own test volumes were removed afterward. Local logs are under ignored `output/pr15/`; the
README's Docker commands reproduce the build/test paths. This does not repeat live W-2 extraction.

The earlier checkpoint negative control failed when its three-line guard was removed. The classifier
regressions exposed malformed/unsupported output being counted as correct. Safe `uncertain` fallback
is preserved, but the sanitized validity flag now makes those benchmark outcomes incorrect.

For the HTML/provenance smoke check:

```bash
ANTHROPIC_API_KEY='' TAX_MATH_MCP_URL='' .venv/bin/python -m src.render \
  --case data/fixtures/skeleton_case.json --output output/iris-offline-draft.html
SILVERFILE_BROWSER='/path/to/Chrome' .venv/bin/python tests/check_draft_browser.py output/iris-offline-draft.html
```

Prior and current checks cover Enter/Space/click disclosure, visible source details and a 390px
viewport. They do not establish screen-reader compatibility. The 42-item guardrail set is a tuned
development set; its passing score is not a new-language accuracy estimate.

## External evidence and remaining owners

- **Docker restart:** [Vidhatri's #17 review](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/17)
  records a partial image-W-2 return, `compose down/up`, the saved pending question in the dashboard,
  resume and a completed draft. Missing recap on partial import was the Iris bug addressed by #15.
  This teammate live evidence is separate from Iris's offline checks.
- **Live token evaluation:** [Vidhatri's #15 comment](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/15#issuecomment-6473238861)
  records ten Intake items per thread as the team's working interpretation, proposes multi-turn
  refinements and offers her key for the run. Max's `max/batch-metrics` at `4372d4c` prepares batch wiring
  and a table generator. Leave that unpublished owner work intact. Require actual per-item counts,
  outcome checks, raw JSON and a curve in `metrics.md`; provider doubles do not supply them.
- **Guardrails:** historical probes needing Juee's review were `No, I don't think my son is going to
  claim me`, `Yes, she itemizes`, and `He can't talk right now, I'm his wife`. Treat them as recorded
  wording questions, not newly measured failures. Do not infer authority or change policy in Intake.
- **Output/policy contracts:** dependent rendering/credits, line 17, QCD and line 25c/other direct inputs
  require their schema/computation/policy owners. The limited Schedule 1 adjustment set also needs a
  stated team policy. Do not label these complete from passing supported-case tests.
- **Security:** #11 now independently recomputes core tax lines and checks source/provenance. The old
  coherently wrong-tax probe is superseded by that integration. Refer to `SECURITY_AND_PII.md` for the
  actual boundary and remaining deployment limits, including unencrypted SQLite and local staff IDs.

## Submission material

Iris's current prose is in `IRIS_REPORT.md`, her disclosure draft is in `AI_DISCLOSURE.md`, and the
recording sequence is in `demo/iris_memory_accessibility.md`. The report/disclosure still require
Iris's personal review. The original professor brief and Iris checklist were supplied locally as
`SilverFile_Codex_Handoff_Iris_Checklist_v2.md`; the brief remains the source for grading requirements.
The local file is not a repository dependency.

Existing disclosure text can be found for Anupama and Iris in `AI_DISCLOSURE.md`, Juee in
`GUARDRAILS_AND_ETHICS.md`, and Qiyan in `SECURITY_AND_PII.md`. No Max or Vidhatri disclosure was found
in this repository. Four statements are available, with differing approval status; two still need to
come from their authors. A generated draft or source link does not establish personal approval.

The dashboard HITL and Docker stretch implementations are merged. The five-page report still needs
team approval and publication; the required video still needs recording/assembly. Iris's remaining
personal work is proofreading her statements and performing the prepared segment, not buying tokens
or rebuilding teammates' subsystems.
