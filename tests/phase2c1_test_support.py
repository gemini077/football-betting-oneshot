from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def kickoff(day: int, hour: int = 12) -> str:
    value = datetime(2026, 1, 1, hour, tzinfo=timezone.utc) + timedelta(days=day)
    return value.isoformat().replace("+00:00", "Z")


def target(match_id: str = "target", *, home: str = "team:home", away: str = "team:away", day: int = 30) -> dict:
    return result(match_id, kickoff(day), home, away, 9, 9)


def balanced_history() -> list[dict]:
    rows: list[dict] = []
    for index in range(10):
        rows.append(result(f"home-{index}", kickoff(index), "team:home", f"team:opponent-h-{index}", 2, 0))
        rows.append(result(f"away-{index}", kickoff(index, 13), f"team:opponent-a-{index}", "team:away", 0, 1))
    return rows
