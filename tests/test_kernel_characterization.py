from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from automatic_model_core import build_automatic_model  # noqa: E402
from market_contracts import settle_contract  # noqa: E402
from model_baselines import build_market_reference  # noqa: E402
from risk_engine import (  # noqa: E402
    asian_handicap_settlement,
    asian_total_settlement,
    dixon_coles_score_matrix,
    exact_total_goals_set,
)


CHAMPION_FIXTURE = ROOT / "tests" / "fixtures" / "exact_distribution" / "current_model_input.json"


def _champion_fixture() -> dict:
    return json.loads(CHAMPION_FIXTURE.read_text(encoding="utf-8"))


def _market_reference_fixture() -> dict:
    return {
        "match_key": "M",
        "snapshot_id": "S",
        "canonical_model_input_sha256": "H",
        "source_cutoff_at": "cut",
        "market_snapshot_at": "market",
        "checkpoint_stage": "T-30M",
        "market": {
            "1x2": [
                {"bookmaker": "A", "home_odds": 2.5, "draw_odds": 3.5, "away_odds": 3.8},
                {"bookmaker": "B", "home_odds": 2.2, "draw_odds": 3.8, "away_odds": 4.2},
            ],
            "handicap": [{"line": -0.25}],
            "total": [{"line": 2.5}],
        },
        "source_snapshots": {
            "nowscore": {
                "snapshots": [
                    {
                        "ouzhi": {
                            "bookmakers": [
                                {
                                    "bookmaker": "A",
                                    "spf_current": {"home": 1.9, "draw": 3.4, "away": 4.5},
                                }
                            ]
                        }
                    }
                ]
            }
        },
    }


def test_champion_frozen_fixture_outputs_are_characterized():
    model = build_automatic_model(_champion_fixture(), include_exact_distribution=False)["model"]

    assert model["lambda_home"] == pytest.approx(1.238422, abs=1e-12)
    assert model["lambda_away"] == pytest.approx(1.551578, abs=1e-12)
    assert model["rho"] == 0.0
    assert model["calibration"]["market_total_line_median"] == pytest.approx(2.625, abs=1e-12)
    assert model["calibration"]["market_probabilities"] == pytest.approx({
        "home": 0.21473620250224484,
        "draw": 0.23940797209497164,
        "away": 0.5458558254027834,
    })
    assert model["probabilities"] == {
        "home": 0.30425,
        "draw": 0.249813,
        "away": 0.445937,
    }
    assert [
        (row["score"], row["probability"], row["fair_odds"], row["rank"])
        for row in model["score_probabilities"][:5]
    ] == [
        ("1-1", 0.118021, 8.473, 1),
        ("0-1", 0.0953, 10.4932, 2),
        ("1-2", 0.09156, 10.9218, 3),
        ("1-0", 0.076065, 13.1466, 4),
        ("0-2", 0.073933, 13.5258, 5),
    ]
    assert model["total_goals_buckets"] == [
        {"goals": "0", "probability": 0.061421},
        {"goals": "1", "probability": 0.171365},
        {"goals": "2", "probability": 0.239054},
        {"goals": "3", "probability": 0.222321},
        {"goals": "4", "probability": 0.155069},
        {"goals": "5", "probability": 0.086528},
        {"goals": "6+", "probability": 0.064242},
    ]
    assert model["btts"]["yes"] == pytest.approx(0.559667, abs=1e-12)
    assert model["btts"]["no"] == pytest.approx(0.440333, abs=1e-12)
    line = next(row for row in model["total_line_analysis"] if row["line"] == 2.75)
    assert line == {
        "line": 2.75,
        "over": {
            "win_equivalent_probability": 0.416999,
            "loss_equivalent_probability": 0.471841,
            "push_equivalent_probability": 0.11116,
            "fair_odds": 2.1315,
        },
        "under": {
            "win_equivalent_probability": 0.471841,
            "loss_equivalent_probability": 0.416999,
            "push_equivalent_probability": 0.11116,
            "fair_odds": 1.8838,
        },
    }


def test_champion_market_handicap_extraction_is_characterized():
    context = _champion_fixture()
    snapshot = context["source_snapshots"]["nowscore"]["snapshots"][0]
    snapshot["yazhi"] = {
        "companies": [
            {"current_handicap": -0.75},
            {"current_handicap": -1.0},
            {"current_handicap": -0.75},
        ]
    }

    result = build_automatic_model(context)

    assert result["decisions"]["score_selection_trace"]["asian_handicap_median"] == pytest.approx(-0.75)


def test_market_reference_selection_dedup_and_consensus_are_characterized():
    result = build_market_reference(_market_reference_fixture())

    assert result["version"] == "market_reference.v1"
    assert result["duplicate_bookmakers_excluded"] == 1
    assert result["market_handicap_line"] == -0.25
    assert result["market_total_line"] == 2.5
    assert [(row["bookmaker"], row["source_provider"], row["odds"]) for row in result["bookmakers"]] == [
        ("A", "nowscore", {"home": 1.9, "draw": 3.4, "away": 4.5}),
        ("B", "snapshot", {"home": 2.2, "draw": 3.8, "away": 4.2}),
    ]
    assert result["probabilities"] == pytest.approx({
        "home": 0.4901750249409263,
        "draw": 0.2787064457892206,
        "away": 0.23111852926985316,
    })


def test_score_matrix_and_quarter_line_pricing_are_characterized():
    matrix = dixon_coles_score_matrix({"lambda_home": 1.4, "lambda_away": 1.4, "rho": 0.0})

    assert sum(matrix.values()) == pytest.approx(1.0, abs=1e-15)
    assert matrix[(0, 0)] == pytest.approx(0.06081006304962981, abs=1e-15)
    assert matrix[(1, 1)] == pytest.approx(0.11918772357727443, abs=1e-15)
    assert matrix[(12, 12)] == pytest.approx(8.518720746719501e-16, abs=1e-18)

    handicap = asian_handicap_settlement(matrix, -0.25)
    total = asian_total_settlement(matrix, 2.75, "over")
    exact = exact_total_goals_set(matrix, (1, 3))
    assert handicap["parts"] == [-0.5, 0.0]
    assert handicap["fair_decimal_odds"] == pytest.approx(2.338339679247518, abs=1e-12)
    assert total["parts"] == [2.5, 3.0]
    assert total["half_win"] == pytest.approx(0.2224837506775789, abs=1e-12)
    assert total["fair_decimal_odds"] == pytest.approx(2.119601044706502, abs=1e-12)
    assert exact["totals"] == [1, 3]
    assert exact["probability"] == pytest.approx(0.39275192721654234, abs=1e-12)

    assert settle_contract(
        {"contract_id": "total", "family": "total", "selection": "over", "line": 2.75},
        (2, 1),
    )["units"] == 0.5
    assert settle_contract(
        {"contract_id": "handicap", "family": "asian_handicap", "selection": "home", "line": -0.25},
        (0, 0),
    )["units"] == -0.5
