# tax_math rules spec (tax year 2025, Form 1040-SR)

Handoff for implementing the four stubbed tools in `src/tools.py`: `standard_deduction`, `senior_deduction`,
`taxable_social_security`, `tax_from_schedule`. All money is `Decimal`. Raise a clear error on invalid input
instead of guessing (an error should surface as an escalation, not a silent zero).

**Read this first: verification status.** I read these sources through a summarizing fetch tool, not by eye.
Before encoding, open each source and confirm the numbers marked below. Test "known answers" should be
re-derived from the IRS documents, not copied from this file.

| Rule | Source | Status |
|---|---|---|
| Standard deduction chart | Form 1040-SR, page 4 | Read; cross-checks with 2025 base amounts. Re-check on the PDF. |
| Senior deduction | Schedule 1-A (2025), Part V, lines 31-37 | Read line by line. Re-check on the PDF. |
| Taxable Social Security | Publication 915 (2025), Worksheet 1 | Read from the publication. NOT confirmed against the Form 1040 instructions worksheet (fetch cut off). Compare the two. |
| Tax rate schedules | Rev. Proc. 2024-40 section 2.01 and the IRS brackets page | Two sources agree on thresholds; the formulas' arithmetic checks out. |

## 1. standard_deduction(filing_status, boxes)

`filing_status` in `single | mfj | mfs | hoh | qss`; `boxes` = number of boxes checked on Form 1040-SR line 12d
(taxpayer 65+, taxpayer blind, spouse 65+, spouse blind). Chart (1040-SR page 4):

| Status | 1 box | 2 | 3 | 4 |
|---|---|---|---|---|
| single | 17,750 | 19,750 | - | - |
| mfj | 33,100 | 34,700 | 36,300 | 37,900 |
| qss | 33,100 | 34,700 | - | - |
| hoh | 25,625 | 27,625 | - | - |
| mfs | 17,350 | 18,950 | 20,550 | 22,150 |

- Boxes outside the row's range (including 0) -> raise.
- The form says not to use the chart if someone can claim the taxpayer as a dependent, the spouse itemizes
  on a separate return, or the taxpayer is a dual-status alien. Those are Rules-agent decisions, not this tool's.
- **Do not use Rev. Proc. 2024-40 for the standard deduction.** It lists $15,000 / $30,000 / $22,500 basic
  amounts, which were superseded for 2025. The 1040-SR chart already reflects the current amounts
  (single: 15,750 + 2,000 = 17,750; mfj: 31,500 + 1,600 = 33,100).

## 2. senior_deduction(filing_status, magi, qualifying_people)  -> Form 1040-SR line 13b

Schedule 1-A Part V:

- threshold = 150,000 if `mfj` else 75,000 (line 32)
- excess = max(0, magi - threshold) (line 33)
- per_person = max(0, 6,000 - 0.06 * excess) (lines 34-35)
- result = per_person * qualifying_people (lines 36a, 36b, 37)

`qualifying_people` is 0, 1 or 2: valid SSN and born before Jan 2, 1961, and the spouse counts only on a joint
return. If married, the taxpayer must file jointly, so `mfs` -> 0. Counting people is Juee's `senior_deduction_count`
rule; this tool only multiplies. Line 37 flows into Schedule 1-A line 38, then 1040-SR line 13b.

## 3. taxable_social_security(filing_status, benefits, other_income, tax_exempt_interest, adjustments)  -> line 6b

Pub. 915 Worksheet 1 (line numbers in parentheses):

```
half   = 0.5 * benefits                                  (2)
l6     = half + sum(other_income) + tax_exempt_interest  (6)   # other_income = lines 1z,2b,3b,4b,5b
if adjustments >= l6: return 0                           (7-8)
l8     = l6 - adjustments
# MFS who lived with spouse at any time in 2025: no base amount
#   l17 = 0.85 * l8 ; result = min(l17, 0.85 * benefits)
base   = 32,000 if mfj else 25,000                       (9)
l10    = l8 - base ; if l10 <= 0: return 0               (10)
tier   = 12,000 if mfj else 9,000                        (11)
l12    = max(0, l10 - tier)                              (12)
l13    = min(l10, tier)                                  (13)
l15    = min(half, 0.5 * l13)                            (14-15)
l17    = l15 + 0.85 * l12                                (16-17)
result = min(l17, 0.85 * benefits)                       (18-19)
```

**Contract gaps to raise with Vidhatri / Juee:**

