from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result


def result(
    match_id: str,
    kickoff: str,
    home: str,
    away: str,
    home_goals: int = 1,
    away_goals: int = 0,
    *,
    competition: str = "competition:test",
    season: str = "season:test:2026",
) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id=competition,
        season_id=season,
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=home_goals,
        away_goals=away_goals,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-11T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_status="resolved",
        resolution_method="manual_verified",
        match_type="league",
    )


def target(
    match_id: str = "target",
    *,
    kickoff: str = "2026-03-01T12:00:00Z",
    home: str = "team:home",
    away: str = "team:away",
) -> dict:
    return result(match_id, kickoff, home, away, 9, 9)


def paired_history(*, count: int = 12) -> list[dict]:
    rows: list[dict] = []
    for index in range(count):
        day = index + 1
        rows.append(result(
            f"home-{index}",
            f"2026-01-{day:02d}T12:00:00Z",
            "team:home",
            f"team:opponent-home-{index}",
            2,
            1,
        ))
        rows.append(result(
            f"away-{index}",
            f"2026-01-{day:02d}T13:00:00Z",
            f"team:opponent-away-{index}",
            "team:away",
            1,
            1,
        ))
    return rows


def fold_targets(count: int = 12) -> list[dict]:
    return [
        result(
            f"target-{index}",
            f"2026-02-{index + 1:02d}T12:00:00Z",
            "team:home",
            "team:away",
            index % 3,
            (index + 1) % 2,
        )
        for index in range(count)
    ]
