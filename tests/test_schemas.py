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
