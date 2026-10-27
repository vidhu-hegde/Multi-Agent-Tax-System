# SilverFile Security and PII Handling

- **Owner:** Qiyan Zhai
- **Focus area:** Security
- **Last updated:** 2026-10-26

## 1. Purpose

SilverFile processes tax-return information that may contain personally identifiable information (PII), financial data, and credentials. This document defines the implemented security boundaries, test evidence, and known limitations.

SilverFile is a draft-return preparation aid. It does not file returns, provide tax advice, or replace an authorized tax preparer.

## 2. Threat model

The current controls address the following risks:

- A taxpayer voluntarily enters a real SSN in a free-text answer.
- An SSN is written to a LangGraph SQLite checkpoint before Intake can redact it.
- Memory, prompts, responses, escalation evidence, or dashboard-facing values expose PII.
- A staff resolution note contains an SSN.
- An SSN-like value is used as a thread ID or staff audit identity.
- An API key appears in application state, debug output, committed files, or a Docker build context.
- Different modules use inconsistent SSN validation or redaction rules.
- A nine-digit monetary amount is incorrectly treated as an SSN.

Security controls are designed to fail closed when input cannot be safely classified or validated.

## 3. PII inventory and minimization

| Data | Purpose | Current handling |
|---|---|---|
| Filing status | Tax-return preparation | Stored as structured Intake data |
| Date of birth | 1040-SR eligibility | Stored in workflow state |
| Blindness status | Deduction rules | Stored as a boolean |
| Financial amounts | Form preparation | Stored as typed monetary values with provenance |
| W-2 employee SSN | Document identity validation | Only 900-series synthetic values accepted; structured W-2 records retain last four digits |
| Dependent SSN | Dependent collection | Only 900-series synthetic values accepted |
| Real or volunteered SSN | Not required | Rejected or redacted before production checkpoint entry |
| API key | Optional model access | Loaded from environment only; excluded from state and debug representation |
| Staff resolution note | HITL audit trail | Redacted before graph resume and persistence |
| Staff identifier | HITL accountability | Must be non-empty and must not contain an SSN-like value |

The demo and automated tests use synthetic identities. Real taxpayer SSNs must not be used.

## 4. Central security boundary

`src/security.py` is the authoritative implementation for:

- 900–999 synthetic SSN validation;
- recursive SSN redaction;
- field-aware resume-input protection;
- staff audit-identifier validation.

Memory, Intake, CLI, and Sessions import these shared helpers rather than maintaining separate regular expressions or redaction implementations.

This prevents security behavior from drifting between modules.

## 5. SSN policy

SilverFile accepts only synthetic SSNs matching:

```text
9XX-XX-XXXX
```

Examples:

- Accepted synthetic value: `901-23-4567`
- Rejected real-range value: `123-45-6789`
- Rejected malformed value: `901234567`

Validation errors do not echo the rejected value.

Strings and nested payloads containing SSN-shaped values are masked in the following form:

```text
***-**-6789
```

W-2 extraction validates the complete synthetic SSN and retains only the last four digits in the structured W-2 record.

## 6. Field-aware ingress protection

LangGraph may persist `Command(resume=...)` before the Intake node processes the reply. Redacting only inside Intake is therefore too late.

Intake questions expose a structured contract:

```text
type
field
input_type
prompt
```

Supported input types are:

- `text`: recursively redact SSN-shaped values before resume;
- `money`: preserve a complete valid monetary value, including a nine-digit amount;
- `test_ssn`: validate the requested 900-series synthetic SSN before resume.

This prevents prompt-text guessing and distinguishes a legitimate value such as `123456789` in a money field from an SSN disclosed in free text.

Production CLI input passes through this protection before creating `Command(resume=...)`.

## 7. Memory and model boundary

Memory and model calls use the shared recursive redaction helper.

The selective-context strategy excludes unnecessary sensitive answers from model context. When previous dialogue is included, message content is redacted before model invocation. Model responses are also redacted before being added to workflow state.

An API key is passed to the provider client through runtime configuration. It is not added to LangGraph state or checkpoints.

## 8. SQLite and session identity

