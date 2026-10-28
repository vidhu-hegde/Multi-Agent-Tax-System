# Context-window evaluation — Iris contribution

Offline review **2026-10-27**: no live measurement was requested or made. Iris has no API credits
available; live execution requires a team member with access. The remaining Iris offline harness/CLI
checks pass, including both strategy flags and PR #13's removal of sampling parameters. Synthetic
usage remains confined to tests. The historical missing-key attempts below are not new attempts.

Status on **2026-10-25: live measurements blocked**. `ANTHROPIC_API_KEY` is not configured.
Both commands below were executed and exited with code 1 and:

> Blocked: ANTHROPIC_API_KEY is not configured; no token measurements were made.

No actual model input-token measurements exist from this work. No flat-curve claim or numeric estimate
is substituted. The provider doubles in unit tests contain synthetic usage values solely to test the
measurement plumbing; they are **not** evaluation results.

| Sequential item | Strategy ON input tokens | Strategy OFF input tokens | Live outcome check |
|---|---|---|---|
| 1 | unavailable | unavailable | not run |
| 2 | unavailable | unavailable | not run |
| 3 | unavailable | unavailable | not run |
| 4 | unavailable | unavailable | not run |
| 5 | unavailable | unavailable | not run |
| 6 | unavailable | unavailable | not run |
| 7 | unavailable | unavailable | not run |
| 8 | unavailable | unavailable | not run |
| 9 | unavailable | unavailable | not run |
| 10 | unavailable | unavailable | not run |

## Reproduce once credentials are configured

Use the same environment, provider/model and ten synthetic inputs for both runs. Configure
`ANTHROPIC_API_KEY` and a model accessible to that account using the existing settings. No particular
model's availability was verified here. Never put a key on a command line or commit it.

```bash
.venv/bin/python -m src.memory --batch --thread-id iris-context-on \
  --output output/context_on.json
.venv/bin/python -m src.memory --batch --no-context-strategy --thread-id iris-context-off \
  --output output/context_off.json
```

Each command uses **one fresh SQLite thread for all ten sequential items**; ON and OFF use different
threads. A previously used thread id is rejected, so use new ids for reruns. Keep the configured
`SILVERFILE_DB_PATH` the same. Outputs include the thread id, model, strategy flag, timestamp,
per-item `input_tokens`, `model_calls` and `correct`. A false outcome saves the measurements but exits
nonzero. A missing usage report fails instead of estimating tokens. Transport/provider failure can
leave a partial thread; rerun with a fresh id. There are no automatic provider retries in this CLI.

The classifier is `src.agents.intake.classify_with_model`, also used by `make_intake`. ON sends a fixed
session summary plus the current item; OFF adds prior classifier dialogue. Each synthetic item asks
for volunteer help with unclear wording; the expected classification is `uncertain`. Each item currently
makes one model call. The harness nevertheless sums every new recorded call's actual input usage per
item. Raw usage is taken from `AIMessage.usage_metadata.input_tokens`, including whatever accounting
the configured provider reports. This work does not estimate unreported retry or cache billing.

After successful live runs, transfer the per-item values and outcome results into the table and plot
both series against item number. Compare first-to-last growth and outcomes; report the observed curve,
not an expected savings percentage. If the curve is not materially flatter, report that failure.

## Limits and coordination

Professor §4.5 refers to ten **invoices** and to a nonexistent invoice scenario in §4.2, while this
project prepares tax returns. The current harness uses ten sequential **synthetic Intake classifier
items**, not ten invoices or ten completed returns. That is a clearly labelled evaluation choice,
not a resolution of the assignment ambiguity. Iris/the team must confirm the intended evaluation unit
with the instructor or record an explicit team assumption before calling §4.5 complete.

`src/graph.py:run_batch` is still the team's stub. `build_graph(use_context_strategy=...)` currently
does not configure models. Vidhatri/Max need to wire the existing `make_intake` factory and connect the
batch hook; the integration example is in `IMPLEMENTATION_NOTES.md`. Extraction now makes live W-2
vision calls (#7/#13), so the historical statement that no other agent calls a model no longer applies.
Its provider usage is not aggregated by this Intake-only harness. The owners must use the same
boundary (or equivalent usage logging) so measurements eventually sum **all** model calls for the
agreed item. Vidhatri's live W-2 results in `evals/README.md` are extraction evidence, not the required
context ON/OFF experiment.

The offline suite verifies selective exclusion of older context, PII minimization, provider usage
propagation, missing-usage failure, validated outcomes and ten sequential items in two distinct
persisted threads. Those tests verify implementation behavior; they do not supply live measurements.
