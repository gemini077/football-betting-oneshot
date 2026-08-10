from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def match(match_id: str, kickoff: str, hg: int, ag: int) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id="team:home",
        away_team_id=f"team:{match_id}",
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


def test_target_and_future_matches_never_enter_pre_match_snapshot():
    records = [
        match("past-a", "2026-07-01T12:00:00Z", 1, 0),
        match("past-b", "2026-07-02T12:00:00Z", 2, 1),
        match("target", "2026-08-01T12:00:00Z", 9, 9),
        match("future-c", "2026-08-02T12:00:00Z", 100, 0),
    ]

    snapshot = TeamStrengthBuilder(records, captured_at="2026-08-10T00:00:00Z").build(
        "team:home",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        competition_id="competition:test",
        season_id="season:2026",
    )

    assert snapshot["matches"] == 2
    assert snapshot["metrics"]["goals_for_per_match"] == 1.5
    assert snapshot["metrics"]["goals_against_per_match"] == 0.5
    assert snapshot["source_match_ids"] == ["past-a", "past-b"]
