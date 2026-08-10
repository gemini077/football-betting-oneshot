from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def result(match_id: str, kickoff: str, competition: str, season: str, score: tuple[int, int]):
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id=competition,
        season_id=season,
        home_team_id="team:target",
        away_team_id=f"team:opponent:{match_id}",
        kickoff_at=kickoff,
        home_goals=score[0],
        away_goals=score[1],
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_last5_crosses_seasons_but_season_to_date_does_not():
    records = [
        result("past:2025", "2025-12-20T12:00:00Z", "competition:old", "season:2025", (1, 0)),
        result("past:2026", "2026-07-20T12:00:00Z", "competition:new", "season:2026", (2, 1)),
    ]
    builder = TeamStrengthBuilder(records, captured_at="2026-08-10T00:00:00Z")

    recent = builder.build(
        "team:target",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        competition_id="competition:new",
        season_id="season:2026",
    )
    season = builder.build(
        "team:target",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="season_to_date",
        competition_id="competition:new",
        season_id="season:2026",
    )

    assert recent["matches"] == 2
    assert recent["source_match_ids"] == ["past:2025", "past:2026"]
    assert season["matches"] == 1
    assert season["source_match_ids"] == ["past:2026"]
