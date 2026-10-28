# SilverFile Security and PII Handling

Owner: **Qiyan Zhai** (focus areas: Security and Review/Audit).

Latest Update: 2026-10-28

Primary code: `src/security.py`, `src/resolution.py`, `src/agents/review.py`, and security boundaries in `src/tools.py`, `src/communication.py`, `src/sessions.py`, `src/agents/human.py`, and `src/dashboard/`.

Primary tests: `tests/test_security.py` and `tests/test_review.py`, with integration coverage in `tests/test_graph.py`, `tests/test_sessions.py`, `tests/test_dashboard.py`, and `tests/test_communication.py`.

## Security responsibility and completed work

SilverFile processes taxpayer documents, Social Security numbers, income amounts, staff corrections, escalation notes, checkpoints, and generated tax-return drafts.

My Security contribution establishes shared boundaries for:

- validating synthetic test SSNs and rejecting real-range SSNs;
- recursively masking SSN-shaped values;
- protecting taxpayer replies before `Command(resume=...)`;
- preventing sensitive staff identifiers and notes from entering checkpoints;
- keeping provider credentials out of state and committed files;
- enforcing safe staff resolution through `Sessions.resolve()`;
- preventing unresolved document and calculation failures from reaching `draft_ready`;
- converting invalid tax-tool inputs into sanitized HITL tickets;
- validating Review/Audit provenance and fail-closed behavior;
- integrating these controls with document recovery, real tax math, and the staff dashboard.

I implemented these protections at shared ingress, persistence, tool, and resolution boundaries so that the CLI and dashboard use the same security rules.

## Implemented controls

| Boundary | Security behavior |
|---|---|
| Test SSNs | Only synthetic SSNs in the `9XX-XX-XXXX` range are accepted where an SSN is required. Invalid values are rejected without being repeated in the error. |
| PII display | Dashed, compact, string, integer, and nested SSN-shaped values are masked to the last four digits. |
| Taxpayer resume input | Text, money, and requested test-SSN inputs are handled separately before they are placed in `Command(resume=...)`. |
| Staff identity | Staff identifiers must be non-empty and cannot contain an SSN-shaped value. |
| Staff notes | Notes are redacted before they are stored in ticket resolutions or checkpoints. |
| Checkpoints | Regression tests inspect SQLite artifacts and verify that selected raw SSNs and rejected tax inputs are absent. |
| Secrets | API keys remain in local configuration, are excluded from state and checkpoints, and are protected by `.gitignore` and `.dockerignore`. |
| Tax tools | Invalid inputs become `ToolInputError` with only the tool and affected field names retained. |
| HITL resolution | Reason-specific corrections are validated before the graph resumes. |
| Review/Audit | Draft lines are independently checked against confirmed sources, tax-rule inputs, provenance records, deterministic tool calls, calculation dependencies, and unresolved scope issues. Equivalent repair actions are consolidated without collapsing cross-agent sequencing. |

## Design decisions and why

### 1. Protect values before checkpointing

Redacting a value only after an agent reads it is too late because LangGraph may persist the resume payload before the next node executes.

I therefore added protection before taxpayer and staff inputs are placed in `Command(resume=...)`. The related tests inspect persisted SQLite bytes rather than checking only the returned Python state.

### 2. Use field-aware input protection

A nine-digit string may be an SSN or a legitimate monetary amount. Applying the same regular expression to every field would either expose PII or corrupt valid tax data.

The ingress boundary distinguishes between:

- ordinary text;
- monetary input;
- explicitly requested synthetic SSNs.

A value such as `123456789` can remain valid in a money field, while the same digits in ordinary text are masked.

### 3. Do not repeat rejected values

Security errors identify the affected field or tool but do not repeat the submitted value.

I applied this rule to:

- SSN validation;
- staff identifiers;
- document-recovery fields;
- dashboard forms;
- staff notes;
- tax-tool failures.

This reduces the chance that an exception, escalation ticket, dashboard page, or checkpoint becomes a second copy of sensitive input.

### 4. Use one staff-resolution boundary

Both the command-line workflow and the dashboard call `Sessions.resolve()`.

This centralizes:

- staff-ID validation;
- note redaction;
- stale-ticket checks;
- allowed actions;
- required corrections;
- written override reasons;
- checkpoint-safe resume payloads.

The dashboard therefore cannot bypass the security behavior of the underlying workflow.

### 5. Fail closed on invalid calculations

The production tax-math functions raise `ValueError` when their contracts are violated. Raw exception text may contain rejected values and should not be copied into workflow state.

I added a boundary in `call_tool()` that converts expected validation failures into `ToolInputError`. The agent boundary then raises a sanitized `tool_input_invalid` escalation containing only:

