from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def result(match_id: str, kickoff: str, home: str, away: str, hg: int, ag: int) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=hg,
        away_goals=ag,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_builder_calculates_transparent_home_away_per_match_metrics():
    records = [
        result("match:a", "2026-07-01T12:00:00Z", "team:home", "team:one", 2, 0),
        result("match:b", "2026-07-10T12:00:00Z", "team:two", "team:home", 1, 1),
        result("match:c", "2026-07-20T12:00:00Z", "team:home", "team:three", 0, 2),
    ]
    builder = TeamStrengthBuilder(records, captured_at="2026-08-10T00:00:00Z")

    snapshot = builder.build(
        "team:home",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        competition_id="competition:test",
        season_id="season:2026",
    )

    assert snapshot["matches"] == 3
    assert snapshot["available_matches"] == 3
    assert snapshot["requested_window"] == "last_5"
    assert snapshot["effective_window"] == "last_3"
    assert snapshot["metrics"]["goals_for_per_match"] == 1.0
    assert snapshot["metrics"]["goals_against_per_match"] == 1.0
    assert snapshot["metrics"]["home"] == {"matches": 2, "goals_for": 2, "goals_against": 2}
    assert snapshot["metrics"]["away"] == {"matches": 1, "goals_for": 1, "goals_against": 1}
    assert snapshot["metrics"]["opponent_adjusted"] is None
    assert snapshot["minutes"] is None
    assert "per90" not in snapshot["metrics"]
    assert snapshot["opponents"] == ["team:one", "team:two", "team:three"]


def test_window_does_not_claim_more_matches_than_available():
    records = [result("match:a", "2026-07-01T12:00:00Z", "team:home", "team:one", 1, 0)]
    snapshot = TeamStrengthBuilder(records, captured_at="2026-08-10T00:00:00Z").build(
        "team:home",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_20",
        competition_id="competition:test",
        season_id="season:2026",
    )

    assert snapshot["matches"] == 1
    assert snapshot["available_matches"] == 1
    assert snapshot["requested_window"] == "last_20"
    assert snapshot["effective_window"] == "last_1"


def test_empty_history_is_explicitly_insufficient_and_not_high_quality():
    snapshot = TeamStrengthBuilder([], captured_at="2026-08-10T00:00:00Z").build(
        "team:home",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        competition_id="competition:test",
        season_id="season:2026",
    )

    assert snapshot["matches"] == 0
    assert snapshot["quality"] == "C"
    assert "insufficient_history" in snapshot["missing_reason"]
