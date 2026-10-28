"""Married filing separately and Social Security (policy.md#taxable-social-security; raised by Max on PR #9).

An MFS filer who lived with their spouse at any time in 2025 has a $0 base amount, not $25,000.
Intake asks only MFS filers with an SSA-1099; Rules records the case; Computation passes it to tax_math.
"""

import json
from decimal import Decimal

import pytest
from langgraph.types import Command

from tests.conftest import SKELETON_CASE

QUESTION = "Did you live with your spouse at any time during 2025?"


def config(thread_id="mfs"):
    return {"configurable": {"thread_id": thread_id}}


def paused_on(result):
    interrupts = result.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None


@pytest.fixture
def mfs_case(tmp_path):
    def make(**answers):
        data = json.loads(open(SKELETON_CASE, encoding="utf-8").read())
        data["answers"].update(filing_status="mfs", spouse_itemizes=False)
        data["answers"].update(answers)
        path = tmp_path / "mfs.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    return make


def test_mfs_filer_with_social_security_is_asked(make_graph, mfs_case):
    result = make_graph().invoke({"case_path": mfs_case()}, config())
    prompt = paused_on(result)
    assert prompt["type"] == "intake_question"
    assert prompt["field"] == "mfs_lived_with_spouse"
    assert QUESTION in prompt["prompt"]


def test_not_living_together_uses_the_standard_base(make_graph, mfs_case):
    graph = make_graph()
    graph.invoke({"case_path": mfs_case()}, config())
    result = graph.invoke(Command(resume="no"), config())
    assert result["status"] == "draft_ready"
    decision = result["rule_decisions"]["social_security_base"]
    assert decision.outcome == {"case": "standard", "mfs_lived_with_spouse": False}
    assert decision.citation == "policy.md#taxable-social-security"


def test_rules_names_the_zero_base_case(make_graph, mfs_case):
    result = make_graph().invoke({"case_path": mfs_case(mfs_lived_with_spouse=True)}, config())
    assert result["rule_decisions"]["social_security_base"].outcome["case"] == "mfs_lived_with_spouse"


def test_not_sure_goes_to_a_volunteer(make_graph, mfs_case):
    graph = make_graph()
    graph.invoke({"case_path": mfs_case()}, config())
    result = graph.invoke(Command(resume="I'm not sure"), config())
    ticket = paused_on(result)
    assert ticket["reason"] == "uncertain"
    assert QUESTION in ticket["evidence"]["question"]
    assert not result.get("lines")


def test_mfs_without_social_security_is_not_asked(make_graph, mfs_case, tmp_path):
    data = json.loads(open(mfs_case(), encoding="utf-8").read())
    data["documents"] = [d for d in data["documents"] if d["form_type"] != "SSA-1099"]
    path = tmp_path / "mfs-no-ssa.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = make_graph().invoke({"case_path": str(path)}, config())
    assert result["status"] == "draft_ready"
    assert result["rule_decisions"]["social_security_base"].outcome["case"] == "unknown"


def test_other_filing_statuses_are_never_asked(make_graph):
    result = make_graph().invoke({"case_path": SKELETON_CASE}, config())
    assert result["status"] == "draft_ready"
    assert result["rule_decisions"]["social_security_base"].outcome["case"] == "standard"


def test_living_together_reaches_computation_with_no_base_amount(make_graph, mfs_case):
    result = make_graph().invoke({"case_path": mfs_case(mfs_lived_with_spouse=True)}, config())
    assert result["status"] == "draft_ready"
    line = result["lines"]["6b"]
    rule, tool = line.provenance
    assert rule.kind == "rule" and rule.source == "social_security_base"
    assert rule.value["case"] == "mfs_lived_with_spouse"
    assert rule.citation == "policy.md#taxable-social-security"
    assert tool.inputs["lived_with_spouse"] is True
    # l8 = 11,000 + 24,420 + 80 = 35,500; 0.85 * 35,500 = 30,175, capped at 0.85 * 22,000 = 18,700
    # (the $25,000 base would give 5,775)
    assert line.amount == Decimal("18700")
