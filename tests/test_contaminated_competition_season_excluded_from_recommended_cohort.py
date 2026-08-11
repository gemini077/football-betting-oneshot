from test_complete_source_ledger_overflow_fails_sanity import complete_source, record
from scripts.football_data.research_sanity import audit_competition_season_sanity, filter_records_by_sanity


def test_failed_competition_season_is_excluded_without_deleting_evidence():
    records = [record(i) for i in range(307)]
    sanity = audit_competition_season_sanity(records, [complete_source()])

    filtered = filter_records_by_sanity(records, sanity)

    assert len(filtered) == 0
    assert sanity["slices"]["competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26"]["excluded_from_research"] is True
    assert sanity["slices"]["competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26"]["ledger_fixture_count"] == 307
