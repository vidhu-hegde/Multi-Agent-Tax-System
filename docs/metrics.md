# Context-window evaluation — Iris contribution

The 2026-10-28 audit ran offline. No live measurement was requested or made. Iris has no API credits
available; live execution requires a team member with access. The remaining Iris offline harness/CLI
checks pass, including both strategy flags and PR #13's removal of sampling parameters. Both modes
also reject missing usage, incorrect reasons, malformed JSON and unsupported classifications. Synthetic
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
for volunteer help with unclear wording; the expected classification is `uncertain`. A valid
`uncertain` response is required for a correct outcome. Malformed JSON or an unsupported reason still safely escalates in Intake, but no longer counts as correct in this benchmark. Each item
currently makes one model call. The harness nevertheless sums every new recorded call's actual input
usage per item. Raw usage is taken from `AIMessage.usage_metadata.input_tokens`, including whatever accounting
the configured provider reports. This work does not estimate unreported retry or cache billing.

After successful live runs, transfer the per-item values and outcome results into the table and plot
both series against item number. Compare first-to-last growth and outcomes; report the observed curve,
not an expected savings percentage. If the curve is not materially flatter, report that failure.

## Limits and coordination

Professor §4.5 refers to ten **invoices** in this tax-return assignment. Vidhatri recorded the team's
working interpretation on [PR #15](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/15#issuecomment-6473238861): ten sequential Intake items in one return thread, not ten returns sharing an identity.
She proposed short multi-turn exchanges with unclear replies, corrections and go-back, keeping Iris's
classifier harness. The current harness still uses one classifier call per item. The multi-turn item
refinement remains to be integrated; this team assumption is not an instructor clarification.

`src/graph.py:run_batch` is still a stub on merged main. Max's open [PR #21](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/21)
(`max/batch-metrics`, reviewed head `684161c`) prepares `run.py --batch` wiring and a results-table
generator. Its current diff contains no measured result JSONs; it prepares the commands to obtain and
retain them. Keep that integration with its owner. Vidhatri offered to perform
the live ON/OFF run after integration. Iris does not need to obtain more credits.

For the agreed classifier-only items, record every classifier call per item; a multi-turn item must
sum its new call IDs. If an item includes image extraction, its usage must also be instrumented and
included. The current harness does not call or account for W-2 extraction and makes no full-return
usage claim. The normal return graph still uses deterministic Intake; its unused strategy parameter
must not be presented as production-wide context reduction. The existing W-2 live checks are separate
extraction evidence, not context-window measurements.

After integration, use the owner-provided `python run.py --batch [--no-context-strategy]` commands.
The direct `src.memory` commands above remain available now. Retain the actual raw result JSONs in
a tracked evidence directory, add the ten rows and a two-series curve, and report outcome validity,
first-to-last growth, model, fresh thread IDs and dates. Do not fill the table from test doubles.

The offline suite verifies selective exclusion of older context, PII minimization, provider usage
propagation, missing-usage failure, validated outcomes and ten sequential items in two distinct
persisted threads. Those tests verify implementation behavior; they do not supply live measurements.
