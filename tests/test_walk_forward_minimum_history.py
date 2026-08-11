from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility


def result(index: int, kickoff: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:{index}",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id="team:a",
        away_team_id="team:b",
        kickoff_at=kickoff,
        home_goals=index % 3,
        away_goals=(index + 1) % 2,
        provider="fixture",
        provider_match_id=f"fixture:{index}",
        source_as_of_at=kickoff,
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref=f"fixture:{index}",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )


def test_each_history_tier_requires_both_teams_to_have_the_requested_depth():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [result(index, (start + timedelta(days=index)).isoformat().replace("+00:00", "Z")) for index in range(25)]

    report = audit_historical_eligibility(records, dataset_digest="fixture-digest")
    target = report["audits"][-1]

    assert target["home_history_matches"] == 24
    assert target["away_history_matches"] == 24
    assert target["eligible_ge_5"] is True
    assert target["eligible_ge_10"] is True
    assert target["eligible_ge_20"] is True
