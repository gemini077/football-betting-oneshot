from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.p0_p1_coverage import audit_retrospective_availability
from scripts.football_data.populate_p0_p1_coverage import _project_identity_gap_summary
from scripts.football_data.project_identity import ProjectProviderIdentityResolver


def _result(index: int, kickoff: str, home: str, away: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=f"history:{index}",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{index}",
        source_as_of_at=kickoff,
        captured_at="2026-08-01T00:00:00Z",
        source_reliable=True,
        resolution_method="manual_verified",
        match_type="league",
    )


def test_resolved_project_mapping_changes_availability_without_changing_history_gate():
    resolver = ProjectProviderIdentityResolver(
        [
            {
                "provider": "500",
                "provider_team_name": "甲队",
                "canonical_team_id": "team:a",
                "canonical_name": "Team A",
                "competition_id": "competition:test",
                "country": "Testland",
                "verified": True,
                "resolution_method": "project_provider_context_verified",
            },
            {
                "provider": "500",
                "provider_team_name": "乙队",
                "canonical_team_id": "team:b",
                "canonical_name": "Team B",
                "competition_id": "competition:test",
                "country": "Testland",
                "verified": True,
                "resolution_method": "project_provider_context_verified",
            },
        ]
    )
    home = resolver.resolve_team("500", "甲队", competition_id="competition:test", country="Testland")
    away = resolver.resolve_team("500", "乙队", competition_id="competition:test", country="Testland")
    records = [
        _result(index, f"2026-07-{index + 1:02d}T12:00:00Z", "team:a", "team:b")
        for index in range(5)
    ]

    unresolved = audit_retrospective_availability(
        [
            {
                "canonical_match_id": "target:unresolved",
                "competition_id": "competition:test",
                "season_id": "season:test:2026",
                "kickoff_at": "2026-08-01T12:00:00Z",
                "home": "甲队",
                "away": "乙队",
            }
        ],
        records,
    )[0]
    resolved = audit_retrospective_availability(
        [
            {
                "canonical_match_id": "target:resolved",
                "competition_id": "competition:test",
                "season_id": "season:test:2026",
                "kickoff_at": "2026-08-01T12:00:00Z",
                "home": "甲队",
                "away": "乙队",
                "home_team_id": home.canonical_team_id,
                "away_team_id": away.canonical_team_id,
            }
        ],
        records,
    )[0]

    assert unresolved["status"] == "IDENTITY_MISSING"
    assert resolved["home_identity_ready"] is True
    assert resolved["away_identity_ready"] is True
    assert resolved["strength_ready"] is True


def test_identity_gap_summary_preserves_baseline_and_classifies_fixtures():
    result = _project_identity_gap_summary(
        previous_audits=[
            {"target_match_id": "target:auto", "status": "IDENTITY_MISSING"},
            {"target_match_id": "target:review", "status": "IDENTITY_MISSING"},
            {"target_match_id": "target:missing", "status": "IDENTITY_MISSING"},
        ],
        targets=[
            {"canonical_match_id": "target:auto", "competition_key": "competition:test"},
            {"canonical_match_id": "target:review", "competition_key": "competition:test"},
        ],
        project_identity={
            "target_evidence": {
                "target:auto": {
                    "home": {"canonical_team_id": "team:a", "resolution_status": "resolved"},
                    "away": {"canonical_team_id": "team:b", "resolution_status": "resolved"},
                },
                "target:review": {
                    "home": {"canonical_team_id": "team:a", "resolution_status": "resolved"},
                    "away": {"canonical_team_id": None, "resolution_status": "review_required"},
                },
            }
        },
        generated_at="2026-08-11T00:00:00Z",
    )

    assert result["starting_identity_missing"] == 3
    assert result["auto_resolved_fixture_count"] == 1
    assert result["review_required_fixture_count"] == 1
    assert result["conflict_fixture_count"] == 0
    assert result["still_unresolved_fixture_count"] == 1
