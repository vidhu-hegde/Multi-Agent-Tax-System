# Eval case 2: the taxpayer's wages disagree with the W-2 (HITL)

Harold Brennan, single, born 1958, tells Intake he earned "about $24,000". His W-2 shows **$26,450**.
Rules will not pick one for him: it raises a `document_conflict` escalation and the return pauses until a
staff member decides. This page shows how to trigger it and how to resolve it.

| | |
|---|---|
| Case file | [`data/fixtures/conflict_case.json`](../data/fixtures/conflict_case.json) |
| Documents | W-2 (typed values: wages $26,450, withheld $2,380, box 12 D $1,000), SSA-1099 ($19,800) |
| Escalation | `document_conflict:wages`, raised by Rules |
| Resolution | Staff continue (the W-2 is right) or stop the session |
| Result after continuing | `draft_ready`, refund **$1,460.25** |

## 1. Trigger the escalation

`run.py` needs `ANTHROPIC_API_KEY` in `.env` to start a session. This case itself makes no model calls,
since its W-2 values are typed in. To try it with no key, see [Without a key](#without-a-key).

```bash
docker compose up -d --build
docker compose run --rm app python run.py --case data/fixtures/conflict_case.json
```

Without Docker, start `python -m src.tax_math.server` in another terminal first, then run
`python run.py --case data/fixtures/conflict_case.json`.

The session stops on the escalation:

```text
Session id: return-…

[Escalation: document_conflict] The taxpayer said about $24000 in wages; the W-2s show $26450.00.
Reply 'continue' (with an optional note) to carry on, or 'stop' to end the session.
>
```

Press **Ctrl-D** here. The session is saved, and the decision belongs to staff. In a real
session the taxpayer would not be the one to resolve it.

## 2. Resolve it as staff

### On the dashboard

1. Open http://127.0.0.1:8000 (Docker starts it; without Docker run `python -m src.dashboard`).
2. Under **Needs a decision**, open the return. The ticket reads *Taxpayer's answer disagrees with a
   document* and shows the evidence: the stated wages ($24,000) and the W-2 amount ($26,450.00).
3. Check with the taxpayer. Here, Harold confirms the W-2 is right and $24,000 was a guess.
4. Type a note (for example *Harold confirmed the W-2 is right*), enter your staff ID, and choose
   **Continue the return**.
5. The page says *Recorded your decision* and the status becomes **Draft ready**. The decision, note and
   staff ID appear under *Decisions so far*. **Open the draft with sources** shows the finished draft.

### Or from the command line

```bash
python run.py --sessions                      # shows the session id and the ticket document_conflict:wages
python run.py --resolve <session id> document_conflict:wages --note "Harold confirmed the W-2 is right" --staff-id staff-7
```

```text
Resolved document_conflict:wages (continue). Session is now:
return-…  draft_ready
```

To see the draft: `python run.py --thread-id <session id> --html output/eval_case_2.html`. With Docker,
put `docker compose run --rm app` in front of each command. The HTML file then stays inside the `output`
volume, so open the draft from the dashboard instead.

### To stop instead

Choose **Stop the session** (or add `--stop` to `--resolve`). The ticket is recorded as stopped and the
return ends as **Stopped** with no draft. Use this when the difference can't be explained.

## 3. The finished draft

```text
    1z  Total wages                                   26,450.00
    6a  Social Security benefits                      19,800.00
    6b  Social Security benefits, taxable amount       6,497.50
     9  Total income                                  32,947.50
   11a  Adjusted gross income                         32,947.50
   12e  Standard deduction                            17,750.00
   13b  Additional deductions from Schedule 1-A        6,000.00
    14  Total deductions                              23,750.00
    15  Taxable income                                 9,197.50
    16  Tax                                              919.75
    18  Tax before credits                               919.75
    22  Tax after credits                                919.75
    24  Total tax                                        919.75
   25a  Federal income tax withheld from W-2           2,380.00
   25d  Total federal income tax withheld              2,380.00
    33  Total payments                                 2,380.00
    34  Overpayment                                    1,460.25
    37  Amount you owe                                     0.00
```

(Lines that are zero are left out above.)

| Line | How it is reached |
|---|---|
| 1z | The W-2 amount staff confirmed, **$26,450**, not the $24,000 Harold guessed |
| 6b | Provisional income $26,450 + ½ × $19,800 = $36,350. Above $34,000: 85% × $2,350 + $4,500 = **$6,497.50**, below the 85% cap of $16,830 |
| 12e, 13b | $15,750 + $2,000 (65 or older) = $17,750; senior deduction $6,000 |
| 16 | Taxable income $9,197.50 at 10% = **$919.75** |
| 34 | Withheld $2,380 − tax $919.75 = **$1,460.25** |

Had the return used Harold's $24,000, the refund would be wrong. That's why Rules escalates instead of
choosing.

## Without a key

- **Dashboard:** `python -m src.dashboard --demo` (with Docker, see "Demo dashboard" in the README) seeds
  a separate demo database offline. Open *demo-wage-conflict* and follow step 2.
- **Automated:** the eval case `eval-case-2-wage-conflict` in `evals/cases.json` runs this case, resolves
  the ticket as staff and checks the draft: `python -m evals.run_evals`.
