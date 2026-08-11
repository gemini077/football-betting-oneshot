from __future__ import annotations

import pytest

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.team_strength import PreMatchSnapshotStore, TeamStrengthBuilder


def make_result(match_id: str, kickoff: str, goals: int) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id="team:home",
        away_team_id="team:away",
        kickoff_at=kickoff,
        home_goals=goals,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{match_id}",
        source_as_of_at=kickoff,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_pre_match_snapshot_cannot_be_overwritten_after_target_result(tmp_path):
    builder = TeamStrengthBuilder(
        [make_result("past", "2026-07-01T12:00:00Z", 1)],
        captured_at="2026-08-01T00:00:00Z",
    )
    original = builder.build(
        "team:home",
        target_kickoff="2026-08-02T12:00:00Z",
        window_type="last_5",
        competition_id="competition:test",
        season_id="season:2026",
    )
    assert original["input_dataset_digest"]
    assert original["builder_version"] == "team-strength-builder.v2-duckdb"
    store = PreMatchSnapshotStore(tmp_path / "snapshots")
    assert store.store.path.name == "team_strength_snapshots.duckdb"
    store.put(original)
    store.put(original)

    changed = TeamStrengthBuilder(
        [
            make_result("past", "2026-07-01T12:00:00Z", 1),
            make_result("target", "2026-08-02T12:00:00Z", 9),
        ],
        captured_at="2026-08-03T00:00:00Z",
    ).build(
        "team:home",
        target_kickoff="2026-08-02T12:00:00Z",
        window_type="last_5",
        competition_id="competition:test",
        season_id="season:2026",
    )

    with pytest.raises(ValueError, match="immutable"):
        store.put(changed, snapshot_id=original["snapshot_id"])


def test_snapshot_bytes_are_stable_when_rebuilt_from_same_captured_evidence():
    records = [make_result("past", "2026-07-01T12:00:00Z", 1)]
    kwargs = {
        "target_kickoff": "2026-08-02T12:00:00Z",
        "window_type": "last_5",
        "competition_id": "competition:test",
        "season_id": "season:2026",
    }
    first = TeamStrengthBuilder(records, captured_at="2026-08-01T00:00:00Z").build("team:home", **kwargs)
    second = TeamStrengthBuilder(records, captured_at="2026-08-01T00:00:00Z").build("team:home", **kwargs)

    assert first == second
