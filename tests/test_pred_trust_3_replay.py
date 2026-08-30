from __future__ import annotations

import pytest

from scripts.prediction_trust_3_replay import (
    CANDIDATE_SPECS,
    derive_market_side_only_lambdas,
)


def test_registry_is_exactly_champion_b_and_one_new_candidate():
    assert [spec["candidate_id"] for spec in CANDIDATE_SPECS] == [
        "champion",
        "existing_challenger_b_market_to_goal_separation",
        "market_side_only_hybrid",
    ]
    assert len(CANDIDATE_SPECS) == 3


def test_market_side_only_reuses_champion_total_and_market_share():
    candidate = derive_market_side_only_lambdas(
        form_home=2.0,
        form_away=1.0,
        market_total=3.2,
        market_share=0.5,
        form_total=3.0,
    )

    champion_total = 0.60 * 3.0 + 0.40 * 3.2
    assert candidate["total"] == pytest.approx(champion_total)
    assert candidate["share"] == pytest.approx(0.5)
    assert candidate["lambda_home"] == pytest.approx(champion_total * 0.5)
    assert candidate["lambda_away"] == pytest.approx(champion_total * 0.5)
