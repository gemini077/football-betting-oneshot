import json
from pathlib import Path

from scripts.football_data.final_source_decisions import build_final_source_discovery


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads(
    (ROOT / "data" / "football_data" / "phase2b_source_discovery_evidence.json").read_text(encoding="utf-8")
)


def test_report_rerun_keeps_frozen_source_observation_time():
    first = build_final_source_discovery(
        report_generated_at="2026-08-11T08:00:00Z",
        evidence=EVIDENCE,
        api_key_present=False,
    )
    second = build_final_source_discovery(
        report_generated_at="2026-08-12T08:00:00Z",
        evidence=EVIDENCE,
        api_key_present=False,
    )

    assert first["report_generated_at"] != second["report_generated_at"]
    assert first["source_evidence_observed_at"] == second["source_evidence_observed_at"]
    assert [row["evidence_observed_at"] for row in first["sources"]] == [
        row["evidence_observed_at"] for row in second["sources"]
    ]
