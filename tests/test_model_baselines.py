import json
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_baselines import (  # noqa: E402
    MARKET_REFERENCE_VERSION,
    SIMPLE_POISSON_VERSION,
    build_market_reference,
    build_simple_poisson_baseline,
)


def make_snapshot(*, venue=True, market=True, checkpoint_stage="T-30M"):
    form = {
        "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
        "away_overall": {"matches": 10, "goals_for": 10, "goals_against": 9},
    }
    if venue:
        form.update({
            "home_home": {"matches": 10, "goals_for": 20, "goals_against": 8},
            "away_away": {"matches": 10, "goals_for": 15, "goals_against": 10},
        })
    snapshot = {
        "match_key": "SYNTH-HOME-vs-AWAY",
        "snapshot_id": "SNAPSHOT-SYNTH-001",
        "canonical_model_input_sha256": "input-sha-synth-001",
        "source_cutoff_at": "2026-08-10T19:30:00+08:00",
        "market_snapshot_at": "2026-08-10T19:31:00+08:00",
        "checkpoint_stage": checkpoint_stage,
        "recent_form": form,
    }
    if market:
        snapshot["market"] = {
            "1x2": [
                {"bookmaker": "A", "home_odds": 2.50, "draw_odds": 3.50, "away_odds": 3.80},
                {"bookmaker": "B", "home_odds": 2.20, "draw_odds": 3.80, "away_odds": 4.20},
                {"bookmaker": "bad", "home_odds": 1.0, "draw_odds": 3.0, "away_odds": 3.0},
            ],
            "handicap": [{"bookmaker": "A", "line": -0.25, "home_odds": 0.91, "away_odds": 0.99}],
            "total": [{"bookmaker": "A", "line": 2.5, "over_odds": 0.93, "under_odds": 0.95}],
        }
    return snapshot


def test_market_reference_devig_medians_and_dispersion_are_auditable():
    result = build_market_reference(make_snapshot())

    assert result["version"] == MARKET_REFERENCE_VERSION
    assert result["status"] == "evaluable"
    assert result["market_bookmaker_count"] == 2
    assert set(result["raw_devig_probabilities"]) == {"A", "B"}
    assert all(value > 0 for value in result["probabilities"].values())
    assert math.isclose(sum(result["probabilities"].values()), 1.0, abs_tol=1e-12)
    assert result["market_dispersion"] > 0
    assert result["market_probability_min"]["home"] < result["market_probability_max"]["home"]
    assert result["market_handicap_line"] == -0.25
    assert result["market_total_line"] == 2.5
    assert result["market_handicap_quotes"]
    assert result["market_total_quotes"]

    first = result["raw_devig_probabilities"]["A"]
    raw = [1 / 2.5, 1 / 3.5, 1 / 3.8]
    total = sum(raw)
    assert first["home"] == pytest.approx(raw[0] / total)


def test_market_reference_rejects_invalid_bookmaker_and_requires_two_valid_quotes():
    snapshot = make_snapshot()
    snapshot["market"]["1x2"] = [
        {"bookmaker": "only", "home_odds": 2.0, "draw_odds": 3.0, "away_odds": 4.0},
        {"bookmaker": "invalid", "home_odds": 2.0, "draw_odds": 1.0, "away_odds": 4.0},
    ]

    result = build_market_reference(snapshot)

    assert result["status"] == "not_evaluable"
    assert result["market_bookmaker_count"] == 1
    assert result["probabilities"] is None
    assert result["reason"] == "insufficient_valid_bookmakers"


def test_market_reference_does_not_fill_missing_market_from_champion():
    snapshot = make_snapshot(market=False)
    snapshot["champion"] = {"probabilities": {"home": 0.9, "draw": 0.05, "away": 0.05}}

    result = build_market_reference(snapshot)

    assert result["status"] == "not_evaluable"
    assert result["probabilities"] is None
    assert result["champion_read"] is False
    assert result["raw_devig_probabilities"] == {}


def test_simple_poisson_prefers_home_and_away_venue_rates():
    result = build_simple_poisson_baseline(make_snapshot())

    assert result["version"] == SIMPLE_POISSON_VERSION
    assert result["status"] == "evaluable"
    assert result["input_source"] == "venue"
    assert result["lambda_home"] == pytest.approx((20 / 10 + 10 / 10) / 2)
    assert result["lambda_away"] == pytest.approx((15 / 10 + 8 / 10) / 2)
    assert result["rho"] == 0.0
    assert result["market_read"] is False
    assert result["champion_read"] is False


def test_simple_poisson_uses_overall_fallback_when_venue_rows_are_unusable():
    result = build_simple_poisson_baseline(make_snapshot(venue=False))

    assert result["status"] == "evaluable"
    assert result["input_source"] == "overall_fallback"
    assert result["lambda_home"] == pytest.approx((12 / 10 + 9 / 10) / 2)
    assert result["lambda_away"] == pytest.approx((10 / 10 + 13 / 10) / 2)


def test_simple_poisson_rejects_missing_form_and_lambda_outside_fixed_bounds():
    missing = make_snapshot(venue=False)
    missing["recent_form"] = {}
    assert build_simple_poisson_baseline(missing)["status"] == "not_evaluable"

    too_large = make_snapshot(venue=False)
    too_large["recent_form"]["home_overall"]["goals_for"] = 100
    result = build_simple_poisson_baseline(too_large)
    assert result["status"] == "not_evaluable"
    assert result["reason"] == "lambda_out_of_bounds"


def test_simple_poisson_outputs_normalized_probabilities_matrix_and_ranked_scores():
    result = build_simple_poisson_baseline(make_snapshot())

    assert math.isclose(sum(result["probabilities"].values()), 1.0, abs_tol=1e-12)
    assert math.isclose(sum(row["probability"] for row in result["score_matrix"]), 1.0, abs_tol=1e-12)
    assert math.isclose(sum(row["probability"] for row in result["total_goals_distribution"]), 1.0, abs_tol=1e-12)
    assert result["btts"]["yes"] + result["btts"]["no"] == pytest.approx(1.0)
    assert result["top1"] == result["score_matrix"][0]
    assert result["top3"] == result["score_matrix"][:3]
    assert result["top5"] == result["score_matrix"][:5]


def test_baseline_snapshot_fields_are_copied_without_recomputation():
    snapshot = make_snapshot()
    expected = {
        key: snapshot[key]
        for key in (
            "match_key", "snapshot_id", "canonical_model_input_sha256",
            "source_cutoff_at", "market_snapshot_at", "checkpoint_stage",
        )
    }

    assert {key: build_market_reference(snapshot)[key] for key in expected} == expected
    assert {key: build_simple_poisson_baseline(snapshot)[key] for key in expected} == expected
