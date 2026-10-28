"""Every case in evals/cases.json runs as part of the test suite."""

import pytest

from evals.run_evals import load_cases, run_case


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_eval_case(case):
    outcome = run_case(case)
    assert outcome.passed, "\n".join(outcome.problems)


def test_live_vision_check_compares_amounts_as_numbers_at_any_depth():
    from evals.live_vision_check import same

    assert same("18000.00", 18000.0)
    assert same([{"code": "D", "amount": "1000.00"}], [{"code": "D", "amount": 1000.0}])
    assert not same([{"code": "D", "amount": "1000.00"}], [{"code": "E", "amount": "1000.00"}])
    assert not same([{"code": "D", "amount": "1000.00"}], [{"code": "D", "amount": "100.00"}])
    assert not same([{"code": "D", "amount": "1000.00"}], [])
    assert same(None, None) and not same(None, "0") and not same(False, True)
