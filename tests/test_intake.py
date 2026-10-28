"""Intake behavior, without tax arithmetic or a network dependency."""

import json
from decimal import Decimal
from importlib import import_module

import pytest
from langgraph.types import Command

from src.state import current_answers

intake_module = import_module("src.agents.intake")


def config(thread="intake"):
    return {"configurable": {"thread_id": thread}}


def question(result):
    value = result["__interrupt__"][0].value

    if (
        isinstance(value, dict)
        and value.get("type") == "intake_question"
    ):
        return value["prompt"]

    return value


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-1", "-Infinity"])
def test_nonfinite_or_negative_money_is_rejected(raw):
    with pytest.raises(ValueError):
        intake_module.parse_money(raw)


def test_plain_filing_status_is_accepted():
    assert intake_module.parse_filing_status("Married filing jointly") == "mfj"


def test_each_reply_is_checkpointed_before_the_next_question(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="single"), config())
    assert current_answers(graph.get_state(config()).values)["filing_status"].value == "single"
    assert "So far:" not in question(result)
    assert question(result).count("?") == 1


def test_correction_keeps_history_and_returns_to_unanswered_question(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    graph.invoke(Command(resume="single"), config())
    result = graph.invoke(Command(resume="change filing status to married filing jointly"), config())
    answers = graph.get_state(config()).values["answers"]
    assert [a.value for a in answers if a.field == "filing_status"] == ["single", "mfj"]
    assert "spouse" in question(result)
    assert current_answers(graph.get_state(config()).values)["filing_status"].value == "mfj"


def test_go_back_reasks_one_field_without_erasing_answers(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    graph.invoke(Command(resume="single"), config())
    result = graph.invoke(Command(resume="go back to filing status"), config())
    assert "Which filing status" in question(result)
    result = graph.invoke(Command(resume="single"), config())
    assert len(graph.get_state(config()).values["answers"]) == 1
    assert question(result).count("?") == 1


def test_unrequested_ssn_is_not_in_saved_prompt_or_escalation(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="My SSN is 123-45-6789; should I file jointly?"), config())
    assert "123-45-6789" not in str(result)
    assert "123-45-6789" not in str(graph.get_state(config()).values)


def test_correction_requests_owner_revalidation_without_changing_old_lines(make_graph):
    from tests.conftest import SKELETON_CASE

    graph = make_graph()
    done = graph.invoke({"case_path": SKELETON_CASE}, config())
    assert done["status"] == "draft_ready"
    graph.invoke({"intake_complete": False, "intake_revisit": "estimated_payments"}, config())
    done = graph.invoke(Command(resume="2000"), config())
    assert done["lines"]["26"].amount == Decimal("2000")
    assert done["review_status"] == "passed"
    assert any(h.to_agent == "rules" for h in done["handoffs"])
    assert done["evidence_epoch"] == 1
    assert done["evidence_history"][0].lines["26"].amount == Decimal("1000")


def test_dependent_and_inventory_use_shared_contracts():
    from src.schemas import DocumentRef

    refs = intake_module.parse_inventory("W-2, SSA-1099")
    assert all(isinstance(ref, DocumentRef) for ref in refs)
    assert [ref.form_type for ref in refs] == ["W-2", "SSA-1099"]
    with pytest.raises(ValueError):
        intake_module.parse_test_ssn("123-45-6789")
    assert intake_module.parse_test_ssn("901-12-3456") == "901-12-3456"


def test_unsupported_inventory_reaches_rules_as_other():
    refs = intake_module.parse_inventory("1099-NEC")
    assert refs[0].form_type == "other"
    assert refs[0].description == "1099-NEC"


def test_dependents_are_collected_as_separate_questions(make_graph, tmp_path):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"]["dependent_count"] = 1
    path = tmp_path / "dependent.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    result = graph.invoke({"case_path": str(path)}, config())
    assert "dependent 1's name" in question(result)
    result = graph.invoke(Command(resume="Synthetic Child"), config())
    assert "related" in question(result)
    result = graph.invoke(Command(resume="child"), config())
    assert "test Social Security number" in question(result)
    result = graph.invoke(Command(resume="123-45-6789"), config())
    assert "test Social Security number" in question(result)
    result = graph.invoke(Command(resume="901-12-3456"), config())
    [dependent] = current_answers(result)["dependents"].value
    assert dependent.name == "Synthetic Child"
    assert dependent.ssn == "901-12-3456"
    assert "901-12-3456" not in intake_module.recap(current_answers(result))
    assert all(a.raw_text is None for a in result["answers"] if a.field.endswith("_ssn"))


def test_repetition_and_drift_preserve_confirmed_answers(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    graph.invoke(Command(resume="single"), config())
    graph.invoke(Command(resume="change filing status to single"), config())
    result = graph.invoke(Command(resume="I was walking my dog earlier"), config())
    assert "spouse who died" in question(result)
    assert len(graph.get_state(config()).values["answers"]) == 1


def test_new_schedule_fields_keep_direct_input_provenance(make_graph):
    from tests.conftest import SKELETON_CASE

    result = make_graph().invoke({"case_path": SKELETON_CASE}, config())
    known = current_answers(result)
    for field in ("schedule2_total_tax", "schedule3_nonrefundable_credits", "schedule3_other_payments"):
        assert known[field].value == Decimal("0")
        assert known[field].entered_by == "case file"
        assert known[field].answered_at.tzinfo is not None


def test_inventory_change_after_extraction_does_not_silently_reuse_stale_documents(make_graph):
    from tests.conftest import SKELETON_CASE

    graph = make_graph()
    graph.invoke({"case_path": SKELETON_CASE}, config())
    graph.invoke({"intake_complete": False, "intake_revisit": "document_inventory"}, config())
    result = graph.invoke(Command(resume="none"), config())
    assert result["status"] == "draft_ready"
    assert result["document_inventory"] == []
    assert result["documents"] == {}
    assert result["lines"]["1z"].amount == Decimal("0")
    assert result["evidence_history"][0].documents["w2-1"].wages == Decimal("18000")


def test_model_classifier_uses_selective_context_and_pauses_through_existing_human_hook(make_graph):
    from langchain_core.messages import AIMessage, HumanMessage

    class Provider:
        def invoke(self, messages):
            assert "old unrelated dialogue" not in str(messages)
            return AIMessage(
                content='{"reason":"uncertain"}',
                usage_metadata={"input_tokens": 41, "output_tokens": 9, "total_tokens": 50},
            )

    graph = make_graph(agents={"intake": intake_module.make_intake(Provider())})
    graph.invoke({"messages": [HumanMessage(content="old unrelated dialogue")]}, config())
    result = graph.invoke(Command(resume="This question is beyond me"), config())
    assert question(result)["reason"] == "uncertain"
    assert sum(result["input_token_usage"].values()) == 41


def test_model_null_response_reasks_without_replaying_the_model_call(make_graph):
    from langchain_core.messages import AIMessage

    class OnceOnlyProvider:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            assert self.calls == 1
            return AIMessage(
                content='{"reason":null}', usage_metadata={"input_tokens": 25, "output_tokens": 5, "total_tokens": 30}
            )

    provider = OnceOnlyProvider()
    graph = make_graph(agents={"intake": intake_module.make_intake(provider, use_context_strategy=False)})
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="My dog is named Spot"), config())
    assert "Which filing status" in question(result)
    result = graph.invoke(Command(resume="single"), config())
    assert sum(result["input_token_usage"].values()) == 25
    assert provider.calls == 1


