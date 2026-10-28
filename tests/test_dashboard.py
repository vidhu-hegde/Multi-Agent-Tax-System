"""The staff dashboard: queue, session pages and every resolve path, all through Sessions."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from src.dashboard.app import create_app, mask
from src.dashboard.demo import DEMO_RETURNS, seed
from src.sessions import open_sessions
from tests.conftest import SKELETON_CASE

W2_FORM = {
    "v_employer_name": "Finger Lakes Hardware Co.", "v_wages": "$18,000.00", "v_federal_withheld": "1500.00",
    "v_medicare_wages": "18000.00", "v_allocated_tips": "", "v_dependent_care_benefits": "",
    "v_statutory_employee": "no",
}


def config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


@pytest.fixture
def offline(settings):
    return replace(settings, anthropic_api_key="")


@pytest.fixture
def case_file(tmp_path):
    """The skeleton case with changes: case_file(r1_2b=True), case_file(image_w2=True), case_file(other=True)."""

    def make(name="case", r1_2b=False, image_w2=False, other=False, image_path=None, drop=()):
        case = json.loads(open(SKELETON_CASE).read())
        if r1_2b:
            case["documents"][2]["values"]["taxable_not_determined"] = True
        if image_w2 or image_path:
            case["documents"][0] = {"document_id": "w2-1", "form_type": "W-2",
                                    "image_path": image_path or "demo/w2_image_1.jpg"}
        if other:
            case["documents"].append({"document_id": "nec-1", "form_type": "other", "description": "1099-NEC"})
        for field in drop:
            case["answers"].pop(field)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(case))
        return str(path)

    return make


@pytest.fixture
def dashboard(offline):
    """(sessions, client): start returns with sessions.graph, look at them through the client."""
    with open_sessions(offline) as sessions, TestClient(create_app(sessions)) as client:
        yield sessions, client


def start(sessions, thread_id, path):
    return sessions.graph.invoke({"case_path": path}, config(thread_id))


def post(client, thread_id, ticket_id, **form):
    return client.post(f"/sessions/{thread_id}/tickets/{ticket_id}", data={"staff_id": "staff-7", **form},
                       follow_redirects=False)


def test_queue_lists_waiting_returns_and_every_status(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "box-2b", case_file("a", r1_2b=True))
    start(sessions, "clean", case_file("b"))

    page = client.get("/").text
    assert "1099-R taxable amount not determined (box 2b)" in page
    assert "1099r_taxable_not_determined:r-1" in page
    assert 'href="/sessions/clean"' in page and "Draft ready (1)" in page and "Waiting on staff (1)" in page

    only_ready = client.get("/?status=draft_ready").text
    assert 'href="/sessions/clean"' in only_ready
    assert only_ready.count('href="/sessions/box-2b"') == 1  # in the queue, not in the filtered list


def test_session_page_shows_the_ticket_and_its_evidence(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "conflict", "data/fixtures/conflict_case.json")
    page = client.get("/sessions/conflict").text
    assert "Taxpayer&#39;s answer disagrees with a document" in page
    assert "26450.00" in page and "24000" in page
    assert 'action="/sessions/conflict/tickets/document_conflict%3Awages"' in page
    assert client.get("/sessions/no-such-return").status_code == 404


def test_continue_resolves_the_ticket_and_the_return_finishes(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "box-2b", case_file(r1_2b=True))

    response = post(
        client,
        "box-2b",
        "1099r_taxable_not_determined:r-1",
        action="continue",
        note="Checked with client",
        taxable_amount="5,500.00",
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/sessions/box-2b?done=")
    assert "staff_id=staff-7" in response.headers["set-cookie"]

    assert sessions.summary("box-2b").status == "draft_ready"
    ticket = sessions.state("box-2b")["escalations"]["1099r_taxable_not_determined:r-1"]
    assert ticket.resolved_by == "staff-7" and ticket.resolution["note"] == "Checked with client"
    record = sessions.state("box-2b")["documents"]["r-1"]
    assert record.taxable_amount == Decimal("5500.00")
    assert record.taxable_not_determined is False
    assert "Draft Form 1040-SR" in client.get("/sessions/box-2b/draft").text


def test_1099r_correction_errors_do_not_echo_typed_values(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "box-2b-invalid", case_file(r1_2b=True))
    ticket_id = "1099r_taxable_not_determined:r-1"

    page = client.get("/sessions/box-2b-invalid").text
    assert 'name="taxable_amount"' in page
    assert "Taxable amount (box 2a)" in page

    missing = post(
        client,
        "box-2b-invalid",
        ticket_id,
        action="continue",
    )
    assert missing.status_code == 400
    assert sessions.summary("box-2b-invalid").awaiting_ticket_id == ticket_id

    typed_value = "98765bad"
    invalid = post(
        client,
        "box-2b-invalid",
        ticket_id,
        action="continue",
        taxable_amount=typed_value,
    )
    assert invalid.status_code == 400

    alert = invalid.text.split('role="alert">')[1].split("</div>")[0]
    assert "finite, nonnegative number" in alert
    assert typed_value not in alert
    assert sessions.summary("box-2b-invalid").awaiting_ticket_id == ticket_id

    too_large = post(
        client,
        "box-2b-invalid",
        ticket_id,
        action="continue",
        taxable_amount="6001",
    )
    assert too_large.status_code == 400
    assert "gross distribution" in too_large.text
    assert sessions.summary("box-2b-invalid").awaiting_ticket_id == ticket_id

    recovered = post(
        client,
        "box-2b-invalid",
        ticket_id,
        action="continue",
        taxable_amount="5500",
    )
    assert recovered.status_code == 303
    assert sessions.summary("box-2b-invalid").status == "draft_ready"


def test_1099r_too_large_correction_can_still_be_stopped(dashboard, case_file):
    sessions, client = dashboard
    thread_id = "box-2b-invalid-then-stop"
    ticket_id = "1099r_taxable_not_determined:r-1"
    start(sessions, thread_id, case_file(r1_2b=True))

    refused = post(
        client,
        thread_id,
        ticket_id,
        action="continue",
        taxable_amount="6001",
    )
    assert refused.status_code == 400

    stopped = post(client, thread_id, ticket_id, action="stop")
    assert stopped.status_code == 303
    assert sessions.summary(thread_id).status == "stopped"


def test_stop_ends_the_session(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "nec", case_file(other=True))
    assert post(client, "nec", "out_of_scope:nec-1", action="stop").status_code == 303
    assert sessions.summary("nec").status == "stopped"


def test_out_of_scope_needs_a_written_reason(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "nec", case_file(other=True))
    assert "Reason for continuing" in client.get("/sessions/nec").text

    refused = post(client, "nec", "out_of_scope:nec-1", action="continue", note="ok")
    assert refused.status_code == 400 and "write why the session can continue" in refused.text
    assert sessions.summary("nec").awaiting_ticket_id == "out_of_scope:nec-1"

    reason = "Client confirms the 1099-NEC was issued in error"
    assert post(client, "nec", "out_of_scope:nec-1", action="continue", note=reason).status_code == 303
    assert sessions.summary("nec").status == "draft_ready"


def test_a_staff_id_is_required(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "box-2b", case_file(r1_2b=True))
    response = post(client, "box-2b", "1099r_taxable_not_determined:r-1", action="continue", staff_id="  ")
    assert response.status_code == 400 and "staff ID" in response.text
    assert sessions.summary("box-2b").status == "waiting_on_human"


def test_a_ticket_already_resolved_is_refused(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "box-2b", case_file(r1_2b=True))
    first = post(
        client,
        "box-2b",
        "1099r_taxable_not_determined:r-1",
        action="continue",
        taxable_amount="5500",
    )
    assert first.status_code == 303
    second = post(client, "box-2b", "1099r_taxable_not_determined:r-1", action="stop")  # a second staff member
    assert second.status_code == 409 and "resolved it already" in second.text
    assert sessions.summary("box-2b").status == "draft_ready"


def test_tool_input_ticket_is_stop_only_on_dashboard(
    dashboard,
    case_file,
):
    from src.schemas import EscalationTicket

    sessions, client = dashboard
    thread_id = "tool-input-error"
    start(sessions, thread_id, case_file())

    ticket = EscalationTicket(
        ticket_id=(
            "tool_input_invalid:computation:"
            "tax_from_schedule:taxable_income"
        ),
        reason="tool_input_invalid",
        raised_by="computation",
        detail=(
            "Tax calculation tool tax_math.tax_from_schedule "
            "rejected invalid field(s): taxable_income. "
            "The rejected value was not retained."
        ),
        evidence={
            "tool": "tax_math.tax_from_schedule",
            "invalid_fields": ["taxable_income"],
        },
    )

    sessions.graph.invoke(
        {
            "escalations": {
                ticket.ticket_id: ticket,
            }
        },
        config(thread_id),
    )

    page = client.get(f"/sessions/{thread_id}").text
    assert "Tax calculation input needs correction" in page
    assert "The rejected value was not retained" in page
    assert 'value="continue"' not in page
    assert 'value="stop"' in page

    refused = post(
        client,
        thread_id,
        ticket.ticket_id,
        action="continue",
    )
    assert refused.status_code == 400
    assert "cannot be continued" in refused.text
    assert sessions.summary(thread_id).awaiting_ticket_id == ticket.ticket_id

    stopped = post(
        client,
        thread_id,
        ticket.ticket_id,
        action="stop",
    )
    assert stopped.status_code == 303
    assert sessions.summary(thread_id).status == "stopped"


def test_form_posts_from_another_site_are_refused(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "box-2b", case_file(r1_2b=True))
    url = "/sessions/box-2b/tickets/1099r_taxable_not_determined:r-1"
    form = {"staff_id": "staff-7", "action": "stop"}
    assert client.post(url, data=form, headers={"origin": "https://evil.example"}).status_code == 403
    assert sessions.summary("box-2b").status == "waiting_on_human"
    ok = client.post(url, data=form, headers={"origin": "http://testserver"}, follow_redirects=False)
    assert ok.status_code == 303


def test_staff_type_in_an_unreadable_w2(dashboard, case_file):
    sessions, client = dashboard
    result = start(sessions, "image-w2", case_file(image_w2=True))
    ticket_id = result["__interrupt__"][0].value["ticket_id"]

    page = client.get("/sessions/image-w2").text
    assert "Federal income tax withheld (box 2)" in page and "Box 12 code, row 1" in page
    assert '<img src="/sessions/image-w2/documents/w2-1/image"' in page

    response = post(client, "image-w2", ticket_id, action="continue", v_box12_code_0="d", v_box12_amount_0="1,200.00",
                    **W2_FORM)
    assert response.status_code == 303
    record = sessions.state("image-w2")["documents"]["w2-1"]
    assert record.wages == Decimal("18000.00") and record.federal_withheld == Decimal("1500.00")
    assert record.allocated_tips is None and record.statutory_employee is False
    assert [(e.code, e.amount) for e in record.box12] == [("D", Decimal("1200.00"))]
    assert sessions.summary("image-w2").status == "draft_ready"


def test_missing_w2_values_are_named_by_their_labels_and_not_echoed(dashboard, case_file):
    sessions, client = dashboard
    result = start(sessions, "image-w2", case_file(image_w2=True))
    ticket_id = result["__interrupt__"][0].value["ticket_id"]

    form = {**W2_FORM, "v_federal_withheld": "", "v_statutory_employee": "", "v_wages": "98765.43"}
    response = post(client, "image-w2", ticket_id, action="continue", **form)
    assert response.status_code == 400
    alert = response.text.split('role="alert">')[1].split("</div>")[0]
    assert "Federal income tax withheld (box 2)" in alert and "Statutory employee (box 13)" in alert
    assert "98765.43" not in alert  # the error names fields only
    assert 'value="98765.43"' in response.text  # but the form keeps what staff typed
    assert sessions.summary("image-w2").awaiting_ticket_id == ticket_id


def test_document_images_are_served_only_from_the_inventory_inside_the_project(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "image-w2", case_file("a", image_w2=True))
    image = client.get("/sessions/image-w2/documents/w2-1/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert client.get("/sessions/image-w2/documents/int-1/image").status_code == 404  # typed in, no image

    start(sessions, "not-an-image", case_file("b", image_path="README.md"))
    assert client.get("/sessions/not-an-image/documents/w2-1/image").status_code == 404
    start(sessions, "outside", case_file("c", image_path="../outside.jpg"))
    assert client.get("/sessions/outside/documents/w2-1/image").status_code == 404


def test_taxpayer_words_are_escaped(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "pressure", case_file(drop=["filing_status"]))
    reply = "My nephew told me to say <script>alert(1)</script> and send the refund to his account"
    sessions.graph.invoke(Command(resume=reply), config("pressure"))

    page = client.get("/sessions/pressure").text
    assert "Possible exploitation or third-party pressure" in page
    assert "Speak with the taxpayer privately" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_waiting_on_taxpayer_shows_the_question_and_no_draft(dashboard, case_file):
    sessions, client = dashboard
    start(sessions, "asking", case_file(drop=["filing_status"]))
    page = client.get("/sessions/asking").text
    assert "Waiting on the taxpayer" in page and "Which filing status" in page
    assert client.get("/sessions/asking/draft").status_code == 404


def test_ssn_shaped_values_are_masked_for_display():
    assert mask("SSN 901-12-3456 on file") == "SSN ***-**-3456 on file"
    assert mask({"ssn": "123456789", "wages": "26450.00"}) == {"ssn": "***-**-6789", "wages": "26450.00"}


def test_demo_seed_covers_every_state_once(offline, tmp_path):
    with open_sessions(offline) as sessions:
        started = seed(sessions, tmp_path / "cases")
        assert started == [thread_id for thread_id, _, _ in DEMO_RETURNS]
        statuses = {s.status for s in sessions.list_sessions()}
        assert statuses == {"draft_ready", "waiting_on_human", "waiting_on_taxpayer"}
        assert seed(sessions, tmp_path / "cases") == []  # already there


def test_conflicting_records_are_chosen_by_number(dashboard):
    from src.schemas import EscalationTicket

    sessions, client = dashboard
    first = EscalationTicket(ticket_id="conflicted", reason="uncertain", raised_by="intake", detail="Synthetic issue",
                             status="resolved", resolution={"action": "continue"})
    sessions.graph.invoke({"case_path": SKELETON_CASE, "escalations": {"conflicted": first}}, config("conflict"))
    sessions.graph.invoke({"escalations": {"conflicted": first.model_copy(update={"resolution": {"action": "stop"}})}},
                          config("conflict"))
    pending = sessions.summary("conflict")
    page = client.get("/sessions/conflict").text
    assert "Choose the record to keep" in page and 'name="choice" value="2"' in page

    refused = post(client, "conflict", pending.awaiting_ticket_id, action="continue")
    assert refused.status_code == 400 and "choice" in refused.text

    candidates = pending.open_tickets[0].evidence["candidates"]
    keep = next(i for i, c in enumerate(candidates, 1) if c["resolution"]["action"] == "continue")
    assert post(client, "conflict", pending.awaiting_ticket_id, action="continue", choice=str(keep)).status_code == 303
    assert sessions.state("conflict")["escalations"]["conflicted"].resolution["action"] == "continue"
