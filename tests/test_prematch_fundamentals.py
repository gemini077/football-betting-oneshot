from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prematch_fundamentals import _espn_recent_form


def test_espn_last_five_is_aggregated_from_each_team_perspective():
    summary = {
        "lastFiveGames": [
            {
                "team": {"id": "10"},
                "events": [
                    {"homeTeamId": "10", "awayTeamId": "20", "homeTeamScore": "2", "awayTeamScore": "1", "gameDate": "2026-07-01T18:00Z"},
                    {"homeTeamId": "30", "awayTeamId": "10", "homeTeamScore": "0", "awayTeamScore": "0", "gameDate": "2026-07-08T18:00Z"},
                ],
            },
            {
                "team": {"id": "20"},
                "events": [
                    {"homeTeamId": "20", "awayTeamId": "40", "homeTeamScore": "1", "awayTeamScore": "3", "gameDate": "2026-07-02T18:00Z"},
                    {"homeTeamId": "50", "awayTeamId": "20", "homeTeamScore": "1", "awayTeamScore": "2", "gameDate": "2026-07-09T18:00Z"},
                ],
            },
        ]
    }

    form = _espn_recent_form(summary, "10", "20")

    assert form["home_overall"]["matches"] == 2
    assert form["home_overall"]["wins"] == 1
    assert form["home_overall"]["draws"] == 1
    assert form["home_home"]["goals_for"] == 2
    assert form["away_overall"]["goals_for"] == 3
    assert form["away_away"]["wins"] == 1