- the safe tax-tool name;
- the affected field names;
- safe staff guidance.

This ticket is stop-only. Staff cannot continue past an invalid calculation and produce a draft from incomplete or malformed source data.

### 6. Preserve the placeholder safety invariant

After PR #10 replaced the original tax stubs with real implementations, the original placeholder safety test no longer had a real stub to exercise.

I updated the test to inject explicit stubs inside the test process. This continues to prove that placeholder calculations cannot reach `draft_ready` without incorrectly treating the production tools as placeholders.

## Human-in-the-loop integrations

### Unreadable documents

When a document cannot be read, staff may type the required fields. The explicit per-form field definitions are the executable contract.

The security boundary ensures that:

- omitted required fields are rejected;
- an explicit zero is not confused with an omitted value;
- typed values are protected before resume;
- staff provenance is retained;
- error messages do not repeat typed values;
- a plain Continue action cannot skip the unresolved document;
- incomplete document recovery cannot produce a completed draft.

I integrated these protections with the document-recovery flow while preserving its original field definitions and ownership.

### 1099-R Box 2b

A `1099r_taxable_not_determined` ticket requires a finite, nonnegative taxable-amount correction that does not exceed the current gross distribution before Continue is accepted.

The correction is validated through the shared resolution boundary before `Sessions.resolve()` resumes LangGraph, applied to the corresponding 1099-R, attributed to the staff member, and followed by recomputation. Direct graph callers receive the same validation inside the Human node; rejected values cause a fresh interrupt rather than poisoning the pending resume value.

During integration with the staff dashboard, I connected the dashboard’s correction form to this existing `Sessions.resolve()` contract. I also added regression coverage for:

- a valid taxable-amount correction;
- a missing correction;
- an invalid correction;
- a correction greater than the gross distribution followed by either a valid correction or Stop;
- a rejected direct graph resume followed by a successful retry;
- a stale or already-resolved ticket;
- a second attempted resolution.

### Invalid tax-tool inputs

A tax-tool validation failure becomes a sanitized, stop-only `tool_input_invalid` ticket.

I added regression coverage verifying that the rejected raw value does not appear in:

- the escalation ticket;
- returned workflow state;
- LangGraph checkpoint state;
- the checkpoint database;
- dashboard output.

A forged dashboard Continue request is also rejected. Staff may only stop the affected workflow, correct its source data, and begin a new return.

## Review and audit controls

Review checks the completed draft without changing calculated values itself.

I expanded Review/Audit in four focused steps:

1. **Source-to-line verification:** rebuilds direct-entry lines from current typed document records and confirmed Intake answers, independently of the draft's provenance.
2. **Independent tax-rule verification:** reconstructs the inputs for Lines 6b, 12e, 13b, and 16 and calls the deterministic tax tools again. Critical age, filing-status, and MFS decisions are also checked against confirmed Intake facts.
3. **Provenance-integrity verification:** checks document identity, form/box/field, recorded value, source snapshot, attribution, timestamp, rule citation, declared dependencies, tool identity, MCP/in-process route (`via`), arguments, and recorded result.
4. **Actionable feedback and recovery testing:** consolidates findings that require the same repair while preserving distinct and cross-agent requests, removes expected monetary amounts from Review reasons, and verifies real Review-to-repair-to-Review workflows through LangGraph.

The completed Review boundary detects:

- placeholder or stub-dependent calculations;
- missing provenance;
- stale or incorrect direct-entry lines compared with confirmed source records;
- missing, malformed, or contradicted Rule Decisions;
- forged, duplicated, stale, or mismatched provenance;
- incorrect deterministic tool identities, arguments, results, or dependencies;
- taxable components larger than their corresponding totals;
- inconsistent refund and amount-owed values;
- incorrect aggregate lines;
- unresolved scope issues;
- incomplete revision cycles.

Review remains read-only: it emits validated `RevisionRequest`s but does not modify documents, Intake answers, Rule Decisions, or calculated lines. Requests are consolidated by their repair identity (`target`, `line`, `field`, and `document_id`) in stable order. A Rules correction remains separate from the required Computation rerun.

I added seeded-error tests showing that Review rejects internally consistent but source-incorrect lines, incorrect tax-rule results, and fabricated evidence. Actual graph tests also verify:

- a one-time Computation error is rejected, recomputed, reviewed again, and reaches `draft_ready`;
- an incorrect Rule Decision follows `Review -> Rules -> Computation -> Review` before reaching `draft_ready`;
- persistent failures still stop at the existing review-pass bound;
- pathological repeated handoffs still trigger the separate loop guard.

A failed calculation does not receive a successful Review fingerprint, and an unresolved Review failure cannot become `draft_ready`.

## Integration with teammate work

