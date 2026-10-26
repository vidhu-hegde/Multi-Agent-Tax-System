# Anupama: inter-agent communication handoff

Date: 2026-10-25. Branch: `anupama/inter-agent-communication`, based on `origin/main` at `0451244`.
No commits, pushes, PRs, or changes to local main were made for this contribution.

## Scope and source documents

Read `Assignment 7_ Implement a multi agent tax system.pdf` and `Working doc.pdf` from the supplied Downloads paths. The assignment specifies the deliverables and constraints; the working document is the team's proposed ownership/integration plan. Anupama's explicit chat request authorizes this implementation and excludes teammates' MCP math, policy corpus, and full dashboard. Document text was treated as task context, not permission to contact teammates, publish, or submit anything. No teammate AI-use statements were invented or collected by messaging.

## Verified baseline and validation

The initial system-Python attempt failed because pytest was absent. Created ignored `.venv` and installed unchanged `requirements.txt` (Python 3.14 on this Windows machine). Before any source changes, `.venv\Scripts\python -m pytest -q` reported **137 passed in 13.95s**, rather than the previously unverified 126.

Final verification after all code changes: full suite **190 passed in 31.25s**; focused communication suite **53 passed** (latest focused run: 2.06s). `git diff --check` is clean. Mocked vision uses actual bytes from both committed images and their independently committed expected records. These are provider-double tests, not evidence of Claude OCR accuracy.

Local Chrome headless checks verify Enter opens a monetary disclosure, Space closes it, mouse click reopens it, the hover source summary is populated, source metadata is visible, and a 390px viewport has no horizontal overflow. Screenshot: ignored `output/draft-browser.png`. This is a browser smoke check, not a screen-reader audit or final accessibility certification.

`ANTHROPIC_API_KEY` is **not configured** in this session. No live request was sent. Live W-2 accuracy and account/model compatibility remain pending.

## Shared contracts and boundary rules

`src/schemas.py` remains the single contract source. Existing frozen, extra-forbidden Pydantic models were extended, not duplicated. Nonempty identifiers/text, finite Decimal amounts, allowed agent names, supported revision targets, and resolution actions are validated; existing model instances are revalidated at boundaries. Business values remain typed using the existing document discriminated union.

| Agent | Inputs consumed | Allowed outputs / responsibility | Must never do |
|---|---|---|---|
| Orchestrator | Shared state, work-product readiness, revisions, escalation status, handoff history | Routing/control metadata, handoffs, escalation tickets; coordinated invalidation when an evidence fingerprint changes | Extract documents, calculate tax, or talk to taxpayer |
| Intake | Existing confirmed answers, pending field, revisions, taxpayer replies or case input, inventory | `IntakeAnswer`, `DocumentRef`, messages/usage, intake control, correction revisions, escalations; archive/invalidate old work and retract superseded inventory records | Compute amounts, decide eligibility, or manufacture rule/line results |
| Extraction | `{"doc": DocumentRef, "revision_epoch": optional int}` | `TaxDocument` records keyed by document ID; document readiness flags or uncertainty tickets | Interpret tax rules, decide line placement, compute return values, or invent missing fields |
| Aggregate documents | Reduced document state and extraction revisions | Completes the existing parallel join, consumes extraction requests, invalidates downstream work after a requested re-read | Extract, calculate, converse |
| Rules | Current answers, inventory, validated documents, revisions | Cited `RuleDecision` records, escalations, remaining revisions | Compute derived return amounts or converse |
| Computation | Current answers, documents, rule decisions, revisions | `LineValue` records with provenance and dependencies, remaining revisions, pending review | Extract, make policy decisions, or perform arithmetic outside the tool boundary |
| Review | Assembled lines, sources, rule decisions and escalation status | `RevisionRequest`, review status/count; sends work back | Modify lines or source documents |
| Human node | Open ticket, staff resolution, explicit conflict choice | Recorded resolutions; explicit candidate selection and downstream invalidation | Silently select a competing record |

`src/communication.py:checked_agent` wraps the existing graph nodes, including supplied test/integration overrides. It validates input contracts and output channels before reducer writes. Dictionary keys must match embedded IDs. Impersonation, invalid routing names, wrong output channels, malformed control values, invalid monetary messages, and unknown extraction revision IDs fail explicitly. An invalid programmer-authored message raises `ValueError`/Pydantic validation, whereas unreadable document contents produce the existing HITL escalation. This validation is an integration boundary, not an authentication system or a guarantee against every possible semantically incorrect agent output.

Messages with `Any` payloads (notably answer values, rule outcomes and tool arguments) intentionally retain the existing flexible wire contract. Model JSON roundtrips preserve wire values; strict LangGraph serialization also preserves Decimal/date/model types inside those payloads. Do not assume JSON can recover arbitrary Python types stored under `Any` without an agreed field parser.

