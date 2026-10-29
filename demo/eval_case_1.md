# Eval case 1: a clean run, with the W-2 read from its image

Margaret Ellis, single, born 1957, brings a W-2 as a photo plus a 1099-INT, an IRA 1099-R and an SSA-1099.
SilverFile reads the W-2 image with Claude, applies the 2025 rules, computes every number through the
tax_math MCP server, reviews the draft and finishes it. **No escalation is raised.**

| | |
|---|---|
| Case file | [`demo/anupama_vision_case.json`](anupama_vision_case.json) |
| W-2 image | [`demo/w2_image_1.jpg`](w2_image_1.jpg) (synthetic; test-range SSN) |
| Needs | `ANTHROPIC_API_KEY` in `.env` (one model call, to read the W-2) |
| Path | Intake → Extraction (vision) → Rules → Computation (MCP) → Review → draft |
| Result | `draft_ready`, refund **$2,455.50** |

## Run it

**With Docker** (tax-math starts with the stack):

```bash
cp .env.example .env              # then add your ANTHROPIC_API_KEY
docker compose up -d --build
docker compose run --rm app python run.py --case demo/anupama_vision_case.json
```

**Without Docker**, in two terminals:

```bash
python -m src.tax_math.server     # terminal 1: the tax_math MCP server on http://localhost:8001/mcp
python run.py --case demo/anupama_vision_case.json --html output/eval_case_1.html   # terminal 2
```

The case file already answers every Intake question, so the session runs to the end without asking anything.

## What you should see

```text
Session id: return-…

Draft 1040-SR (draft_ready)
    1z  Total wages                                   18,000.00
    2a  Tax-exempt interest                               80.00
    2b  Taxable interest                                 420.00
    4a  IRA distributions                              6,000.00
    4b  IRA distributions, taxable amount              6,000.00
    6a  Social Security benefits                      22,000.00
    6b  Social Security benefits, taxable amount       5,775.00
     9  Total income                                  30,195.00
   11a  Adjusted gross income                         30,195.00
   12e  Standard deduction                            17,750.00
   13b  Additional deductions from Schedule 1-A        6,000.00
    14  Total deductions                              23,750.00
    15  Taxable income                                 6,445.00
    16  Tax                                              644.50
    18  Tax before credits                               644.50
    22  Tax after credits                                644.50
    24  Total tax                                        644.50
   25a  Federal income tax withheld from W-2           1,500.00
   25b  Federal income tax withheld from 1099            600.00
   25d  Total federal income tax withheld              2,100.00
    26  Estimated tax payments                         1,000.00
    33  Total payments                                 3,100.00
    34  Overpayment                                    2,455.50
    37  Amount you owe                                     0.00
```

(Lines that are zero, such as 3a/3b, 5a/5b and the Schedule 2/3 lines 17, 20, 23 and 31, are left out above.)

## Why these numbers are right

| Line | How it is reached |
|---|---|
| 1z, 25a | Read from the W-2 image: box 1 wages $18,000, box 2 withheld $1,500 |
| 6b | Provisional income $18,000 + $420 + $80 + $6,000 + ½ × $22,000 = $35,500. Above the $34,000 second base: 85% × $1,500 + $4,500 = **$5,775**, below the 85% cap of $18,700 |
| 12e | 2025 single standard deduction $15,750 + $2,000 for age 65 or older = **$17,750** |
| 13b | Senior deduction (Schedule 1-A): $6,000, since MAGI is far below $75,000 |
| 16 | Taxable income $6,445 in the 10% bracket of the rate schedule = **$644.50** |
| 34 | Payments $3,100 − tax $644.50 = **$2,455.50** |

## What to check

- **The W-2 really came from the image.** On the dashboard (http://127.0.0.1:8000), open the session: the
  W-2's record says it was read from `demo/w2_image_1.jpg`, and *View image* shows the photo. The provenance
  records the image's SHA-256, the model and the API response id.
- **Every computed number came from an MCP tool call.** In the draft with sources (the dashboard's *Open the
  draft with sources*, or `output/eval_case_1.html`), click any computed amount, for example line 16: it shows
  the tool (`tax_math.tax_from_schedule`), its inputs, and the server it ran on (`via http://…/mcp`).
- **No escalations:** the session is *Draft ready* with no tickets, and `python run.py --sessions` lists it as
  `draft_ready`.

## Without a key

The same return with the W-2 typed in instead of photographed runs offline as the eval case
`eval-case-1-clean-run` (`data/fixtures/skeleton_case.json`):

```bash
python -m evals.run_evals         # or: docker compose run --rm app python -m evals.run_evals
```

**Already run, nothing to install:** [`traces/demo_eval-case-1-clean-run_draft.html`](../traces/demo_eval-case-1-clean-run_draft.html)
is this return's finished draft. Open it in a browser and click any amount for its sources.
[`traces/demo_eval-case-1-clean-run_state.json`](../traces/demo_eval-case-1-clean-run_state.json) is the full saved
state, with every line's provenance.

`python -m src.dashboard --demo` shows it as *demo-clean-return*. To check the image reading on its own:
`python -m evals.live_vision_check` (needs the key) reads both W-2 images and compares all 16 fields.
