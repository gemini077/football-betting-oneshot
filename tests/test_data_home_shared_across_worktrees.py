from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import HistoricalResultStore
from scripts.football_data.team_strength import PreMatchSnapshotStore
from scripts.football_data.data_home import resolve_football_data_home


def _record() -> dict:
    return make_historical_match_result(
        canonical_match_id="match:shared-home",
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id="team:home",
        away_team_id="team:away",
        kickoff_at="2026-08-01T12:00:00Z",
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id="fixture:shared-home",
        source_as_of_at="2026-08-01T12:00:00Z",
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref="fixture:shared-home",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_data_home_is_shared_across_two_worktree_roots(tmp_path, monkeypatch):
    shared_home = tmp_path / "shared-football-data"
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    worktree_a.mkdir()
    worktree_b.mkdir()
    monkeypatch.setenv("FOOTBALL_DATA_HOME", str(shared_home))

    monkeypatch.chdir(worktree_a)
    historical_a = HistoricalResultStore()
    historical_a.append(_record())
    snapshot_a = PreMatchSnapshotStore()
    snapshot_a.put(
        {
            "snapshot_id": "snapshot:shared-home",
            "target_match_id": "match:target",
            "team_id": "team:home",
            "as_of_at": "2026-08-10T00:00:00Z",
            "matches": 1,
        }
    )
    historical_path = historical_a.path
    historical_digest = historical_a.dataset_digest()
    snapshot_path = snapshot_a.store.path
    snapshot_digest = snapshot_a.store.dataset_digest()

    monkeypatch.chdir(worktree_b)
    historical_b = HistoricalResultStore()
    snapshot_b = PreMatchSnapshotStore()
    assert resolve_football_data_home() == shared_home
    assert historical_b.path == historical_path
    assert snapshot_b.store.path == snapshot_path
    assert historical_b.count() == 1
    assert historical_b.dataset_digest() == historical_digest
    assert snapshot_b.store.count() == 1
    assert snapshot_b.store.dataset_digest() == snapshot_digest
