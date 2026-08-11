from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility


def result(match_id: str, kickoff: str, home: str, away: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )


def test_walk_forward_target_excludes_target_and_future_results():
    records = [
        result("past-a", "2026-07-01T12:00:00Z", "team:a", "team:x"),
        result("past-b", "2026-07-02T12:00:00Z", "team:y", "team:b"),
        result("target", "2026-08-01T12:00:00Z", "team:a", "team:b"),
        result("future-c", "2026-08-02T12:00:00Z", "team:a", "team:z"),
    ]

    report = audit_historical_eligibility(records, dataset_digest="fixture-digest")
    target = next(row for row in report["audits"] if row["target_match_id"] == "target")

    assert target["home_history_matches"] == 1
    assert target["away_history_matches"] == 1
    assert "target" not in target["home_source_match_ids"]
    assert "future-c" not in target["home_source_match_ids"]
    assert target["eligible_ge_5"] is False
