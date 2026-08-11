from scripts.football_data.research_sanity import audit_competition_season_sanity
from scripts.football_data.historical_results import make_historical_match_result


def record(index: int) -> dict:
    kickoff = f"2025-08-{(index % 28) + 1:02d}T12:00:00Z"
    return make_historical_match_result(
        canonical_match_id=f"match:{index}",
        competition_id="competition:portugal-primeira-liga",
        season_id="season:portugal-primeira-liga:2025-26",
        home_team_id=f"team:home:{index}",
        away_team_id=f"team:away:{index}",
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


def complete_source(parsed: int = 306) -> dict:
    return {
        "provider": "openfootball",
        "source_file": "portugal/2025-26_pt1.txt",
        "competition_key": "portugal-primeira-liga",
        "competition_id": "competition:portugal-primeira-liga",
        "season_id": "season:portugal-primeira-liga:2025-26",
        "provider_season_id": "2025-26",
        "listed_match_count": parsed,
        "parsed_result_count": parsed,
        "source_completeness_status": "COMPLETE",
    }


def test_ledger_overflow_against_complete_source_fails_sanity():
    report = audit_competition_season_sanity([record(i) for i in range(307)], [complete_source()])
    slice_report = report["slices"]["competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26"]

    assert slice_report["ledger_fixture_count"] == 307
    assert slice_report["known_complete_source_fixture_count"] == 306
    assert slice_report["sanity_status"] == "FAIL"
    assert "ledger_exceeds_known_complete_source" in slice_report["sanity_reasons"]
