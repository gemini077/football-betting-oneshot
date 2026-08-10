from __future__ import annotations

from scripts.football_data.team_strength import classify_history_recency


def test_verified_bridge_requires_season_opening_evidence_and_is_not_strict_ready():
    verified = classify_history_recency(
        "2026-05-16T12:00:00Z",
        "2026-08-11T00:00:00Z",
        bridge_context={
            "season_stage": "opening",
            "bridge_status": "verified",
            "bridge_from_season": "season:test:2025",
            "bridge_verification_evidence": ["schedule:opening-round"],
        },
    )
    unverified = classify_history_recency(
        "2026-05-16T12:00:00Z",
        "2026-08-11T00:00:00Z",
        bridge_context={"season_stage": "opening", "bridge_status": "unverified"},
    )

    assert verified["history_recency_status"] == "offseason_bridge"
    assert verified["current_strength_ready"] is False
    assert unverified["history_recency_status"] == "stale"
