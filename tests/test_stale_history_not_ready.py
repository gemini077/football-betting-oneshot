from __future__ import annotations

from scripts.football_data.health import build_team_strength_health
from scripts.football_data.historical_results import make_historical_match_result


def result(match_id: str, kickoff: str, home: str, away: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2025",
        home_team_id=home,
        away_team_id=away,
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
    )


def test_history_available_is_separate_from_current_strength_ready():
    records = [
        result(f"match:{index}", f"2025-05-{index + 1:02d}T12:00:00Z", "team:home", "team:away")
        for index in range(5)
    ]
    health = build_team_strength_health(
        [{
            "id": "target:stale",
            "home_team_id": "team:home",
            "away_team_id": "team:away",
            "kickoff": "2026-08-11T00:00:00Z",
        }],
        records,
        captured_at="2026-08-10T00:00:00Z",
    )

    assert health["both_history_available"] == 1
    assert health["both_current_strength_ready"] == 0
    assert health["stale_history"] == 1
    assert health["coverage_by_match"][0]["status"] == "stale_history"
    assert health["coverage_by_match"][0]["reasons"] == ["stale_history"]
