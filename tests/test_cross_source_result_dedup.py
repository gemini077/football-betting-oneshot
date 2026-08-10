from __future__ import annotations

from scripts.football_data.historical_results import deduplicate_historical_results, make_historical_match_result


def result(provider: str) -> dict:
    return make_historical_match_result(
        canonical_match_id="match:competition:sweden-allsvenskan:2026-08-03:team:ik-sirius:team:sweden:halmstads-bk",
        competition_id="competition:sweden-allsvenskan",
        season_id="season:sweden-allsvenskan:2026",
        home_team_id="team:ik-sirius",
        away_team_id="team:sweden:halmstads-bk",
        kickoff_at="2026-08-03T18:00:00Z",
        home_goals=0,
        away_goals=2,
        provider=provider,
        provider_match_id=f"{provider}:SWE:2026-08-03:Sirius:Halmstad",
        source_as_of_at="2026-08-03T18:00:00Z",
        captured_at="2026-08-10T12:00:00Z",
        source_record_ref=f"{provider}:record",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_openfootball_and_football_data_same_result_count_once():
    report = deduplicate_historical_results([result("openfootball"), result("football-data.co.uk")])

    assert len(report.records) == 1
    assert report.records[0]["eligible_for_team_strength"] is True
    assert {item["provider"] for item in report.records[0]["source_confirmations"]} == {"openfootball", "football-data.co.uk"}
