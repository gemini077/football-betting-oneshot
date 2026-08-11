from __future__ import annotations

from scripts.football_data.phase2c1_model import CandidateSpec, build_team_strength_prediction

from phase2c1_test_support import balanced_history, target


def test_changing_target_score_does_not_change_prediction_inputs_or_output():
    rows = balanced_history()
    first = build_team_strength_prediction(target(), rows, CandidateSpec(window="last_10", shrinkage=3))
    changed_target = target()
    changed_target["home_goals"] = 0
    changed_target["away_goals"] = 7
    second = build_team_strength_prediction(changed_target, rows, CandidateSpec(window="last_10", shrinkage=3))

    assert first == second
