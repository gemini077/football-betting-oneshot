"""Verify shared Football Data Home datasets against tracked manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .data_home import historical_results_path, resolve_football_data_home, team_strength_snapshots_path
from .storage import DatasetNotAvailableError, DuckDBSnapshotStore, HistoricalResultStore


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_ROOT = ROOT / "data" / "football_data" / "manifests"


def _verify_one(
    *,
    name: str,
    path: Path,
    manifest_path: Path,
    factory: Callable[[Path], Any],
) -> dict[str, Any]:
    if not path.exists() or not manifest_path.exists():
        return {
            "status": DatasetNotAvailableError.code,
            "path": str(path),
            "manifest": str(manifest_path),
        }
    try:
        store = factory(path)
        actual_count = store.count()
        actual_digest = store.dataset_digest()
    except (DatasetNotAvailableError, OSError, ValueError) as exc:
        return {"status": DatasetNotAvailableError.code, "path": str(path), "detail": str(exc)}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_count = manifest.get("record_count")
    expected_digest = manifest.get("dataset_sha256")
    status = "OK" if (actual_count == expected_count and actual_digest == expected_digest) else "DIGEST_MISMATCH"
    return {
        "status": status,
        "path": str(path),
        "manifest": str(manifest_path),
        "expected_record_count": expected_count,
        "actual_record_count": actual_count,
        "expected_dataset_sha256": expected_digest,
        "actual_dataset_sha256": actual_digest,
    }


def verify_data_home(
    *,
    data_home: str | Path | None = None,
    manifest_root: str | Path = DEFAULT_MANIFEST_ROOT,
) -> dict[str, Any]:
    home = Path(data_home) if data_home is not None else resolve_football_data_home()
    manifests = Path(manifest_root)
    datasets = {
        "historical_results": _verify_one(
            name="historical_results",
            path=historical_results_path(home),
            manifest_path=manifests / "historical_results.dataset.json",
            factory=HistoricalResultStore,
        ),
        "team_strength": _verify_one(
            name="team_strength",
            path=team_strength_snapshots_path(home),
            manifest_path=manifests / "team_strength.dataset.json",
            factory=DuckDBSnapshotStore,
        ),
    }
    statuses = {item["status"] for item in datasets.values()}
    status = "OK" if statuses == {"OK"} else ("DIGEST_MISMATCH" if "DIGEST_MISMATCH" in statuses else "DATASET_NOT_AVAILABLE")
    return {"status": status, "data_home": str(home), "datasets": datasets}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--manifest-root", type=Path, default=DEFAULT_MANIFEST_ROOT)
    args = parser.parse_args(argv)
    result = verify_data_home(data_home=args.data_home, manifest_root=args.manifest_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"OK": 0, "DATASET_NOT_AVAILABLE": 2, "DIGEST_MISMATCH": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
