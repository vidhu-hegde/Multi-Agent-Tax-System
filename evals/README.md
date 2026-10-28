# Eval cases

End-to-end cases that run through the real graph, offline (no API key). Every case also runs in
`pytest` via `tests/test_evals.py`.

```bash
python -m evals.run_evals                            # all cases, one line each
python -m evals.run_evals --case eval-case-2-wage-conflict
```

## Adding a case

Add an object to `cases` in `cases.json`. Set `owner` to your name and `area` to your part.

| Key | Meaning |
|---|---|
| `id` | Unique, kebab-case |
| `owner`, `area`, `description` | Who maintains it, which part it tests, and what it shows, in a sentence |
| `case_file` | Starting point, e.g. `data/fixtures/skeleton_case.json` |
| `answers` | Answers to add or change, e.g. `{"taxpayer_dob": "1965-03-01"}` |
| `remove_answers` | Answers to delete, so Intake asks for them (then script `replies`) |
| `documents` / `add_documents` | Replace the document list, or append to it |
| `document_values` | Change one document's typed values: `{"r-1": {"taxable_not_determined": true}}`. Use `null` to drop them (an image-only document) |
| `replies` | The taxpayer's replies to Intake's questions, in order |
| `staff` | Staff decisions for escalations, in order. `reason` must match the escalation; the rest is sent as the resolution, e.g. `{"reason": "document_conflict", "action": "continue", "note": "..."}`. For an unreadable document, add `"values": {...}` |
| `fault` | Inject a broken agent to exercise the loop bounds: `computation_6b_too_large`, `intake_never_finishes` |
| `expect` | What must come out (all optional, see below) |

`expect` keys:

| Key | Checks |
|---|---|
| `status` | Final status: `draft_ready`, `stopped`, `waiting_on_human`, ... |
| `escalations` | The escalation reasons the case paused on, in order. `[]` means none |
| `lines` | Amounts on the draft, e.g. `{"1z": "18000.00"}` (compared as numbers) |
| `hops` | The orchestrator's route, e.g. `["intake", "extraction", ...]` |
| `state` | Exact values of other state fields, e.g. `{"review_passes": 3}` |

A case fails if a reply or staff decision is left unused, if the session asks a question with no
scripted reply, or if an escalation arrives that the next staff decision didn't expect.

## Checked on every case

- A finished draft has a record for every in-scope document, and every line has a source.
- No SSN outside the 900–999 test range appears anywhere in the saved state.

## Cases still to add (owners)

- **Iris:** resume after restart, "go back" and "change X to Y" corrections, dependents.
- **Anupama:** W-2 read from an image (once there's an API key; mark it so it can be skipped offline).
- **Max:** real tax_math numbers on the clean case (standard deduction, senior deduction, Social Security, tax) once the server lands. Update `eval-case-1-clean-run`'s expected lines.
- **Juee:** rules edge dates (born 1 vs 2 January 1961), box counts, more out-of-scope items.
- **Qiyan:** Review catching seeded errors; SSN masking in tickets and traces.
