from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import HistoricalResultStore


def _record(match_id: str, kickoff_at: str) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id="team:home",
        away_team_id="team:away",
        kickoff_at=kickoff_at,
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff_at,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_duckdb_store_preserves_logical_records_and_order_independent_digest(tmp_path):
    records = [
        _record("match:a", "2026-08-01T12:00:00Z"),
        _record("match:b", "2026-08-02T12:00:00Z"),
    ]
    store = HistoricalResultStore(tmp_path / "historical_results.duckdb")

    store.append_many(reversed(records))

    logical_records = list(store.iter_records())
    assert sorted(logical_records, key=lambda row: row["canonical_match_id"]) == sorted(
        records, key=lambda row: row["canonical_match_id"]
    )
    digest_before = store.dataset_digest()
    store.append_many(records)
    assert store.count() == len(records)
    assert store.dataset_digest() == digest_before

