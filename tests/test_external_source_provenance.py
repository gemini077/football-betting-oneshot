from __future__ import annotations

from scripts.football_data.providers.openfootball import OpenFootballHistoricalAdapter


def test_openfootball_provenance_has_reproducible_source_coordinates():
    adapter = OpenFootballHistoricalAdapter(
        competition_id="competition:test",
        season_id="season:test",
        provider_competition_id="source:test",
        provider_competition_name="Test",
        provider_season_id="2025",
        provider_season_name="2025",
        repository="openfootball/europe",
        commit_sha="abc123",
        source_file="sweden/2025_se1.txt",
        captured_at="2026-08-10T00:00:00Z",
        team_identity_resolver={
            "A FC": {"canonical_team_id": "team:a", "verified": True, "resolution_method": "manual_verified"},
            "B FC": {"canonical_team_id": "team:b", "verified": True, "resolution_method": "manual_verified"},
        },
    )
    record = adapter.parse_text("= Test\n\n  Sat Mar 29 2025\n    15:00  A FC  v B FC  2-1\n")[0]

    provenance = record["provenance"]
    assert provenance["repository"] == "openfootball/europe"
    assert provenance["commit_sha"] == "abc123"
    assert provenance["source_file"] == "sweden/2025_se1.txt"
    assert len(provenance["raw_sha256"]) == 64
    assert provenance["parser_version"].startswith("openfootball")
    assert provenance["data_license"] == "CC0-1.0"
    assert provenance["synthetic"] is False
