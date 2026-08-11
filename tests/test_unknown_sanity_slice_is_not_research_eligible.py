from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.research_sanity import (
    audit_competition_season_sanity,
    filter_records_by_sanity,
)


def _record() -> dict:
    return make_historical_match_result(
        canonical_match_id="match:unknown-slice",
        competition_id="competition:unverified",
        season_id="season:unverified:2026",
        home_team_id="team:home",
        away_team_id="team:away",
        kickoff_at="2026-08-01T12:00:00Z",
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id="fixture:unknown-slice",
        source_as_of_at="2026-08-01T12:00:00Z",
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref="fixture:unknown-slice",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )


def test_unknown_sanity_slice_is_not_research_eligible():
    record = _record()
    report = audit_competition_season_sanity([record], [])
    slice_report = next(iter(report["slices"].values()))

    assert slice_report["sanity_status"] == "UNKNOWN"
    assert "dataset_sanity_not_passed" in slice_report["sanity_reasons"]
    assert slice_report["research_eligible"] is False
    assert slice_report["excluded_from_research"] is True
    assert filter_records_by_sanity([record], report) == []
