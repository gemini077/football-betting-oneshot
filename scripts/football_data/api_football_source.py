"""Non-network API-Football adoption boundary for Phase 2B."""

from __future__ import annotations

from typing import Any


COMMERCIAL_BOUNDARY = {
    "internal_analysis_only": True,
    "raw_redistribution": False,
    "commercial_rights_review_required": True,
}


def build_api_football_status(
    *,
    key_present: bool,
    coverage_page_checked: bool,
    evidence_observed_at: str,
    season_specific_coverage_checked: bool = False,
    real_ingestion_executed: bool = False,
    requests_used: int = 0,
) -> dict[str, Any]:
    """Return an auditable status without ever fabricating API results."""

    requests_used = max(0, int(requests_used))
    if not key_present:
        status = "NOT_EXECUTED_NO_KEY"
        season_specific_coverage_checked = False
        real_ingestion_executed = False
        requests_used = 0
    elif not season_specific_coverage_checked:
        status = "COVERAGE_CATALOG_ONLY"
        real_ingestion_executed = False
    elif not real_ingestion_executed:
        status = "COVERAGE_CHECKED_NOT_INGESTED"
    else:
        status = "INGESTION_EXECUTED"
    return {
        "source": "API-Football",
        "status": status,
        "api_key_required": True,
        "api_key_persisted": False,
        "coverage_page_checked": bool(coverage_page_checked),
        "season_specific_coverage_checked": bool(season_specific_coverage_checked),
        "real_ingestion_executed": bool(real_ingestion_executed),
        "requests_used": requests_used,
        "evidence_observed_at": evidence_observed_at,
        "commercial_boundary": dict(COMMERCIAL_BOUNDARY),
        "notes": [
            "The API key is read only from API_FOOTBALL_KEY when an operator explicitly enables an adapter run.",
            "No key means no live request and no synthetic response.",
        ],
    }


__all__ = ["COMMERCIAL_BOUNDARY", "build_api_football_status"]
