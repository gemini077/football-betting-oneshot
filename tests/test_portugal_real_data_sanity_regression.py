from pathlib import Path

import pytest

from scripts.football_data.research_sanity import (
    audit_competition_season_sanity,
    load_source_manifest_entries,
)
from scripts.football_data.storage import HistoricalResultStore
from scripts.football_data.verify_data_home import verify_data_home


ROOT = Path(__file__).resolve().parents[1]
PORTUGAL_SLICE = "competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26"


def test_real_portugal_complete_source_overflow_remains_a_sanity_failure():
    verification = verify_data_home()
    if verification["status"] != "OK":
        pytest.skip("shared Football Data Home unavailable; real-data regression not executed")

    manifest_paths = [
        ROOT / "data" / "football_data" / "openfootball" / "source_manifest.json",
        ROOT / "data" / "football_data" / "football_data_uk" / "source_manifest.json",
        ROOT / "data" / "football_data" / "p0_p1_source_manifest.json",
    ]
    entries = load_source_manifest_entries(manifest_paths)
    report = audit_competition_season_sanity(HistoricalResultStore().records(), entries)
    slice_report = report["slices"][PORTUGAL_SLICE]

    assert slice_report["ledger_fixture_count"] == 370
    assert slice_report["known_complete_source_fixture_count"] == 306
    assert slice_report["source_parsed_fixture_count"] == 612
    assert slice_report["sanity_status"] == "FAIL"
    assert slice_report["duplicate_audit"]["source_observation_identity_split_duplicate_count"] == 66
    assert slice_report["duplicate_audit"]["possible_identity_split_duplicate_count"] >= 66
    assert "ledger_exceeds_known_complete_source" in slice_report["sanity_reasons"]
    assert "possible_identity_split_duplicate" in slice_report["sanity_reasons"]
