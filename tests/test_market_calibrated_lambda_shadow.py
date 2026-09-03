from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from automatic_model_core import _total_line_pricing
from market_calibrated_lambda_shadow import (
    CANDIDATE_ID,
    _devig_multiplicative,
    _devig_power,
    _devig_shin,
    derive_market_calibrated_lambdas,
    market_implied_total,
    solve_total_lambda,
)


def _fair_two_way_odds(expected_goals: float, line: float) -> tuple[float, float]:
    priced = _total_line_pricing(expected_goals, line)
    over = priced["over"]
    under = priced["under"]
    over_probability = over["win_equivalent_probability"] / (
        over["win_equivalent_probability"] + over["loss_equivalent_probability"]
    )
    under_probability = under["win_equivalent_probability"] / (
        under["win_equivalent_probability"] + under["loss_equivalent_probability"]
    )
    return 1 / over_probability, 1 / under_probability


def test_devig_methods_normalize_and_shin_matches_reference_example():
    odds = [2.6, 2.4, 4.3]
    multiplicative = _devig_multiplicative(odds)
    power = _devig_power(odds)
    shin = _devig_shin(odds)

    for probabilities in (multiplicative, power, shin):
        assert sum(probabilities) == pytest.approx(1.0, abs=1e-12)
        assert all(0 < value < 1 for value in probabilities)

    assert shin == pytest.approx(
        [0.37299406033208965, 0.4047794109200184, 0.2222265287474275],
        abs=1e-9,
    )
    assert power != pytest.approx(multiplicative, abs=1e-5)


@pytest.mark.parametrize("line", [2.0, 2.25, 2.5, 2.75, 3.0])
def test_total_lambda_solver_recovers_synthetic_market_with_quarter_lines(line):
    expected_goals = 2.73
    over_odds, under_odds = _fair_two_way_odds(expected_goals, line)

    solved = solve_total_lambda(
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
    )

    assert solved == pytest.approx(expected_goals, abs=2e-5)


def test_market_total_uses_robust_multi_book_multi_line_consensus():
    expected_goals = 2.9
    companies = []
    for line in (2.5, 2.75, 3.0):
        over_odds, under_odds = _fair_two_way_odds(expected_goals, line)
        companies.extend(
            [
                {
                    "name": f"A-{line}",
                    "current_line": line,
                    "current_over_water": over_odds - 1,
                    "current_under_water": under_odds - 1,
                },
                {
                    "name": f"B-{line}",
                    "current_line": line,
                    "current_over_water": over_odds - 1,
                    "current_under_water": under_odds - 1,
                },
            ]
        )

    result = market_implied_total({"daxiao": {"companies": companies}})

    assert result["line_count"] == 3
    assert result["solved_quote_count"] == 6
    assert result["total"] == pytest.approx(expected_goals, abs=2e-5)


def test_candidate_derivation_uses_market_prices_and_has_no_postmatch_argument():
    context = {
        "source_snapshots": {
            "nowscore": {
                "snapshots": [
                    {
                        "ouzhi": {
                            "bookmakers": [
                                {"spf_current": {"home": 2.1, "draw": 3.3, "away": 3.8}},
                                {"spf_current": {"home": 2.05, "draw": 3.4, "away": 3.9}},
                            ]
                        },
                        "daxiao": {
                            "companies": [
                                {
                                    "name": "A",
                                    "current_line": 2.75,
                                    "current_over_water": 0.92,
                                    "current_under_water": 0.94,
                                },
                                {
                                    "name": "B",
                                    "current_line": 2.5,
                                    "current_over_water": 0.78,
                                    "current_under_water": 1.04,
                                },
                            ]
                        },
                    }
                ]
            }
        }
    }

    candidate = derive_market_calibrated_lambdas(context)

    assert candidate["candidate_id"] == CANDIDATE_ID
    assert candidate["rho"] == 0.0
    assert candidate["lambda_home"] > 0
    assert candidate["lambda_away"] > 0
    assert candidate["lambda_home"] + candidate["lambda_away"] == pytest.approx(
        candidate["total"]
    )
    assert "actual" not in inspect.signature(derive_market_calibrated_lambdas).parameters
    assert "result" not in inspect.signature(derive_market_calibrated_lambdas).parameters
