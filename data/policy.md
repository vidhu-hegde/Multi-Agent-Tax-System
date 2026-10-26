# SilverFile policy reference (tax year 2025)

Owner: Juee (Guardrails and ethics). This is the reference corpus the agents are grounded in. Every
`RuleDecision` cites one section below by its id (for example `policy.md#standard-deduction`), and every
escalation reason maps to a section. Section ids are stable: rename a heading, never its id.

Source: the Kushim SilverFile brief (sections 2, 3.2, 3.3, 4.3 and 4.4) and the team's decisions in
`docs/IMPLEMENTATION_NOTES.md`. SilverFile is a preparation aid. Nothing here is tax advice.

---

<a id="non-negotiables"></a>
## 1. Non-negotiable rules

1. **Never file anything.** The output is a draft return plus an audit record for a human.
2. **Never give tax advice.** See [advice](#advice).
3. **Never show a dollar amount without a source.** Every amount on the draft carries provenance. When an
   amount is not calculated, it is recorded as "direct user input" with who entered it and when.
4. **Always hand off to a human** in the conditions in [escalation](#escalation).
5. **Only the in-scope return profile** in [scope](#scope). Everything else escalates.
6. **Only test SSNs** (900–999 prefix). See [ssn-test-range](#ssn-test-range).

---

<a id="1040sr-eligibility"></a>
## 2. Form 1040-SR eligibility

- The taxpayer must have been born **before 2 January 1961**.
- On a joint return (MFJ), **only one spouse** needs to meet this.
- There is **no income limit**.
- If neither person qualifies, the return is out of scope: escalate `out_of_scope`
  (`not_1040sr_eligible`).

<a id="filing-status"></a>
## 3. Filing status

The five statuses are Single, Married filing jointly (MFJ), Married filing separately (MFS), Head of
household (HOH) and Qualifying surviving spouse (QSS).

SilverFile records the status the taxpayer gives. It does not choose one for them. Escalate
`filing_status_ambiguity` when:

- a spouse died **during 2025**: MFJ vs QSS vs Single needs a person to decide;
- QSS is chosen but the spouse did not die in 2023 or 2024;
- MFJ is chosen but the taxpayer says the spouse has died.

<a id="standard-deduction"></a>
## 4. Standard deduction (line 12e)

1. Count the boxes checked on **line 12d**, one each for: taxpayer 65 or older, taxpayer blind,
   spouse 65 or older, spouse blind. Spouse boxes count only on a joint return.
2. Read the Standard Deduction Chart printed on the 1040-SR.

| Filing status | 2025 base amount | Each checked box adds |
|---|---|---|
| Single | $15,750 | $2,000 |
| Head of household | $23,625 | $2,000 |
| Married filing jointly | $31,500 | $1,600 |
| Qualifying surviving spouse | $31,500 | $1,600 |
| Married filing separately | $15,750 | $1,600 |

$2,000 applies when unmarried and not a surviving spouse; otherwise $1,600. The arithmetic is done by
the `tax_math` tools, never by an agent.

<a id="standard-deduction-exceptions"></a>
### 4.1 When the chart does not apply (escalate)

The chart does not apply, and SilverFile escalates `out_of_scope`, if:

| Intake answer | Ticket key |
|---|---|
| Someone else can claim the taxpayer as a dependent (`taxpayer_claimed_dependent` = yes) | `taxpayer_is_a_dependent` |
| Filing separately and the spouse itemizes (`spouse_itemizes` = yes) | `mfs_spouse_itemizes` |
| The taxpayer was a dual-status alien in 2025 (`dual_status_alien` = yes) | `dual_status_alien` |

"Not sure" to any of these questions escalates as `uncertain`.

<a id="senior-deduction"></a>
## 5. Enhanced senior deduction (Schedule 1-A, line 13b)

- **$6,000 per qualifying person aged 65 or older**; $12,000 when both spouses qualify on a joint return.
- Phases out above **$75,000 MAGI** ($150,000 joint) at **6% of the excess, per qualifying person**.
- It is **in addition to** the extra standard deduction for age in section 4. Treating them as the same
  thing is a common mistake.
- Applies to tax years 2025–2028.
- Within SilverFile's scope, MAGI equals AGI (line 11a). Anything that would need add-backs is out of scope.
- The team counts no qualifying people on an MFS return (`src/agents/rules.py`), because the deduction
  requires a joint return when married.

<a id="taxable-social-security"></a>
## 6. Taxable Social Security (line 6b)

- Provisional income = AGI without Social Security benefits + tax-exempt interest + half of the benefits.
- Base amounts: $25,000 (single and other statuses) / $32,000 (MFJ).
- Second-tier amounts: $34,000 / $44,000.
- **Ordering:** 6b needs every other income line first, and 6b then feeds total income and AGI.
  The orchestrator must run it after the other income lines.

<a id="document-conflicts"></a>
## 7. Conflicts between what the taxpayer says and a document

- When the taxpayer's answer and a document disagree, SilverFile does not pick one. It escalates
  `document_conflict` and staff decide.
- **Wages:** Intake asks "About how much did you earn from jobs?" Because the question asks for an
  estimate, a difference of **$500 or less** from the W-2 box 1 total is treated as rounding, not a
  conflict. A larger difference escalates. "Not sure" is a valid answer and skips the check.
- The tolerance is a team decision, recorded here so it can be reviewed. It applies only to the wage
  estimate question. Exact figures (withholding, document amounts) have no tolerance.

<a id="scope"></a>
## 8. Scope

**In scope**

- Amounts from W-2, SSA-1099, 1099-R, 1099-INT and 1099-DIV.
- All five filing statuses.
- Standard deduction only, plus the Schedule 1-A senior deduction.
- Schedules 1, 2 and 3: the taxpayer types the totals in directly.

**Out of scope: escalate `out_of_scope`, never attempt**

| Topic | Examples Intake listens for (`src/guardrails.py`) |
|---|---|
| Itemized deductions (Schedule A) | "itemized deductions", "Schedule A" |
| Self-employment or business income (Schedule C), including 1099-NEC | "1099-NEC", "self-employed", "freelance", "my own business", "1099-K" |
| Rental income (Schedule E) | "rental income", "rental property", "Schedule E" |
| Capital gains needing Schedule D | "capital gains", "Schedule D", "sold some stock", "1099-B" |
| Digital assets | "digital assets", "crypto", "bitcoin", "NFT" |
| Foreign income or accounts | "foreign income", "foreign bank account", "overseas account", "FBAR" |
| Amended or prior-year returns | "amended return", "prior-year return", "my 2023 return" |
| State returns | "state return" |
| Not eligible for 1040-SR | see [1040sr-eligibility](#1040sr-eligibility) |
| Chart does not apply | see [standard-deduction-exceptions](#standard-deduction-exceptions) |
| W-2 values outside scope | see [w2-scope-signals](#w2-scope-signals) |

A clear denial is not a disclosure: "I do not have foreign income" does not escalate.

<a id="1099r-box-2b"></a>
### 8.1 1099-R with box 2b "taxable amount not determined"

Always escalate `1099r_taxable_not_determined`, whatever else is known. Working out the taxable part
needs the Simplified Method or the General Rule. Neither is in scope, and neither is in `tax_math`.

**Resolution rule:** staff may continue only after entering the taxable amount themselves (recorded as
direct input by that staff member), or stop the return. Continuing without an amount must not produce
a draft that silently treats the distribution as fully taxable or fully tax-free.

<a id="w2-scope-signals"></a>
### 8.2 W-2 values that put a return out of scope

Recorded by the team in `docs/IMPLEMENTATION_NOTES.md` (W-2 record fields). Each one escalates
`out_of_scope` with key `<document id>:<field>`. To verify against the IRS *2025 General Instructions for
Forms W-2 and W-3* before submission.

| W-2 field | Escalate when | Why |
|---|---|---|
| Box 13 statutory employee | checked | Statutory employee wages go on Schedule C |
| Box 8 allocated tips | more than 0 | Form 4137 |
| Box 10 dependent care benefits | more than 0 | Form 2441 |
| Box 5 Medicare wages | more than $200,000 | Additional Medicare Tax, Form 8959 |
| Box 12 code A, B, M, N | present | Uncollected Social Security/Medicare tax, Schedule 2 |
| Box 12 code K, Z | present | Excise or additional tax |
| Box 12 code Q | present | Nontaxable combat pay election |
| Box 12 code R, W | present | Archer MSA / HSA forms |
| Box 12 code T | present | Adoption benefits, Form 8839 |
| Box 12 code H, FF, GG, HH, II | present | Need forms or judgement outside scope |
| Box 12 any other unlisted code | present | Escalate as `uncertain` |

No action: box 12 codes C, D, E, F, G, S, AA, BB, DD, EE, J, L, P, V, Y; the retirement-plan and
third-party-sick-pay checkboxes.

---

<a id="advice"></a>
## 9. Tax advice, planning and optimisation

**Transcription and arithmetic are not advice. Optimisation and planning are advice.**

| Not advice: SilverFile answers or simply asks again | Advice: SilverFile declines and escalates `advice_request` |
|---|---|
| "What does 'filing status' mean?" | "Would I pay less if we filed separately?" |
| "Should I type the date with dashes?" | "Should I convert my IRA to a Roth?" |
| "My 1099-R is from a Roth IRA." | "Can I deduct my medications?" |
| "We file separately." (an answer) | "How can I get a bigger refund?" |

What SilverFile says: *"That's a question for a volunteer preparer. I can't give tax advice, but I've
noted it so they can help."* It then returns to the same question. The taxpayer's question is saved in
the ticket so the preparer can follow up. Kushim already offers advice services, so this is also the
hand-off point to them.

<a id="exploitation"></a>
## 10. Financial exploitation and third-party pressure

Elder financial abuse often travels through tax refunds. SilverFile is not asked to judge anyone. It is
asked to **notice and stop**. Escalate `exploitation_concern` when the taxpayer's words suggest:

- the refund is going to an account that is not theirs, or one they cannot describe;
- someone else controls their money, or is telling them what to answer;
- pressure, fear or threats ("he won't let me", "I'll get in trouble");
- a scam contact ("someone called and said I owe the IRS");
- someone else is answering for them **without stating an authority**.

A stated legal authority (power of attorney, legal guardian, conservator, court-appointed or authorized
representative) means a third party may answer for the taxpayer. Refund-routing warning signs still
escalate even then.

What SilverFile says: *"Thank you. I've asked a member of staff to look at this before we go on."* It
does not accuse anyone, ask why, or repeat the concern back. Staff should speak with the client directly
and privately before continuing.

Safety is ranked first: if a reply contains both an advice question and an exploitation sign, it is
escalated as exploitation. A false alarm costs a staff member a minute; a miss can cost a client their
refund.

<a id="uncertainty"></a>
## 11. Honest uncertainty

"I'm not sure — let me flag this for a volunteer" is a correct answer. When the taxpayer says they are
not sure, don't know or can't remember, and the question needs a definite answer, SilverFile escalates
`uncertain` rather than guessing. Exception: the wage estimate accepts "not sure" (section 7).

<a id="ssn-test-range"></a>
## 12. Social Security numbers

- Only IRS test SSNs are accepted: the first three digits must be 900–999 (`901-12-3456`). Any other SSN
  is rejected with a plain explanation, so a real SSN can never be entered.
- SilverFile asks for an SSN only where the form needs one (dependents). It never asks for the
  taxpayer's own SSN in the dialogue.
- An SSN volunteered where it was not asked for is removed from saved answers, tickets and model
  context (`[SSN removed]`). W-2 records keep only the last four digits.

<a id="escalation"></a>
## 13. Escalation reasons

| Reason (`src/schemas.py`) | Brief | Raised by | Policy section |
|---|---|---|---|
| `out_of_scope` | 4.4 #1 | Rules, Intake | [scope](#scope) |
| `document_conflict` | 4.4 #2 | Rules | [document-conflicts](#document-conflicts) |
| `1099r_taxable_not_determined` | 4.4 #3 | Rules, Intake | [1099r-box-2b](#1099r-box-2b) |
| `advice_request` | 4.4 #4 | Intake | [advice](#advice) |
| `filing_status_ambiguity` | 4.4 #5 | Rules | [filing-status](#filing-status) |
| `exploitation_concern` | 4.4 #6 | Intake | [exploitation](#exploitation) |
| `uncertain` | 4.3 | Intake, orchestrator | [uncertainty](#uncertainty) |
| `review_limit` | 4.1 | Orchestrator | review loop bound |
| `loop_guard` | 4.1 | Orchestrator | loop guard |

<a id="dignity"></a>
## 14. Accessibility and dignity in the dialogue

| Area (brief 4.3) | What SilverFile does |
|---|---|
| One question at a time | Each prompt asks for exactly one field and contains one question mark. |
| Plain language | Filing statuses are written out in full with their short forms; tax terms get a short explanation in brackets the first time; "modified adjusted gross income" never appears. |
| Repetition and drift | Answers are appended, never overwritten. "go back to …" and "change … to …" work at any time. Repeating an escalated question does not raise a second ticket. |
| No unnecessary PII | See [ssn-test-range](#ssn-test-range). |
| Resumability | Sessions are saved after every answer; on return the taxpayer hears a short summary of what was covered. |
| Honest uncertainty | See [uncertainty](#uncertainty). |

Wording rules for anything said to the taxpayer: short sentences; no blame ("Sorry, I didn't understand
that" rather than "Invalid input"); say what to type ("Please type yes or no"); never mention internal
names such as ticket ids, agents or reason codes.
