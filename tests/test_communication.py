"""Communication contracts, real fixture bytes with mocked vision, and rendered provenance."""
import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic import APIConnectionError
from langgraph.types import Command
from pydantic import ValidationError

from src.agents.extraction import VISION_FIELDS, make_extraction, manual_record
from src.communication import validate_update
from src.memory import serializer
from src.render import render_draft
from src.schemas import (DocumentRef, EscalationTicket, Handoff, IntakeAnswer, LineValue,
                         Provenance, RevisionRequest, RuleDecision, W2Record)
from tests.conftest import SKELETON_CASE


class Vision:
    def __init__(self, observation, stop="end_turn"):
        self.observation, self.stop, self.calls = observation, stop, []
        self.messages = self

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(stop_reason=self.stop, model="fixture-provider", id="response-test",
                               content=[SimpleNamespace(type="text", text=self.observation)])


def fixture(number):
    fields = json.loads(Path(f"data/fixtures/w2_{number}_expected.json").read_text())
    image = fields.pop("image")
    return DocumentRef(document_id=f"w2-{number}", form_type="W-2", image_path=image), fields


@pytest.mark.parametrize("number", [1, 2])
def test_vision_transcribes_fixture_contract_and_sends_the_actual_image(settings, number):
    ref, fields = fixture(number)
    provider = Vision(json.dumps({"fields": fields, "issues": []}))
    record = make_extraction(settings, provider)({"doc": ref})["documents"][ref.document_id]
    expected = W2Record(document_id=ref.document_id, source=record.source, **fields)
    assert record == expected
    image = provider.calls[0]["messages"][0]["content"][0]["source"]
    assert image["media_type"] == "image/jpeg"
    assert base64.b64decode(image["data"]) == Path(ref.image_path).read_bytes()
    assert record.source.inputs["response_id"] == "response-test"
    assert len(record.source.inputs["sha256"]) == 64
    assert fields["employee_ssn"] not in record.model_dump_json()


@pytest.mark.parametrize("problem", ["missing", "unreadable", "badmoney", "realssn", "extra", "truncated", "notjson", "missingbox2"])
def test_vision_failures_never_publish_partial_or_guessed_records(settings, problem):
    ref, fields = fixture(1)
    issues = []
    if problem == "missing":
        fields.pop("wages")
    if problem == "unreadable":
        issues = ["wages"]
    if problem == "badmoney":
        fields["wages"] = "unknown"
    if problem == "realssn":
        fields["employee_ssn"] = "123-45-6789"
    if problem == "extra":
        fields["taxable_income"] = "123"
    if problem == "missingbox2":
        fields["federal_withheld"] = None
    text = "not JSON" if problem == "notjson" else json.dumps({"fields": fields, "issues": issues})
    provider = Vision(text, "max_tokens" if problem == "truncated" else "end_turn")
    result = make_extraction(settings, provider)({"doc": ref})
    assert "documents" not in result
    ticket = next(iter(result["escalations"].values()))
    assert ticket.reason == "uncertain"
    assert ticket.evidence["document_id"] == ref.document_id
    assert "123-45-6789" not in ticket.model_dump_json()
    assert "901-23-4567" not in ticket.model_dump_json()


def test_image_file_failure_and_missing_credentials_are_safe(settings, tmp_path):
    from dataclasses import replace
    ref, fields = fixture(1)
    unavailable = make_extraction(replace(settings, anthropic_api_key=""))({"doc": ref})
    assert "documents" not in unavailable
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    provider = Vision(json.dumps({"fields": fields, "issues": []}))
    for path in (bad, tmp_path / "missing.jpg"):
        result = make_extraction(settings, provider)({"doc": ref.model_copy(update={"image_path": str(path)})})
        assert "documents" not in result
    assert provider.calls == []


def test_provider_exception_does_not_leak_request_or_key(settings):
    import httpx
    ref, _ = fixture(1)
    class Failed:
        messages = None
        def create(self, **kwargs):
            raise APIConnectionError(message="secret-and-raw-response", request=httpx.Request("POST", "https://example.test"))
    provider = Failed()
    provider.messages = provider
    result = make_extraction(settings, provider)({"doc": ref})
    assert "secret-and-raw-response" not in str(result)
    assert "documents" not in result


