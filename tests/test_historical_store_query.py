from __future__ import annotations

import pytest

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import DatasetNotAvailableError, HistoricalResultStore


def _record(
    match_id: str,
    kickoff_at: str,
    *,
    competition_id: str = "competition:test",
    home_team_id: str = "team:home",
    away_team_id: str = "team:away",
) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id=competition_id,
        season_id="season:2026",
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        kickoff_at=kickoff_at,
        home_goals=2,
        away_goals=1,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff_at,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_missing_bulk_dataset_is_explicit(tmp_path):
    store = HistoricalResultStore(tmp_path / "historical_results.duckdb")

    with pytest.raises(DatasetNotAvailableError, match="DATASET_NOT_AVAILABLE"):
        store.count()


def test_store_supports_team_before_kickoff_competition_and_digest_queries(tmp_path):
    store = HistoricalResultStore(tmp_path / "historical_results.duckdb")
    past = _record("match:past", "2026-08-01T12:00:00Z")
    later = _record("match:later", "2026-08-05T12:00:00Z")
    other_competition = _record(
        "match:other",
        "2026-08-02T12:00:00Z",
        competition_id="competition:other",
        home_team_id="team:other-home",
        away_team_id="team:home",
    )

    store.append_many([later, other_competition, past])

    assert store.count() == 3
    assert [row["canonical_match_id"] for row in store.query_by_team("team:home")] == [
        "match:past",
        "match:other",
        "match:later",
    ]
    assert [row["canonical_match_id"] for row in store.query_before_kickoff("team:home", "2026-08-03T00:00:00Z")] == [
        "match:past",
        "match:other",
    ]
    assert [row["canonical_match_id"] for row in store.query_by_competition("competition:other")] == ["match:other"]
    assert store.dataset_digest() == store.dataset_digest()
    assert len(store.dataset_digest()) == 64

