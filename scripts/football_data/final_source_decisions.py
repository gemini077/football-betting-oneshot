"""Materialize final source decisions from frozen discovery evidence."""

from __future__ import annotations

from typing import Any, Mapping

from .api_football_source import build_api_football_status


def _rows_by_source(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = evidence.get("sources")
    if not isinstance(rows, list):
        raise ValueError("source discovery evidence must contain a sources list")
    result = {str(row.get("source")): row for row in rows if isinstance(row, Mapping)}
    required = {"openfootball/champions-league", "football-data.org", "K League official/public", "API-Football"}
    missing = sorted(required - result.keys())
    if missing:
        raise ValueError(f"source discovery evidence is missing: {', '.join(missing)}")
    return result


def _materialize_source(row: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    return {
        "source": row["source"],
        "role": role,
        "status": row.get("status_at_observation") or row.get("evidence_status"),
        "evidence_status": row.get("evidence_status"),
        "evidence_observed_at": row.get("observed_at"),
        "evidence_source": row.get("evidence_source"),
        "live_check_executed": bool(row.get("live_check_executed")),
        "data_captured_at": row.get("data_captured_at"),
        "source_url": row.get("source_url"),
        "evidence_ref": row.get("evidence_ref"),
    }


def build_final_source_discovery(
    *,
    report_generated_at: str,
    evidence: Mapping[str, Any],
    api_key_present: bool,
) -> dict[str, Any]:
    """Build a report without changing or refreshing frozen source evidence."""

    rows = _rows_by_source(evidence)
    evidence_observed_at = str(evidence.get("evidence_observed_at") or "")
    if not evidence_observed_at:
        raise ValueError("source discovery evidence must contain evidence_observed_at")

    openfootball = _materialize_source(
        rows["openfootball/champions-league"],
        role="offline historical/schema reference",
    )
    openfootball.update(
        {
            "license": "CC0-1.0",
            "prior_season_status": rows["openfootball/champions-league"].get("prior_season_status"),
            "current_2026_27_status": rows["openfootball/champions-league"].get("current_2026_27_status"),
            "current_ingestion_executed": False,
            "license_url": "https://raw.githubusercontent.com/openfootball/champions-league/master/LICENSE.md",
            "season_specific_conclusion": rows["openfootball/champions-league"].get("season_specific_conclusion"),
        }
    )

    football_data = _materialize_source(rows["football-data.org"], role="candidate historical results API")
    football_data.update(
        {
            "policy_url": rows["football-data.org"].get("policy_url"),
            "current_ingestion_executed": False,
            "public_catalog_candidate": bool(rows["football-data.org"].get("public_catalog_candidate")),
            "authenticated_api_check_executed": bool(rows["football-data.org"].get("authenticated_api_check_executed")),
            "season_specific_coverage_verified": bool(rows["football-data.org"].get("season_specific_coverage_verified")),
        }
    )

    k_league = _materialize_source(rows["K League official/public"], role="official schedule/results reference only")
    k_league.update({"terms_url": rows["K League official/public"].get("terms_url"), "current_ingestion_executed": False})

    api_evidence = rows["API-Football"]
    api_status = build_api_football_status(
        key_present=api_key_present,
        coverage_page_checked=bool(api_evidence.get("coverage_page_checked")),
        evidence_observed_at=str(api_evidence.get("observed_at") or evidence_observed_at),
        season_specific_coverage_checked=bool(api_evidence.get("season_specific_coverage_verified")),
        real_ingestion_executed=bool(api_evidence.get("real_ingestion_executed")),
        requests_used=int(api_evidence.get("requests_used") or 0),
    )
    api_status.update(
        {
            "evidence_status": api_evidence.get("evidence_status"),
            "evidence_source": api_evidence.get("evidence_source"),
            "live_check_executed": bool(api_evidence.get("live_check_executed")),
            "data_captured_at": api_evidence.get("data_captured_at"),
            "source_url": api_evidence.get("source_url"),
            "terms_url": api_evidence.get("terms_url"),
            "evidence_ref": api_evidence.get("evidence_ref"),
            "coverage_page_observed_in_bounded_review": bool(api_evidence.get("coverage_page_observed_in_bounded_review")),
        }
    )

    return {
        "contract_version": "phase2b_final_source_discovery.v2",
        "report_generated_at": report_generated_at,
        "source_evidence_observed_at": evidence_observed_at,
        "data_captured_at": evidence.get("data_captured_at"),
        "evidence_source": evidence.get("evidence_source"),
        "live_check_executed": bool(evidence.get("live_check_executed")),
        "sources": [
            openfootball,
            football_data,
            k_league,
        ],
        "api_football": api_status,
        "k_league_source_gap": True,
        "sources_adopted": [
            "existing OpenFootball prior-season reference remains available; no new current-season source adopted",
        ],
        "sources_rejected_or_deferred": [
            "OpenFootball current 2026-27 UEFA: not verified in frozen evidence",
            "football-data.org: deferred pending authenticated, terms-reviewed capture",
            "K League official/public: source missing under current redistribution/commercial boundary",
            "API-Football: deferred; no key and no live ingestion",
        ],
        "notes": [
            "No source result rows were added in Phase 2B.5.",
            "Source evidence timestamps are frozen; report reruns must not refresh them.",
            "UEFA and K League demand remain in the fixed denominator.",
        ],
    }


__all__ = ["build_final_source_discovery"]