@pytest.mark.parametrize("form,values,field", [
    ("1099-INT", {"payer_name": "Test Bank", "interest": "123.45"}, "interest"),
    ("1099-DIV", {"payer_name": "Test Fund", "ordinary_dividends": "123.45", "qualified_dividends": "20"}, "ordinary_dividends"),
    ("1099-R", {"payer_name": "Test Pension", "gross_distribution": "123.45", "taxable_amount": "100"}, "gross_distribution"),
    ("SSA-1099", {"net_benefits": "123.45"}, "net_benefits"),
])
def test_direct_entry_keeps_identity_time_and_decimal_through_extraction(settings, form, values, field):
    when = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    ref = DocumentRef(document_id="manual", form_type=form, values=values, entered_by="staff-Anupama", entered_at=when)
    record = make_extraction(settings)({"doc": ref})["documents"]["manual"]
    assert getattr(record, field) == Decimal("123.45")
    assert record.source.kind == "user_input"
    assert record.source.source.startswith("direct user input")
    assert record.source.entered_by == "staff-Anupama"
    assert record.source.recorded_at == when
    assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("values", [{"interest": "NaN"}, {"interest": "-1"}, {"extra": 1}, {"source": {}}, {"document_id": "forged"}])
def test_bad_manual_values_are_rejected(values):
    with pytest.raises(ValueError):
        manual_record(DocumentRef(document_id="m", form_type="1099-INT", values={"payer_name": "Test", **values}))


