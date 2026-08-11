from __future__ import annotations

from scripts.football_data.providers.openfootball import OpenFootballHistoricalAdapter


def test_champions_league_football_txt_is_reused_by_existing_adapter():
    raw = """= UEFA Champions League 2025/26

# Date       Tue Sep 16 2025 - Sat May 30 2026
# Matches    2

▪ Matchday 1
  Tue Sep 16 2025
    20:00  Alpha FC                 v Beta FC                  2-1
  Wed Sep 17
             Gamma FC               v Alpha FC                 0-0
"""
    adapter = OpenFootballHistoricalAdapter(
        competition_id="competition:uefa-champions-league",
        season_id="season:uefa-champions-league:2025-26",
        provider_competition_id="openfootball:champions-league",
        provider_competition_name="UEFA Champions League",
        provider_season_id="2025-26",
        provider_season_name="2025/26",
        repository="openfootball/champions-league",
        commit_sha="fixture-commit",
        source_file="2025-26/cl.txt",
        captured_at="2026-08-10T00:00:00Z",
        team_identity_resolver={
            name: {
                "canonical_team_id": f"team:{name.casefold().replace(' ', '-')}",
                "verified": True,
                "resolution_method": "manual_verified",
            }
            for name in ("Alpha FC", "Beta FC", "Gamma FC")
        },
    )

    records = adapter.parse_text(raw)

    assert len(records) == 2
    assert records[0]["competition_id"] == "competition:uefa-champions-league"
    assert records[0]["provider_competition_id"] == "openfootball:champions-league"
    assert records[0]["provenance"]["repository"] == "openfootball/champions-league"
    assert records[0]["provenance"]["source_file"] == "2025-26/cl.txt"
    assert records[0]["eligible_for_team_strength"] is True
