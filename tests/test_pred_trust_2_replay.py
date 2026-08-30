from __future__ import annotations

import math

import pytest

from scripts.prediction_trust_2_replay import (
    CANDIDATE_SPECS,
    build_score_matrix,
    derive_candidate_lambdas,
)


def test_candidate_registry_is_bounded_and_structurally_distinct():
    assert [spec["candidate_id"] for spec in CANDIDATE_SPECS] == [
        "champion",
        "challenger_a_strength_separation",
        "challenger_b_market_to_goal_separation",
    ]
    assert len(CANDIDATE_SPECS) == 3
    assert len({spec["hypothesis"] for spec in CANDIDATE_SPECS}) == 3


def test_candidate_lambdas_isolate_the_declared_boundaries():
    inputs = {
        "form_home": 2.0,
        "form_away": 1.0,
        "market_total": 3.2,
        "market_share": 0.5,
        "form_total": 3.0,
    }
    champion = derive_candidate_lambdas("champion", **inputs)
    strength = derive_candidate_lambdas(
        "challenger_a_strength_separation", **inputs
    )
    market = derive_candidate_lambdas(
        "challenger_b_market_to_goal_separation", **inputs
    )

    assert champion["total"] == pytest.approx(0.6 * 3.0 + 0.4 * 3.2)
    assert champion["share"] == pytest.approx(0.65 * (2.0 / 3.0) + 0.35 * 0.5)
    assert strength["total"] == pytest.approx(champion["total"])
    assert strength["share"] == pytest.approx(2.0 / 3.0)
    assert market["total"] == pytest.approx(3.2)
    assert market["share"] == pytest.approx(0.5)


def test_score_matrix_is_normalized_and_retains_right_tail():
    matrix = build_score_matrix(2.2, 1.3)
    assert sum(matrix.values()) == pytest.approx(1.0)
    assert matrix[(5, 1)] > 0
    assert sum(value for (home, away), value in matrix.items() if home + away >= 4) > 0
    assert max(matrix, key=matrix.get) == (2, 1)
    assert all(math.isfinite(value) and value >= 0 for value in matrix.values())
