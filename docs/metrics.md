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
# Strategy ON, then OFF: each writes output/context_{on,off}.json from a new thread (or pass --thread-id <new id>).
.venv/bin/python run.py --batch
.venv/bin/python run.py --batch --no-context-strategy
# The ten result rows and first-to-last growth for the table above; --out copies both raw files to commit.
.venv/bin/python -m src.metrics_table output/context_on.json output/context_off.json --out docs/metrics
# run.py --batch calls Iris's entry point, which also runs directly: .venv/bin/python -m src.memory --batch
```

Each command uses **one fresh SQLite thread for all ten sequential items**; ON and OFF use different
threads. A previously used thread id is rejected, so use new ids for reruns. Keep the configured
`SILVERFILE_DB_PATH` the same. Outputs include the thread id, model, strategy flag, timestamp,
per-item `input_tokens`, `model_calls` and `correct`, and each item's three per-turn results (reply,
expected label, model label, validity, input tokens). A false outcome saves the measurements but exits
nonzero. A missing usage report fails instead of estimating tokens. Transport/provider failure can
leave a partial thread; rerun with a fresh id. There are no automatic provider retries in this CLI.

The classifier is `src.agents.intake.classify_with_model`, also used by `make_intake`. ON sends a fixed
session summary plus the current turn; OFF adds all prior classifier dialogue in the thread. Both runs
read the same ten items from `evals/context_items.json`, in the same order, with the same fixed seed
answer (`filing_status = single`, set once before the first turn and never changed).

Each item is a short exchange of three unclear replies to one Intake question: muddled answers,
corrections ("actually…") and requests to go back that do not use Intake's `go back to <field>` or
`change <field> to <value>` commands, plus replies that need a volunteer, ask for advice, disclose
out-of-scope income or a 1099-R whose taxable amount is not determined, or suggest a third party is
steering the return. Each turn is sent as production Intake sends it, `{"question", "reply"}`, with
Intake's own question text. A test checks that no guardrail rule, command or field parser would handle
any turn, so in a real session every one reaches the model. Each turn has one expected label decidable
from that turn alone (`null` means re-ask the question), so ON is not penalised for leaving out earlier
dialogue: 15 `null`, 8 `uncertain`, 2 each of `advice_request`, `exploitation_concern` and
`out_of_scope`, and 1 `1099r_taxable_not_determined`.

A turn is correct when the model's output is valid JSON with a supported reason and matches its
expected label; malformed JSON or an unsupported reason still safely escalates in Intake, but is not
correct here. An item is correct only when all three turns are. Each turn makes one model call, so an
item makes three; its `input_tokens` is the sum of those calls' actual usage, taken from
`AIMessage.usage_metadata.input_tokens`, including whatever accounting the configured provider reports.
This work does not estimate unreported retry or cache billing.

Vidhatri's earlier live run on `claude-sonnet-5-5` used the previous single-turn items (one fixed
sentence per item): ON 207 input tokens flat, OFF 207 → 594. It was a preliminary run of a different item
set; it is not entered in the table above and is not comparable with these items.

After successful live runs, transfer the per-item values and outcome results into the table and plot
both series against item number. Compare first-to-last growth and outcomes; report the observed curve,
not an expected savings percentage. If the curve is not materially flatter, report that failure.

## Limits and coordination

Professor §4.5 refers to ten **invoices** in this tax-return assignment. Vidhatri recorded the team's
working interpretation on [PR #15](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/15#issuecomment-6473238861): ten sequential Intake items in one return thread, not ten returns sharing an identity.
She proposed short multi-turn exchanges with unclear replies, corrections and go-back, keeping Iris's
classifier harness. Those items are now in `evals/context_items.json` (three turns per item); this team
assumption is not an instructor clarification.

`python run.py --batch [--no-context-strategy]` runs this context benchmark (it calls the `src.memory`
entry point; [PR #21](https://github.com/vidhu-hegde/Multi-Agent-Tax-System/pull/21)), and
`python -m src.metrics_table` turns the two result files into the table above and copies the raw JSON
to `docs/metrics/`. No measured result JSONs are committed yet; the Reproduce section has the commands to
obtain and retain them. Vidhatri offered to perform
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
