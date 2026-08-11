from __future__ import annotations

from scripts.football_data.final_source_decisions import build_final_source_discovery


def test_uefa_prior_season_does_not_become_current_season_ready():
    report = build_final_source_discovery(
        checked_at="2026-08-11T00:00:00Z",
        api_key_present=False,
    )

    by_name = {row["source"]: row for row in report["sources"]}
    assert by_name["openfootball/champions-league"]["current_2026_27_status"] == "MISSING"
    assert by_name["openfootball/champions-league"]["prior_season_status"] == "AVAILABLE"
    assert by_name["K League official/public"]["status"] == "SOURCE_MISSING"
    assert report["k_league_source_gap"] is True
    assert report["api_football"]["status"] == "NOT_EXECUTED_NO_KEY"
