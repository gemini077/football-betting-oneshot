from __future__ import annotations

from scripts.football_data.historical_results import deduplicate_historical_results, make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def result(provider: str, home_goals: int, away_goals: int) -> dict:
    return make_historical_match_result(
        canonical_match_id="match:competition:sweden-allsvenskan:2026-08-03:team:ik-sirius:team:sweden:halmstads-bk",
        competition_id="competition:sweden-allsvenskan",
        season_id="season:sweden-allsvenskan:2026",
        home_team_id="team:ik-sirius",
        away_team_id="team:sweden:halmstads-bk",
        kickoff_at="2026-08-03T18:00:00Z",
        home_goals=home_goals,
        away_goals=away_goals,
        provider=provider,
        provider_match_id=f"{provider}:same-match",
        source_as_of_at="2026-08-03T18:00:00Z",
        captured_at="2026-08-10T12:00:00Z",
        source_record_ref=f"{provider}:record",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_conflicting_cross_source_result_is_not_used_by_team_strength():
    report = deduplicate_historical_results([
        result("openfootball", 0, 2),
        result("football-data.co.uk", 1, 2),
    ])

    assert report.conflicts == 1
    assert all(item["eligible_for_team_strength"] is False for item in report.records)
    assert TeamStrengthBuilder(report.records).build(
        "team:ik-sirius",
        target_kickoff="2026-08-11T00:00:00Z",
        window_type="last_5",
    )["matches"] == 0
