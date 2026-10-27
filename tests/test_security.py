"""Security tests for SSN validation and PII redaction."""

import pytest
import run

import src.memory as memory
from src.schemas import SSN_PATTERN
from src.security import (
    SSNValidationError,
    TEST_SSN_PATTERN,
    redact_ssns,
    validate_test_ssn,
)
from src.graph import build_graph
import src.security as security


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


def test_checkpoint_contains_no_full_ssn_from_cli_resume(settings):
    """Raw taxpayer replies must be protected before SQLite persistence."""
    raw_ssn = "123-45-6789"
    ask_count = 0

    def ask(_prompt):
        nonlocal ask_count
        ask_count += 1
        if ask_count == 1:
            return f"My SSN is {raw_ssn}"
        raise KeyboardInterrupt

    with memory.open_checkpointer(settings) as saver:
        graph = build_graph(settings, checkpointer=saver)
        run.drive(
            graph,
            "security-checkpoint-test",
            {},
            ask=ask,
            say=lambda _message: None,
        )

    sqlite_artifacts = list(
        settings.db_path.parent.glob(settings.db_path.name + "*")
    )
    assert sqlite_artifacts

    persisted_bytes = b"".join(
        path.read_bytes()
        for path in sqlite_artifacts
    )

    assert raw_ssn.encode() not in persisted_bytes


def test_resume_ingress_protection_is_field_aware():
    """Ingress protection must distinguish text, money, and requested test SSNs."""
    assert (
        security.protect_resume_input(
            "My SSN is 123-45-6789",
            input_type="text",
        )
        == "My SSN is ***-**-6789"
    )

    # A nine-digit amount is valid in a money field and must not be mistaken for an SSN.
    assert (
        security.protect_resume_input(
            "123456789",
            input_type="money",
        )
        == "123456789"
    )

    # Requested synthetic SSNs are validated rather than masked before parsing.
    assert (
        security.protect_resume_input(
            "901-23-4567",
            input_type="test_ssn",
        )
        == "901-23-4567"
    )

    with pytest.raises(SSNValidationError):
        security.protect_resume_input(
            "123-45-6789",
            input_type="test_ssn",
        )


def test_intake_interrupt_exposes_security_context(settings):
    """The caller needs trusted metadata before creating Command(resume=...)."""
    with memory.open_checkpointer(settings) as saver:
        graph = build_graph(settings, checkpointer=saver)
        result = graph.invoke(
            {},
            memory.thread_config("security-contract-test"),
        )

    question = result["__interrupt__"][0].value

    assert question["type"] == "intake_question"
    assert question["field"] == "filing_status"
    assert question["input_type"] == "text"
    assert "filing status" in question["prompt"]