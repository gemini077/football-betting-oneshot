from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.runtime_snapshot import (
    build_manifest,
    file_sha256,
    immutable_object_key,
    manifest_object_key,
)
from scripts.football_data.storage import HistoricalResultStore
from scripts.football_data.bootstrap_runtime_data import bootstrap_runtime_data


class FakeObjectStore:
    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})
        self.calls: list[tuple[str, str]] = []

    def head_object(self, key: str) -> dict:
        self.calls.append(("head", key))
        if key not in self.objects:
            from scripts.football_data.runtime_snapshot import ObjectNotFound

            raise ObjectNotFound()
        return {"ContentLength": len(self.objects[key])}

    def download(self, key: str, destination: Path) -> None:
        self.calls.append(("get", key))
        if key not in self.objects:
            from scripts.football_data.runtime_snapshot import ObjectNotFound

            raise ObjectNotFound()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])


def _record(index: int) -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:bootstrap:{index}",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id=f"team:test:home:{index}",
        away_team_id=f"team:test:away:{index}",
        kickoff_at=f"2026-08-{index + 1:02d}T12:00:00Z",
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{index}",
        source_as_of_at=f"2026-08-{index + 1:02d}T12:00:00Z",
        captured_at="2026-08-30T00:00:00Z",
        source_record_ref=f"fixture:{index}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def _snapshot(tmp_path: Path, name: str, count: int = 2) -> tuple[Path, dict, bytes]:
    db = tmp_path / f"{name}.duckdb"
    HistoricalResultStore(db).append_many(_record(index) for index in range(1, count + 1))
    store = HistoricalResultStore(db)
    artifact = file_sha256(db)
    manifest = build_manifest(
        dataset_sha256=store.dataset_digest(),
        record_count=store.count(),
        artifact_sha256=artifact,
        source_manifest_hashes=["b" * 64],
        builder_version="test-builder.v1",
        now="2026-08-30T01:02:03Z",
    )
    return db, manifest, db.read_bytes()


def test_current_snapshot_success_exports_isolated_data_home(tmp_path):
    db, manifest, artifact = _snapshot(tmp_path, "current")
    manifest_path = tmp_path / "runtime_snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    object_store = FakeObjectStore({immutable_object_key(manifest["dataset_sha256"]): artifact})
    env_path = tmp_path / "github.env"
    data_home = tmp_path / "runner" / "runtime"

    result = bootstrap_runtime_data(
        manifest_path=manifest_path,
        data_home=data_home,
        runtime_temp=tmp_path / "runner-temp",
        github_env_path=env_path,
        health_path=tmp_path / "health.json",
        object_store=object_store,
    )

    assert result["status"] == "READY"
    assert result["runtime_data_snapshot"]["status"] == "READY"
    assert result["record_count"] == manifest["record_count"]
    assert HistoricalResultStore(data_home / "historical_results.duckdb").dataset_digest() == manifest["dataset_sha256"]
    env_lines = env_path.read_text(encoding="utf-8").splitlines()
    assert env_lines[0] == f"FOOTBALL_DATA_HOME={data_home.resolve()}"
    assert env_lines[1] == f"FOOTBALL_DATA_RUNTIME_SNAPSHOT_HEALTH={(tmp_path / 'health.json').resolve()}"
    assert (tmp_path / "health.json").exists()
    assert ("head", manifest["object_key"]) in object_store.calls
    assert ("get", manifest["object_key"]) in object_store.calls


def test_current_failure_uses_exact_previous_snapshot(tmp_path):
    previous_db, previous, previous_bytes = _snapshot(tmp_path, "previous", count=1)
    current_db, current, current_bytes = _snapshot(tmp_path, "current", count=2)
    current["previous_snapshot_version"] = previous["snapshot_version"]
    current["snapshot_version"] = current["snapshot_version"]
    current_object = b"corrupted current snapshot"
    manifest_path = tmp_path / "runtime_snapshot_manifest.json"
    manifest_path.write_text(json.dumps(current), encoding="utf-8")
    object_store = FakeObjectStore({
        current["object_key"]: current_object,
        manifest_object_key(previous["snapshot_version"]): json.dumps(previous).encode("utf-8"),
        previous["object_key"]: previous_bytes,
    })

    result = bootstrap_runtime_data(
        manifest_path=manifest_path,
        data_home=tmp_path / "runtime",
        runtime_temp=tmp_path / "runner-temp",
        object_store=object_store,
    )

    assert result["status"] == "DEGRADED_LAST_KNOWN_GOOD"
    assert result["runtime_data_snapshot"]["status"] == "DEGRADED_LAST_KNOWN_GOOD"
    assert result["snapshot_version"] == previous["snapshot_version"]
    assert result["record_count"] == previous["record_count"]
    assert HistoricalResultStore(tmp_path / "runtime" / "historical_results.duckdb").count() == 1
    assert result["attempts"][0]["status"] == "FAILED"


def test_current_and_previous_failure_is_fail_closed_without_empty_success(tmp_path):
    _, current, _ = _snapshot(tmp_path, "current")
    _, previous, _ = _snapshot(tmp_path, "previous")
    current["previous_snapshot_version"] = previous["snapshot_version"]
    manifest_path = tmp_path / "runtime_snapshot_manifest.json"
    manifest_path.write_text(json.dumps(current), encoding="utf-8")
    object_store = FakeObjectStore({
        current["object_key"]: b"bad-current",
        manifest_object_key(previous["snapshot_version"]): json.dumps(previous).encode("utf-8"),
        previous["object_key"]: b"bad-previous",
    })
    data_home = tmp_path / "runtime"
    env_path = tmp_path / "github.env"

    result = bootstrap_runtime_data(
        manifest_path=manifest_path,
        data_home=data_home,
        runtime_temp=tmp_path / "runner-temp",
        github_env_path=env_path,
        object_store=object_store,
    )

    assert result["status"] == "FAILED"
    assert result["error"] == "DATA_PLANE_BOOTSTRAP_FAILED"
    assert result["runtime_data_snapshot"]["status"] == "FAILED"
    assert not (data_home / "historical_results.duckdb").exists()
    assert not env_path.exists()


def test_missing_current_object_without_previous_never_reports_success(tmp_path):
    _, manifest, _ = _snapshot(tmp_path, "current")
    manifest_path = tmp_path / "runtime_snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = bootstrap_runtime_data(
        manifest_path=manifest_path,
        data_home=tmp_path / "runtime",
        runtime_temp=tmp_path / "runner-temp",
        object_store=FakeObjectStore(),
    )

    assert result["status"] == "FAILED"
    assert result["runtime_data_snapshot"]["status"] == "FAILED"