- Resolved in #9/#10: Rules records lived_with_spouse, Computation passes it, and an unknown answer with
  benefits raises ValueError.
- The worksheet's line 3 also includes lines 7a and 8, which are out of scope here (they escalate).
- Worksheet line 7 is Schedule 1 lines 11-20, 23, 25 only, not every adjustment (it excludes, for example,
  student loan interest). The agent passes line 10 as `adjustments`; fine for most seniors, but a known edge.

## 4. tax_from_schedule(filing_status, taxable_income)  -> line 16

> Decided Oct 27: keep the rate schedule (the brief's line table specifies it) and round every tool result to cents, half up, in call_tool(). See IMPLEMENTATION_NOTES.md, 'Line 16 and rounding'.

Rev. Proc. 2024-40, section 2.01 (tax = base + rate * (income - lower bound)):

| Status | Bracket lower bound | Base tax | Rate |
|---|---|---|---|
| single | 0 / 11,925 / 48,475 / 103,350 / 197,300 / 250,525 / 626,350 | 0 / 1,192.50 / 5,578.50 / 17,651 / 40,199 / 57,231 / 188,769.75 | 10 / 12 / 22 / 24 / 32 / 35 / 37% |
| mfj, qss | 0 / 23,850 / 96,950 / 206,700 / 394,600 / 501,050 / 751,600 | 0 / 2,385 / 11,157 / 35,302 / 80,398 / 114,462 / 202,154.50 | same rates |
| hoh | 0 / 17,000 / 64,850 / 103,350 / 197,300 / 250,500 / 626,350 | 0 / 1,700 / 7,442 / 15,912 / 38,460 / 55,484 / 187,031.50 | same rates |
| mfs | 0 / 11,925 / 48,475 / 103,350 / 197,300 / 250,525 / 375,800 | 0 / 1,192.50 / 5,578.50 / 17,651 / 40,199 / 57,231 / 101,077.25 | same rates |

Resolved Oct 27, see the note at the top of this section.

## 5. Test vectors

Marked **(IRS)** if the source states the answer, **(derived)** if I computed it from the formulas above
(re-derive by hand before trusting).

- standard_deduction: (single, 1) -> 17,750 (IRS); (mfj, 2) -> 34,700 (IRS); (hoh, 1) -> 25,625 (IRS);
  (mfs, 4) -> 22,150 (IRS); (single, 3) -> error.
- senior_deduction: (single, 75,000, 1) -> 6,000; (single, 85,000, 1) -> 5,400; (single, 100,000, 1) -> 4,500;
  (single, 175,000, 1) -> 0; (mfj, 150,000, 2) -> 12,000; (mfj, 160,000, 2) -> 10,800; (mfs, any, 0) -> 0 (all derived).
- taxable_social_security: single, benefits 5,980, other_income [28,990], tax_exempt 0, adjustments 0 -> 2,990
  (Pub. 915 Example 1, reported by the fetch; confirm). Derived: single, 10,000 / [15,000] -> 0;
  single, 20,000 / [40,000] -> 17,000 (the 85% cap binds).
- tax_from_schedule (derived): (single, 11,925) -> 1,192.50; (single, 50,000) -> 5,914.00; (hoh, 17,000) -> 1,700;
  (mfj, 100,000) -> 11,828; (mfs, 400,000) -> 110,031.25.

## 6. Resolved questions

1. Resolved: Rounding / Tax Table vs schedule. Resolved Oct 27, see section 4.
2. Resolved: "lived with spouse" input for MFS (section 3). Resolved in #9/#10; Intake asks, Computation
   passes it, and unknown with benefits raises.
3. Resolved: did the assignment supply its own `tax_math` reference? None was used; numbers verified by
   Vidhatri against the 2025 sources in #10.
4. Resolved: cross-check `data/policy.md` against this spec. Merged in #9.

## Sources

- Form 1040-SR (2025): https://www.irs.gov/pub/irs-pdf/f1040s.pdf
- Schedule 1-A (2025): https://www.irs.gov/pub/irs-pdf/f1040s1a.pdf
- Publication 915 (2025): https://www.irs.gov/publications/p915
- Rev. Proc. 2024-40: https://www.irs.gov/pub/irs-drop/rp-24-40.pdf
- Federal income tax rates and brackets: https://www.irs.gov/filing/federal-income-tax-rates-and-brackets
- Form 1040 instructions (2025), lines 6a/6b worksheet and Tax Table: https://www.irs.gov/instructions/i1040gi