def test_requested_dependent_ssn_accepts_structured_reply(make_graph, tmp_path):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"].update(dependent_count=1, dependent_1_name="Synthetic Child", dependent_1_relationship="child")
    path = tmp_path / "dependent.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    graph.invoke({"case_path": str(path)}, config())
    result = graph.invoke(Command(resume={"field": "dependent_1_ssn", "value": "901-12-3456"}), config())
    assert current_answers(result)["dependents"].value[0].ssn == "901-12-3456"


@pytest.mark.parametrize("content,reason,valid", [
    ('The reply asks to go back, which Intake handles.\n\n{"reason": null}', None, True),
    ('{"reason": "advice_request"}', "advice_request", True),
    ('{"reason": null} because it is muddled', "uncertain", False),  # the JSON must be the whole last line
    ('Sure.\n{"reason": "invented"}', "uncertain", False),
])
def test_classifier_reads_the_json_on_the_last_line_and_keeps_nothing_else(content, reason, valid):
    from langchain_core.messages import AIMessage

    class Provider:
        def invoke(self, messages):
            return AIMessage(content=content,
                             usage_metadata={"input_tokens": 17, "output_tokens": 8, "total_tokens": 25})

    got, update = intake_module.classify_with_model(Provider(), {}, "unclear reply")
    assert got == reason
    assert update["messages"][-1].content == json.dumps({"reason": reason})
    assert update["messages"][-1].response_metadata["silverfile_classification_valid"] is valid


