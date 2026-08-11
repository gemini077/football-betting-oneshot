from __future__ import annotations

from scripts.football_data.phase2c1_model import probability_payload


def test_top_scores_use_probability_then_home_then_away_order():
    payload = probability_payload(1.0, 1.0)
    assert [(row["home_goals"], row["away_goals"]) for row in payload["top_scores"][:3]] == [
        (0, 0),
        (0, 1),
        (1, 0),
    ]

