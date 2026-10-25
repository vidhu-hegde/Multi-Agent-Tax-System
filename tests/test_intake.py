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
    return result["__interrupt__"][0].value


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
    assert "single" in question(result).lower()
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
    assert any(h.to_agent == "rules" and "revision" in h.reason for h in done["handoffs"])


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
    assert "spouse pass away" in question(result)
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
    ticket = question(result)
    assert ticket["reason"] == "uncertain"
    assert result["status"] == "waiting_on_human"
    assert len(result["document_inventory"]) == 4
    assert ticket["evidence"]["field"] == "document_inventory"


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
        ("schedule2_total_tax", "25"),
        ("schedule3_nonrefundable_credits", "10"),
        ("schedule3_other_payments", "30"),
        ("taxpayer_claimed_dependent", True),
        ("dual_status_alien", True),
        ("spouse_itemizes", True),
        ("dependent_count", 1),
    ],
)
def test_unintegrated_downstream_inputs_pause_instead_of_being_silently_ignored(make_graph, tmp_path, field, value):
    from tests.conftest import SKELETON_CASE

    case = json.loads(open(SKELETON_CASE).read())
    case["answers"][field] = value
    if field == "spouse_itemizes":
        case["answers"]["filing_status"] = "mfs"
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
    assert isinstance(question(result), str)  # staff continue returns to the affected input
    assert not result.get("intake_complete")


@pytest.mark.parametrize("disclosure", [
    "I have foreign income", "I have a foreign account", "I have digital assets",
    "I received a 1099-NEC", "I have self-employment income", "I have business income",
    "I have rental income", "I need Schedule D for capital gains", "I want itemized deductions",
    "I need an amended return", "I need a prior-year return", "I need a state return",
])
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
    result = graph.invoke(Command(resume={"field": "filing_status", "value": "single", "note": "I have foreign income"}), config())
    assert question(result)["reason"] == "out_of_scope"
    assert "filing_status" not in current_answers(result)


def test_explicit_denial_is_not_treated_as_positive_scope_disclosure(make_graph):
    graph = make_graph()
    graph.invoke({}, config())
    result = graph.invoke(Command(resume="I do not have foreign income"), config())
    assert isinstance(question(result), str)
    assert "Which filing status" in question(result)
    assert not result.get("escalations")
