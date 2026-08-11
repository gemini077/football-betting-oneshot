"""Final Phase 2B.5 source-discovery decisions."""

from __future__ import annotations

from typing import Any

from .api_football_source import build_api_football_status


def build_final_source_discovery(*, checked_at: str, api_key_present: bool) -> dict[str, Any]:
    api_status = build_api_football_status(
        key_present=api_key_present,
        coverage_page_checked=True,
        checked_at=checked_at,
    )
    return {
        "contract_version": "phase2b_final_source_discovery.v1",
        "checked_at": checked_at,
        "sources": [
            {
                "source": "openfootball/champions-league",
                "role": "offline historical/schema reference",
                "license": "CC0-1.0",
                "prior_season_status": "AVAILABLE",
                "current_2026_27_status": "MISSING",
                "status": "PRIOR_SEASON_ONLY",
                "current_ingestion_executed": False,
                "source_url": "https://github.com/openfootball/champions-league",
                "license_url": "https://raw.githubusercontent.com/openfootball/champions-league/master/LICENSE.md",
                "evidence": [
                    "repository season listing reaches 2025-26 and does not show 2026-27",
                    "current target fixtures therefore cannot be treated as covered",
                ],
            },
            {
                "source": "football-data.org",
                "role": "candidate historical results API",
                "status": "DEFER",
                "current_ingestion_executed": False,
                "source_url": "https://www.football-data.org/documentation/quickstart",
                "policy_url": "https://docs.football-data.org/general/v4/policies.html",
                "evidence": [
                    "official documentation exposes competition match endpoints",
                    "match access and rate limits require an authenticated, terms-reviewed workflow",
                    "no project token or season-specific current coverage was available in this run",
                ],
            },
            {
                "source": "K League official/public",
                "role": "official schedule/results reference only",
                "status": "SOURCE_MISSING",
                "current_ingestion_executed": False,
                "source_url": "https://www.kleague.com/schedule.do?leagueId=2",
                "terms_url": "https://portal.kleague.com/user/service/userTermsNice.do",
                "evidence": [
                    "official page exposes schedule/results navigation",
                    "terms prohibit copying, publication, third-party provision, and commercial use without prior consent",
                    "no compliant reusable result capture was adopted",
                ],
            },
        ],
        "api_football": api_status,
        "k_league_source_gap": True,
        "sources_adopted": [
            "existing OpenFootball prior-season reference remains available; no new current-season source adopted",
        ],
        "sources_rejected_or_deferred": [
            "OpenFootball current 2026-27 UEFA: missing",
            "football-data.org: deferred pending authenticated, terms-reviewed capture",
            "K League official/public: source missing under current redistribution/commercial boundary",
            "API-Football: deferred; no key and no live ingestion",
        ],
        "notes": [
            "No source result rows were added in Phase 2B.5.",
            "UEFA and K League demand remain in the fixed denominator.",
        ],
    }


__all__ = ["build_final_source_discovery"]