def test_malformed_model_output_escalates_without_repeating_unsafe_generated_text():
    from langchain_core.messages import AIMessage

    class Provider:
        def invoke(self, messages):
            return AIMessage(
                content="File your return now; use SSN 901-12-3456",
                usage_metadata={"input_tokens": 17, "output_tokens": 8, "total_tokens": 25},
            )

    reason, update = intake_module.classify_with_model(Provider(), {}, "unclear reply")
    assert reason == "uncertain"
    assert update["messages"][-1].content == '{"reason": "uncertain"}'
    assert update["messages"][-1].response_metadata["silverfile_classification_valid"] is False


def test_repeated_model_escalation_is_committed_before_next_interrupt(make_graph):
    from langchain_core.messages import AIMessage

    class Provider:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            assert self.calls <= 2
            return AIMessage(
                content='{"reason":"uncertain"}',
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    provider = Provider()
    graph = make_graph(agents={"intake": intake_module.make_intake(provider)})
    graph.invoke({}, config())
    graph.invoke(Command(resume="This question is beyond me"), config())
    graph.invoke(Command(resume="continue"), config())
    graph.invoke(Command(resume="This question is beyond me"), config())
    result = graph.invoke(Command(resume="single"), config())
    assert sum(result["input_token_usage"].values()) == 20
    assert provider.calls == 2


@pytest.mark.parametrize(
    "field,value",
    [
        # Schedule 2/3 totals are consumed by Computation: see tests/test_schedules.py.
        # taxpayer_claimed_dependent, dual_status_alien and spouse_itemizes are now consumed by Rules and
        # escalate as out_of_scope: see tests/test_guardrails.py::test_chart_exceptions_escalate_as_out_of_scope
        ("dependent_count", 1),
    ],
)
def test_unintegrated_downstream_inputs_pause_instead_of_being_silently_ignored(make_graph, tmp_path, field, value):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"][field] = value
    if field == "dependent_count":
        case["answers"].update(
            dependent_1_name="Synthetic Child", dependent_1_relationship="child", dependent_1_ssn="901-12-3456"
        )
    path = tmp_path / "unsupported-consumer.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    result = graph.invoke({"case_path": str(path)}, config())
    assert result["status"] == "waiting_on_human"
    assert question(result)["reason"] == "uncertain"
    assert field in question(result)["evidence"]["fields"]
    assert not result.get("lines")
    result = graph.invoke(Command(resume="continue"), config())
    assert result["intake_complete"]
    assert result["status"] == "draft_ready"
    assert "__interrupt__" not in result


@pytest.mark.parametrize(
    "disclosure",
    [
        "I have foreign income",
        "I have a foreign account",
        "I have digital assets",
        "I received a 1099-NEC",
        "I have self-employment income",
        "I have business income",
        "I have rental income",
        "I need Schedule D for capital gains",
        "I want itemized deductions",
        "I need an amended return",
        "I need a prior-year return",
        "I need a state return",
    ],
)
def test_scope_disclosure_at_filing_status_pauses_for_human(make_graph, disclosure):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume=disclosure), config())
    assert isinstance(question(result), dict)
    assert question(result)["reason"] == "out_of_scope"
    assert result["status"] == "waiting_on_human"
    assert "filing_status" not in current_answers(result)


def test_scope_precheck_runs_before_accepting_free_text_field(make_graph, tmp_path):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"]["dependent_count"] = 1
    path = tmp_path / "scope-name.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    graph.invoke({"case_path": str(path)}, config())
    result = graph.invoke(Command(resume="I have foreign income"), config())
    assert question(result)["reason"] == "out_of_scope"
    assert "dependent_1_name" not in current_answers(result)
    assert current_answers(result)["filing_status"].value == "single"


