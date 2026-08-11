"""Migrate local legacy JSON bulk data into ignored DuckDB datasets.

The command never downloads third-party data and never fabricates missing
records. It can migrate a local legacy JSON ledger/snapshot directory when
present; a fresh checkout without those captures exits with
``DATASET_NOT_AVAILABLE`` and leaves the tracked manifests as the rebuild
instructions and provenance boundary.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .contracts import validate_record
from .data_home import resolve_football_data_home
from .storage import (
    DatasetNotAvailableError,
    DuckDBSnapshotStore,
    HistoricalResultStore,
    SnapshotStore,
    content_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEGACY_LEDGER = ROOT / "data" / "football_data" / "historical_result_ledger"
DEFAULT_LEGACY_SNAPSHOTS = ROOT / "data" / "football_data" / "team_strength_snapshots"
DEFAULT_MANIFEST_ROOT = ROOT / "data" / "football_data" / "manifests"
SOURCE_MANIFESTS = {
    "p0_p1_source_manifest": ROOT / "data" / "football_data" / "p0_p1_source_manifest.json",
    "openfootball_source_manifest": ROOT / "data" / "football_data" / "openfootball" / "source_manifest.json",
    "football_data_uk_source_manifest": ROOT / "data" / "football_data" / "football_data_uk" / "source_manifest.json",
    "football_data_uk_demand_manifest": ROOT / "data" / "football_data" / "football_data_uk" / "demand_source_manifest.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_legacy_json_records(
    root: Path,
    *,
    contract_kind: str,
    content_addressed: bool = True,
) -> list[dict[str, Any]]:
    if not root.exists():
        raise DatasetNotAvailableError(root)
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if content_addressed:
            value = SnapshotStore(root).get(path.stem)
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
        validate_record(contract_kind, value)
        records.append(value)
    if not records:
        raise DatasetNotAvailableError(root)
    return records


def _source_manifest_hashes() -> dict[str, str]:
    output: dict[str, str] = {}
    for name, path in SOURCE_MANIFESTS.items():
        if path.exists():
            output[name] = content_sha256(json.loads(path.read_text(encoding="utf-8")))
    return output


def _time_bounds(records: Iterable[dict[str, Any]], field: str) -> tuple[str | None, str | None]:
    values = sorted(str(record.get(field)) for record in records if record.get(field))
    return (values[0], values[-1]) if values else (None, None)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def migrate(
    *,
    legacy_ledger_root: Path = DEFAULT_LEGACY_LEDGER,
    legacy_snapshot_root: Path = DEFAULT_LEGACY_SNAPSHOTS,
    output_root: Path | None = None,
    manifest_root: Path = DEFAULT_MANIFEST_ROOT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated = generated_at or _now()
    output_root = Path(output_root) if output_root is not None else resolve_football_data_home()
    historical_records = _load_legacy_json_records(legacy_ledger_root, contract_kind="historical_match_result")
    snapshot_records = _load_legacy_json_records(
        legacy_snapshot_root,
        contract_kind="team_strength_snapshot",
        content_addressed=False,
    )

    historical_store = HistoricalResultStore(output_root / "historical_results.duckdb")
    historical_store.append_many(historical_records)
    snapshot_store = DuckDBSnapshotStore(output_root / "team_strength_snapshots.duckdb")
    for snapshot in snapshot_records:
        snapshot_store.put(snapshot)

    kickoff_min, kickoff_max = _time_bounds(historical_records, "kickoff_at")
    as_of_min, as_of_max = _time_bounds(snapshot_records, "as_of_at")
    source_hashes = _source_manifest_hashes()
    historical_manifest = {
        "dataset_version": "historical_results.duckdb.v1",
        "contract_version": "historical_match_result.v1",
        "record_count": historical_store.count(),
        "eligible_record_count": sum(row.get("eligible_for_team_strength") is True for row in historical_records),
        "min_kickoff_at": kickoff_min,
        "max_kickoff_at": kickoff_max,
        "source_manifest_hashes": source_hashes,
        "dataset_sha256": historical_store.dataset_digest(),
        "builder_version": "rebuild_historical_store.v1",
        "parser_versions": {
            "historical_result_contract": "historical_match_result.v1",
            "legacy_json_migration": "rebuild_historical_store.v1",
        },
        "generated_at": generated,
        "storage_format": "duckdb",
        "storage_location_policy": "${FOOTBALL_DATA_HOME}/historical_results.duckdb (shared local analytical store)",
        "source_location_policy": "source manifests and captured evidence references; raw third-party files are not committed",
    }
    snapshot_manifest = {
        "dataset_version": "team_strength_snapshots.duckdb.v1",
        "contract_version": "team_strength_snapshot.v1",
        "record_count": snapshot_store.count(),
        "min_as_of_at": as_of_min,
        "max_as_of_at": as_of_max,
        "source_manifest_hashes": source_hashes,
        "input_historical_dataset_sha256": historical_store.dataset_digest(),
        "dataset_sha256": snapshot_store.dataset_digest(),
        "builder_version": "team-strength-builder.v2-duckdb",
        "parser_versions": {"team_strength_builder": "team-strength-builder.v2-duckdb"},
        "generated_at": generated,
        "storage_format": "duckdb",
        "storage_location_policy": "${FOOTBALL_DATA_HOME}/team_strength_snapshots.duckdb (shared local analytical store)",
        "immutability_policy": "snapshot_id is primary key; conflicting content is rejected",
    }
    _write_json(manifest_root / "historical_results.dataset.json", historical_manifest)
    _write_json(manifest_root / "team_strength.dataset.json", snapshot_manifest)
    return {
        "status": "OK",
        "historical": historical_manifest,
        "snapshots": snapshot_manifest,
        "output_root": str(output_root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-ledger-root", type=Path, default=DEFAULT_LEGACY_LEDGER)
    parser.add_argument("--legacy-snapshot-root", type=Path, default=DEFAULT_LEGACY_SNAPSHOTS)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--manifest-root", type=Path, default=DEFAULT_MANIFEST_ROOT)
    parser.add_argument("--generated-at")
    args = parser.parse_args(argv)
    try:
        result = migrate(
            legacy_ledger_root=args.legacy_ledger_root,
            legacy_snapshot_root=args.legacy_snapshot_root,
            output_root=args.output_root,
            manifest_root=args.manifest_root,
            generated_at=args.generated_at,
        )
    except DatasetNotAvailableError as exc:
        print(json.dumps({"status": DatasetNotAvailableError.code, "detail": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
