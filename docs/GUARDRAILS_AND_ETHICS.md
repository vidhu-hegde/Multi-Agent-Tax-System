# Guardrails and ethics

Owner: **Juee Patil** (focus area: Guardrails and ethics).
Code: `src/guardrails.py`, scope checks in `src/agents/rules.py`. Policy: `data/policy.md`.
Tests: `tests/test_guardrails.py`.

SilverFile talks to older taxpayers about money. Brief section 2 says breaching its rules "is the
assignment", so each guardrail below has one place it is enforced, one policy section that explains
it, and a test that proves it.

## What each guardrail does

| Guardrail (brief) | Where it is enforced | Policy | Test |
|---|---|---|---|
| Never give tax advice (2, 4.4 #4) | `guardrails.classify_reply` on every Intake turn; Intake declines and raises `advice_request` | `#advice` | `test_replies_get_the_expected_escalation[advice_request-…]` |
| Notice financial exploitation and third-party pressure (4.4 #6) | `guardrails.classify_reply`, checked first on every turn | `#exploitation` | `…[exploitation_concern-…]`, `test_exploitation_outranks_advice` |
| Out-of-scope disclosures escalate (3.3, 4.4 #1) | `guardrails.scope_disclosure` | `#scope` | `…[out_of_scope-…]` |
| Standard Deduction Chart exceptions escalate (3.2) | `rules.CHART_EXCEPTIONS` | `#standard-deduction-exceptions` | `test_chart_exceptions_escalate_as_out_of_scope` |
| W-2 values outside scope escalate | `rules.w2_scope_tickets` | `#w2-scope-signals` | `test_w2_scope_signals_escalate` |
| 1099-R box 2b always escalates (4.4 #3) | `guardrails.R1099_2B` (what the person says) and Rules (the document) | `#1099r-box-2b` | `…[1099r_taxable_not_determined-…]` |
| Honest uncertainty (4.3) | `guardrails.UNCERTAIN` | `#uncertainty` | `…[uncertain-…]` |
| Every rule decision is grounded and cited | Every `RuleDecision.citation` points at a `policy.md` section | all | `test_every_rules_citation_has_a_policy_section` |

## Design decisions and why

**1. Named rules instead of a bare keyword list.** The first version of Intake flagged any reply
containing "roth", "should I" or "file separately". That wrongly escalated ordinary answers such as
"My 1099-R is from a Roth IRA" (in scope), "Should I type the date with dashes?" (a question about the
form) and "We file separately" (an answer). Each false alarm interrupts an anxious taxpayer and takes
staff time. Each rule now has a name, so a ticket can show which rule fired, and the false positives
are kept as regression tests.

**2. Advice needs a decision AND a tax topic.** Transcription and arithmetic are not advice;
optimisation and planning are (brief section 2). So a reply counts as advice when it asks for a
decision or recommendation ("should I", "is it better", "what's the best way", "do you recommend")
about a tax choice (filing jointly or separately, deducting, converting, withdrawing, paying less). A
question about how to fill in the form is not advice: Intake simply asks again.

**3. Safety outranks everything.** Exploitation is checked before advice, scope and uncertainty. If a
reply contains both ("My son says I should file jointly so the refund goes to his account"), it becomes
an exploitation ticket. A false alarm costs a staff member a minute; a miss can cost a client their
refund. Elder financial abuse often travels through tax refunds (brief 4.4).

**4. Notice and stop; don't accuse.** The taxpayer hears only "Thank you. I've asked a member of staff
to look at this before we go on." SilverFile doesn't ask why, repeat the concern back, or name anyone,
because the third party may be in the room. The ticket holds the exact words for staff, who are asked
to speak with the client privately.

**5. A stated legal authority is respected, but refund routing is still checked.** Brief 4.4 flags "a
third party answering on the taxpayer's behalf without a stated authority". Someone who says they hold
power of attorney, guardianship or a conservatorship may answer. Redirecting the refund away from the
taxpayer still escalates, whoever says it.

**6. A denial is not a disclosure.** "I do not have foreign income" and "no crypto, no business income"
don't escalate. The check looks back within the same clause for a negation.

**7. The chart exceptions are scope decisions, made by Rules.** Brief 3.2 says the Standard Deduction
Chart does not apply if the taxpayer can be claimed as a dependent, if a separately filing spouse
itemizes, or if the taxpayer was a dual-status alien, "all three are escalation conditions". Intake
only records the yes or no. Rules turns a "yes" into an `out_of_scope` ticket and records
`standard_deduction_chart_applies = False`, citing the policy. Before this change those answers paused
on a generic "needs integration" ticket that didn't say why.

**8. Guardrails never do tax.** `src/guardrails.py` reads words and returns a reason. It never
calculates, picks a filing status or decides eligibility. This keeps Intake within its constraint
("must not perform arithmetic or interpret tax rules").

**9. The policy file is checked by tests.** `data/policy.md` is the reference corpus Rules must cite.
Tests fail if Rules cites a section that doesn't exist, if an escalation reason has no policy entry, or
if a 2025 figure from the brief goes missing.

## Measured behaviour

`tests/test_guardrails.py` holds a labelled set of taxpayer replies: 20 ordinary answers and 32 that
must escalate, across five reasons. It includes every example from the brief and every phrase used in
the team's existing tests. All are classified correctly. The false-positive cases from the old keyword
lists are part of the set.

This is a hand-written set, not real taxpayers. It shows the rules do what the policy says, not how
they would perform on real conversations. Intake also has an optional model fallback for replies that
don't parse (`make_intake(model)`). It can only return an approved escalation reason or none, and its
live accuracy has not been measured.

## Known limits and failure modes

- **Wording we didn't anticipate.** Lexical rules miss paraphrases ("my boy looks after the bank
  stuff"). The model fallback only runs on replies that don't parse as an answer, so a valid answer with
  a worrying remark attached is only caught if a rule matches. Mitigation: grow the labelled set from
  demo sessions; staff can also flag a session by hand.
- **Over-flagging.** Broad rules ("I'm answering for my mother") will sometimes stop an honest helper.
  We accept this trade-off on purpose (decision 3). Staff can continue in one click.
- **Continuing past a scope ticket.** Staff can currently resolve any ticket with "continue". For
  `out_of_scope` and 1099-R box 2b this lets a draft be produced that ignores the problem. Policy
  `#1099r-box-2b` says staff must enter the taxable amount or stop. Enforcing that in the human node needs
  Vidhatri (owner of `src/agents/human.py`); raised with her.
- **Wage-estimate tolerance.** A difference of $500 or less between the stated wages and the W-2 is
  treated as rounding, because Intake asks for an estimate. This is a recorded team decision
  (`#document-conflicts`), not a rule from the brief.
- **W-2 box 12 list.** Taken from the team's notes and still to be checked against the IRS 2025 W-2/W-3
  instructions.
- **English only.** The rules assume English replies.

## AI-use disclosure (Juee)

Juee used Claude (Anthropic) to work through the brief, read the existing repository and draft the
guardrails work. Claude proposed the named-rule design for `src/guardrails.py`, wrote the first version
of `data/policy.md` from the brief's figures and the team's notes, added the Standard Deduction Chart
and W-2 scope checks to the Rules agent, and wrote `tests/test_guardrails.py` and this section. It also
spotted the false positives in the earlier keyword lists by running ordinary answers through them. Juee
reviewed each rule and the policy wording, chose the trade-offs (safety ranked first, stated authority
respected), ran the full test suite locally and committed the work. Policy figures were checked against
the brief, not against IRS publications, and the W-2 box 12 list still needs that check.
