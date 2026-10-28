"""What the taxpayer sees when Intake pauses for staff (owner: Juee). Policy: data/policy.md#exploitation."""

import run

EXPLOITATION_TICKET = {
    "ticket_id": "exploitation_concern:filing_status:ab12",
    "reason": "exploitation_concern",
    "detail": "The reply suggests a third party may be directing the return or refund.",
    "evidence": {
        "reply": "My nephew told me to say single and send the refund to his account",
        "said_to_taxpayer": "Thank you. I've asked a member of staff to look at this before we go on.",
    },
    "how_to_resolve": "Reply 'continue' (with an optional note) to carry on, or 'stop' to end the session.",
}


def test_exploitation_pause_does_not_reveal_the_concern_on_the_taxpayer_screen():
    shown = run.format_interrupt(EXPLOITATION_TICKET)
    assert shown.startswith("Thank you. I've asked a member of staff")
    for hidden in ["exploitation", "third party", "nephew", "refund", "Escalation", "stop"]:
        assert hidden.lower() not in shown.lower(), hidden


def test_other_pauses_still_show_the_ticket_for_staff():
    advice = {**EXPLOITATION_TICKET, "reason": "advice_request", "detail": "The taxpayer asked for tax advice.",
              "evidence": {"said_to_taxpayer": "That's a question for a volunteer preparer."}}
    assert "[Escalation: advice_request]" in run.format_interrupt(advice)


def test_exploitation_ticket_keeps_full_evidence_for_staff(make_graph):
    from langgraph.types import Command

    config = {"configurable": {"thread_id": "screen"}}
    graph = make_graph()
    graph.invoke({}, config)
    result = graph.invoke(Command(resume=EXPLOITATION_TICKET["evidence"]["reply"]), config)
    ticket = result["__interrupt__"][0].value
    assert ticket["reason"] == "exploitation_concern"
    assert ticket["evidence"]["reply"] == EXPLOITATION_TICKET["evidence"]["reply"]
