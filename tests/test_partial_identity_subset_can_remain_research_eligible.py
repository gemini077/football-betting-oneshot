from test_complete_source_ledger_overflow_fails_sanity import complete_source, record
from scripts.football_data.research_sanity import audit_competition_season_sanity


def test_smaller_identity_mapped_subset_is_not_called_overflow():
    report = audit_competition_season_sanity([record(i) for i in range(200)], [complete_source()])
    slice_report = report["slices"]["competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26"]

    assert slice_report["sanity_status"] == "PASS"
    assert slice_report["research_population_scope"] == "IDENTITY_MAPPED_SUBSET"
    assert slice_report["generalization_scope"] == "observed identity-mapped subset only"
    assert slice_report["excluded_from_research"] is False
