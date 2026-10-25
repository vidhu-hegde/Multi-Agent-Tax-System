# Iris memory/accessibility segment for the team demo

This is a **rehearsal script**, not a recorded demo. Integrate these shots into the team's required
5–10 minute video. Use only synthetic data and a dedicated demo database. Do not treat the current
stub tax output as a correct completed return.

## Live dialogue without model credentials

The existing `run.py` main requires an API key even for deterministic Intake. This direct invocation
uses its existing driver and the production graph, avoiding a duplicate UI or graph implementation.
Run from the repository root. Reuse the same command to resume after Ctrl-C.

```bash
SILVERFILE_DB_PATH=output/iris-demo.sqlite .venv/bin/python -c '
from src.config import load_settings
from src.graph import build_graph
from src.memory import open_checkpointer, thread_config
from run import drive
settings = load_settings()
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
3. Say `I was walking my dog earlier`. Show the same pending question and retained recap.
4. Enter `go back to filing status`, then `married filing jointly`. Show the changed status in the
   recap. Enter `change filing status to single` to return to the original status without erasing history.
5. Enter `I'm not sure` at the pending blindness question. Show the volunteer wording and typed
   uncertainty pause. Ctrl-C to stop the taxpayer-side process before staff resolution.
6. In a separately labelled **staff** terminal, resolve the pause through the existing staff API:

```bash
SILVERFILE_DB_PATH=output/iris-demo.sqlite .venv/bin/python -c '
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
   survived the human handoff. Continue with `no`, `no`, `no`, `none`, `1` to reach the later dependent
   questions (Schedule 1 and both Schedule 3 totals, Schedule 2, and estimated payments each need an
   explicit `0` as they appear). Dependent name, relationship and test SSN each have their own turn.
   Use `Synthetic Child`, `child`, and only the test-range value `901-12-3456`. Never enter a real SSN. A positive dependent count currently pauses for downstream form integration after collection; show that honest limit rather than claiming a completed dependent return.

The first pause plus correction/restart/handoff segment demonstrates at least four §4.3 choices:
one question at a time, plain wording, repetition/drift tolerance, resumability and honest uncertainty.
The dependent shots also show deliberate PII minimization. No screen-reader/UI certification is claimed.

## Automated evidence shots

```bash
.venv/bin/python -m pytest tests/test_merge_order.py -v
.venv/bin/python -m pytest tests/test_memory.py -v
.venv/bin/python -m pytest tests/test_intake.py -v
```

Show `test_multiple_real_process_restarts_and_thread_isolation`, correction revalidation and
`test_dependents_are_collected_as_separate_questions`. For the context segment, show `docs/metrics.md`;
if live measurements remain blocked, say so. Synthetic test usage values are not benchmark results.

Suggested team-video allocation: scope/architecture 1 minute; restart/correction dialogue 2 minutes;
volunteer handoff 1 minute; document/provenance/dashboard teammate segments 2–3 minutes; context
measurements and limitations 1 minute. Max/Vidhatri own assembling the final UI/video; Juee owns
wording approval and the final escalation demonstration.
