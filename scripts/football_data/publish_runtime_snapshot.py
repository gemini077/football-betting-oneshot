#!/usr/bin/env python3
"""Publish the authoritative local historical DuckDB as an immutable snapshot."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

try:  # ``python -m scripts.football_data.publish_runtime_snapshot``
    from .data_home import historical_results_path, resolve_football_data_home
    from .runtime_snapshot import (
        DEFAULT_BUILDER_VERSION,
        EXPECTED_DATASET_SHA256,
        EXPECTED_RECORD_COUNT,
        ObjectNotFound,
        ObjectStore,
        S3ObjectStore,
        SnapshotConfig,
        SnapshotConfigurationError,
        SnapshotError,
        SnapshotManifestError,
        SnapshotVerificationError,
        atomic_write_json,
        build_manifest,
        file_sha256,
        load_manifest,
        manifest_object_key,
        source_manifest_hashes,
        temporary_directory,
        verify_artifact,
        verify_duckdb_dataset,
    )
    from .verify_data_home import verify_data_home
except ImportError:  # pragma: no cover - keeps direct script execution usable
    from football_data.data_home import historical_results_path, resolve_football_data_home
    from football_data.runtime_snapshot import (
        DEFAULT_BUILDER_VERSION,
        EXPECTED_DATASET_SHA256,
        EXPECTED_RECORD_COUNT,
        ObjectNotFound,
        ObjectStore,
        S3ObjectStore,
        SnapshotConfig,
        SnapshotConfigurationError,
        SnapshotError,
        SnapshotManifestError,
        SnapshotVerificationError,
        atomic_write_json,
        build_manifest,
        file_sha256,
        load_manifest,
        manifest_object_key,
        source_manifest_hashes,
        temporary_directory,
        verify_artifact,
        verify_duckdb_dataset,
    )
    from football_data.verify_data_home import verify_data_home


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_MANIFEST_PATH = ROOT / "data" / "football_data" / "runtime_snapshot_manifest.json"
DEFAULT_AUTHORITATIVE_MANIFEST_PATH = ROOT / "data" / "football_data" / "manifests" / "historical_results.dataset.json"


def _read_source_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotManifestError("authoritative source manifest is unreadable") from error
    if not isinstance(value, dict):
        raise SnapshotManifestError("authoritative source manifest must be an object")
    return value


def verify_authoritative_local_dataset(
    *,
    data_home: str | Path,
    authoritative_manifest_path: str | Path = DEFAULT_AUTHORITATIVE_MANIFEST_PATH,
) -> dict[str, Any]:
    """Run the existing data-home verification plus the fixed acceptance pin."""

    home = Path(data_home)
    manifest_path = Path(authoritative_manifest_path)
    source_payload = _read_source_manifest(manifest_path)
    if (
        source_payload.get("record_count") != EXPECTED_RECORD_COUNT
        or source_payload.get("dataset_sha256") != EXPECTED_DATASET_SHA256
    ):
        raise SnapshotVerificationError(code="AUTHORITATIVE_VERIFICATION_FAILED")
    try:
        verification = verify_data_home(data_home=home, manifest_root=manifest_path.parent)
    except Exception as error:
        raise SnapshotVerificationError(code="AUTHORITATIVE_VERIFICATION_FAILED") from error
    history = (verification.get("datasets") or {}).get("historical_results") or {}
    if history.get("status") != "OK":
        raise SnapshotVerificationError(code="AUTHORITATIVE_VERIFICATION_FAILED")
    result = verify_duckdb_dataset(
        historical_results_path(home),
        expected_count=EXPECTED_RECORD_COUNT,
        expected_digest=EXPECTED_DATASET_SHA256,
    )
    return {"status": "OK", **result}


def _ensure_immutable_object(
    object_store: ObjectStore,
    *,
    key: str,
    source: Path,
    expected_artifact_sha256: str,
    temporary_root: Path,
) -> str:
    """Put once, or accept an already-present byte-identical immutable object."""

    try:
        object_store.head_object(key)
    except ObjectNotFound:
        object_store.put_file(key, source, content_type="application/vnd.duckdb")
        return "UPLOADED"

    existing = temporary_root / "existing.duckdb"
    object_store.download(key, existing)
    try:
        verify_artifact(existing, expected_artifact_sha256)
    except SnapshotVerificationError as error:
        raise SnapshotVerificationError(code="IMMUTABLE_OBJECT_CONFLICT") from error
    return "EXISTING_MATCH"


def publish_snapshot(
    *,
    data_home: str | Path | None = None,
    runtime_manifest_path: str | Path = DEFAULT_RUNTIME_MANIFEST_PATH,
    authoritative_manifest_path: str | Path = DEFAULT_AUTHORITATIVE_MANIFEST_PATH,
    object_store: ObjectStore | None = None,
    config: SnapshotConfig | None = None,
    now: datetime | str | None = None,
    temp_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify, upload, read back and finally advance the tracked runtime pin."""

    home = Path(data_home) if data_home is not None else resolve_football_data_home()
    database_path = historical_results_path(home)
    local = verify_authoritative_local_dataset(
        data_home=home,
        authoritative_manifest_path=authoritative_manifest_path,
    )
    artifact_sha256 = file_sha256(database_path)
    source_payload = _read_source_manifest(Path(authoritative_manifest_path))
    builder_version = str(source_payload.get("builder_version") or DEFAULT_BUILDER_VERSION)
    previous_snapshot_version: str | None = None
    runtime_path = Path(runtime_manifest_path)
    if runtime_path.exists():
        previous_snapshot_version = load_manifest(runtime_path)["snapshot_version"]
    manifest = build_manifest(
        dataset_sha256=local["dataset_sha256"],
        record_count=local["record_count"],
        artifact_sha256=artifact_sha256,
        source_manifest_hashes=source_manifest_hashes(source_payload),
        builder_version=builder_version,
        previous_snapshot_version=previous_snapshot_version,
        now=now,
    )

    store = object_store
    if store is None:
        store = S3ObjectStore.from_config(config or SnapshotConfig.from_environment(role="PUBLISH"))

    with temporary_directory(temp_root) as temporary:
        temporary_root = Path(temporary)
        upload_status = _ensure_immutable_object(
            store,
            key=manifest["object_key"],
            source=database_path,
            expected_artifact_sha256=artifact_sha256,
            temporary_root=temporary_root,
        )
        head = store.head_object(manifest["object_key"])
        content_length = head.get("ContentLength") if isinstance(head, Mapping) else None
        if content_length is not None and int(content_length) != database_path.stat().st_size:
            raise SnapshotVerificationError(code="ARTIFACT_SIZE_MISMATCH")

        fresh_copy = temporary_root / "fresh.duckdb"
        store.download(manifest["object_key"], fresh_copy)
        verify_artifact(fresh_copy, artifact_sha256)
        verify_duckdb_dataset(
            fresh_copy,
            expected_count=manifest["record_count"],
            expected_digest=manifest["dataset_sha256"],
        )

        sidecar = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        store.put_bytes(
            manifest_object_key(manifest["snapshot_version"]),
            sidecar,
            content_type="application/json",
        )
        atomic_write_json(runtime_path, manifest)

    return {
        "status": "OBJECT_SNAPSHOT_VERIFIED",
        "snapshot_version": manifest["snapshot_version"],
        "object_key": manifest["object_key"],
        "artifact_sha256": artifact_sha256,
        "dataset_sha256": manifest["dataset_sha256"],
        "record_count": manifest["record_count"],
        "object_upload": upload_status,
        "runtime_manifest_path": str(runtime_path),
    }


