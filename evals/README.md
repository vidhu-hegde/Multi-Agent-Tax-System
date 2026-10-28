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

## Live W-2 vision check

The cases above run offline, so a W-2 image goes to staff to type in. To check that Claude reads both
committed W-2 images correctly, add your own `ANTHROPIC_API_KEY` to `.env` and run:

```bash
python -m evals.live_vision_check
```

It reads `demo/w2_image_1.jpg` and `demo/w2_image_2.jpg` through the Extraction agent's `read_w2()` and
compares every field with `data/fixtures/w2_N_expected.json` (two requests). Without a key it is skipped.

| Date | Model | Result |
|---|---|---|
| 2026-10-27 | claude-sonnet-5-5 | 2 of 2 images, 16 of 16 fields each |

The full image-based clean run, `python run.py --case demo/anupama_vision_case.json`, also finished with
the W-2 read from its image (wages $18,000, withholding $1,500 on lines 1z and 25a).

## Iris memory/Intake evidence

Eight Iris-owned cases cover corrected adjustments, go-back, repetition/drift, scope disclosure at a
payment question, and the four dependent/Schedule 2/3 readiness gates. A gate case passes by retaining
the input and pausing for staff; it does not establish complete dependent/schedule output.

Actual restart evidence lives in the existing pytest workflow because the JSON runner uses an
in-memory saver and cannot prove process restarts:

```bash
python -m pytest tests/test_iris_integration.py tests/test_memory.py -v
```

`test_restart_correction_recomputes_and_preserves_audit_and_isolation` starts five separate Python
processes with one SQLite database, checks one recap after resume, correction history, updated payment
provenance, archived prior lines and isolation of another return. The partial case import initially
failed this test; Intake now checkpoints imported answers before interrupting on a missing field.
`test_uncertainty_is_visible_to_staff_and_resumes_the_same_question` verifies staff recovery through
`Sessions.resolve()` after reopening SQLite. Benchmark tests use provider doubles only.

## Cases still to add (owners)

- **Iris with Anupama/Max:** replace the dependent/Schedule 2/3 pause expectations with correct-output cases when the consumers land. The current collection, correction and restart checks are available above.
- **Anupama:** W-2 read from an image is now checked live (above); add a case for a second, harder image if useful.
- **Max:** real tax_math numbers on the clean case (standard deduction, senior deduction, Social Security, tax) once the server lands. Update `eval-case-1-clean-run`'s expected lines.
- **Juee:** rules edge dates (born 1 vs 2 January 1961), box counts, more out-of-scope items.
- **Qiyan:** Review catching seeded errors; SSN masking in tickets and traces.
