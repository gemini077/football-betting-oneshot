from __future__ import annotations

from scripts.football_data.project_identity import (
    ProjectFixtureObservation,
    ProjectProviderIdentityCandidateBuilder,
)


ALIASES = [
    {
        "canonical": "North United",
        "aliases": ["North Utd"],
        "evidence": "reviewed_context_fixture",
    }
]

CANONICAL = [
    {
        "provider": "football-data.co.uk",
        "provider_team_name": "North Utd",
        "canonical_name": "North United Alpha",
        "canonical_team_id": "team:alpha:north-united",
        "competition": "competition:alpha",
        "country": "Alpha",
        "verified": True,
        "resolution_method": "cross_source_context_verified",
    },
    {
        "provider": "football-data.co.uk",
        "provider_team_name": "North Utd",
        "canonical_name": "North United Beta",
        "canonical_team_id": "team:beta:north-united",
        "competition": "competition:beta",
        "country": "Beta",
        "verified": True,
        "resolution_method": "cross_source_context_verified",
    },
]


def _observations(competition_id: str, country: str) -> list[ProjectFixtureObservation]:
    return [
        ProjectFixtureObservation(
            target_match_id=f"target:north-{index}",
            provider="500",
            provider_match_id=f"500-north-{index}",
            competition_id=competition_id,
            country=country,
            kickoff_at=f"2026-07-{index + 10:02d}T12:00:00Z",
            side="home",
            provider_team_name="North United",
        )
        for index in (1, 2)
    ]


def test_reviewed_alias_group_is_scoped_to_competition_and_country():
    result = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=CANONICAL,
        project_alias_rows=ALIASES,
    ).build(_observations("competition:alpha", "Alpha"))

    assert result["summary"]["AUTO_VERIFIED"] == 1
    assert result["provider_mappings"][0]["canonical_team_id"] == "team:alpha:north-united"


def test_alias_group_without_context_does_not_auto_verify_ambiguous_candidates():
    result = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=CANONICAL,
        project_alias_rows=ALIASES,
    ).build(_observations("", ""))

    assert result["summary"]["AUTO_VERIFIED"] == 0
    assert result["summary"]["UNRESOLVED"] == 1
    evidence = result["candidates"][0]["evidence"]
    assert evidence["reviewed_alias_group_used"] is True
    assert evidence["candidate_canonical_team_ids_before_context"] == [
        "team:alpha:north-united",
        "team:beta:north-united",
    ]
    assert evidence["candidate_canonical_team_ids_after_context"] == []


def test_alias_group_without_reviewed_evidence_does_not_propagate():
    result = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=[CANONICAL[0]],
        project_alias_rows=[
            {"canonical": "North United", "aliases": ["North Utd"]}
        ],
    ).build(_observations("competition:alpha", "Alpha"))

    assert result["summary"]["AUTO_VERIFIED"] == 0
    assert result["summary"]["UNRESOLVED"] == 1
    assert result["candidates"][0]["evidence"]["reviewed_alias_group_used"] is False
