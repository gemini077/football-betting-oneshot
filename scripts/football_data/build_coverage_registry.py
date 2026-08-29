"""Build the HC-AUTO-1 registry and audit existing daily fixture snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The existing script modules support both direct CLI imports and package
# imports; expose the repository's scripts directory for the latter path.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from prediction_universe import load_prediction_universe
except ImportError:  # package imports used by tests
    from scripts.prediction_universe import load_prediction_universe

try:
    from .coverage_gate import ExactCoverageIdentityResolver, audit_fixture_set
    from .coverage_registry import (
        DEFAULT_REGISTRY_PATH,
        CoverageRegistryBuilder,
        write_coverage_registry,
    )
    from .storage import HistoricalResultStore
except ImportError:  # direct script invocation
    from football_data.coverage_gate import ExactCoverageIdentityResolver, audit_fixture_set
    from football_data.coverage_registry import (
        DEFAULT_REGISTRY_PATH,
        CoverageRegistryBuilder,
        write_coverage_registry,
    )
    from football_data.storage import HistoricalResultStore


DEFAULT_AUDIT_PATH = PROJECT_ROOT / "data" / "football_data" / "hc_auto_1" / "daily_fixture_audit.json"
DEFAULT_UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_audit(
    registry: dict[str, Any],
    *,
    dates: list[str],
    universe_root: Path,
    historical_records: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    resolver = ExactCoverageIdentityResolver()
    audits: list[dict[str, Any]] = []
    for business_date in dates:
        snapshot = load_prediction_universe(business_date, universe_root)
        fixtures = snapshot.get("fixtures", []) if isinstance(snapshot, dict) else []
        audit = audit_fixture_set(
            fixtures if isinstance(fixtures, list) else [],
            registry,
            historical_records=historical_records,
            identity_resolver=resolver,
            now=now,
        )
        audits.append({
            "business_date": business_date,
            "snapshot_path": str(universe_root / f"{business_date}.json"),
            "snapshot_status": snapshot.get("status") if isinstance(snapshot, dict) else "MISSING",
            "snapshot_source": snapshot.get("source") if isinstance(snapshot, dict) else None,
            "snapshot_fetched_at": snapshot.get("fetched_at") if isinstance(snapshot, dict) else None,
            "fixture_count": len(fixtures) if isinstance(fixtures, list) else 0,
            "audit": audit,
        })
    return {
        "contract_version": "hc_auto_1.daily_fixture_audit.v1",
        "generated_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "registry_digest": registry.get("registry_digest"),
        "dates": audits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the league-agnostic historical coverage registry")
    parser.add_argument("--date", action="append", dest="dates", help="Prediction Universe business date; repeatable")
    parser.add_argument("--universe-root", type=Path, default=DEFAULT_UNIVERSE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--now", help="ISO timestamp used for deterministic registry/audit freshness")
    args = parser.parse_args()

    now = _parse_now(args.now)
    try:
        historical_records = list(HistoricalResultStore().iter_records())
    except Exception:
        historical_records = []
    registry = CoverageRegistryBuilder(historical_records=historical_records, now=now).build()
    output = write_coverage_registry(registry, args.output)
    dates = args.dates or []
    audit = build_audit(
        registry,
        dates=dates,
        universe_root=args.universe_root,
        historical_records=historical_records,
        now=now,
    )
    audit_output = DEFAULT_AUDIT_PATH if args.audit_output is None else args.audit_output
    _write_json(audit_output, audit)
    print(json.dumps({
        "registry": str(output),
        "registry_digest": registry.get("registry_digest"),
        "competition_count": registry.get("competition_count", 0),
        "historical_match_count": sum(row.get("historical_match_count", 0) for row in registry.get("competitions", [])),
        "daily_audit": str(audit_output),
        "dates": [{
            "business_date": item["business_date"],
            "fixture_count": item["fixture_count"],
            "status_counts": item["audit"]["summary"]["status_counts"],
            "reason_counts": item["audit"]["summary"]["reason_counts"],
            "non_blocking": item["audit"]["summary"]["non_blocking"],
        } for item in audit["dates"]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
