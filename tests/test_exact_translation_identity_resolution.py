from __future__ import annotations

from scripts.football_data.project_identity import build_project_identity_output


CANONICAL = [
    {
        "provider": "football-data.co.uk",
        "provider_team_name": "Brann",
        "canonical_name": "SK Brann",
        "canonical_team_id": "team:norway:brann",
        "competition": "competition:norway-eliteserien",
        "country": "Norway",
        "verified": True,
        "resolution_method": "cross_source_context_verified",
    },
    {
        "provider": "football-data.co.uk",
        "provider_team_name": "Molde",
        "canonical_name": "Molde FK",
        "canonical_team_id": "team:norway:molde",
        "competition": "competition:norway-eliteserien",
        "country": "Norway",
        "verified": True,
        "resolution_method": "cross_source_context_verified",
    },
]


def test_exact_translation_and_provider_id_context_resolve_both_sides():
    output = build_project_identity_output(
        events=[
            {
                "canonical_match_id": "target:brann-molde",
                "provider_match_ids": ["500-100"],
                "competition": {
                    "canonical_competition_id": "competition:norway-eliteserien",
                    "country": "Norway",
                },
                "kickoff_at": "2026-08-01T17:00:00Z",
                "home": "project-brann",
                "away": "project-molde",
            }
        ],
        translations={
            "100": {
                "home_team_en": "Brann",
                "away_team_en": "Molde",
                "resolution_status": "EXACT_MATCH",
                "team_id_provider": "nowscore",
                "home_provider_team_id": "101",
                "away_provider_team_id": "102",
                "source_file": "data/fetch_runs/fixture.json",
            }
        },
        canonical_mappings=CANONICAL,
    )

    target = output["target_evidence"]["target:brann-molde"]
    assert target["home"]["canonical_team_id"] == "team:norway:brann"
    assert target["away"]["canonical_team_id"] == "team:norway:molde"
    assert output["summary"]["resolved_target_count"] == 1
    assert all(row["verified"] is True for row in output["provider_mappings"])
    assert all(
        row["provider_team_id"] is None
        for row in output["provider_mappings"]
        if row["provider"] == "500"
    )
    assert all(
        row["provider_team_id"] is not None
        for row in output["provider_mappings"]
        if row["provider"] == "nowscore"
    )


def test_translation_suggestion_without_exact_status_does_not_verify():
    output = build_project_identity_output(
        events=[
            {
                "canonical_match_id": "target:suggestion",
                "provider_match_ids": ["500-101"],
                "competition": {
                    "canonical_competition_id": "competition:norway-eliteserien",
                    "country": "Norway",
                },
                "kickoff_at": "2026-08-01T17:00:00Z",
                "home": "project-brann",
                "away": "project-molde",
            }
        ],
        translations={
            "101": {
                "home_team_en": "Brann",
                "away_team_en": "Molde",
                "resolution_status": "SUGGESTED",
                "source_file": "translation-only.json",
            }
        },
        canonical_mappings=CANONICAL,
    )

    assert output["provider_mappings"] == []
    assert output["summary"]["unresolved_target_count"] == 1


def test_single_exact_translation_without_provider_id_requires_review():
    output = build_project_identity_output(
        events=[
            {
                "canonical_match_id": "target:single-no-id",
                "provider_match_ids": ["500-102"],
                "competition": {
                    "canonical_competition_id": "competition:norway-eliteserien",
                    "country": "Norway",
                },
                "kickoff_at": "2026-08-01T17:00:00Z",
                "home": "project-brann",
                "away": "project-molde",
            }
        ],
        translations={
            "102": {
                "home_team_en": "Brann",
                "away_team_en": "Molde",
                "resolution_status": "EXACT_MATCH",
                "source_file": "translation-only.json",
            }
        },
        canonical_mappings=CANONICAL,
    )

    assert output["provider_mappings"] == []
    assert output["summary"]["REVIEW_REQUIRED"] == 2
    target = output["target_evidence"]["target:single-no-id"]
    assert target["home"]["resolution_status"] == "unresolved"
