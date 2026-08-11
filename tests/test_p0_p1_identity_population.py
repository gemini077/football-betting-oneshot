from __future__ import annotations

from scripts.football_data.p0_p1_identity import (
    P0P1TeamIdentityCandidateBuilder,
    SourceMatchObservation,
)


def _observations() -> list[SourceMatchObservation]:
    fixtures = [
        ("2025-04-01", "Alpha FC", "Beta FC", "Alpha", "Beta", 1, 0),
        ("2025-04-08", "Beta FC", "Gamma FC", "Beta", "Gamma", 2, 1),
        ("2025-04-15", "Gamma FC", "Alpha FC", "Gamma", "Alpha", 0, 1),
        ("2025-04-22", "Alpha FC", "Gamma FC", "Alpha", "Gamma", 2, 0),
        ("2025-04-29", "Gamma FC", "Beta FC", "Gamma", "Beta", 1, 1),
        ("2025-05-06", "Beta FC", "Alpha FC", "Beta", "Alpha", 0, 2),
    ]
    output: list[SourceMatchObservation] = []
    for date, of_home, of_away, fd_home, fd_away, home_goals, away_goals in fixtures:
        output.extend(
            [
                SourceMatchObservation(
                    provider="openfootball",
                    competition_id="competition:test-league",
                    season_id="season:test:2025",
                    country="Testland",
                    kickoff_at=f"{date}T12:00:00Z",
                    home_name=of_home,
                    away_name=of_away,
                    home_goals=home_goals,
                    away_goals=away_goals,
                    source_ref=f"openfootball:{date}",
                ),
                SourceMatchObservation(
                    provider="football-data.co.uk",
                    competition_id="competition:test-league",
                    season_id="season:test:2025",
                    country="Testland",
                    kickoff_at=f"{date}T12:00:00Z",
                    home_name=fd_home,
                    away_name=fd_away,
                    home_goals=home_goals,
                    away_goals=away_goals,
                    source_ref=f"football-data:{date}",
                ),
            ]
        )
    return output


def test_cross_source_graph_can_auto_verify_only_repeated_unique_context():
    result = P0P1TeamIdentityCandidateBuilder().build(_observations())

    auto = [row for row in result["candidates"] if row["status"] == "AUTO_VERIFIED"]
    assert len(auto) == 6
    assert {row["provider"] for row in auto} == {"openfootball", "football-data.co.uk"}
    assert all(row["verified"] is True for row in auto)
    assert all(row["resolution_method"] == "cross_source_context_verified" for row in auto)
    assert all(row["evidence"]["aligned_match_count"] >= 3 for row in auto)
    assert all(row["evidence"]["distinct_opponent_count"] >= 2 for row in auto)

    alpha_ids = {
        row["canonical_team_id"]
        for row in auto
        if row["provider_team_name"] in {"Alpha FC", "Alpha"}
    }
    assert len(alpha_ids) == 1


def test_generic_name_never_becomes_auto_verified():
    rows = _observations()
    rows = [
        SourceMatchObservation(
            **{
                **row.__dict__,
                "home_name": "City" if row.home_name == "Alpha FC" else row.home_name,
                "away_name": "City" if row.away_name == "Alpha FC" else row.away_name,
            }
        )
        for row in rows
    ]
    result = P0P1TeamIdentityCandidateBuilder().build(rows)

    city_rows = [row for row in result["candidates"] if row["provider_team_name"] == "City"]
    assert city_rows
    assert all(row["status"] in {"UNRESOLVED", "CONFLICT", "REVIEW_REQUIRED"} for row in city_rows)
    assert all(row["verified"] is False for row in city_rows)


def test_insufficient_context_is_review_required_not_verified():
    rows = _observations()[:2]
    result = P0P1TeamIdentityCandidateBuilder().build(rows)

    assert result["summary"]["AUTO_VERIFIED"] == 0
    assert any(row["status"] == "REVIEW_REQUIRED" for row in result["candidates"])
