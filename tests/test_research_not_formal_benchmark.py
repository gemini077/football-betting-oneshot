from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility


def test_research_audit_is_not_a_formal_benchmark_input():
    row = make_historical_match_result(
        canonical_match_id="match:test",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id="team:a",
        away_team_id="team:b",
        kickoff_at="2026-08-01T12:00:00Z",
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id="fixture:test",
        source_as_of_at="2026-08-01T12:00:00Z",
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref="fixture:test",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )

    report = audit_historical_eligibility([row], dataset_digest="fixture-digest")

    assert report["research_only"] is True
    assert report["formal_benchmark_eligible"] is False
    assert report["validated_for_model"] is False
    assert "prediction_id" not in report
    assert "benchmark_records" not in report
