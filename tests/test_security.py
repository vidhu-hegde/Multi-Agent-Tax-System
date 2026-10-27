"""Security tests for SSN validation and PII redaction."""

import pytest
import run
import re

import src.memory as memory
import src.security as security
from src.schemas import SSN_PATTERN
from src.security import (
    SSNValidationError,
    TEST_SSN_PATTERN,
    redact_ssns,
    validate_test_ssn,
)
from src.graph import build_graph
from src.sessions import open_sessions
from dataclasses import replace
from pathlib import Path


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


def test_staff_resolution_does_not_persist_ssns(
    settings,
    make_case,
):
    """Dashboard/staff metadata must be protected before graph resume."""

    note_ssn = "123-45-6789"
    thread_id = "security-staff-resolution"
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    case_path = make_case(r1_2b=True)

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {"case_path": case_path},
            config,
        )

        ticket_id = sessions.summary(thread_id).awaiting_ticket_id
        assert ticket_id is not None

        sessions.resolve(
            thread_id,
            ticket_id,
            note=f"Called taxpayer about {note_ssn}",
            resolved_by="staff-security-test",
        )

        ticket = sessions.state(thread_id)["escalations"][ticket_id]

        assert note_ssn not in str(ticket.resolution)
        assert ticket.resolution["note"] == (
            "Called taxpayer about ***-**-6789"
        )
        assert ticket.resolved_by == "staff-security-test"

    sqlite_artifacts = list(
        settings.db_path.parent.glob(settings.db_path.name + "*")
    )
    persisted_bytes = b"".join(
        path.read_bytes()
        for path in sqlite_artifacts
    )

    assert note_ssn.encode() not in persisted_bytes


def test_staff_identifier_rejects_ssn_before_resume(
    settings,
    make_case,
):
    """Audit identities must never be SSNs or SSN-derived identifiers."""

    staff_ssn = "234-56-7890"
    thread_id = "security-staff-identity"
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    with open_sessions(settings) as sessions:
        sessions.graph.invoke(
            {"case_path": make_case(r1_2b=True)},
            config,
        )

        ticket_id = sessions.summary(thread_id).awaiting_ticket_id
        assert ticket_id is not None

        with pytest.raises(ValueError, match="staff identifier"):
            sessions.resolve(
                thread_id,
                ticket_id,
                note="Reviewed",
                resolved_by=f"staff-{staff_ssn}",
            )

        # Rejection happens before Command(resume=...), so the ticket remains open.
        assert (
            sessions.summary(thread_id).awaiting_ticket_id
            == ticket_id
        )

    persisted_bytes = b"".join(
        path.read_bytes()
        for path in settings.db_path.parent.glob(
            settings.db_path.name + "*"
        )
    )
    assert staff_ssn.encode() not in persisted_bytes


def test_settings_repr_does_not_expose_api_key(settings):
    """Exceptions and debug output must not reveal configured secrets."""

    secret = "unit-test-provider-secret"
    configured = replace(
        settings,
        anthropic_api_key=secret,
    )

    rendered = repr(configured)

    assert secret not in rendered
    assert "anthropic_api_key" not in rendered


def test_docker_context_excludes_secrets_and_runtime_data():
    """Future Docker builds must not receive local secrets or checkpoints."""

    repository = Path(__file__).resolve().parents[1]
    entries = {
        line.strip()
        for line in (repository / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    required = {
        ".env",
        ".env.*",
        "!.env.example",
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        "*.sqlite",
        "*.sqlite3",
        "*.sqlite-wal",
        "*.sqlite-shm",
        "*.db",
        "output/",
        "traces/",
        ".git/",
    }

    assert required <= entries


def test_api_key_is_not_serialized_to_state_or_checkpoint(settings):
    """Runtime credentials must stay in configuration, not workflow data."""

    secret = "unit-test-provider-secret"
    configured = replace(
        settings,
        anthropic_api_key=secret,
    )

    with memory.open_checkpointer(configured) as saver:
        graph = build_graph(
            configured,
            checkpointer=saver,
        )
        result = graph.invoke(
            {},
            memory.thread_config("security-secret-test"),
        )

        assert secret not in str(result)
        assert secret not in str(
            graph.get_state(
                memory.thread_config("security-secret-test")
            ).values
        )

    persisted_bytes = b"".join(
        path.read_bytes()
        for path in configured.db_path.parent.glob(
            configured.db_path.name + "*"
        )
    )
    assert secret.encode() not in persisted_bytes


def test_repository_text_files_do_not_contain_secret_values():
    """Committed source, docs, and fixtures must not contain live credentials."""

    repository = Path(__file__).resolve().parents[1]
    text_suffixes = {
        ".py",
        ".md",
        ".json",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
    }
    explicit_files = {
        ".env.example",
        ".gitignore",
        ".dockerignore",
        "requirements.txt",
    }
    ignored_parts = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        "output",
    }

    patterns = [
        re.compile(
            r"(?m)^\s*(?:export\s+)?"
            r"(?:ANTHROPIC_API_KEY|OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY)"
            r"\s*=\s*"
            r"(?:[\"'][^\"']+[\"']|[^\s#]+)"
            r"\s*$"
        ),
        re.compile(
            r"\b(?:sk-ant-|sk-proj-|ghp_)"
            r"[A-Za-z0-9_-]{12,}\b"
        ),
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
        ),
    ]

    offenders = []

    for path in repository.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        if (
            path.suffix.lower() not in text_suffixes
            and path.name not in explicit_files
        ):
            continue

        text = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        if any(pattern.search(text) for pattern in patterns):
            offenders.append(
                str(path.relative_to(repository))
            )

    assert offenders == []