@pytest.mark.parametrize("model,payload", [
    (IntakeAnswer, {"field": " ", "value": 1}),
    (IntakeAnswer, {"field": "age", "value": 1, "entered_by": ""}),
    (RuleDecision, {"rule_id": "scope", "outcome": True, "explanation": "test", "citation": ""}),
    (LineValue, {"line": "1z", "amount": "Infinity", "provenance": [{"kind": "document", "source": "test"}]}),
    (LineValue, {"line": "1z", "amount": "10", "provenance": []}),
    (RevisionRequest, {"target": "human", "reason": "fix"}),
    (EscalationTicket, {"ticket_id": "t", "reason": "invented", "raised_by": "intake", "detail": "test"}),
    (Handoff, {"from_agent": "unknown", "to_agent": "rules", "reason": "test"}),
])
def test_malformed_shared_messages_fail(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("agent,update", [
    ("extraction", {"lines": {}}), ("orchestrator", {"documents": {}}),
    ("review", {"lines": {}}), ("rules", {"answers": []}),
    ("computation", {"last_agent": "intake"}),
    ("orchestrator", {"next_agent": "nonexistent"}),
    ("intake", {"rule_decisions": {}}),
    ("extraction", {"documents": {"wrong": {"form_type": "SSA-1099", "document_id": "actual", "net_benefits": "2", "source": {"kind": "user_input", "source": "test"}}}}),
])
def test_invalid_handoffs_and_role_violations_fail(agent, update):
    with pytest.raises(ValueError):
        validate_update(agent, update)


def test_graph_rejects_agent_role_violation_before_merging(make_graph):
    with pytest.raises(ValueError, match="Malformed lines"):
        make_graph(agents={"intake": lambda state: {"lines": {"1z": "bad"}, "intake_complete": True}}).invoke({}, {"configurable": {"thread_id": "bad-agent"}})


def test_contracts_survive_checkpoint_and_json_roundtrips():
    source = Provenance(kind="tool", source="tax_math.sum", value=Decimal("12.34"), inputs={"values": [Decimal("12.34")]})
    records = [IntakeAnswer(field="estimated_payments", value=Decimal("12.34")),
               W2Record(document_id="w", employer_name="Test", wages="12.34", source=source),
               RuleDecision(rule_id="scope", outcome={"issues": []}, explanation="test", citation="policy.md#scope"),
               LineValue(line="1z", amount="12.34", provenance=[source]),
               RevisionRequest(target="intake", field="estimated_payments", line="26", reason="verify"),
               EscalationTicket(ticket_id="t", reason="uncertain", raised_by="extraction", detail="test")]
    serde = serializer()
    for record in records:
        encoded = serde.dumps_typed(record)
        assert serde.loads_typed(encoded) == record
        # JSON preserves the wire representation (Any values deliberately remain JSON values).
        assert type(record).model_validate_json(record.model_dump_json()).model_dump_json() == record.model_dump_json()


def test_manual_provenance_and_tool_inputs_reach_derived_line_and_html(make_graph):
    graph = make_graph()
    state = graph.invoke({"case_path": SKELETON_CASE}, {"configurable": {"thread_id": "audit"}})
    source = state["documents"]["w2-1"].source
    wages = state["lines"]["1z"]
    doc = wages.provenance[0]
    assert doc.entered_by == source.entered_by
    assert doc.recorded_at == source.recorded_at
    assert doc.inputs["record_source"] == source.model_dump(mode="json")
    assert doc not in state["lines"]["9"].provenance
    assert state["lines"]["9"].depends_on
    assert not state["lines"]["9"].is_stub  # own sum is real; renderer checks stub ancestors
    html = render_draft(state)
    assert '$18,000.00' in html
    assert 'direct user input' in html and 'recorded_at' in html and 'case file' in html
    assert 'tax_math.sum' in html and '&quot;values&quot;' in html
    # Tests use verified (non-stub) tax tools by default, so the line is displayable.
    assert '<details id="line-9">' in html
    assert '<details id="line-1z">' in html and '<summary title=' in html


def test_renderer_blocks_missing_or_cyclic_dependencies_stubs_and_stale_review():
    real = LineValue(line="1z", amount="123.45", provenance=[Provenance(kind="document", source='<script>alert(1)</script>')])
    ready = {"status": "draft_ready", "review_status": "passed", "lines": {"1z": real}}
    html = render_draft(ready)
    assert '$123.45' in html and '<script>' not in html and '&lt;script&gt;' in html
    for state in [
        {**ready, "review_status": "pending"},
        {**ready, "revision_requests": [RevisionRequest(target="computation", reason="check")]},
        {**ready, "lines": {"1z": real.model_copy(update={"depends_on": ["missing"]})}},
        {**ready, "lines": {"1z": real.model_copy(update={"depends_on": ["1z"]})}},
        {**ready, "lines": {"1z": real.model_copy(update={"provenance": [Provenance(kind="tool", source="stub", stub=True)]})}},
    ]:
        assert '$123.45' not in render_draft(state)


def test_typed_intake_revision_targets_named_field(make_graph):
    graph = make_graph()
    cfg = {"configurable": {"thread_id": "named-revision"}}
    graph.invoke({"case_path": SKELETON_CASE}, cfg)
    request = RevisionRequest(target="intake", field="estimated_payments", reason="verify")
    waiting = graph.invoke({"revision_requests": [request]}, cfg)
    prompt = waiting["__interrupt__"][0].value
    assert prompt["type"] == "intake_question"
    assert prompt["field"] == "estimated_payments"
    assert prompt["input_type"] == "money"
    assert "estimated tax" in prompt["prompt"]
    done = graph.invoke(Command(resume="2500"), cfg)
    assert done["lines"]["26"].amount == Decimal("2500")
    assert not done["revision_requests"]
    assert done["evidence_history"][0].lines["26"].amount == Decimal("1000")


def test_changed_evidence_cannot_reuse_a_previous_wage_conflict_approval(make_graph):
    graph = make_graph()
    cfg = {"configurable": {"thread_id": "approval-epoch"}}
    waiting = graph.invoke({"case_path": "data/fixtures/conflict_case.json"}, cfg)
    first_id = waiting["__interrupt__"][0].value["ticket_id"]
    done = graph.invoke(Command(resume="continue"), cfg)
    assert done["status"] == "draft_ready"
    graph.invoke({"intake_complete": False, "intake_revisit": "stated_wages"}, cfg)
    waiting = graph.invoke(Command(resume="99999"), cfg)
    second_id = waiting["__interrupt__"][0].value["ticket_id"]
    assert second_id != first_id
    assert waiting["escalations"][first_id].status == "resolved"
    assert waiting["escalations"][second_id].status == "open"
    assert waiting["lines"] == {}


def test_replaced_inventory_extracts_new_values_and_keeps_prior_audit(make_graph):
    graph = make_graph()
    cfg = {"configurable": {"thread_id": "replace-doc"}}
    graph.invoke({"case_path": SKELETON_CASE}, cfg)
    graph.invoke({"intake_complete": False, "intake_revisit": "document_inventory"}, cfg)
    refs = [{"document_id": "w2-1", "form_type": "W-2", "entered_by": "staff-Anupama", "values": {"employer_name": "New Test", "wages": "987.65", "federal_withheld": "45"}}]
    done = graph.invoke(Command(resume=json.dumps(refs)), cfg)
    assert done["documents"]["w2-1"].wages == Decimal("987.65")
    assert done["__interrupt__"][0].value["reason"] == "document_conflict"
    done = graph.invoke(Command(resume="continue"), cfg)
    assert done["lines"]["1z"].amount == Decimal("987.65")
    assert done["evidence_history"][0].documents["w2-1"].wages == Decimal("18000")
    assert 'staff-Anupama' in render_draft(done)


def test_extraction_revision_retries_existing_document_and_rechecks_draft(make_graph):
    graph = make_graph()
    cfg = {"configurable": {"thread_id": "re-extract"}}
    graph.invoke({"case_path": SKELETON_CASE}, cfg)
    request = RevisionRequest(target="extraction", document_id="w2-1", reason="Verify the original document again")
    # Same deterministic record source timestamp makes an identical retry idempotent.
    done = graph.invoke({"revision_requests": [request], "review_status": "failed"}, cfg)
    assert done["status"] == "draft_ready"
    assert done["lines"]["1z"].amount == Decimal("18000")
    assert not done["revision_requests"]
    assert done["evidence_epoch"] == 1


def test_extraction_revision_without_document_identity_is_rejected():
    with pytest.raises(ValidationError, match="document_id"):
        RevisionRequest(target="extraction", reason="Which document?")


def test_mocked_fixture_images_run_through_parallel_graph_and_html(make_graph, settings, tmp_path):
    case = json.loads(Path(SKELETON_CASE).read_text())
    ref, fields = fixture(1)
    case["documents"][0].pop("values")
    path = tmp_path / "vision-case.json"
    path.write_text(json.dumps(case))
    provider = Vision(json.dumps({"fields": fields, "issues": []}))
    state = make_graph(agents={"extraction": make_extraction(settings, provider)}).invoke(
        {"case_path": str(path)}, {"configurable": {"thread_id": "vision-graph"}})
    assert state["status"] == "draft_ready"
    assert state["lines"]["1z"].amount == Decimal("18000")
    html = render_draft(state)
    assert 'response-test' in html and 'sha256' in html and 'demo/w2_image_1.jpg' in html
    assert fields["employee_ssn"] not in html


def test_evidence_archive_and_provenance_survive_sqlite_restart(settings, make_graph):
    from src.memory import open_checkpointer
    cfg = {"configurable": {"thread_id": "archived-evidence"}}
    with open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        graph.invoke({"case_path": SKELETON_CASE}, cfg)
        graph.invoke({"intake_complete": False, "intake_revisit": "estimated_payments"}, cfg)
        state = graph.invoke(Command(resume="2222"), cfg)
        expected = render_draft(state)
    with open_checkpointer(settings) as saver:
        graph = make_graph(checkpointer=saver)
        restored = graph.get_state(cfg).values
        assert restored["evidence_history"][0].lines["26"].amount == Decimal("1000")
        assert restored["lines"]["26"].amount == Decimal("2222")
        assert render_draft(restored) == expected


def test_failed_reread_requires_fresh_human_review_and_hides_old_amount(make_graph, settings, tmp_path):
    case = json.loads(Path(SKELETON_CASE).read_text())
    case["documents"][0].pop("values")
    path = tmp_path / "reread-image.json"
    path.write_text(json.dumps(case))
    ref, fields = fixture(1)
    provider = Vision(json.dumps({"fields": fields, "issues": []}))
    graph = make_graph(agents={"extraction": make_extraction(settings, provider)})
    cfg = {"configurable": {"thread_id": "failed-reread"}}
    graph.invoke({"case_path": str(path)}, cfg)
    provider.observation = 'invalid response'
    request = RevisionRequest(target="extraction", document_id="w2-1", reason="Image requires another look")
    waiting = graph.invoke({"revision_requests": [request]}, cfg)
    assert waiting["__interrupt__"][0].value["reason"] == "uncertain"
    assert not waiting["document_readiness"]["w2-1"]
    done = graph.invoke(Command(resume="continue"), cfg)
    assert '$18,000.00' not in render_draft(done)
    assert done["evidence_history"][0].documents["w2-1"].wages == Decimal("18000")


@pytest.mark.parametrize("agent,update", [("intake", {"intake_complete": "yes"}),
                                         ("review", {"review_passes": -1}),
                                         ("computation", {"review_status": "approved"})])
def test_invalid_control_messages_are_rejected(agent, update):
    with pytest.raises(ValueError):
        validate_update(agent, update)


def test_new_document_ingress_invalidates_prior_calculations(make_graph):
    graph = make_graph()
    cfg = {"configurable": {"thread_id": "new-document"}}
    graph.invoke({"case_path": SKELETON_CASE}, cfg)
    record = manual_record(DocumentRef(document_id="extra-interest", form_type="1099-INT", entered_by="staff-A",
                                      values={"payer_name": "New Bank", "interest": "23.45"}))
    done = graph.invoke({"documents": {record.document_id: record}}, cfg)
    assert done["evidence_epoch"] == 1
    assert done["lines"]["2b"].amount == Decimal("443.45")
    assert done["evidence_history"][0].lines["2b"].amount == Decimal("420")
    assert 'staff-A' in render_draft(done)


@pytest.mark.parametrize("wrapper", ["bare", "fenced", "preamble", "preamble_fenced"])
def test_vision_accepts_json_presentation_variants(settings, wrapper):
    ref, fields = fixture(1)
    payload = json.dumps({"fields": fields, "issues": []})
    response = {
        "bare": payload,
        "fenced": "```json\n" + payload + "\n```",
        "preamble": "Here are the transcribed W-2 fields:\n" + payload,
        "preamble_fenced": "Here is the transcription:\n```JSON\n" + payload + "\n```",
    }[wrapper]
    record = make_extraction(settings, Vision(response))({"doc": ref})["documents"][ref.document_id]
    assert record.wages == Decimal(fields["wages"])
    assert record.employee_ssn_last4 == fields["employee_ssn"][-4:]
    assert fields["employee_ssn"] not in record.model_dump_json()


@pytest.mark.parametrize("wrapper", ["truncated", "unclosed_fence", "two_objects", "trailing_text", "bad_fenced", "long_preamble"])
def test_malformed_wrapped_vision_responses_escalate_without_raw_data(settings, wrapper):
    ref, fields = fixture(1)
    payload = json.dumps({"fields": fields, "issues": []})
    response = {
        "truncated": "Transcription:\n" + payload[:-2],
        "unclosed_fence": "```json\n" + payload,
        "two_objects": payload + "\n" + payload,
        "trailing_text": payload + " extra text",
        "bad_fenced": "```json\nnot JSON: 123-45-6789 provider-secret\n```",
        "long_preamble": "x" * 513 + payload,
    }[wrapper]
    result = make_extraction(settings, Vision(response))({"doc": ref})
    assert "documents" not in result
    assert not result["document_readiness"][ref.document_id]
    ticket = next(iter(result["escalations"].values()))
    assert ticket.reason == "uncertain"
    assert fields["employee_ssn"] not in ticket.model_dump_json()
    assert '123-45-6789' not in ticket.model_dump_json()
    assert 'provider-secret' not in ticket.model_dump_json()


def _audit_for(html, line):
    return html.split(f'<details id="line-{line}">', 1)[1].split('</td>', 1)[0]


def test_diamond_audit_visits_each_ancestor_once_and_preserves_sources():
    when = datetime(2026, 10, 26, tzinfo=timezone.utc)
    original = Provenance(kind="user_input", source="direct user input: W-2 shared",
                          entered_by="staff-test", recorded_at=when)
    shared = Provenance(kind="document", source="shared W-2, box 1", value="100",
                        inputs={"record_source": original.model_dump(mode="json")},
                        entered_by=original.entered_by, recorded_at=original.recorded_at)
    def tool(line, source, parents):
        return LineValue(line=line, amount="100", provenance=[Provenance(kind="tool", source=source,
                         value="100", inputs={"values": ["100"]})], depends_on=parents)
    lines = {
        "1z": LineValue(line="1z", amount="100", provenance=[shared]),
        "2a": tool("2a", "left calculation", ["1z"]),
        "2b": tool("2b", "right calculation", ["1z"]),
        "9": tool("9", "join calculation", ["2a", "2b"]),
    }
    html = render_draft({"lines": lines, "status": "draft_ready", "review_status": "passed"})
    audit = _audit_for(html, "9")
    for key in lines:
        assert audit.count(f'data-source-line="{key}"') == 1
    for source in [shared.source, "left calculation", "right calculation", "join calculation"]:
        assert audit.count(f'<strong>{source}</strong>') == 1
    assert 'record_source' in audit and original.source in audit
    assert 'staff-test' in audit and when.isoformat() in audit
    assert 'Calculation inputs:' in audit
    assert '<a href="#audit-9-2">1z</a> (shown above)' in audit
    # Visited sets reset per displayed line, so its own source remains available too.
    assert _audit_for(html, "1z").count('data-source-line="1z"') == 1


def test_layered_diamond_audit_size_grows_with_nodes_not_paths():
    def render_layers(depth):
        lines = {"shared": LineValue(line="shared", amount="1", provenance=[Provenance(kind="document", source="base source")])}
        parents = ["shared"]
        for layer in range(depth):
            children = [f"left-{layer}", f"right-{layer}"]
            for key in children:
                lines[key] = LineValue(line=key, amount="1", depends_on=parents,
                                      provenance=[Provenance(kind="tool", source=f"calculation-{key}")])
            parents = children
        lines["9"] = LineValue(line="9", amount="1", depends_on=parents,
                               provenance=[Provenance(kind="tool", source="final calculation")])
        return _audit_for(render_draft({"lines": lines, "status": "draft_ready", "review_status": "passed"}), "9")
    small, large = render_layers(8), render_layers(16)
    assert small.count('data-source-line=') == 18
    assert large.count('data-source-line=') == 34
    assert large.count('data-source-line="shared"') == 1
    assert len(large) < 2.5 * len(small)


@pytest.mark.production_stubs
@pytest.mark.parametrize("mark_stubs_nonstub", [False, True])
def test_skeleton_uses_local_provenance_and_deduplicated_dependency_traces(make_graph, monkeypatch, mark_stubs_nonstub):
    from src.tools import TOOLS
    if mark_stubs_nonstub:
        # Exercise every rendered line without claiming real tax math; flags change only in this test.
        for name, (fn, _) in list(TOOLS.items()):
            monkeypatch.setitem(TOOLS, name, (fn, False))
    state = make_graph().invoke({"case_path": SKELETON_CASE}, {"configurable": {"thread_id": "compact-skeleton"}})
    for line in state["lines"].values():
        if line.depends_on:
            assert not any(p.kind in {"document", "user_input"} for p in line.provenance)
            assert len([p for p in line.provenance if p.kind == "tool"]) == 1
    assert sum(len(line.provenance) for line in state["lines"].values()) < 60
    html = render_draft(state)
    assert len(html.encode()) < 250000
    if mark_stubs_nonstub:
        audit = _audit_for(html, "37")
        visited = set()
        def collect(key):
            if key in visited:
                return
            visited.add(key)
            for parent in state["lines"][key].depends_on:
                collect(parent)
        collect("37")
        assert audit.count('data-source-line=') == len(visited)
        for key in visited:
            assert audit.count(f'data-source-line="{key}"') == 1
            for step in state["lines"][key].provenance:
                assert step.source in audit
        assert 'record_source' in audit and 'case file' in audit and 'recorded_at' in audit
    else:
        # A real sum depending on a stub is still withheld without copying its ancestor's flags.
        assert not state["lines"]["9"].is_stub
        assert 'id="line-9"' not in html
