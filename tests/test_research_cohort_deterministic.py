from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility


def result(index: int) -> dict:
    kickoff = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat().replace("+00:00", "Z")
    return make_historical_match_result(
        canonical_match_id=f"match:{index}",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id="team:a",
        away_team_id="team:b",
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
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


def test_same_inputs_in_different_order_have_same_cohort_id():
    records = [result(index) for index in range(30)]
    first = audit_historical_eligibility(records, dataset_digest="fixture-digest")
    second = audit_historical_eligibility(list(reversed(records)), dataset_digest="fixture-digest")

    assert first["cohorts"]["standard"]["research_cohort_id"] == second["cohorts"]["standard"]["research_cohort_id"]
