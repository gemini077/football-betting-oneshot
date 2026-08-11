from __future__ import annotations

from scripts.football_data.project_identity import (
    ProjectFixtureObservation,
    ProjectProviderIdentityCandidateBuilder,
)


def test_repeated_exact_translation_fixtures_produce_one_reviewed_mapping():
    builder = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=[
            {
                "provider": "football-data.co.uk",
                "provider_team_name": "Brann",
                "canonical_name": "SK Brann",
                "canonical_team_id": "team:norway:brann",
                "competition": "competition:norway-eliteserien",
                "country": "Norway",
                "verified": True,
                "resolution_method": "cross_source_context_verified",
            }
        ]
    )
    observations = [
        ProjectFixtureObservation(
            target_match_id="target:1",
            provider="500",
            provider_match_id="500-1",
            competition_id="competition:norway-eliteserien",
            country="Norway",
            kickoff_at="2026-07-01T17:00:00Z",
            side="home",
            provider_team_name="布兰",
            translated_team_name="Brann",
            translation_status="EXACT_MATCH",
            source_ref="translation:1",
            opponent_name="莫尔德",
        ),
        ProjectFixtureObservation(
            target_match_id="target:2",
            provider="500",
            provider_match_id="500-2",
            competition_id="competition:norway-eliteserien",
            country="Norway",
            kickoff_at="2026-07-08T17:00:00Z",
            side="away",
            provider_team_name="布兰",
            translated_team_name="Brann",
            translation_status="EXACT_MATCH",
            source_ref="translation:2",
            opponent_name="维京",
        ),
    ]

    result = builder.build(observations)

    assert result["summary"]["AUTO_VERIFIED"] == 1
    mapping = result["provider_mappings"][0]
    assert mapping["canonical_team_id"] == "team:norway:brann"
    assert mapping["evidence"]["supporting_fixture_count"] == 2


def test_fuzzy_like_name_without_reviewed_evidence_stays_unresolved():
    builder = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=[
            {
                "provider": "football-data.co.uk",
                "provider_team_name": "Brann",
                "canonical_name": "SK Brann",
                "canonical_team_id": "team:norway:brann",
                "competition": "competition:norway-eliteserien",
                "country": "Norway",
                "verified": True,
                "resolution_method": "cross_source_context_verified",
            }
        ]
    )
    result = builder.build(
        [
            ProjectFixtureObservation(
                target_match_id="target:3",
                provider="500",
                provider_match_id="500-3",
                competition_id="competition:norway-eliteserien",
                country="Norway",
                kickoff_at="2026-07-15T17:00:00Z",
                side="home",
                provider_team_name="Brann FC",
            )
        ]
    )

    assert result["summary"]["AUTO_VERIFIED"] == 0
    assert result["summary"]["UNRESOLVED"] == 1

