from __future__ import annotations

from pathlib import Path

from scripts.football_data.providers.openfootball import OpenFootballHistoricalAdapter, parse_football_txt_rows


FIXTURE = Path(__file__).parent / "fixtures" / "football_data" / "openfootball" / "synthetic_allsvenskan.txt"


def reviewed_identities():
    return {
        "IK Sirius": {"canonical_team_id": "team:ik-sirius", "verified": True, "resolution_method": "manual_verified"},
        "IF Brommapojkarna": {"canonical_team_id": "team:if-brommapojkarna", "verified": True, "resolution_method": "manual_verified"},
        "Djurgårdens IF": {"canonical_team_id": "team:djurgardens", "verified": True, "resolution_method": "manual_verified"},
        "Västerås SK": {"canonical_team_id": "team:vasteras-sk", "verified": True, "resolution_method": "manual_verified"},
    }


def test_openfootball_native_txt_shape_is_normalized_without_network():
    adapter = OpenFootballHistoricalAdapter(
        competition_id="competition:sweden-allsvenskan",
        season_id="season:sweden-allsvenskan:2025",
        provider_competition_id="europe:sweden:se1",
        provider_competition_name="Sweden Allsvenskan",
        provider_season_id="2025",
        provider_season_name="2025",
        repository="openfootball/europe",
        commit_sha="commit:fixture",
        source_file="sweden/2025_se1.txt",
        captured_at="2026-08-10T00:00:00Z",
        team_identity_resolver=reviewed_identities(),
        synthetic=True,
    )

    records = adapter.parse_text(FIXTURE.read_text(encoding="utf-8"))

    assert len(records) == 3
    assert records[0]["raw_home_team"] == "IK Sirius"
    assert records[0]["home_goals"] == 1
    assert records[0]["away_goals"] == 0
    assert records[0]["kickoff_at"] == "2025-03-29T15:00:00Z"
    assert records[0]["match_type"] == "league"
    assert records[0]["provenance"]["repository"] == "openfootball/europe"
    assert records[0]["provenance"]["commit_sha"] == "commit:fixture"
    assert records[0]["provenance"]["source_file"] == "sweden/2025_se1.txt"
    assert records[0]["provenance"]["raw_sha256"]
    assert records[0]["provenance"]["synthetic"] is True
    assert records[0]["provenance"]["source"] == "synthetic_openfootball_fixture"
    assert records[0]["eligible_for_team_strength"] is False


def test_openfootball_only_accepts_unambiguous_90_minute_scores():
    raw = """= UEFA Europa League - Quali 2025/26

Thu Jul 10 2025
  17:00  Normal FC (AAA) v Plain FC (BBB) 2-1 (1-0)
  18:00  Extra FC (AAA) v Time FC (BBB) 3-2 a.e.t. (1-1, 1-1)
  19:00  Shoot FC (AAA) v Out FC (BBB) 5-6 pen. 2-2 a.e.t. (1-1, 1-1)
"""
    rows = parse_football_txt_rows(raw)

    assert rows[0]["home_goals"] == 2
    assert rows[0]["away_goals"] == 1
    assert rows[0]["score_semantics"] == "90_minute_unambiguous"
    assert rows[1]["home_goals"] is None
    assert rows[1]["away_goals"] is None
    assert rows[1]["score_semantics"] == "ambiguous_extra_time_or_shootout"
    assert rows[2]["home_goals"] is None
    assert rows[2]["away_goals"] is None
    assert rows[2]["score_semantics"] == "ambiguous_extra_time_or_shootout"

    adapter = OpenFootballHistoricalAdapter(
        competition_id="competition:uefa-europa-league",
        season_id="season:uefa-europa-league:2025-26",
        provider_competition_id="champions-league:el",
        provider_competition_name="UEFA Europa League",
        provider_season_id="2025-26",
        provider_season_name="2025/26",
        repository="openfootball/champions-league",
        commit_sha="a" * 40,
        source_file="2025-26/elq.txt",
        captured_at="2026-08-16T00:00:00Z",
        team_identity_resolver={
            "Normal FC (AAA)": {"canonical_team_id": "team:normal", "verified": True, "resolution_method": "manual_verified"},
            "Plain FC (BBB)": {"canonical_team_id": "team:plain", "verified": True, "resolution_method": "manual_verified"},
            "Extra FC (AAA)": {"canonical_team_id": "team:extra", "verified": True, "resolution_method": "manual_verified"},
            "Time FC (BBB)": {"canonical_team_id": "team:time", "verified": True, "resolution_method": "manual_verified"},
            "Shoot FC (AAA)": {"canonical_team_id": "team:shoot", "verified": True, "resolution_method": "manual_verified"},
            "Out FC (BBB)": {"canonical_team_id": "team:out", "verified": True, "resolution_method": "manual_verified"},
        },
    )
    records = adapter.parse_text(raw)
    assert records[0]["eligible_for_team_strength"] is True
    assert records[1]["eligible_for_team_strength"] is False
    assert records[2]["eligible_for_team_strength"] is False
    assert records[1]["score_semantics"] == "ambiguous_extra_time_or_shootout"