Workflow sessions use opaque thread IDs. SSN-like thread IDs are rejected by both the thread configuration helper and the SQLite checkpointer boundary.

Automated tests inspect SQLite database bytes to verify that a real SSN volunteered through the production CLI resume path is not persisted.

SQLite provides persistence, not authentication or encryption. File-system access and encryption-at-rest remain deployment responsibilities.

## 9. HITL and dashboard-facing data

`Sessions.resolve()` is the shared staff/Dashboard resolution boundary.

Before graph resume:

- free-text resolution notes are recursively redacted;
- SSN-like staff identifiers are rejected;
- unsafe identity rejection leaves the escalation ticket open;
- only the protected decision is passed to `Command(resume=...)`.

Session summaries expose the taxpayer-facing prompt, not internal `field` or `input_type` metadata.

Dashboard authentication and role-based access control are not yet implemented and remain a cross-team dependency.

## 10. Secrets handling

Each developer must:

1. Copy `.env.example` to `.env`.
2. Add their own API key locally.
3. Never commit or share `.env`.
4. Avoid placing keys in screenshots, traces, fixtures, or issue comments.

Ordinary unit tests do not require an API key. A real key is needed only for live provider calls, including the context-window benchmark.

Implemented controls include:

- `.env` and `.env.*` are ignored by Git;
- `.env.example` contains no key;
- `Settings.anthropic_api_key` is excluded from `repr(Settings)`;
- tests verify that the key is absent from workflow state and SQLite;
- repository text files are scanned for common credential formats;
- `.dockerignore` excludes local secrets, databases, traces, output, Git metadata, virtual environments, and caches;
- `.env.example` remains available as a safe configuration template.

Secrets must be injected when a container starts, not copied into an image.

## 11. Synthetic fixtures and committed artifacts

Committed W-2 examples and SSN values must remain synthetic and use the allowed 900-series range.

Generated databases, ordinary traces, filled intermediate PDFs, and output files are ignored. Any curated demo trace added later must be reviewed and scanned before commit.

The repository secret scan reports only offending filenames and does not print the suspected credential.

## 12. Automated evidence

Relevant tests are located in:

```text
tests/test_security.py
tests/test_schemas.py
tests/test_memory.py
tests/test_intake.py
tests/test_sessions.py
tests/test_graph.py
```

The tests cover:

- valid and invalid synthetic SSNs;
- safe validation errors;
- recursive string and integer redaction;
- shared Memory/Security redaction ownership;
- field-aware text, money, and test-SSN handling;
- pre-checkpoint CLI protection;
- structured Intake security metadata;
- thread-ID rejection;
- staff-note redaction;
- staff-identity rejection;
- API-key representation and persistence;
- repository credential scanning;
- Docker context exclusions;
- restart and session compatibility.

Latest local regression evidence:

```text
Security + Smoke: 28 passed
Full suite: 171 passed, 1 known upstream failure
```

The remaining failure is the previously identified `merge_answers` same-microsecond event-identity conflict. It is unrelated to the security changes and is tracked separately for final integration.

## 13. Known limitations and follow-up work

The following items are not yet complete:

- Dashboard authentication and role-based authorization;
- encryption at rest for SQLite;
- production retention and deletion policy;
- verification of future committed demo traces;
- security review of the final Dockerfile and deployment configuration;
- protection for any future production entry point that bypasses `run.drive()` or `Sessions.resolve()`;
- final OCR pipeline review and assurance that raw document text is not persisted unnecessarily;
- structured, reason-specific HITL resolution validation;
- final resolution of the answer-event identity conflict in `merge_answers`.

Any new caller that creates `Command(resume=...)` must apply the same field-aware protection before invoking the graph.

## 14. Cross-team responsibilities

- **Qiyan:** security policy, validation, redaction, security tests, and security review.
- **Iris:** Intake, memory, checkpoint, and context-strategy integration.
- **Vidhatri:** graph routing and resume integration.
- **Max:** Dashboard, Docker, computation services, and runtime deployment.
- **Anupama:** document extraction and provenance contracts.
- **Juee:** policy catalogue, scope rules, and HITL wording.

Security requirements apply across these components even when their primary implementation belongs to another team member.