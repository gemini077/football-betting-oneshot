from scripts.football_data.api_football_source import build_api_football_status


def test_api_football_no_key_does_not_claim_coverage_check():
    result = build_api_football_status(
        key_present=False,
        coverage_page_checked=False,
        evidence_observed_at="2026-08-11T07:36:41Z",
    )

    assert result["status"] == "NOT_EXECUTED_NO_KEY"
    assert result["coverage_page_checked"] is False
    assert result["evidence_observed_at"] == "2026-08-11T07:36:41Z"
    assert result["season_specific_coverage_checked"] is False
    assert result["real_ingestion_executed"] is False
    assert result["requests_used"] == 0
