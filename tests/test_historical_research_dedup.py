from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility


def result(provider: str, match_id: str, kickoff: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id="team:a",
        away_team_id="team:b",
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
        provider=provider,
        provider_match_id=f"{provider}:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref=f"{provider}:{match_id}",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )


def test_cross_source_same_canonical_fixture_is_counted_once():
    first = result("openfootball", "match:shared", "2026-07-01T12:00:00Z")
    second = result("football-data.co.uk", "match:shared", "2026-07-01T12:00:00Z")
    report = audit_historical_eligibility([first, second], dataset_digest="fixture-digest")

    assert report["deduplicated_fixture_count"] == 1
    assert report["deduplication"]["duplicates_collapsed"] == 1
    assert report["source_breakdown"]["multi_source_corroborated_fixture_count"] == 1
