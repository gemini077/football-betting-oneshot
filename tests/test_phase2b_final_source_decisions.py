from __future__ import annotations

import json
from pathlib import Path

from scripts.football_data.final_source_decisions import build_final_source_discovery


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads(
    (ROOT / "data" / "football_data" / "phase2b_source_discovery_evidence.json").read_text(encoding="utf-8")
)


def test_uefa_prior_season_does_not_become_current_season_ready():
    report = build_final_source_discovery(
        report_generated_at="2026-08-11T08:00:00Z",
        evidence=EVIDENCE,
        api_key_present=False,
    )

    by_name = {row["source"]: row for row in report["sources"]}
    assert by_name["openfootball/champions-league"]["current_2026_27_status"] == "NOT_VERIFIED"
    assert by_name["openfootball/champions-league"]["prior_season_status"] == "AVAILABLE"
    assert by_name["K League official/public"]["status"] == "SOURCE_MISSING"
    assert report["k_league_source_gap"] is True
    assert report["api_football"]["status"] == "NOT_EXECUTED_NO_KEY"
