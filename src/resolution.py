"""Validation helpers for human-in-the-loop resolutions."""

from decimal import Decimal, InvalidOperation


def validate_resolution_corrections(
    reason: str,
    action: str,
    corrections: dict | None,
) -> dict:
    """Validate reason-specific fields before graph resume."""

    if action == "stop":
        return {}

    if reason == "tool_input_invalid":
        raise ValueError(
            "This calculation-input ticket cannot be continued. "
            "Stop the session, correct the source data, "
            "and start a new return."
        )

    if reason == "1099r_taxable_not_determined":
        if (
            not isinstance(corrections, dict)
            or "taxable_amount" not in corrections
        ):
            raise ValueError(
                "A corrected taxable amount is required "
                "before continuing this 1099-R ticket."
            )

        try:
            amount = Decimal(
                str(corrections["taxable_amount"])
            )
        except (
            InvalidOperation,
            ValueError,
            TypeError,
        ) as exc:
            raise ValueError(
                "The corrected taxable amount must be "
                "a finite, nonnegative number."
            ) from exc

        if not amount.is_finite() or amount < 0:
            raise ValueError(
                "The corrected taxable amount must be "
                "a finite, nonnegative number."
            )

        return {
            "taxable_amount": str(amount),
        }

    if corrections:
        raise ValueError(
            f"Corrections are not supported for {reason}."
        )

    return {}