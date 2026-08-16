from __future__ import annotations

import pytest

from scripts.football_data.build_id2_v3_staging import (
    NEW_BENFICA,
    OLD_BENFICA,
    _append_snapshots_in_one_transaction,
    build,
)
from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import DuckDBSnapshotStore, HistoricalResultStore


def _result(*, home: str, away: str, kickoff: str, source_file: str = "2024-25/elq.txt"):
    return make_historical_match_result(
        canonical_match_id=f"match:test:{kickoff}",
        competition_id="competition:uefa-europa-league",
        season_id="season:uefa-europa-league:2024-25",
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
        provider="openfootball",
        provider_match_id=f"{source_file}:{kickoff}",
        source_as_of_at="2026-08-16T00:00:00Z",
        raw_home_team="SL Benfica (POR)",
        raw_away_team="Heart of Midlothian (SCO)",
        raw_competition="UEFA Europa League",
        raw_season="2024/25",
        resolution_status="resolved",
        resolution_method="cross_source_context_verified",
        source_file=source_file,
        raw_sha256="a" * 64,
        repository="openfootball/champions-league",
        commit_sha="a" * 40,
    )


def test_invalid_baseline_digest_does_not_create_output(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    store = HistoricalResultStore(baseline / "historical_results.duckdb")
    store.append(_result(home=OLD_BENFICA, away="team:scotland:heart-of-midlothian-fc", kickoff="2024-08-01T00:00:00Z"))
    snapshots = DuckDBSnapshotStore(baseline / "team_strength_snapshots.duckdb")
    snapshots.put({"snapshot_id": "snapshot-1", "team_id": OLD_BENFICA})
    monkeypatch.setattr("scripts.football_data.build_id2_v3_staging.EXPECTED_BASELINE_COUNT", 1)
    monkeypatch.setattr("scripts.football_data.build_id2_v3_staging.EXPECTED_BASELINE_DIGEST", "0" * 64)
    output = tmp_path / "v3"
    with pytest.raises(ValueError, match="authoritative baseline mismatch"):
        build(baseline=baseline, raw_root=tmp_path, manifest=tmp_path / "manifest.json", identities=tmp_path / "identity.json", output=output, cutoff="2026-08-13T17:00:00Z")
    assert not output.exists()


def test_cutoff_leak_does_not_create_output(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    store = HistoricalResultStore(baseline / "historical_results.duckdb")
    store.append(_result(home=OLD_BENFICA, away="team:scotland:heart-of-midlothian-fc", kickoff="2024-08-01T00:00:00Z"))
    DuckDBSnapshotStore(baseline / "team_strength_snapshots.duckdb").put({"snapshot_id": "snapshot-1", "team_id": OLD_BENFICA})
    monkeypatch.setattr("scripts.football_data.build_id2_v3_staging.EXPECTED_BASELINE_COUNT", 1)
    monkeypatch.setattr("scripts.football_data.build_id2_v3_staging.EXPECTED_BASELINE_DIGEST", store.dataset_digest())
    monkeypatch.setattr("scripts.football_data.build_id2_v3_staging.load_openfootball_records", lambda *args, **kwargs: [_result(home=OLD_BENFICA, away="team:scotland:heart-of-midlothian-fc", kickoff="2026-08-14T00:00:00Z")])
    output = tmp_path / "v3"
    with pytest.raises(ValueError, match="source rows at/after cutoff"):
        build(baseline=baseline, raw_root=tmp_path, manifest=tmp_path / "manifest.json", identities=tmp_path / "identity.json", output=output, cutoff="2026-08-13T17:00:00Z")
    assert not output.exists()


def test_snapshot_bulk_transaction_rolls_back_invalid_row(tmp_path):
    store = DuckDBSnapshotStore(tmp_path / "snapshots.duckdb")
    with pytest.raises(ValueError, match="immutable snapshot"):
        _append_snapshots_in_one_transaction(store, [{"snapshot_id": "ok", "team_id": "team:a"}, {"team_id": "missing-id"}])
    assert store.count() == 0


def test_snapshot_bulk_transaction_preserves_count_and_digest(tmp_path):
    store = DuckDBSnapshotStore(tmp_path / "snapshots.duckdb")
    rows = [{"snapshot_id": "a", "team_id": "team:a"}, {"snapshot_id": "b", "team_id": "team:b"}]
    _append_snapshots_in_one_transaction(store, rows)
    assert store.count() == 2
    assert store.dataset_digest()
    reopened = DuckDBSnapshotStore(tmp_path / "snapshots.duckdb")
    assert reopened.count() == 2
    assert reopened.dataset_digest() == store.dataset_digest()
