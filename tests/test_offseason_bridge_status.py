from __future__ import annotations

from scripts.football_data.health import build_team_strength_health
from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import TeamStrengthBuilder


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


def bridge_context() -> dict:
    return {
        "season_stage": "opening",
        "bridge_status": "verified",
        "bridge_from_season": "season:test:2025",
        "bridge_reason": "explicit schedule season opening evidence",
        "bridge_verification_evidence": ["schedule fixture:opening-round"],
    }


def test_verified_previous_season_bridge_is_explicit_and_not_current():
    snapshot = TeamStrengthBuilder(
        [result("match:old", "2026-05-16T12:00:00Z", "team:home", "team:away")],
        captured_at="2026-08-10T00:00:00Z",
    ).build(
        "team:home",
        target_kickoff="2026-08-11T00:00:00Z",
        window_type="last_5",
        bridge_context=bridge_context(),
    )

    assert snapshot["history_recency_status"] == "offseason_bridge"
    assert snapshot["current_strength_ready"] is False
    assert snapshot["bridge_from_season"] == "season:test:2025"
    assert snapshot["bridge_status"] == "verified"
    assert snapshot["bridge_reason"] == "explicit schedule season opening evidence"


def test_unverified_bridge_context_remains_stale():
    snapshot = TeamStrengthBuilder(
        [result("match:old", "2026-05-16T12:00:00Z", "team:home", "team:away")],
        captured_at="2026-08-10T00:00:00Z",
    ).build(
        "team:home",
        target_kickoff="2026-08-11T00:00:00Z",
        window_type="last_5",
        bridge_context={"season_stage": "opening", "bridge_status": "unverified"},
    )

    assert snapshot["history_recency_status"] == "stale"
    assert snapshot["bridge_status"] == "unverified"
    assert snapshot["current_strength_ready"] is False


def test_health_reports_bridge_only_separately_from_ready():
    health = build_team_strength_health(
        [{
            "id": "target:bridge",
            "home_team_id": "team:home",
            "away_team_id": "team:away",
            "kickoff": "2026-08-11T00:00:00Z",
            "bridge_context": bridge_context(),
        }],
        [result("match:old", "2026-05-16T12:00:00Z", "team:home", "team:away")],
        captured_at="2026-08-10T00:00:00Z",
    )

    assert health["both_history_available"] == 1
    assert health["both_current_strength_ready"] == 0
    assert health["bridge_only"] == 1
    assert health["stale_history"] == 0
