from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def result(match_id: str, entity_type: str, kickoff: str):
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id=f"competition:{entity_type}",
        season_id="season:2026",
        home_team_id="team:shared-label",
        away_team_id=f"team:opponent:{match_id}",
        kickoff_at=kickoff,
        home_goals=2,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
        entity_type=entity_type,
        match_type="friendly" if entity_type == "national_team" else "league",
    )


def test_club_and_national_team_history_never_mix():
    records = [
        result("club-match", "club", "2026-07-01T12:00:00Z"),
        result("national-match", "national_team", "2026-07-10T12:00:00Z"),
    ]
    builder = TeamStrengthBuilder(records)

    club = builder.build(
        "team:shared-label",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        entity_type="club",
        competition_id="competition:club",
        season_id="season:2026",
    )
    national = builder.build(
        "team:shared-label",
        target_kickoff="2026-08-01T12:00:00Z",
        window_type="last_5",
        entity_type="national_team",
        competition_id="competition:national_team",
        season_id="season:2026",
    )

    assert club["source_match_ids"] == ["club-match"]
    assert national["source_match_ids"] == ["national-match"]
