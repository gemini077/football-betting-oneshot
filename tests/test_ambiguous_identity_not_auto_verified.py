from __future__ import annotations

from scripts.football_data.project_identity import ProjectFixtureObservation, ProjectProviderIdentityCandidateBuilder


def test_same_exact_translation_with_two_canonical_candidates_is_conflict():
    builder = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=[
            {
                "provider": "source-a",
                "provider_team_name": "United",
                "canonical_name": "United A",
                "canonical_team_id": "team:test:united-a",
                "competition": "competition:test",
                "country": "Testland",
                "verified": True,
                "resolution_method": "manual_verified",
            },
            {
                "provider": "source-b",
                "provider_team_name": "United",
                "canonical_name": "United B",
                "canonical_team_id": "team:test:united-b",
                "competition": "competition:test",
                "country": "Testland",
                "verified": True,
                "resolution_method": "manual_verified",
            },
        ]
    )
    result = builder.build(
        [
            ProjectFixtureObservation(
                target_match_id="target:ambiguous",
                provider="500",
                provider_match_id="500-ambiguous",
                competition_id="competition:test",
                country="Testland",
                kickoff_at="2026-08-01T12:00:00Z",
                side="home",
                provider_team_name="Unknown United",
                translated_team_name="United",
                translation_status="EXACT_MATCH",
                source_ref="translation:ambiguous",
            )
        ]
    )

    assert result["summary"]["CONFLICT"] == 1
    assert result["provider_mappings"] == []

