"""Every case in evals/cases.json runs as part of the test suite."""

import pytest

from evals.run_evals import load_cases, run_case


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_eval_case(case):
    outcome = run_case(case)
    assert outcome.passed, "\n".join(outcome.problems)
