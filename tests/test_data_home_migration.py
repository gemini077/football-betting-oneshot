from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.migrate_data_home import migrate_data_home
from scripts.football_data.storage import DuckDBSnapshotStore, HistoricalResultStore


def test_migration_copies_both_datasets_and_preserves_legacy(tmp_path):
    source = tmp_path / "legacy"
    destination = tmp_path / "shared"
    historical = HistoricalResultStore(source / "historical_results.duckdb")
    historical.append(
        make_historical_match_result(
            canonical_match_id="match:migrate",
            competition_id="competition:test",
            season_id="season:2026",
            home_team_id="team:home",
            away_team_id="team:away",
            kickoff_at="2026-08-01T12:00:00Z",
            home_goals=1,
            away_goals=0,
            provider="fixture",
            provider_match_id="fixture:migrate",
            source_as_of_at="2026-08-01T12:00:00Z",
            captured_at="2026-08-10T00:00:00Z",
            source_record_ref="fixture:migrate",
            source_reliable=True,
            resolution_method="manual_verified",
        )
    )
    snapshots = DuckDBSnapshotStore(source / "team_strength_snapshots.duckdb")
    snapshots.put(
        {
            "snapshot_id": "snapshot:migrate",
            "target_match_id": "match:target",
            "team_id": "team:home",
            "as_of_at": "2026-08-10T00:00:00Z",
        }
    )
    historical_digest = historical.dataset_digest()
    snapshot_digest = snapshots.dataset_digest()

    result = migrate_data_home(source_root=source, destination_root=destination)

    assert result["status"] == "OK"
    assert result["legacy_cache_preserved"] is True
    assert HistoricalResultStore(source / "historical_results.duckdb").dataset_digest() == historical_digest
    assert DuckDBSnapshotStore(source / "team_strength_snapshots.duckdb").dataset_digest() == snapshot_digest
    assert HistoricalResultStore(destination / "historical_results.duckdb").dataset_digest() == historical_digest
    assert DuckDBSnapshotStore(destination / "team_strength_snapshots.duckdb").dataset_digest() == snapshot_digest