## Extraction integration

`make_extraction(settings, client=None)` is wired into `build_graph`; tests can inject a provider double through the existing `agents={"extraction": ...}` override. Production lazily creates the Anthropic client using `load_settings()` and `SILVERFILE_MODEL`, sends an image block before the transcription instructions, and validates its JSON observation against the existing `W2Record`. API retries are disabled; timeout is 60 seconds. See [Anthropic vision documentation](https://platform.claude.com/docs/en/build-with-claude/vision) for the image message interface.

Every supported field must be observed. Visibly blank optional amounts can be null; visibly unchecked boxes are false; visibly empty box 12 is an empty list. The model must list unreadable/missing fields as issues. An issue, omitted observation, unreadable box 2, malformed data, invalid SSN, truncated response, unsupported/corrupt/missing image, or provider error publishes no partial record. Errors are sanitized before ticket creation. This does not claim that model confidence guarantees correct transcription; live comparison remains necessary.

The source retains image path, SHA-256, document ID, actual response model/ID and timestamp. The existing SSN validator discards all but the last four digits after checking the test range. No raw provider response, image base64, or full extracted SSN is placed in shared state or tickets. The image itself is sent to Anthropic; only synthetic fixture images were used here. Existing security-owner ingress and tracing limitations still apply.

For manual 1099-INT, 1099-DIV, 1099-R, SSA-1099 (and legacy typed W-2), use existing `DocumentRef.values`, plus `entered_by` and timezone-aware `entered_at`. `manual_record` validates the existing union and creates `kind="user_input"`, source `direct user input: ...`, with the same identity/time. Reserved source/identity keys inside values are rejected. Explicit metadata should be supplied by the authenticated entry frontend; the backward-compatible default identity is `case file` and time is import time. If both values and an image path exist, values take precedence and the record is honestly labelled direct input; legacy fixtures intentionally use this form.

```python
from datetime import datetime, timezone
from src.schemas import DocumentRef
from src.agents.extraction import manual_record

ref = DocumentRef(
    document_id="interest-demo", form_type="1099-INT",
    values={"payer_name": "Synthetic Bank", "interest": "123.45", "federal_withheld": "0"},
    entered_by="staff-demo", entered_at=datetime.now(timezone.utc),
)
record = manual_record(ref)
```

Other non-W-2 images are not transcribed; enter their typed values. Optional manual amount defaults remain the existing contracts' defaults; callers should explicitly confirm zeros rather than infer them from unreadable documents.

## Provenance, revisions and evidence changes

Document-to-line provenance now preserves the complete original source object, entrant identity, timestamp, document ID and field/box reference. Existing tool result/source/inputs remain attached. Derived lines include ancestor provenance and still carry `depends_on`; stub flags therefore propagate through totals. Future MCP code must retain the actual tool name, arguments, result, time and available call identifiers in this same provenance contract.

`RevisionRequest.field` identifies a specific Intake field; existing line-10/26 mapping and `intake_revisit` remain compatible. `RevisionRequest.document_id` is required for extraction revisions. A re-read uses the existing `Send` fan-out and reducer: an identical manual retry is idempotent; a changed record requires the existing explicit human candidate selection. Failed re-reads flag the document unverified and cannot make the old amount visible as a valid result. A retry failure has a fresh revision ticket identity.

`src/evidence.py` archives prior work products as typed `EvidenceSnapshot` entries, clears stale lines/rules, increments an evidence epoch and resets review when confirmed evidence changes. Inventory edits remove superseded/removed extracted records through coordinated `Overwrite`, retaining unchanged references; prior records remain in audit history. The existing conflict reducer remains responsible for competing concurrent writes. New answer/document/inventory ingress is also detected by a stored computation evidence fingerprint. Rule ticket IDs gain `:evidence-N` for changed evidence, so an older resolved approval cannot authorize the new occurrence. Historical approvals remain stored; new scope decisions refer to the new IDs. Same-evidence approvals retain their existing behavior.

No tax policy was changed. In particular, a staff continue still means the legacy graph can proceed; it is not proof that an unsupported tax situation has become in scope. Juee/Max must settle that policy and downstream readiness. The renderer independently withholds incomplete/unverified/stale/stub values.

## HTML draft view

`render_draft(state) -> str` uses existing `LineValue` records and `FORM_LINES`; it computes no tax. It is a standalone supported-line draft view, not a pixel replica of the official IRS PDF, filing software, or a full dashboard. Monetary values are native `details/summary` controls with readable source identity/time and calculation inputs, complete escaped audit records, and dependency traces. They support click, keyboard activation, visible focus and a source summary on hover. Large type, wrapped text, semantic table headers and responsive layout support review.

A value is withheld when the current evidence is not reviewed, revisions/escalations remain, a required document is absent/unverified, a dependency is missing/cyclic, or any dependency is a stub. Missing values are never silently converted to displayed zero. Existing orchestrator `draft_ready` alone does not guarantee a complete real-tax result. Rendering malformed line records or mismatched line IDs fails validation.

Dashboard integration: obtain typed state through `sessions.state(thread_id)`, call `render_draft`, and embed/download the returned HTML. Continue using the existing `sessions.resolve` hook for staff actions; never use this renderer to resolve tickets or mark a return filed. `python run.py --html output/draft.html ...` writes the same view when the CLI run returns. The old console printer is not the HTML provenance interface.

## Demonstration and reproduction

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest tests/test_communication.py -q
.\.venv\Scripts\python -m src.render --case data/fixtures/skeleton_case.json --output output/draft_1040sr.html
.\.venv\Scripts\python tests/check_draft_browser.py
```

Open `output/draft_1040sr.html`. Tab to wages, press Enter or Space, or click it. Read the document box, direct-input metadata and sum arguments. Inspect the audit record and hover source summary. Confirm tax/stub-dependent totals are withheld. Browser checking needs a local Chrome/Edge (or `SILVERFILE_BROWSER` executable path) and `websockets`, installed transitively by current requirements. It writes an isolated browser profile/screenshot under ignored `output/` and does not open the user's normal browser profile.

For live vision, configure `ANTHROPIC_API_KEY` and an account-supported `SILVERFILE_MODEL` locally in ignored `.env`. Never paste credentials into code, screenshots or logs. Then:

```powershell
.\.venv\Scripts\python -m src.render --case demo/anupama_vision_case.json --output output/vision_draft.html
```

This synthetic case replaces the legacy typed W-2 with the real committed fixture image and labels the other manual records. Compare every extracted field against `data/fixtures/w2_1_expected.json`; repeat with image 2 and its expected record, adjusting synthetic stated wages to match or explicitly exercising conflict escalation. Without credentials the case pauses safely and its HTML withholds monetary results. It does not simulate a successful live extraction.

The focused tests include malformed contracts/handoffs, both image fixtures, unreadable/provider/file failures, all four manual form types, Decimal/strict-checkpoint serialization, role enforcement, named revisions, document replacement/retraction, new-evidence approvals, graph-level mocked vision, failed re-read suppression, restart preservation, and escaping/stub/stale/cycle handling. Browser smoke checks complement these tests; a human screen-reader review and the final recorded team demo remain pending.

## Remaining dependencies

- **Max:** replace local/stub tax tools with actual MCP math and retain tool-call provenance; integrate the HTML view into the dashboard and verify completed-return readiness. Existing dependent/Schedule 2/3/QCD/other direct-line consumers remain incomplete; this contribution does not add tax computations for them.
- **Juee:** authoritative policy corpus/citations, scope decisions and wording approval. Existing wage tolerance and continuing past out-of-scope approvals were not redefined.
- **Vidhatri/Iris:** review the typed field/document revision, evidence epoch/archive and graph-boundary integrations; preserve them when adding model-backed agents. The normal Intake-model and batch wiring remain existing dependencies.
- **Qiyan/Max:** authenticated entry identity, redaction before raw LangGraph resume persistence, trace retention, deployment access controls. Source validation does not replace security controls.
- **Team:** local live Claude credentials/model test, live image accuracy comparison, full real-tax end-to-end demo, final report/video and each person's own AI-use disclosure.

See `ANUPAMA_REPORT.md` for the report contribution and `AI_DISCLOSURE.md` for Anupama's session-specific disclosure.


## Changed files (21)

| Area | Files |
|---|---|
| Shared contracts and state | `src/schemas.py`, `src/state.py`, new `src/communication.py`, new `src/evidence.py` |
| Existing graph/agent integration | `src/graph.py`, `src/agents/orchestrator.py`, `src/agents/intake.py`, `src/agents/extraction.py`, `src/agents/human.py`, `src/agents/computation.py` |
| Draft view and CLI | new `src/render.py`, `run.py` |
| Tests | new `tests/test_communication.py`, new `tests/check_draft_browser.py`, `tests/test_intake.py` (two expectations updated for implemented safe retraction/invalidation) |
| Documentation/demo | `README.md`, `docs/IMPLEMENTATION_NOTES.md`, new `docs/ANUPAMA_HANDOFF.md`, new `docs/ANUPAMA_REPORT.md`, new `docs/AI_DISCLOSURE.md`, new `demo/anupama_vision_case.json` |

The ignored `.venv` and generated `output/` artifacts are local runtime files, not source changes. Requirements were not edited. The branch remains uncommitted at `0451244`; nothing was pushed or submitted.
