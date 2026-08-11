import json
from pathlib import Path

from scripts.football_data.final_source_decisions import build_final_source_discovery


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads(
    (ROOT / "data" / "football_data" / "phase2b_source_discovery_evidence.json").read_text(encoding="utf-8")
)


def test_frozen_source_evidence_is_not_reported_as_live_check():
    report = build_final_source_discovery(
        report_generated_at="2026-08-11T08:00:00Z",
        evidence=EVIDENCE,
        api_key_present=False,
    )
    by_source = {row["source"]: row for row in report["sources"]}

    assert report["live_check_executed"] is False
    assert all(row["live_check_executed"] is False for row in report["sources"])
    assert by_source["openfootball/champions-league"]["current_2026_27_status"] == "NOT_VERIFIED"
    assert report["api_football"]["coverage_page_checked"] is False
