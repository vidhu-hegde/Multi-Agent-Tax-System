# SilverFile Security and PII Handling

- **Owner:** Qiyan Zhai
- **Focus area:** Security
- **Last updated:** 2026-10-27

## 1. Scope

SilverFile handles tax information containing PII, financial data, and credentials. The security work focuses on:

- preventing real SSNs and secrets from entering saved state;
- validating synthetic test identities;
- protecting taxpayer and staff resume inputs before checkpointing;
- preserving safe audit provenance;
- preventing unresolved, missing, or placeholder values from reaching `draft_ready`.

SilverFile prepares draft returns only. It does not file returns or replace an authorized tax preparer.

## 2. PII and SSN controls

SilverFile accepts only synthetic SSNs in the `9XX-XX-XXXX` range. Validation errors do not repeat rejected values.

Real or volunteered SSNs are rejected or redacted as:

```text
***-**-6789
```

`src/security.py` is the shared implementation for:

- synthetic SSN validation;
- recursive SSN redaction;
- field-aware resume protection;
- staff identifier validation.

W-2 records retain only the validated SSN’s last four digits. Real taxpayer SSNs must not be used in demos or tests.

## 3. Field-aware input protection

LangGraph may checkpoint `Command(resume=...)` before an agent processes it, so protection must happen before graph resume.

Structured Intake questions identify:

```text
type
field
input_type
prompt
```

Supported input handling includes:

- `text`: redact SSN-shaped content;
- `money`: preserve a valid monetary value, including nine-digit amounts;
- `test_ssn`: require a valid 900-series synthetic SSN.

Production CLI and staff resolution paths apply these controls before invoking the graph.

## 4. Memory, checkpoints, and secrets

Model context and stored messages use recursive redaction. Selective context avoids sending unnecessary sensitive answers to the model.

SSN-like thread IDs and staff identifiers are rejected. Staff notes are redacted before persistence.

API keys are loaded from environment configuration and excluded from application state and debug representation. `.env`, databases, traces, output files, Git metadata, and virtual environments are excluded from the Docker build context.

SQLite provides persistence but not authentication or encryption at rest. Deployment access control and encryption remain future responsibilities.

## 5. HITL resolution security

`Sessions.resolve()` is the shared staff-resolution boundary. It:

- validates the staff identifier;
- redacts free-text notes;
- validates reason-specific correction values;
- leaves the ticket open when validation fails;
- resumes the graph only with the protected decision.

### Unreadable documents

An unreadable document cannot be silently skipped. Staff must enter the required values or stop the session.

Each supported form has an explicit `STAFF_ENTRY_FIELDS` contract. An explicit `0`, `false`, `null`, or `[]` is accepted where valid, but an omitted required field is rejected rather than silently becoming zero.

Validated entries receive staff provenance and replace the failed document state.

### 1099-R Box 2b

A `1099r_taxable_not_determined` ticket cannot be resolved with plain `continue`.

Staff must supply:

```text
corrections.taxable_amount
```

The amount is validated, recorded with staff provenance, and sent through recomputation and review.

## 6. Review boundary

Security Review rejects draft lines with missing provenance or stub/placeholder calculations.

A stub-derived result must not reach `draft_ready`, even when the placeholder returns a syntactically valid zero.

Tests may explicitly inject verified test tools. Production stubs must remain marked as stubs until the real tax-math implementation is integrated.

## 7. Integration record

Commit `e5803ac` merged current `main`, including PRs #7, #8, and #9, into `Qiyan-security`.

The conflict resolution preserved both teammate functionality and the security boundaries:

- `run.py` supports document-value recovery while protecting taxpayer and staff resume inputs.
- `src/agents/human.py` supports unreadable-document values and validated 1099-R corrections.
- Successful document recovery replaces the failed document state.
- `src/agents/intake.py` combines structured security metadata with the shared guardrail flow.
- `src/sessions.py` supports both `values` and `corrections` while retaining note redaction and staff-ID validation.
- Communication and MFS tests now use the structured Intake interrupt contract.
- The 1099-R eval now supplies `corrections.taxable_amount` rather than bypassing the ticket.

## 8. Test evidence

Security and integration coverage includes:

- synthetic SSN validation and redaction;
- field-aware resume protection;
- checkpoint and restart safety;
- staff-note and staff-identity protection;
- API-key and repository secret scanning;
- unreadable-document recovery;
- missing-field rejection;
- structured guardrail questions;
- MFS Social Security handling;
- mandatory 1099-R correction;
- placeholder calculation rejection;
- strict MsgPack serialization.

Latest results:

```text
Focused integration suite: 193 passed
Communication tests: 67 passed
MFS Social Security tests: 7 passed
Eval pytest cases: 15 passed
Full suite with LANGGRAPH_STRICT_MSGPACK=true: 464 passed
```

The earlier answer-event timestamp collision has been fixed. The integrated pytest suite currently has no failures.

## 9. Remaining work

The following work remains:

- integrate PR #10’s real tax-math implementation;
- rerun the standalone end-to-end eval suite after #10;
- review the final Docker and deployment configuration;
- add Dashboard authentication and role-based authorization;
- define production data retention, deletion, and encryption policies;
- review any future entry point that bypasses `run.drive()` or `Sessions.resolve()`;
- perform live provider testing when an API key is available.

Until PR #10 replaces the tax-math stubs, a standalone eval may resolve the 1099-R ticket and then reach `review_limit`. This is expected fail-closed behavior and must not be bypassed by weakening Review.

## 10. Ownership

- **Qiyan:** security validation, redaction, HITL protection, tests, and security review.
- **Iris:** Intake, memory, checkpoints, and context integration.
- **Vidhatri:** orchestration and resume integration.
- **Max:** tax math, Dashboard, Docker, and runtime deployment.
- **Anupama:** extraction and provenance contracts.
- **Juee:** policy, scope guardrails, and HITL wording.

Security requirements apply across these components even when their primary implementation belongs to another team member.