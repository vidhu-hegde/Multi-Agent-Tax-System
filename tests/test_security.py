"""Security tests for SSN validation and PII redaction."""

import pytest

import src.memory as memory
from src.schemas import SSN_PATTERN
from src.security import (
    SSNValidationError,
    TEST_SSN_PATTERN,
    redact_ssns,
    validate_test_ssn,
)


@pytest.mark.parametrize(
    "value",
    [
        "900-12-3456",
        "901-23-4567",
        "999-99-9999",
    ],
)
def test_only_900_to_999_test_ssns_are_accepted(value):
    assert validate_test_ssn(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "123-45-6789",
        "899-45-6789",
        "000-12-3456",
        "901234567",
        "901-2-4567",
        None,
    ],
)
def test_real_range_or_invalid_ssns_are_rejected_without_echoing(value):
    with pytest.raises(SSNValidationError) as error:
        validate_test_ssn(value)

    if value is not None:
        assert str(value) not in str(error.value)


def test_redaction_masks_dashed_and_compact_ssns():
    safe = redact_ssns(
        "Taxpayer 123-45-6789; spouse 987654321"
    )

    assert safe == (
        "Taxpayer ***-**-6789; spouse ***-**-4321"
    )
    assert "123-45-6789" not in safe
    assert "987654321" not in safe


def test_redaction_recurses_through_log_and_trace_payloads():
    payload = {
        "prompt": "Confirm 123-45-6789",
        "messages": [
            "Test SSN 901234567",
            {"note": "No sensitive value here"},
        ],
    }

    safe = redact_ssns(payload)

    assert safe == {
        "prompt": "Confirm ***-**-6789",
        "messages": [
            "Test SSN ***-**-4567",
            {"note": "No sensitive value here"},
        ],
    }

    # Sanitization returns a safe copy instead of modifying the source.
    assert payload["prompt"] == "Confirm 123-45-6789"


def test_schema_and_security_use_the_same_ssn_pattern():
    assert SSN_PATTERN == TEST_SSN_PATTERN


def test_memory_uses_shared_redaction_helper():
    """Memory and model paths must use the central security boundary."""
    assert memory.redact_ssns is redact_ssns


def test_redaction_masks_integer_ssn_in_trace_payload():
    """Nine-digit integers must not bypass recursive trace redaction."""
    payload = {"tool_input": {"taxpayer_id": 123456789}}

    redacted = redact_ssns(payload)

    assert redacted["tool_input"]["taxpayer_id"] == "***-**-6789"
    assert "123456789" not in str(redacted)