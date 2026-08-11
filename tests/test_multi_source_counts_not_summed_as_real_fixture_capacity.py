from test_complete_source_ledger_overflow_fails_sanity import complete_source, record
from scripts.football_data.research_sanity import audit_competition_season_sanity


def test_complete_sources_are_corroborations_not_additive_capacity():
    report = audit_competition_season_sanity(
        [record(i) for i in range(307)],
        [complete_source(), {**complete_source(), "provider": "football-data.co.uk", "source_file": "PO1.csv"}],
    )
    slice_report = report["slices"]["competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26"]

    assert slice_report["source_parsed_fixture_count"] == 612
    assert slice_report["known_complete_source_fixture_count"] == 306
    assert slice_report["sanity_status"] == "FAIL"
