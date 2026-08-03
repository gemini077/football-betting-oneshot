"""Repair cross-market contradictions in already-published reports.

This migration is deliberately narrow: it changes a report only when its
stored total and exact-total selections are on opposite sides of the same
line.  Reports without that contradiction are left byte-for-byte untouched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from automatic_model_core import (
    _align_exact_total_candidate,
    _dimension_predictions,
    _total_bucket_compatible,
)


def _stored_dimensions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    model = payload.get("model") or {}
    decisions = payload.get("decisions") or {}
    return model.get("dimension_predictions") or decisions.get("dimension_predictions") or {}


def repair_report_payload(payload: dict[str, Any]) -> bool:
    """Repair one in-memory report and return whether it was changed."""

    model = payload.get("model") or {}
    decisions = payload.get("decisions") or {}
    current = _stored_dimensions(payload)
    total = current.get("total") or {}
    exact = current.get("exact_total") or {}
    exact_goals = exact.get("goals") or exact.get("selection")
    if not total or not exact or total.get("selection") not in {"over", "under"}:
        return False
    if _total_bucket_compatible(
        exact_goals,
        selection=str(total.get("selection")),
        line=total.get("line"),
    ):
        return False

    candidates = list(model.get("market_predictions") or [])
    total_rows = list(model.get("total_goals_buckets") or [])
    if not candidates or not total_rows:
        return False

    dimensions = _dimension_predictions(candidates)
    candidates = _align_exact_total_candidate(candidates, total_rows, dimensions.get("total"))
    normalized = _dimension_predictions(candidates)
    # A historical repair must not silently re-rank unrelated families or
    # replace the report's already-selected primary contract.  Only the two
    # dimensions involved in the contradiction are replaced.
    repaired_dimensions = dict(current)
    repaired_dimensions["total"] = normalized["total"]
    repaired_dimensions["exact_total"] = normalized["exact_total"]
    model["market_predictions"] = candidates
    model["dimension_predictions"] = repaired_dimensions
    decisions["dimension_predictions"] = repaired_dimensions
    automation = payload.setdefault("automation", {})
    automation["consistency_repair"] = {
        "status": "repaired_existing_report",
        "rule": "exact_total_must_match_selected_total_side",
        "source": "scripts.repair_report_consistency",
    }
    return True


def repair_report_file(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = repair_report_payload(payload)
    if changed:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/analysis_reports/current"))
    parser.add_argument("--report", type=Path, action="append")
    args = parser.parse_args()
    paths = args.report or sorted(args.root.glob("*.json"))
    repaired = [path for path in paths if repair_report_file(path)]
    for path in repaired:
        print(path)
    print(f"repaired={len(repaired)} scanned={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
