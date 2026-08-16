"""Build a clean ID2 external staging store from the verified baseline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .build_openfootball_pilot import load_openfootball_records
from .historical_results import deduplicate_historical_results
from .storage import DuckDBSnapshotStore, HistoricalResultStore


OLD_BENFICA = "team:portugal:benfica"
NEW_BENFICA = "team:portugal:sport-lisboa-e-benfica"
EXPECTED_BASELINE_COUNT = 1554
EXPECTED_BASELINE_DIGEST = "710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e"


def _replace(value: Any) -> Any:
    if isinstance(value, str):
        # Canonical IDs also occur inside immutable composite match/snapshot
        # identities and opponent/source-match lists, so exact-token replacement
        # must cover embedded governed IDs without touching unrelated text.
        return value.replace(OLD_BENFICA, NEW_BENFICA)
    if isinstance(value, list):
        return [_replace(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item) for key, item in value.items()}
    return value


def _rows_with_team(records: list[dict[str, Any]], team_id: str) -> list[dict[str, Any]]:
    return [
        row for row in records
        if row.get("home_team_id") == team_id or row.get("away_team_id") == team_id
    ]


def _source_rows_with_raw_team(records: list[dict[str, Any]], raw_name: str) -> list[dict[str, Any]]:
    return [row for row in records if raw_name in {row.get("raw_home_team"), row.get("raw_away_team")}]


def _append_snapshots_in_one_transaction(store: DuckDBSnapshotStore, rows: list[dict[str, Any]]) -> None:
    # DuckDBSnapshotStore has no public bulk-insert API; this local transaction
    # uses its existing schema/connection only and does not alter store semantics.
    connection = store._connect(read_only=False)
    try:
        connection.execute("BEGIN TRANSACTION")
        for row in rows:
            identity = str(row.get("snapshot_id") or "")
            if not identity:
                raise ValueError("immutable snapshot requires snapshot_id")
            digest, encoded = HistoricalResultStore._encoded(row)
            connection.execute(
                """INSERT INTO team_strength_snapshots
                   (snapshot_id, snapshot_digest, target_match_id, team_id, as_of_at,
                    input_dataset_digest, builder_version, snapshot_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [identity, digest, row.get("target_match_id"), row.get("team_id"), row.get("as_of_at"),
                 row.get("input_dataset_digest"), row.get("builder_version"), encoded],
            )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _preflight(
    *,
    baseline_history: list[dict[str, Any]],
    baseline_snapshots: list[dict[str, Any]],
    baseline_digest: str,
    source_rows: list[dict[str, Any]],
    cutoff: str,
) -> dict[str, Any]:
    """Run every validation that can fail before staging output is created."""
    if len(baseline_history) != EXPECTED_BASELINE_COUNT or baseline_digest != EXPECTED_BASELINE_DIGEST:
        raise ValueError(f"authoritative baseline mismatch: count={len(baseline_history)} digest={baseline_digest}")
    cutoff_dt = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    source_after_cutoff = [
        row for row in source_rows
        if datetime.fromisoformat(str(row["kickoff_at"]).replace("Z", "+00:00")) >= cutoff_dt
    ]
    if source_after_cutoff:
        raise ValueError(f"source rows at/after cutoff: {len(source_after_cutoff)}")
    dedup = deduplicate_historical_results(source_rows)
    if dedup.duplicates_collapsed or dedup.possible_duplicates or dedup.conflicts:
        raise ValueError(
            f"source integrity failure: duplicates={dedup.duplicates_collapsed} "
            f"possible_duplicates={dedup.possible_duplicates} conflicts={dedup.conflicts}"
        )
    for row in source_rows:
        for field in ("raw_home_team", "raw_away_team", "raw_competition", "raw_season", "provenance", "source_file", "raw_sha256"):
            if field not in row and field not in row.get("provenance", {}):
                raise ValueError(f"source row missing required provenance field: {field}")
    migrated_history = [_replace(row) for row in baseline_history]
    migrated_snapshots = [_replace(row) for row in baseline_snapshots]
    old_id_occurrences = sum(json.dumps(row, ensure_ascii=False).count(OLD_BENFICA) for row in migrated_history + migrated_snapshots)
    if old_id_occurrences:
        raise ValueError(f"old Benfica ID remains after canonicalization: {old_id_occurrences}")
    if not any(NEW_BENFICA in json.dumps(row, ensure_ascii=False) for row in migrated_history + migrated_snapshots):
        raise ValueError("authoritative Benfica canonicalization produced no authoritative new ID")
    return {
        "source_after_cutoff": source_after_cutoff,
        "dedup": dedup,
        "migrated_history": migrated_history,
        "migrated_snapshots": migrated_snapshots,
        "old_id_occurrences": old_id_occurrences,
    }


