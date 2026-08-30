#!/usr/bin/env python3
"""Bootstrap an exact private historical snapshot into an isolated runtime home."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # ``python -m scripts.football_data.bootstrap_runtime_data``
    from .data_home import historical_results_path
    from .runtime_snapshot import (
        ObjectNotFound,
        ObjectStore,
        S3ObjectStore,
        SnapshotConfig,
        SnapshotError,
        SnapshotManifestError,
        SnapshotVerificationError,
        atomic_install_verified,
        load_manifest,
        manifest_object_key,
        read_json_object,
        temporary_directory,
        verify_snapshot_file,
    )
except ImportError:  # pragma: no cover - keeps direct script execution usable
    from football_data.data_home import historical_results_path
    from football_data.runtime_snapshot import (
        ObjectNotFound,
        ObjectStore,
        S3ObjectStore,
        SnapshotConfig,
        SnapshotError,
        SnapshotManifestError,
        SnapshotVerificationError,
        atomic_install_verified,
        load_manifest,
        manifest_object_key,
        read_json_object,
        temporary_directory,
        verify_snapshot_file,
    )


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_MANIFEST_PATH = ROOT / "data" / "football_data" / "runtime_snapshot_manifest.json"
RUNTIME_SNAPSHOT_HEALTH_ENV = "FOOTBALL_DATA_RUNTIME_SNAPSHOT_HEALTH"


def default_runtime_data_home() -> Path:
    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    root = Path(runner_temp) if runner_temp else Path(tempfile.gettempdir())
    return root / "football-data" / "runtime"


def _bootstrap_one(object_store: ObjectStore, manifest: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    object_store.head_object(str(manifest["object_key"]))
    object_store.download(str(manifest["object_key"]), destination)
    verification = verify_snapshot_file(destination, manifest)
    return {"manifest": dict(manifest), **verification}


def _load_previous_manifest(
    object_store: ObjectStore,
    *,
    previous_snapshot_version: str,
    destination: Path,
) -> dict[str, Any]:
    key = manifest_object_key(previous_snapshot_version)
    object_store.head_object(key)
    object_store.download(key, destination)
    manifest = read_json_object(destination)
    if manifest["snapshot_version"] != previous_snapshot_version:
        raise SnapshotManifestError("previous manifest version does not match the pinned version")
    return manifest


def _health_payload(
    *,
    status: str,
    manifest: Mapping[str, Any] | None,
    bootstrap_at: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "snapshot_version": manifest.get("snapshot_version") if manifest else None,
        "dataset_sha256": manifest.get("dataset_sha256") if manifest else None,
        "record_count": manifest.get("record_count") if manifest else None,
        "bootstrap_at": bootstrap_at,
    }


def _write_health(path: Path | None, payload: Mapping[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _export_data_home(path: Path | None, data_home: Path, health_path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"FOOTBALL_DATA_HOME={data_home.resolve()}\n")
        if health_path is not None:
            handle.write(f"{RUNTIME_SNAPSHOT_HEALTH_ENV}={health_path.resolve()}\n")


def bootstrap_runtime_data(
    *,
    manifest_path: str | Path = DEFAULT_RUNTIME_MANIFEST_PATH,
    data_home: str | Path | None = None,
    runtime_temp: str | Path | None = None,
    github_env_path: str | Path | None = None,
    health_path: str | Path | None = None,
    object_store: ObjectStore | None = None,
    config: SnapshotConfig | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Download and verify current, then exact previous, before atomic install."""

    bootstrap_at = _timestamp(now)
    target_home = Path(data_home) if data_home is not None else default_runtime_data_home()
    health_file = Path(health_path) if health_path is not None else None
    env_file = Path(github_env_path) if github_env_path is not None else None
    attempts: list[dict[str, Any]] = []

    try:
        current = load_manifest(manifest_path)
    except SnapshotError as error:
        payload = _failure_payload(bootstrap_at, attempts, error.code)
        _write_health(health_file, payload["runtime_data_snapshot"])
        return payload

    try:
        store = object_store or S3ObjectStore.from_config(config or SnapshotConfig.from_environment(role="RUNTIME"))
    except SnapshotError as error:
        payload = _failure_payload(bootstrap_at, attempts, error.code)
        _write_health(health_file, payload["runtime_data_snapshot"])
        return payload

    runtime_base = Path(runtime_temp) if runtime_temp is not None else Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    runtime_base.mkdir(parents=True, exist_ok=True)

    with temporary_directory(runtime_base) as temporary:
        temporary_root = Path(temporary)
        candidates: list[tuple[str, dict[str, Any]]] = [("CURRENT", current)]
        for label, manifest in candidates:
            downloaded = temporary_root / f"{label.lower()}.duckdb"
            try:
                verified = _bootstrap_one(store, manifest, downloaded)
                installed = atomic_install_verified(
                    downloaded,
                    target_home,
                    expected_artifact_sha256=manifest["artifact_sha256"],
                )
                # The install is copied into the isolated home only after the
                # downloaded file has passed all artifact and DuckDB checks.
                verify_snapshot_file(installed, manifest)
                status = "READY"
                health = _health_payload(status=status, manifest=manifest, bootstrap_at=bootstrap_at)
                _write_health(health_file, health)
                _export_data_home(env_file, target_home, health_file)
                return {
                    "status": status,
                    "error": None,
                    "snapshot_version": manifest["snapshot_version"],
                    "dataset_sha256": verified["dataset_sha256"],
                    "record_count": verified["record_count"],
                    "data_home": str(target_home.resolve()),
                    "bootstrap_at": bootstrap_at,
                    "attempts": attempts + [{"snapshot_version": manifest["snapshot_version"], "status": "VERIFIED"}],
                    "runtime_data_snapshot": health,
                }
            except SnapshotError as error:
                attempts.append({"snapshot_version": manifest["snapshot_version"], "status": "FAILED", "reason": error.code})
            except Exception:
                attempts.append({"snapshot_version": manifest["snapshot_version"], "status": "FAILED", "reason": "SNAPSHOT_ATTEMPT_FAILED"})

        previous_version = current.get("previous_snapshot_version")
        if previous_version:
            previous_manifest_path = temporary_root / "previous-manifest.json"
            try:
                previous = _load_previous_manifest(
                    store,
                    previous_snapshot_version=previous_version,
                    destination=previous_manifest_path,
                )
                downloaded = temporary_root / "previous.duckdb"
                verified = _bootstrap_one(store, previous, downloaded)
                installed = atomic_install_verified(
                    downloaded,
                    target_home,
                    expected_artifact_sha256=previous["artifact_sha256"],
                )
                verify_snapshot_file(installed, previous)
                status = "DEGRADED_LAST_KNOWN_GOOD"
                health = _health_payload(status=status, manifest=previous, bootstrap_at=bootstrap_at)
                _write_health(health_file, health)
                _export_data_home(env_file, target_home, health_file)
                return {
                    "status": status,
                    "error": None,
                    "snapshot_version": previous["snapshot_version"],
                    "dataset_sha256": verified["dataset_sha256"],
                    "record_count": verified["record_count"],
                    "data_home": str(target_home.resolve()),
                    "bootstrap_at": bootstrap_at,
                    "attempts": attempts + [{"snapshot_version": previous["snapshot_version"], "status": "VERIFIED"}],
                    "runtime_data_snapshot": health,
                }
            except SnapshotError as error:
                attempts.append({"snapshot_version": str(previous_version), "status": "FAILED", "reason": error.code})
            except Exception:
                attempts.append({"snapshot_version": str(previous_version), "status": "FAILED", "reason": "SNAPSHOT_ATTEMPT_FAILED"})

    payload = _failure_payload(bootstrap_at, attempts, "DATA_PLANE_BOOTSTRAP_FAILED")
    _write_health(health_file, payload["runtime_data_snapshot"])
    return payload


def _timestamp(value: datetime | str | None) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now(timezone.utc)
    else:
        parsed = value or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _failure_payload(bootstrap_at: str, attempts: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    health = _health_payload(status="FAILED", manifest=None, bootstrap_at=bootstrap_at)
    return {
        "status": "FAILED",
        "error": "DATA_PLANE_BOOTSTRAP_FAILED" if reason != "GITHUB_RUNTIME_CONFIG_MISSING" else reason,
        "snapshot_version": None,
        "dataset_sha256": None,
        "record_count": None,
        "bootstrap_at": bootstrap_at,
        "attempts": attempts,
        "runtime_data_snapshot": health,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST_PATH)
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--runtime-temp", type=Path)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--health-path", type=Path)
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    result = bootstrap_runtime_data(
        manifest_path=args.manifest,
        data_home=args.data_home,
        runtime_temp=args.runtime_temp,
        github_env_path=args.github_env,
        health_path=args.health_path,
        now=args.now,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"READY", "DEGRADED_LAST_KNOWN_GOOD"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
