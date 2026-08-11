from __future__ import annotations

from scripts.football_data.project_identity import (
    ProjectFixtureObservation,
    ProjectProviderIdentityCandidateBuilder,
)


def test_reviewed_alias_group_with_two_same_context_candidates_is_conflict():
    result = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=[
            {
                "provider": "football-data.co.uk",
                "provider_team_name": "Coastal United",
                "canonical_name": "Coastal United A",
                "canonical_team_id": "team:coastal:a",
                "competition": "competition:coastal",
                "country": "Coastland",
                "verified": True,
                "resolution_method": "cross_source_context_verified",
            },
            {
                "provider": "football-data.co.uk",
                "provider_team_name": "Coastal FC",
                "canonical_name": "Coastal United B",
                "canonical_team_id": "team:coastal:b",
                "competition": "competition:coastal",
                "country": "Coastland",
                "verified": True,
                "resolution_method": "cross_source_context_verified",
            },
        ],
        project_alias_rows=[
            {
                "canonical": "Coastal United",
                "aliases": ["Coastal FC"],
                "evidence": "reviewed_coastal_fixture",
            }
        ],
    ).build(
        [
            ProjectFixtureObservation(
                target_match_id=f"target:coastal-{index}",
                provider="500",
                provider_match_id=f"500-coastal-{index}",
                competition_id="competition:coastal",
                country="Coastland",
                kickoff_at=f"2026-07-{index + 10:02d}T12:00:00Z",
                side="home",
                provider_team_name="Coastal United",
            )
            for index in (1, 2)
        ]
    )

    assert result["summary"]["AUTO_VERIFIED"] == 0
    assert result["summary"]["CONFLICT"] == 1
    row = result["candidates"][0]
    assert row["canonical_team_id"] is None
    assert row["evidence"]["candidate_canonical_team_ids_after_context"] == [
        "team:coastal:a",
        "team:coastal:b",
    ]
    assert row["conflicts"] == ["multiple_unique_canonical_candidates"]
