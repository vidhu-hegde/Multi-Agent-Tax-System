# SilverFile demo script

This is SilverFile, our team's prototype for preparing a draft Form 1040-SR. This is the staff dashboard Kushim employees would use.

The README lists who owned each area; I did agent memory. Then the six agents, and what each one isn't allowed to do.

Here's the README graph. The Orchestrator picks the next step from saved state. Each document gets its own extraction branch, merged in Aggregate documents. Review can send work back, and anything needing a person becomes an interrupt.

Here's our first test case: a synthetic W-2 with a test-range Social Security number.

We're using a local vision model through Ollama; that's the model setting you see here. Both W-2 images come back with all sixteen fields matching.

Now the full eval case one runs through the graph. The wages come from the image, Rules checks the case, the tax tools do the math, and Review passes it. The overpayment is two thousand four hundred fifty-five dollars and fifty cents.

In the dashboard, the W-2 record points back to the image file. On the draft, every amount opens to show where it came from. Wages go back to W-2 box one. Taxable Social Security shows all the other income it needed first, which is the ordering dependency in the brief. And I can open line sixteen with the keyboard: it shows the tax-from-schedule tool call and each step behind it.

The same return fills in the official 2025 form as a draft for human review. You can see the age box, the standard deduction and the separate senior deduction on line 13b.

This is a new taxpayer session. Intake asks one question at a time, in plain words. After three answers I press Control-C, so the process is completely gone.

Now a brand-new process opens the same session. It gives a short recap and picks up at the blindness question. When I say I was distracted and ask it to repeat, it just asks again. I can go back to filing status, give a different answer, and then change it back to single, and the other answers are kept. When I say I'm not sure, it doesn't guess. It flags a volunteer and pauses.

This is eval case two. Harold says he made about twenty-four thousand, but his W-2 says twenty-six thousand four hundred fifty. Rules won't pick one, so the return stops for staff.

The staff queue now shows every required stop. There's Harold's conflict, a 1099-NEC we don't support, a 1099-R with box 2b checked, a spouse who died this year, possible third-party pressure, a tax-advice request, and the volunteer ticket from my "not sure".

On the pressure ticket, a nephew is telling her to send the refund to his account, and staff are told to talk to her privately. On the advice ticket, the system said it can't give tax advice and noted the question for a volunteer.

Back on Harold's return, staff can see both amounts. After checking with him, I record a note and my staff ID and continue. The decision is saved with who made it and when.

Now the draft uses the W-2 wages, twenty-six thousand four hundred fifty, and the overpayment is one thousand four hundred sixty dollars and twenty-five cents.

Here's his draft on the official form.

Staff mark it as submitted to staff. That's only an internal handoff. The page says plainly that nothing was electronically filed.

And the Submitted filter lists it.

To check inputs we didn't tune for, here's a new case for Rosa: thirty-five thousand in wages, a hundred twenty in interest. It runs through the same graph: tax of one thousand one hundred thirty-seven, overpayment of two thousand one hundred thirteen, which matches our hand calculation.

This separate return has a dependent. Name, relationship, and a test-range SSN reach the draft, masked here.

These tests cover the graph rules. The document reducer gives the same result in either merge order. Review stops after its pass limit, and the loop guard breaks a repeated handoff. Only SSNs from 900 to 999 are accepted, and real-looking ones are refused.

All twenty-five eval cases pass, including both demo cases and all six escalation conditions.

This is the ten-item batch, run live. With selective recall on, input tokens stay between two forty-seven and two eighty-eight. With the no-context-strategy flag, they climb to eight sixty-one. Both runs get every answer right and finish the same reviewed return.

The table in docs slash metrics is the same set of numbers. We read the brief's ten invoices as ten intake items in one return, and the doc says so.

Here's the Docker setup: Compose starts the dashboard and the tax-math service.

I run Harold's case inside the app container, using the same command as our eval case two instructions, and it stops on the conflict.

I resolve it in the container's dashboard, with a note and my staff ID.

Then I take the whole stack down, which removes the containers, and bring it back up.

The decision and staff ID are still there, because the database lives on a Docker volume.

Our five-page report covers the design and each agent, memory and accessibility, testing and failure handling, and the team roles and scope limits.

We also wrote a detailed disclosure of how we used AI, and it's in the repository.

That's SilverFile. Thanks for watching.