def interactive_config(
    *,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] = getpass.getpass,
) -> SnapshotConfig:
    """Collect local publisher settings without ever echoing applicationKey."""

    return SnapshotConfig(
        endpoint_url=input_fn("endpoint: ").strip(),
        bucket=input_fn("bucket: ").strip(),
        region=input_fn("region: ").strip(),
        access_key_id=input_fn("keyID: ").strip(),
        secret_access_key=secret_input_fn("applicationKey: "),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST_PATH)
    parser.add_argument("--authoritative-manifest", type=Path, default=DEFAULT_AUTHORITATIVE_MANIFEST_PATH)
    parser.add_argument("--now")
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args(argv)

    try:
        config = interactive_config() if args.interactive else SnapshotConfig.from_environment(role="PUBLISH")
        result = publish_snapshot(
            data_home=args.data_home,
            runtime_manifest_path=args.runtime_manifest,
            authoritative_manifest_path=args.authoritative_manifest,
            config=config,
            now=args.now,
            temp_root=args.temp_root,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except SnapshotConfigurationError as error:
        if error.code == "LOCAL_PUBLISHER_INPUT_REQUIRED":
            print("LOCAL_PUBLISHER_INPUT_REQUIRED")
            print("python -m scripts.football_data.publish_runtime_snapshot --interactive")
        else:
            print(json.dumps({"status": error.code}, ensure_ascii=False))
        return 2
    except SnapshotError as error:
        print(json.dumps({"status": error.code}, ensure_ascii=False))
        return 1
    except (KeyboardInterrupt, EOFError):
        print(json.dumps({"status": "LOCAL_PUBLISHER_INPUT_REQUIRED"}, ensure_ascii=False))
        return 2
    except Exception:
        # Never echo transport/library exception text: it may contain secret material.
        print(json.dumps({"status": "PUBLISH_FAILED"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
