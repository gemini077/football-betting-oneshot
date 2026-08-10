from __future__ import annotations

from scripts.football_data.providers.openfootball import OpenFootballHistoricalAdapter


TEXT = """= Context fixture\n\n  Sat Mar 29 2025\n    15:00  Reviewed FC          v Unknown FC                 1-0\n"""


def test_unreviewed_external_name_cannot_make_a_result_eligible():
    adapter = OpenFootballHistoricalAdapter(
        competition_id="competition:test",
        season_id="season:test",
        provider_competition_id="source:test",
        provider_competition_name="Context fixture",
        provider_season_id="2025",
        provider_season_name="2025",
        repository="openfootball/europe",
        commit_sha="commit:test",
        source_file="tests/context.txt",
        captured_at="2026-08-10T00:00:00Z",
        team_identity_resolver={
            "Reviewed FC": {
                "canonical_team_id": "team:reviewed",
                "verified": True,
                "resolution_method": "manual_verified",
                "verification_evidence": ["competition file and country context reviewed"],
            },
            "Unknown FC": {
                "canonical_team_id": "team:unknown",
                "verified": False,
                "resolution_method": "normalized_alias",
            },
        },
    )

    record = adapter.parse_text(TEXT)[0]

    assert record["resolution_status"] == "unresolved"
    assert record["resolution_method"] == "unresolved"
    assert record["eligible_for_team_strength"] is False
    assert "identity_unresolved" in record["missing_reason"]
