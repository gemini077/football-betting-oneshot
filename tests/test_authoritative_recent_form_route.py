from __future__ import annotations

from datetime import datetime, timezone

from scripts.football_data.historical_results import make_historical_match_result
from scripts.recent_form_cache import load_authoritative_recent_form


HOME_ID = "team:test:home"
AWAY_ID = "team:test:away"
COMPETITION_ID = "competition:test-league"
CUTOFF = "2026-08-30T12:00:00Z"
NOW = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)


def _record(index: int, *, target: str, venue: str, kickoff: str) -> dict:
    opponent = f"team:test:opponent-{index}"
    home_id, away_id = (target, opponent) if venue == "home" else (opponent, target)
    return make_historical_match_result(
        canonical_match_id=f"match:test:{index}",
        competition_id=COMPETITION_ID,
        season_id="season:test:2026",
        home_team_id=home_id,
        away_team_id=away_id,
        kickoff_at=kickoff,
        home_goals=2,
        away_goals=1,
        provider="football-data.co.uk",
        provider_match_id=f"test:{index}",
        source_as_of_at=kickoff,
        captured_at="2026-08-26T00:00:00Z",
        source_record_ref=f"test-source:{index}",
        source_reliable=True,
        raw_home_team=home_id,
        raw_away_team=away_id,
        raw_competition="Test League",
        raw_season="2026",
        source_file="TEST.csv",
        match_type="league",
        resolution_method="manual_verified",
    )


def _records(*, stale: bool = False) -> list[dict]:
    latest = [
        "2026-06-01T12:00:00Z" if stale else "2026-08-20T12:00:00Z",
        "2026-06-02T12:00:00Z" if stale else "2026-08-21T12:00:00Z",
        "2026-06-03T12:00:00Z" if stale else "2026-08-22T12:00:00Z",
        "2026-06-04T12:00:00Z" if stale else "2026-08-23T12:00:00Z",
        "2026-06-05T12:00:00Z" if stale else "2026-08-24T12:00:00Z",
        "2026-06-06T12:00:00Z" if stale else "2026-08-25T12:00:00Z",
    ]
    rows = []
    for index, kickoff in enumerate(latest, 1):
        rows.append(_record(index, target=HOME_ID, venue="home" if index % 2 else "away", kickoff=kickoff))
        rows.append(_record(index + 10, target=AWAY_ID, venue="away" if index % 2 else "home", kickoff=kickoff))
    return rows


def _request() -> tuple[dict, dict, dict]:
    job = {
        "match_id": "fixture:test:1",
        "home": "Home FC",
        "away": "Away FC",
        "league": "Test League",
        "kickoff": "2026-08-30T20:00:00+08:00",
    }
    fixture = {
        "matchId": job["match_id"],
        "homeTeam": job["home"],
        "awayTeam": job["away"],
        "league": job["league"],
    }
    identity = {
        "home_team_id": HOME_ID,
        "away_team_id": AWAY_ID,
        "status": "AUTO_RESOLVED",
        "resolution_method": "reviewed_canonical_provider_crosswalk",
    }
    return job, fixture, identity


def test_authoritative_history_builds_the_same_four_block_contract_without_future_leakage():
    job, fixture, identity = _request()
    future = _record(99, target=HOME_ID, venue="home", kickoff="2026-08-30T13:00:00Z")
    loaded = load_authoritative_recent_form(
        job,
        fixture,
        CUTOFF,
        NOW,
        identity=identity,
        competition_id=COMPETITION_ID,
        historical_records=[*_records(), future],
    )

    assert loaded is not None
    assert loaded["source"] == "authoritative_historical_results"
    assert loaded["provenance"]["synthetic"] is False
    assert loaded["provenance"]["competition_id"] == COMPETITION_ID
    assert all(row["kickoff_at"] < CUTOFF for row in loaded["records"])
    assert all(loaded["recent_form"][key]["matches"] > 0 for key in ("home_overall", "home_home", "away_overall", "away_away"))
    assert loaded["source_refs"]


def test_authoritative_history_fails_closed_when_latest_team_history_is_stale():
    job, fixture, identity = _request()
    assert load_authoritative_recent_form(
        job,
        fixture,
        CUTOFF,
        NOW,
        identity=identity,
        competition_id=COMPETITION_ID,
        historical_records=_records(stale=True),
    ) is None


def test_authoritative_history_queries_the_store_with_exact_pre_kickoff_filters():
    job, fixture, identity = _request()

    class Store:
        def __init__(self) -> None:
            self.filters = None

        def iter_records(self, **filters):
            self.filters = filters
            return iter(_records())

    store = Store()
    loaded = load_authoritative_recent_form(
        job,
        fixture,
        CUTOFF,
        NOW,
        identity=identity,
        competition_id=COMPETITION_ID,
        historical_store=store,
    )

    assert loaded is not None
    assert store.filters == {
        "competition_id": COMPETITION_ID,
        "before_kickoff": CUTOFF,
        "entity_type": "club",
        "eligible_only": True,
    }