I developed the initial Security boundaries independently where stable shared contracts were already available. I then retested and extended them as document recovery, guardrails, real tax math, and the dashboard were merged.

During integration, I:

- preserved Vidhatri’s document-recovery and dashboard contracts;
- connected the dashboard’s correction flow to the protected `Sessions.resolve()` boundary;
- preserved Max’s tax-math functions while adding sanitized handling for rejected inputs;
- retained Juee’s policy and guardrail reasons as the policy source;
- preserved Anupama’s extraction, provenance, and vision-demo design;
- resolved security-sensitive merge conflicts;
- added cross-component regression tests;
- ran the final offline and live validation against the integrated system.

My contribution does not replace or claim ownership of those components. It protects the shared boundaries through which they exchange, persist, display, and correct sensitive information.

Merge chronology, individual conflict resolutions, commit identifiers, intermediate test results, and detailed changed-file lists are recorded in PR #11 rather than in this long-lived security reference.

## Verification

### Automated regression suite

With strict LangGraph checkpoint serialization enabled:

```text
639 passed
```

This includes security, Review/Audit, true LangGraph revision loops, communication, sessions, dashboard, document recovery, guardrails, tax math, cents-rounding, provenance, and checkpoint tests. The focused Review and graph run passed `88` tests, including both recoverable revision workflows.

### Offline end-to-end evaluations

```text
16 of 16 cases passed in-process, and 16 of 16 through a live local MCP server
```

These evaluations cover:

- clean draft generation;
- document conflicts;
- out-of-scope requests;
- written reasons for staff overrides;
- 1099-R Box 2b correction;
- advice requests;
- filing-status ambiguity;
- exploitation concerns;
- honest uncertainty;
- unreadable-document recovery;
- Review and loop limits;
- SSN refusal and masking.

### Live vision verification

With a locally configured and Git-ignored API key:

```text
PASS  demo/w2_image_1.jpg: 16 of 16 fields match
PASS  demo/w2_image_2.jpg: 16 of 16 fields match

2 of 2 W-2 images read correctly
```

The live extraction used `claude-sonnet-5-5`. I did not add the API key to source control or workflow state.

### Anupama vision case

Anupama designed and supplied `demo/anupama_vision_case.json` and its taxpayer scenario.

I did not redesign the case or change its source data. During final Security integration, I:

- updated its stale description after real tax math replaced the original calculation stubs;
- ran the case with the live vision integration;
- verified the merged extraction, provenance, computation, Review, and Security path;
- confirmed that the run reached `draft_ready`.

The resulting draft included:

- taxable Social Security benefits of `$5,775.00`;
- total income of `$30,195.00`;
- taxable income of `$6,445.00`;
- tax of `$644.50`;
- an overpayment of `$2,455.50`.

I report these results as integration evidence, not as a claim that I designed Anupama’s case or implemented Max’s tax formulas.

## Known limits

- SSN redaction is pattern-based. It protects recognized dashed, compact, string, integer, and nested SSN-shaped values, but it is not a general-purpose detector for every possible form of PII.
- The protections depend on callers using the shared `protect_resume_input()`, `Sessions.resolve()`, `call_tool()`, and redaction boundaries. Any future entry point must reuse these boundaries rather than writing directly to workflow state or checkpoints.
- The local SQLite checkpoint database is not encrypted. Production use would require deployment-level encryption, access control, retention, and secure-deletion policies.
- The current local staff dashboard does not provide production authentication or role-based authorization. Staff-ID validation supports audit records but is not a replacement for identity management.
- The application cannot control logs, retention, or telemetry independently maintained by an external model provider. Provider-side privacy settings must be reviewed before production use.
- Security tests use synthetic identifiers and deliberately rejected values. They verify the implemented boundaries and selected persisted artifacts, but they cannot prove that every future code path is free of PII leakage.

## AI-use disclosure

I used OpenAI Codex to inspect the existing SilverFile repository, assignment context, teammate branches, and PR changes. Codex assisted me with identifying security-sensitive integration boundaries and with designing, generating, reviewing, and revising parts of the Security implementation and tests.

I used Codex to assist with:

- centralized SSN validation and recursive PII redaction;
- field-aware protection before LangGraph resume and checkpoint persistence;
- staff identifier and note protection;
- secret-handling and Docker-context tests;
- the sanitized `ToolInputError` and `tool_input_invalid` HITL boundary;
- independent source-to-line, tax-rule, and provenance-integrity Review checks;
- Review finding consolidation and real LangGraph revision-loop tests;
- dashboard and 1099-R security integration;
- merge-conflict analysis and regression-test planning;
- documentation, handoff notes, and this Security report.

The live W-2 extraction used Anthropic Claude Sonnet 5.5 as part of testing the application.
