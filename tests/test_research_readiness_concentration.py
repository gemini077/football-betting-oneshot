from scripts.football_data.research_preflight import concentration_metrics


def test_concentration_reports_largest_competition_season_and_team_shares():
    rows = [
        {"competition_id": "competition:a", "season_id": "season:a:2025", "home_team_id": "team:one", "away_team_id": "team:two"},
        {"competition_id": "competition:a", "season_id": "season:a:2025", "home_team_id": "team:one", "away_team_id": "team:three"},
        {"competition_id": "competition:b", "season_id": "season:b:2025", "home_team_id": "team:one", "away_team_id": "team:five"},
        {"competition_id": "competition:b", "season_id": "season:b:2025", "home_team_id": "team:four", "away_team_id": "team:six"},
    ]

    result = concentration_metrics(rows)

    assert result["fixture_count"] == 4
    assert result["largest_competition"]["share"] == 0.5
    assert result["largest_season"]["share"] == 0.5
    assert result["largest_team_appearance"]["team_id"] == "team:one"
