from __future__ import annotations

from scripts.football_data.health import build_team_strength_health
from scripts.football_data.historical_results import make_historical_match_result


def result(match_id: str, team: str, opponent: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id=team,
        away_team_id=opponent,
        kickoff_at="2026-07-01T12:00:00Z",
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at="2026-07-01T12:00:00Z",
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_health_report_counts_both_one_sided_and_neither():
    current = [
        {"id": "target:both", "home_team_id": "team:home", "away_team_id": "team:away", "kickoff": "2026-08-01T12:00:00Z"},
        {"id": "target:home", "home_team_id": "team:home", "away_team_id": "team:no-history", "kickoff": "2026-08-01T12:00:00Z"},
        {"id": "target:none", "home": "Unknown FC", "away": "Unknown United", "kickoff": "2026-08-01T12:00:00Z"},
    ]
    records = [result("past-home", "team:home", "team:away"), result("past-away", "team:away", "team:home")]

    health = build_team_strength_health(current, records, captured_at="2026-08-10T00:00:00Z")

    assert health["current_matches"] == 3
    assert health["both_teams_evaluable"] == 1
    assert health["home_only"] == 1
    assert health["away_only"] == 0
    assert health["neither"] == 1
    assert health["identity_unresolved"] == 1
    assert len(health["coverage_by_match"]) == 3
