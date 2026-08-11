from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility


def result(index: int) -> dict:
    kickoff = (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat().replace("+00:00", "Z")
    return make_historical_match_result(
        canonical_match_id=f"match:{index}",
        competition_id="competition:test",
        season_id="season:test:2025",
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


def test_split_is_strictly_chronological_and_reports_actual_bucket_counts():
    report = audit_historical_eligibility([result(index) for index in range(160)], dataset_digest="fixture-digest")
    split = report["chronological_split"]

    assert split["method"] == "global_date_order_60_20_20"
    assert split["development"]["count"] > 0
    assert split["validation"]["count"] > 0
    assert split["held_out_test"]["count"] > 0
    assert split["development"]["max_kickoff_at"] < split["validation"]["min_kickoff_at"]
    assert split["validation"]["max_kickoff_at"] < split["held_out_test"]["min_kickoff_at"]