def _baseline_preflight(
    *, baseline_history: list[dict[str, Any]], baseline_snapshots: list[dict[str, Any]], baseline_digest: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(baseline_history) != EXPECTED_BASELINE_COUNT or baseline_digest != EXPECTED_BASELINE_DIGEST:
        raise ValueError(f"authoritative baseline mismatch: count={len(baseline_history)} digest={baseline_digest}")
    migrated_history = [_replace(row) for row in baseline_history]
    migrated_snapshots = [_replace(row) for row in baseline_snapshots]
    old_id_occurrences = sum(json.dumps(row, ensure_ascii=False).count(OLD_BENFICA) for row in migrated_history + migrated_snapshots)
    if old_id_occurrences:
        raise ValueError(f"old Benfica ID remains after canonicalization: {old_id_occurrences}")
    if not any(NEW_BENFICA in json.dumps(row, ensure_ascii=False) for row in migrated_history + migrated_snapshots):
        raise ValueError("authoritative Benfica canonicalization produced no authoritative new ID")
    return migrated_history, migrated_snapshots


def build(*, baseline: Path, raw_root: Path, manifest: Path, identities: Path, output: Path, cutoff: str) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite staging directory: {output}")
    baseline_history = HistoricalResultStore(baseline / "historical_results.duckdb").records()
    baseline_snapshots = DuckDBSnapshotStore(baseline / "team_strength_snapshots.duckdb").records()
    baseline_store = HistoricalResultStore(baseline / "historical_results.duckdb")
    baseline_digest = baseline_store.dataset_digest()
    _baseline_preflight(
        baseline_history=baseline_history, baseline_snapshots=baseline_snapshots, baseline_digest=baseline_digest,
    )
    all_source_rows = load_openfootball_records(
        raw_root,
        manifest_path=manifest,
        identity_path=identities,
    )
    source_rows = all_source_rows
    preflight = _preflight(
        baseline_history=baseline_history, baseline_snapshots=baseline_snapshots,
        baseline_digest=baseline_digest, source_rows=source_rows, cutoff=cutoff,
    )
    source_after_cutoff = preflight["source_after_cutoff"]
    dedup = preflight["dedup"]
    migrated_history = preflight["migrated_history"]
    migrated_snapshots = preflight["migrated_snapshots"]
    old_id_occurrences = preflight["old_id_occurrences"]
    output.mkdir(parents=True)
    history = HistoricalResultStore(output / "historical_results.duckdb")
    snapshots = DuckDBSnapshotStore(output / "team_strength_snapshots.duckdb")
    history.append_many(migrated_history)
    _append_snapshots_in_one_transaction(snapshots, migrated_snapshots)
    history.append_many(source_rows)
    all_history = history.records()
    all_snapshots = snapshots.records()
    old_id_occurrences = sum(json.dumps(row, ensure_ascii=False).count(OLD_BENFICA) for row in all_history + all_snapshots)
    if old_id_occurrences:
        raise ValueError(f"old Benfica ID remains in staged data: {old_id_occurrences}")
    hearts_raw = _source_rows_with_raw_team(source_rows, "Heart of Midlothian (SCO)")
    hearts_eligible = [row for row in hearts_raw if row.get("eligible_for_team_strength") is True]
    target_cutoff = datetime.fromisoformat("2026-08-13T18:45:00+00:00")
    hearts_europa_eligible_before_target = [
        row for row in hearts_eligible
        if row.get("competition_id") == "competition:uefa-europa-league"
        and datetime.fromisoformat(str(row["kickoff_at"]).replace("Z", "+00:00")) < target_cutoff
    ]
    manifest_value = {
        "schema": "id2_v3_staging_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "baseline": {
            "root": str(baseline),
            "historical_count": len(baseline_history),
            "historical_digest": baseline_digest,
            "snapshot_count": len(baseline_snapshots),
            "snapshot_digest": DuckDBSnapshotStore(baseline / "team_strength_snapshots.duckdb").dataset_digest(),
        },
        "canonicalization": {"old_id": OLD_BENFICA, "new_id": NEW_BENFICA, "old_occurrences_after": old_id_occurrences},
        "europa_source": {
            "source_manifest": str(manifest),
            "identity_evidence": str(identities),
            "cutoff_at": cutoff,
            "inserted_count": len(source_rows),
            "heart_raw_rows": len(hearts_raw),
            "heart_team_strength_eligible_rows": len(hearts_eligible),
            "heart_europa_eligible_before_target": len(hearts_europa_eligible_before_target),
            "minimum_history": 5,
            "history_gate_status": "INSUFFICIENT_HISTORY" if len(hearts_europa_eligible_before_target) < 5 else "PASS",
            "heart_raw_kickoffs": sorted(row.get("kickoff_at") for row in hearts_raw),
            "source_resolved_count": sum(row.get("resolution_status") == "resolved" for row in source_rows),
            "source_team_strength_eligible_count": sum(row.get("eligible_for_team_strength") is True for row in source_rows),
            "duplicates_collapsed": dedup.duplicates_collapsed,
            "possible_duplicates": dedup.possible_duplicates,
            "conflicts": dedup.conflicts,
            "source_rows_at_or_after_cutoff": len(source_after_cutoff),
        },
        "final": {
            "historical_count": history.count(),
            "historical_digest": history.dataset_digest(),
            "snapshot_count": snapshots.count(),
            "snapshot_digest": snapshots.dataset_digest(),
            "old_benfica_occurrences": old_id_occurrences,
            "database_readable": HistoricalResultStore(output / "historical_results.duckdb").count() == history.count()
            and DuckDBSnapshotStore(output / "team_strength_snapshots.duckdb").count() == snapshots.count()
            and HistoricalResultStore(output / "historical_results.duckdb").dataset_digest() == history.dataset_digest()
            and DuckDBSnapshotStore(output / "team_strength_snapshots.duckdb").dataset_digest() == snapshots.dataset_digest(),
        },
    }
    (output / "id2_staging_manifest.json").write_text(
        json.dumps(manifest_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