def test_scope_precheck_reads_entire_structured_turn(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(
        Command(resume={"field": "filing_status", "value": "single", "note": "I have foreign income"}), config()
    )
    assert question(result)["reason"] == "out_of_scope"
    assert "filing_status" not in current_answers(result)


def test_explicit_denial_is_not_treated_as_positive_scope_disclosure(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="I do not have foreign income"), config())
    assert isinstance(question(result), str)
    assert "Which filing status" in question(result)
    assert not result.get("escalations")


@pytest.mark.parametrize("reply, expected", [("2000", Decimal("2000")), ("1000", Decimal("1000"))])
def test_review_revision_for_direct_intake_line_is_answered_and_consumed(make_graph, reply, expected):
    from src.schemas import RevisionRequest
    from tests.conftest import SKELETON_CASE

    graph = make_graph()
    original = graph.invoke({"case_path": SKELETON_CASE}, config())
    request = RevisionRequest(target="intake", line="26", reason="Please confirm the estimated payment")
    result = graph.invoke({"revision_requests": [request], "review_status": "failed"}, config())
    assert isinstance(question(result), str)
    assert "estimated tax" in question(result)
    assert request in graph.get_state(config()).values["revision_requests"]
    result = graph.invoke(Command(resume=reply), config())
    assert result["status"] == "draft_ready"
    assert result["review_status"] == "passed"
    assert result["lines"]["26"].amount == expected
    assert not any(r.target == "intake" for r in result["revision_requests"])
    assert not result.get("escalations")
    if reply == "1000":
        assert result["review_passes"] == original["review_passes"] + 1


@pytest.mark.parametrize("line", [None, "12d", "unknown"])
def test_unsupported_intake_revision_is_explicit_handoff_without_loop(make_graph, line):
    from src.schemas import RevisionRequest
    from tests.conftest import SKELETON_CASE

    graph = make_graph()
    graph.invoke({"case_path": SKELETON_CASE}, config())
    request = RevisionRequest(target="intake", line=line, reason="Check the taxpayer input")
    other = RevisionRequest(target="computation", line="9", reason="Recompute income")
    result = graph.invoke({"revision_requests": [request, other], "review_status": "failed"}, config())
    ticket = question(result)
    assert isinstance(ticket, dict)
    assert ticket["reason"] == "uncertain"
    assert ticket["evidence"]["dependency"] == "RevisionRequest.field / Intake targeting contract"
    assert result["revision_requests"] == [other]
    assert not any(t.reason == "loop_guard" for t in result["escalations"].values())
    stopped = graph.invoke(Command(resume="stop"), config())
    assert stopped["status"] == "stopped"


def test_intake_revision_can_use_existing_explicit_revisit_field(make_graph):
    from src.schemas import RevisionRequest
    from tests.conftest import SKELETON_CASE

    graph = make_graph()
    graph.invoke({"case_path": SKELETON_CASE}, config())
    request = RevisionRequest(target="intake", reason="Confirm adjustment amount")
    result = graph.invoke({"revision_requests": [request], "intake_revisit": "adjustments"}, config())
    assert "Schedule 1, line 26" in question(result)
    result = graph.invoke(Command(resume="25"), config())
    assert result["status"] == "draft_ready"
    assert result["lines"]["10"].amount == Decimal("25")
    assert not result["revision_requests"]


@pytest.mark.parametrize(
    "reply",
    [
        "123456789",
        "123456789.00",
        123456789,
        "change estimated payments to 123456789",
        {"field": "estimated_payments", "value": "123456789"},
    ],
)
def test_monetary_reply_keeps_valid_nine_digit_amount(make_graph, tmp_path, reply):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"].pop("estimated_payments")
    path = tmp_path / "large-payment.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    graph.invoke({"case_path": str(path)}, config())
    result = graph.invoke(Command(resume=reply), config())
    assert result["status"] == "draft_ready"
    assert current_answers(result)["estimated_payments"].value == Decimal("123456789")
    assert result["lines"]["26"].amount == Decimal("123456789")
    assert result["lines"]["26"].provenance[0].entered_by == "taxpayer"


