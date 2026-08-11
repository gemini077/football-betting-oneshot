from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_model import CandidateSpec, build_team_strength_prediction

from phase2c1_test_support import result, target


def test_basic_formula_uses_competition_environment_and_venue_split():
    rows = [
        result("league-1", "2025-12-01T12:00:00Z", "team:other-1", "team:other-2", 1, 1),
        result("league-2", "2025-12-02T12:00:00Z", "team:other-3", "team:other-4", 1, 1),
        result("home-1", "2025-12-03T12:00:00Z", "team:home", "team:opponent-1", 3, 1),
        result("home-2", "2025-12-04T12:00:00Z", "team:home", "team:opponent-2", 3, 1),
        result("away-1", "2025-12-05T12:00:00Z", "team:opponent-3", "team:away", 2, 1),
        result("away-2", "2025-12-06T12:00:00Z", "team:opponent-4", "team:away", 2, 1),
    ]

    prediction = build_team_strength_prediction(
        target(day=10),
        rows,
        CandidateSpec(window="last_10", shrinkage=0, minimum_history=2),
    )

    # League home/away rates are 2.0/1.0.  The teams have 3/1 home
    # and 1/2 away rates, so the transparent relative-strength formula gives
    # 3.0 and 1.0 respectively.
    assert prediction["lambda_home"] == pytest.approx(3.0)
    assert prediction["lambda_away"] == pytest.approx(1.0)
    assert prediction["features"]["formula_version"] == "basic_team_strength_poisson.v1"
