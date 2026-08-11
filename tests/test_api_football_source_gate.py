from __future__ import annotations

from scripts.football_data.api_football_source import build_api_football_status


def test_api_football_without_key_is_explicitly_not_executed():
    result = build_api_football_status(
        key_present=False,
        coverage_page_checked=True,
        checked_at="2026-08-11T00:00:00Z",
    )

    assert result["status"] == "NOT_EXECUTED_NO_KEY"
    assert result["coverage_page_checked"] is True
    assert result["season_specific_coverage_checked"] is False
    assert result["real_ingestion_executed"] is False
    assert result["requests_used"] == 0
    assert result["api_key_persisted"] is False
    assert result["commercial_boundary"] == {
        "internal_analysis_only": True,
        "raw_redistribution": False,
        "commercial_rights_review_required": True,
    }


def test_api_football_status_never_claims_ingestion_from_catalog_only():
    result = build_api_football_status(
        key_present=True,
        coverage_page_checked=True,
        checked_at="2026-08-11T00:00:00Z",
        season_specific_coverage_checked=False,
        real_ingestion_executed=False,
        requests_used=0,
    )

    assert result["status"] == "COVERAGE_CATALOG_ONLY"
    assert result["real_ingestion_executed"] is False
    assert result["requests_used"] == 0

