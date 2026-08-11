from __future__ import annotations

from scripts.football_data.phase2c1_model import CandidateSpec, build_team_strength_prediction

from phase2c1_test_support import balanced_history, result, target


def test_phase2c1_features_use_only_kickoffs_before_target():
    rows = balanced_history()
    rows.extend(
        [
            target(day=30),
            result("future", "2026-02-01T12:00:00Z", "team:home", "team:future", 100, 0),
        ]
    )

    prediction = build_team_strength_prediction(
        target(),
        rows,
        CandidateSpec(window="last_10", shrinkage=3),
    )

    assert "target" not in prediction["features"]["used_match_ids"]
    assert "future" not in prediction["features"]["used_match_ids"]
    assert all(value < "2026-01-31T00:00:00Z" for value in prediction["features"]["used_kickoffs"])
