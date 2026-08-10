from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def result(match_id: str, kickoff: str, competition: str, match_type: str):
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id=competition,
        season_id="season:2026",
        home_team_id="team:club",
        away_team_id=f"team:opponent:{match_id}",
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
        match_type=match_type,
    )


def test_recent_form_uses_eligible_competitive_matches_not_only_target_competition():
    records = [
        result("league", "2026-07-01T12:00:00Z", "competition:league", "league"),
        result("cup", "2026-07-10T12:00:00Z", "competition:cup", "domestic_cup"),
        result("continental", "2026-07-20T12:00:00Z", "competition:ucl", "continental_club"),
    ]

    snapshot = TeamStrengthBuilder(records).build(
        "team:club",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        competition_id="competition:ucl",
        season_id="season:2026",
    )

    assert snapshot["matches"] == 3
    assert snapshot["source_match_ids"] == ["league", "cup", "continental"]
