# Iris memory/accessibility segment for the team demo

Use these shots in the team's required 5-to-10-minute video. This file is the rehearsal script;
the recording still needs to be made. Use only synthetic data and a dedicated demo database. Real
tax functions, Schedule 2/3 consumers, MCP transport, Docker and Security/Review are merged. Dependent
output and live context measurements remain incomplete. A successful demo of memory does not establish
a complete tax system.

## Dialogue without model credentials

The existing `run.py` main requires an API key even for deterministic Intake. This direct invocation
uses its existing driver and the production graph, avoiding a duplicate UI or graph implementation.
Run from the repository root. For a new rehearsal choose a fresh database filename; retain that
filename and thread ID for every restart in the rehearsal. Reuse the same command to resume after Ctrl-C.

```bash
ANTHROPIC_API_KEY='' TAX_MATH_MCP_URL='' SILVERFILE_DB_PATH=output/iris-demo.sqlite .venv/bin/python -c '
from dataclasses import replace
from src.config import load_settings
from src.graph import build_graph
from src.memory import open_checkpointer, thread_config
from run import drive
settings = replace(load_settings(), anthropic_api_key="")
config = thread_config("iris-demo-return")
with open_checkpointer(settings) as saver:
    graph = build_graph(settings, saver)
    start = None if graph.get_state(config).values else {}
    drive(graph, "iris-demo-return", start)
'
```

1. Enter `single`, `none`, `1950-02-03`, then Ctrl-C. Close the terminal process completely.
2. Run the command again. Show the short recap and the **blindness** question; the birth date is not
   requested again. This demonstrates persistence across process restart.
3. Say `I was walking my dog earlier`. Show the same pending question without repeating the recap.
4. Enter `go back to filing status`, then `married filing jointly`. Show that the next question advances
   without repeating the recap. Enter `change filing status to single` to return to the original status
   without erasing history. A later restart summarizes the current confirmed status.
5. Enter `I'm not sure` at the pending blindness question. Show the volunteer wording and typed
   uncertainty pause. Ctrl-C to stop the taxpayer-side process before staff resolution.
6. In a separately labelled **staff** terminal, resolve the pause through the existing staff API:

```bash
ANTHROPIC_API_KEY='' TAX_MATH_MCP_URL='' SILVERFILE_DB_PATH=output/iris-demo.sqlite .venv/bin/python -c '
from src.sessions import open_sessions
with open_sessions() as sessions:
    summary = sessions.summary("iris-demo-return")
    print(summary.status)
    summary = sessions.resolve("iris-demo-return", summary.awaiting_ticket_id,
                               note="Volunteer will help clarify the question", resolved_by="demo-volunteer")
    print(summary.status, summary.pending_question)
'
```

7. Restart the taxpayer command. Show that the pending blindness question and prior confirmed values
   survived the human handoff. Answer blindness `no`, claimed-as-a-dependent `no`, dual-status `no`,
   document inventory `none`, and dependent count `1`. Then answer adjustments, Schedule 2,
   Schedule 3 nonrefundable credits, Schedule 3 other payments, and estimated payments with `0` each.
   Dependent name, relationship and test SSN then each have their own turn.
   Use `Synthetic Child`, `child`, and only the test-range value `901-12-3456`. Never enter a real SSN.
   A positive dependent count pauses after collection because downstream form integration is missing.
   Show that pause and explain what still needs to be implemented.

The restart, correction and handoff steps cover five §4.3 choices: one question at a time, plain
wording, repetition/drift tolerance, resumability and honest uncertainty. The dependent steps show
PII minimization. Screen-reader and UI accessibility still need human review.

## Automated evidence shots

```bash
.venv/bin/python -m pytest tests/test_merge_order.py -v
.venv/bin/python -m pytest tests/test_memory.py -v
.venv/bin/python -m pytest tests/test_intake.py -v
.venv/bin/python -m pytest tests/test_iris_integration.py -v
ANTHROPIC_API_KEY='' TAX_MATH_MCP_URL='' .venv/bin/python -m evals.run_evals
```

Show `test_restart_correction_recomputes_and_preserves_audit_and_isolation`: it checks five separate
Python processes, a partial-import checkpoint, one recap, corrections, archived old values and another
return's isolation. The staff-recovery integration test checks the production session interface.
Show the eight `iris-...` shared cases. The integrated suite has 25 cases: the three Schedule cases
now verify completed lines/refunds, while only the dependent case checks a missing-output handoff.
Fault tests reject lost dependent answers, wrong tickets and zeroed nonzero Schedule inputs.

For the context segment, show `docs/metrics.md`. Say: "The offline harness is verified. A team member
with model credits still needs to run the measured ON/OFF comparison after batch integration.
Vidhatri has offered to run it; the team has chosen ten Intake items per thread, with multi-turn
refinement pending." Synthetic test usage values are not benchmark results.

## Integrated draft/provenance shot without API credits

```bash
ANTHROPIC_API_KEY='' TAX_MATH_MCP_URL='' .venv/bin/python -m src.render --case data/fixtures/skeleton_case.json --output output/iris-offline-draft.html
```

Open `output/iris-offline-draft.html`, Tab to an amount and press Enter/Space to inspect its sources.
The fixture contains typed synthetic document values, so this shot makes no OCR call. It complements
the taxpayer-dialogue segment; it is Anupama's renderer over the team's merged graph, not an Iris UI.
The browser smoke check passed again on 2026-10-28 for keyboard/click disclosure, visible source
metadata and a 390px layout. It does not establish screen-reader compatibility.

The dialogue sequence above was also exercised offline on 2026-10-28, including corrections and
staff resolution across SQLite reopenings. Actual process-restart evidence comes from the separate
subprocess tests. Neither check produces the required recorded team video.

## Narration and final proofreading

Suggested Iris narration: "Every return has its own opaque ID. We save answers before asking the next
question, so stopping the process does not lose progress. A correction preserves the old answer for
audit and sends the affected work through fresh calculation and review. The short recap appears once
when we resume. When someone is unsure, we preserve their answers and ask a volunteer rather than
guessing." Show the matching actions while saying this.

Proofread [Iris's report contribution](../docs/IRIS_REPORT.md) and
[AI-use disclosure](../docs/AI_DISCLOSURE.md) before the team incorporates them. Known guardrail wording
follow-ups are recorded in [the current handoff](../docs/IRIS_HANDOFF.md). Automated rehearsal evidence
does not replace Iris's personal review or the team's final video.

Suggested team-video allocation: scope/architecture 1 minute; restart/correction dialogue 2 minutes;
volunteer handoff 1 minute; document/provenance/dashboard teammate segments 2 to 3 minutes; context
measurements and limitations 1 minute. Max/Vidhatri own assembling the final UI/video; Juee owns
wording approval and the final escalation demonstration.

## Final recording checklist

- Record this segment on the integrated PR revision; keep the full team video between 5 and 10 minutes.
- Show at least four choices through actions, not only test output. The restart, correction/drift and uncertainty steps cover them.
- Vidhatri's graded clean/HITL walkthroughs are `demo/eval_case_1.md` and `demo/eval_case_2.md`; use their finished-draft shots for the team portion.
- The Docker restart requested by Iris was already exercised with a live image W-2 in [Vidhatri's #17 review](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/17). Use the PR's Reviews tab for the exact recorded steps; no new key is required for this offline segment.
- Show the live token curve only once actual measurements exist. Leave it explicitly pending otherwise.
