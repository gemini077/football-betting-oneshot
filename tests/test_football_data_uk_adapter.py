from __future__ import annotations

from scripts.football_data.health import build_team_strength_health
from scripts.football_data.providers.football_data_uk import FootballDataCoUkHistoricalAdapter


CSV = """Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA
Sweden,SWEDEN,2026,03/08/2026,18:00,Sirius,Halmstad,0,2,A,1.5,4.2,6.0
Sweden,SWEDEN,2026,03/08/2026,20:00,Djurgarden,Vasteras SK,6,0,H,1.4,4.5,7.0
"""


def adapter() -> FootballDataCoUkHistoricalAdapter:
    return FootballDataCoUkHistoricalAdapter(
        competition_id="competition:sweden-allsvenskan",
        season_id="season:sweden-allsvenskan:2026",
        provider_competition_id="football-data.co.uk:sweden:allsvenskan",
        provider_competition_name="Sweden Allsvenskan",
        provider_season_id="2026",
        provider_season_name="2026",
        source_url="https://www.football-data.co.uk/new/SWE.csv",
        source_file="SWE.csv",
        captured_at="2026-08-10T12:00:00Z",
        team_identity_resolver={
            "Sirius": {"canonical_team_id": "team:ik-sirius", "verified": True, "resolution_method": "manual_verified"},
            "Halmstad": {"canonical_team_id": "team:sweden:halmstads-bk", "verified": True, "resolution_method": "manual_verified"},
            "Djurgarden": {"canonical_team_id": "team:djurgardens", "verified": True, "resolution_method": "manual_verified"},
            "Vasteras SK": {"canonical_team_id": "team:vasteras-sk", "verified": True, "resolution_method": "manual_verified"},
        },
    )


def test_football_data_adapter_normalizes_results_only_and_preserves_provenance():
    records = adapter().parse_csv_text(CSV)

    assert len(records) == 2
    assert records[0]["kickoff_at"] == "2026-08-03T18:00:00Z"
    assert records[0]["home_team_id"] == "team:ik-sirius"
    assert records[0]["away_team_id"] == "team:sweden:halmstads-bk"
    assert records[0]["home_goals"] == 0
    assert records[0]["away_goals"] == 2
    assert records[0]["source_as_of_at"] == "2026-08-03T18:00:00Z"
    assert records[0]["captured_at"] == "2026-08-10T12:00:00Z"
    assert records[0]["provenance"]["commercial_use_review"] == "required"
    assert records[0]["provenance"]["raw_redistribution"] is False
    assert records[0]["provenance"]["internal_analysis_only"] is True
    assert records[0]["provenance"]["source"] == "football-data.co.uk"
    assert "PSCH" not in records[0]


def test_unreviewed_football_data_team_name_remains_ineligible():
    records = adapter().parse_csv_text(CSV.replace("Sirius", "Unknown FC", 1))

    assert records[0]["resolution_status"] == "unresolved"
    assert records[0]["eligible_for_team_strength"] is False


def test_current_football_data_results_replace_stale_status_for_target_teams():
    records = adapter().parse_csv_text(CSV)
    health = build_team_strength_health(
        [{
            "id": "target:sweden",
            "home_team_id": "team:ik-sirius",
            "away_team_id": "team:sweden:halmstads-bk",
            "competition_id": "competition:sweden-allsvenskan",
            "season_id": "season:sweden-allsvenskan:2026",
            "kickoff_at": "2026-08-11T00:00:00Z",
        }],
        records,
        captured_at="2026-08-10T12:00:00Z",
    )

    assert health["both_history_available"] == 1
    assert health["both_current_strength_ready"] == 1
    assert health["stale_history"] == 0
