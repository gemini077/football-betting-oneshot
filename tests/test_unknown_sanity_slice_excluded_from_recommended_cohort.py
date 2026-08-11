from datetime import datetime, timedelta, timezone

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_preflight import audit_historical_eligibility
from scripts.football_data.research_sanity import audit_competition_season_sanity


def _record(index: int) -> dict:
    kickoff = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat().replace("+00:00", "Z")
    return make_historical_match_result(
        canonical_match_id=f"match:unknown:{index}",
        competition_id="competition:unverified",
        season_id="season:unverified:2026",
        home_team_id="team:home",
        away_team_id="team:away",
        kickoff_at=kickoff,
        home_goals=index % 2,
        away_goals=(index + 1) % 2,
        provider="fixture",
        provider_match_id=f"fixture:unknown:{index}",
        source_as_of_at=kickoff,
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref=f"fixture:unknown:{index}",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )


def test_unknown_sanity_slice_cannot_enter_any_research_cohort():
    records = [_record(index) for index in range(25)]
    baseline = audit_historical_eligibility(records, dataset_digest="fixture-digest")
    sanity = audit_competition_season_sanity(records, [])
    hardened = audit_historical_eligibility(records, dataset_digest="fixture-digest", sanity_report=sanity)

    assert baseline["tier_counts"]["standard_ge_10"] > 0
    assert hardened["tier_counts"]["minimum_ge_5"] == 0
    assert hardened["tier_counts"]["standard_ge_10"] == 0
    assert hardened["tier_counts"]["strict_ge_20"] == 0
    assert hardened["recommended_cohort"]["cohort_size"] == 0