@pytest.mark.parametrize(
    "reply",
    [
        "123-45-6789",
        "My SSN is 123456789",
        "SSN: 901-12-3456",
        {"field": "estimated_payments", "value": "My SSN is 123-45-6789"},
    ],
)
def test_ssn_like_text_is_not_accepted_as_payment(make_graph, tmp_path, reply):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"].pop("estimated_payments")
    path = tmp_path / "not-a-payment.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    graph.invoke({"case_path": str(path)}, config())
    result = graph.invoke(Command(resume=reply), config())
    assert isinstance(question(result), str)
    assert "estimated_payments" not in current_answers(result)
    assert "123-45-6789" not in str(graph.get_state(config()).values)
    assert "123456789" not in str(graph.get_state(config()).values)


def test_unrequested_numeric_ssn_in_structured_escalation_is_redacted(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume={"value": "I have foreign income", "ssn": 123456789}), config())
    assert question(result)["reason"] == "out_of_scope"
    assert "123456789" not in str(result)
    assert "123456789" not in str(graph.get_state(config()).values)


def test_go_back_during_revision_does_not_consume_a_different_requested_field(make_graph):
    from src.schemas import RevisionRequest
    from tests.conftest import SKELETON_CASE

    graph = make_graph()
    graph.invoke({"case_path": SKELETON_CASE}, config())
    request = RevisionRequest(target="intake", line="26", reason="Confirm estimated payment")
    graph.invoke({"revision_requests": [request]}, config())
    result = graph.invoke(Command(resume="go back to filing status"), config())
    assert "Which filing status" in question(result)
    result = graph.invoke(Command(resume="single"), config())
    assert "estimated tax" in question(result)
    assert request in graph.get_state(config()).values["revision_requests"]
    result = graph.invoke(Command(resume="1000"), config())
    assert result["status"] == "draft_ready"
    assert not result["revision_requests"]


def test_repeated_unchanged_intake_revisions_reach_existing_review_bound(make_graph, settings):
    from src.schemas import RevisionRequest
    from tests.conftest import SKELETON_CASE

    def recurring_review(state):
        return {
            "revision_requests": [RevisionRequest(target="intake", line="26", reason="Confirm again")],
            "review_status": "failed",
            "review_passes": state.get("review_passes", 0) + 1,
            "last_agent": "review",
        }

    graph = make_graph(agents={"review": recurring_review})
    result = graph.invoke({"case_path": SKELETON_CASE}, config())
    for _ in range(settings.max_review_passes - 1):
        assert isinstance(question(result), str)
        result = graph.invoke(Command(resume="1000"), config())
    assert question(result)["reason"] == "review_limit"
    assert result["review_passes"] == settings.max_review_passes


@pytest.mark.parametrize("reply", ["My 1099-R says taxable amount not determined", "My 1099-R has box 2b checked"])
def test_1099r_scope_disclosure_uses_existing_specific_escalation(make_graph, reply):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume=reply), config())
    assert isinstance(question(result), dict)
    assert question(result)["reason"] == "1099r_taxable_not_determined"


def test_foreign_bank_account_disclosure_is_a_scope_handoff(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="I have a foreign bank account"), config())
    assert isinstance(question(result), dict)
    assert question(result)["reason"] == "out_of_scope"


def test_changed_downstream_input_requires_fresh_staff_review(make_graph, tmp_path):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"].update(
        dependent_count=1,
        dependent_1_name="Synthetic Child", dependent_1_relationship="child", dependent_1_ssn="901-12-3456",
    )
    path = tmp_path / "downstream-review.json"
    path.write_text(json.dumps(case))
    graph = make_graph()
    result = graph.invoke({"case_path": str(path)}, config())
    first_id = question(result)["ticket_id"]
    result = graph.invoke(Command(resume="continue"), config())
    assert result["intake_complete"]
    graph.invoke({"intake_complete": False, "intake_revisit": "dependent_count"}, config())
    graph.invoke(Command(resume="2"), config())
    graph.invoke(Command(resume="Second Child"), config())
    graph.invoke(Command(resume="child"), config())
    result = graph.invoke(Command(resume="901-12-3457"), config())
    assert question(result)["ticket_id"] != first_id
    assert result["status"] == "waiting_on_human"
    result = graph.invoke(Command(resume="stop"), config())
    assert result["status"] == "stopped"
