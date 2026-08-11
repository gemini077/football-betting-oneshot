import json
from pathlib import Path

from scripts.football_data.final_source_decisions import build_final_source_discovery


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads(
    (ROOT / "data" / "football_data" / "phase2b_source_discovery_evidence.json").read_text(encoding="utf-8")
)


def test_football_data_org_without_token_stays_catalog_candidate():
    report = build_final_source_discovery(
        report_generated_at="2026-08-11T08:00:00Z",
        evidence=EVIDENCE,
        api_key_present=False,
    )
    row = next(item for item in report["sources"] if item["source"] == "football-data.org")

    assert row["status"] == "DEFER"
    assert row["public_catalog_candidate"] is True
    assert row["authenticated_api_check_executed"] is False
    assert row["season_specific_coverage_verified"] is False
