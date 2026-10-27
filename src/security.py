"""Central security helpers for SSN validation and PII redaction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from decimal import Decimal, InvalidOperation


# SilverFile accepts only synthetic SSNs with a 900-999 prefix.
TEST_SSN_PATTERN = r"^9\d{2}-\d{2}-\d{4}$"
_TEST_SSN_RE = re.compile(TEST_SSN_PATTERN)

# Detect both dashed and compact SSN-shaped values for masking.
_SSN_SHAPE_RE = re.compile(
    r"(?<!\d)(\d{3})-?(\d{2})-?(\d{4})(?!\d)"
)


class SSNValidationError(ValueError):
    """An SSN value that is unsafe or invalid for the SilverFile demo."""


def validate_test_ssn(value: Any) -> str:
    """Return a valid synthetic SSN or reject it without echoing the value."""

    if not isinstance(value, str):
        raise SSNValidationError(
            "Only a synthetic SSN in 9XX-XX-XXXX format is allowed."
        )

    if _TEST_SSN_RE.fullmatch(value) is None:
        raise SSNValidationError(
            "Only a synthetic SSN in 9XX-XX-XXXX format is allowed."
        )

    return value


def validate_staff_identifier(value: Any) -> str:
    """Return a non-PII staff identifier without echoing unsafe input."""

    if (
        not isinstance(value, str)
        or not value.strip()
        or _SSN_SHAPE_RE.search(value) is not None
    ):
        raise ValueError(
            "Use a non-SSN staff identifier for audit records."
        )

    return value.strip()


def redact_ssns(value: Any) -> Any:
    """Return a safe copy with SSN-shaped values masked to ***-**-1234."""

    # bool is a subclass of int, so require the exact int type.
    if type(value) is int and 100_000_000 <= value <= 999_999_999:
        digits = str(value)
        return f"***-**-{digits[-4:]}"

    if isinstance(value, str):
        return _SSN_SHAPE_RE.sub(
            lambda match: f"***-**-{match.group(3)}",
            value,
        )

    if isinstance(value, Mapping):
        return {
            key: redact_ssns(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [redact_ssns(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_ssns(item) for item in value)

    if isinstance(value, set):
        return {redact_ssns(item) for item in value}

    if isinstance(value, frozenset):
        return frozenset(redact_ssns(item) for item in value)

    return value


def protect_resume_input(value: Any, *, input_type: str) -> Any:
    """Protect a reply before it is placed inside Command(resume=...)."""

    if input_type not in {"text", "money", "test_ssn"}:
        raise ValueError("Unsupported resume input type")

    if input_type == "test_ssn":
        candidate = value.strip() if isinstance(value, str) else value
        return validate_test_ssn(candidate)

    if input_type == "money":
        try:
            candidate = Decimal(
                str(value).strip().replace("$", "").replace(",", "")
            )
        except (InvalidOperation, ValueError, TypeError):
            return redact_ssns(value)

        if candidate.is_finite() and candidate >= 0:
            return value

    return redact_ssns(value)