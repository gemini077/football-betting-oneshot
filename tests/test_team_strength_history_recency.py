from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


def result(match_id: str, kickoff: str, home: str = "team:home", away: str = "team:away") -> dict:
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


def test_old_history_is_not_current_even_when_source_was_captured_today():
    records = [
        result(f"match:{index}", f"2025-05-{index + 1:02d}T12:00:00Z")
        for index in range(5)
    ]
    snapshot = TeamStrengthBuilder(records, captured_at="2026-08-10T00:00:00Z").build(
        "team:home",
        target_kickoff="2026-08-11T00:00:00Z",
        window_type="last_5",
    )

    assert snapshot["matches"] == 5
    assert snapshot["latest_historical_match_at"] == "2025-05-05T12:00:00Z"
    assert snapshot["history_age_days"] > 365
    assert snapshot["history_recency_status"] == "stale"
    assert snapshot["current_strength_ready"] is False
    assert snapshot["captured_at"] == "2026-08-10T00:00:00Z"
    assert snapshot["source_as_of_at"] == "2025-05-05T12:00:00Z"
    assert snapshot["freshness"]["state"] == "stale"
    assert snapshot["freshness"]["reference"] == "source_as_of_at"


def test_recent_current_season_result_replaces_stale_status():
    snapshot = TeamStrengthBuilder(
        [result("match:recent", "2026-08-03T12:00:00Z", "team:home", "team:away")],
        captured_at="2026-08-10T00:00:00Z",
    ).build("team:home", target_kickoff="2026-08-11T00:00:00Z", window_type="last_5")

    assert snapshot["history_age_days"] == 7.5
    assert snapshot["history_recency_status"] == "current"
    assert snapshot["current_strength_ready"] is True
