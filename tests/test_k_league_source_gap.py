from __future__ import annotations

from scripts.football_data.p0_p1_coverage import evaluate_k_league_source_decision


def test_k_league_without_compliant_source_remains_source_gap():
    result = evaluate_k_league_source_decision([])

    assert result["K_LEAGUE_SOURCE_GAP"] is True
    assert result["status"] == "SOURCE_MISSING"
    assert result["demand_remains_in_denominator"] is True
