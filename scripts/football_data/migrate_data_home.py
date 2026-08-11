"""Safely copy the legacy worktree cache into the shared Football Data Home.

This command only copies already-created local DuckDB datasets.  It never
downloads, fabricates, or deletes source data.  A destination with different
logical content is rejected rather than overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from .data_home import resolve_football_data_home
from .storage import DatasetNotAvailableError, DuckDBSnapshotStore, HistoricalResultStore


ROOT = Path(__file__).resolve().parents[2]
LEGACY_DATA_HOME = ROOT / ".cache" / "football_data"


class DatasetDigestMismatchError(ValueError):
    code = "DIGEST_MISMATCH"


def _inspect(path: Path, factory: Callable[[Path], Any]) -> dict[str, Any]:
    if not path.exists():
        raise DatasetNotAvailableError(path)
    store = factory(path)
    return {"path": str(path), "record_count": store.count(), "dataset_sha256": store.dataset_digest()}


def _copy_one(
    *,
    source_path: Path,
    destination_path: Path,
    factory: Callable[[Path], Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    if destination_path.exists():
        existing = _inspect(destination_path, factory)
        if (
            existing["record_count"] != expected["record_count"]
            or existing["dataset_sha256"] != expected["dataset_sha256"]
        ):
            raise DatasetDigestMismatchError(
                f"{DatasetDigestMismatchError.code}: destination differs: {destination_path}"
            )
        return {**existing, "action": "already_present"}

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_name(
        f".{destination_path.stem}.{uuid.uuid4().hex}.migration{destination_path.suffix}"
    )
    try:
        shutil.copy2(source_path, temporary_path)
        copied = _inspect(temporary_path, factory)
        if (
            copied["record_count"] != expected["record_count"]
            or copied["dataset_sha256"] != expected["dataset_sha256"]
        ):
            raise DatasetDigestMismatchError(
                f"{DatasetDigestMismatchError.code}: copied dataset differs: {source_path}"
            )
        os.replace(temporary_path, destination_path)
        return {**copied, "path": str(destination_path), "action": "copied"}
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def migrate_data_home(
    *,
    source_root: str | Path = LEGACY_DATA_HOME,
    destination_root: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(source_root)
    destination = Path(destination_root) if destination_root is not None else resolve_football_data_home()
    source_historical_path = source / "historical_results.duckdb"
    source_snapshot_path = source / "team_strength_snapshots.duckdb"
    historical_expected = _inspect(source_historical_path, HistoricalResultStore)
    snapshot_expected = _inspect(source_snapshot_path, DuckDBSnapshotStore)

    historical = _copy_one(
        source_path=source_historical_path,
        destination_path=destination / "historical_results.duckdb",
        factory=HistoricalResultStore,
        expected=historical_expected,
    )
    snapshots = _copy_one(
        source_path=source_snapshot_path,
        destination_path=destination / "team_strength_snapshots.duckdb",
        factory=DuckDBSnapshotStore,
        expected=snapshot_expected,
    )
    return {
        "status": "OK",
        "source_root": str(source),
        "destination_root": str(destination),
        "historical_results": historical,
        "team_strength_snapshots": snapshots,
        "legacy_cache_preserved": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=LEGACY_DATA_HOME)
    parser.add_argument("--destination-root", type=Path)
    args = parser.parse_args(argv)
    try:
        result = migrate_data_home(
            source_root=args.source_root,
            destination_root=args.destination_root,
        )
    except DatasetNotAvailableError as exc:
        print(json.dumps({"status": DatasetNotAvailableError.code, "detail": str(exc)}))
        return 2
    except DatasetDigestMismatchError as exc:
        print(json.dumps({"status": DatasetDigestMismatchError.code, "detail": str(exc)}))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
