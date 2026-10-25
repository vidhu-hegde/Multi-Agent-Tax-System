from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas import Dependent, LineValue, Provenance, RuleDecision


def test_only_test_range_ssns_are_accepted():
    Dependent(name="Sam", ssn="901-23-4567", relationship="grandchild")
    for bad in ["123-45-6789", "899-12-3456", "901234567", "901-23-456"]:
        with pytest.raises(ValidationError):
            Dependent(name="Sam", ssn=bad, relationship="grandchild")


def test_line_value_needs_provenance():
    with pytest.raises(ValidationError):
        LineValue(line="1z", amount=Decimal("100"), provenance=[])
    LineValue(line="1z", amount=Decimal("100"), provenance=[Provenance(kind="user_input", source="intake")])


def test_rule_decision_must_cite():
    with pytest.raises(ValidationError):
        RuleDecision(rule_id="scope", outcome={}, explanation="x", citation="")


def _w2(**values):
    from src.schemas import W2Record

    source = Provenance(kind="document", source="demo/w2_image_1.jpg")
    return W2Record(document_id="w2-1", source=source, employer_name="Acme", wages=Decimal("100"), **values)


def test_w2_keeps_only_the_last_four_ssn_digits():
    record = _w2(employee_ssn="901-23-4567")
    assert record.employee_ssn_last4 == "4567"
    assert "901-23" not in record.model_dump_json()


def test_w2_with_a_real_looking_ssn_is_rejected():
    for real in ["123-45-6789", "899-12-3456"]:
        with pytest.raises(ValidationError, match="test range"):
            _w2(employee_ssn=real)


def test_w2_ein_format_is_checked():
    assert _w2(employer_ein="00-1234567").employer_ein == "00-1234567"
    with pytest.raises(ValidationError):
        _w2(employer_ein="001234567")
