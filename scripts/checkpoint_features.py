#!/usr/bin/env python3
"""Turn immutable checkpoint snapshots into bounded market-movement features."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean, median


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_ROOT = ROOT / "data" / "market_history" / "checkpoints"


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _market_point(snapshot: dict, captured_at: str | None = None) -> dict | None:
    probability_rows = []
    for row in (snapshot.get("ouzhi") or {}).get("bookmakers") or []:
        odds = row.get("spf_current") or {}
        try:
            prices = [float(odds[key]) for key in ("home", "draw", "away")]
        except (KeyError, TypeError, ValueError):
            continue
        if any(price <= 1 for price in prices):
            continue
        inverse = [1 / price for price in prices]
        total = sum(inverse)
        probability_rows.append([value / total for value in inverse])
    if not probability_rows:
        return None
    asian = []
    for row in (snapshot.get("yazhi") or {}).get("companies") or []:
        try:
            asian.append(float(row.get("current_handicap")))
        except (TypeError, ValueError):
            pass
    totals = []
    for row in (snapshot.get("daxiao") or {}).get("companies") or []:
        try:
            totals.append(float(row.get("current_line")))
        except (TypeError, ValueError):
            pass
    probabilities = {
        key: fmean(row[index] for row in probability_rows)
        for index, key in enumerate(("home", "draw", "away"))
    }
    leaders = max(probabilities, key=probabilities.get)
    dispersion = fmean(
        max(row) - min(row) for row in probability_rows
    ) if probability_rows else None
    return {
        "captured_at": captured_at or snapshot.get("fetched_at"),
        "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
        "leader": leaders,
        "asian_handicap": round(median(asian), 4) if asian else None,
        "total_line": round(median(totals), 4) if totals else None,
        "company_count": len(probability_rows),
        "dispersion": round(dispersion, 6) if dispersion is not None else None,
    }


def _snapshot_from_record(record: dict, root: Path) -> dict:
    manifest_ref = record.get("fetch_manifest")
    if not manifest_ref:
        return {}
    manifest_path = Path(str(manifest_ref))
    manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    manifest = _load(manifest_path)
    sources = manifest.get("sources") or {}
    for name in ("nowscore", "500_deep"):
        source = sources.get(name) or {}
        candidates = []
        if source.get("file"):
            candidates.append(source["file"])
        candidates.extend(row.get("file") for row in source.get("matches") or [] if row.get("file"))
        for value in candidates:
            path = Path(str(value))
            path = path if path.is_absolute() else root / path
            snapshot = _load(path)
            if snapshot:
                return snapshot
    return {}


def build_checkpoint_features(
    canonical_id: str,
    current_snapshot: dict | None = None,
    *,
    root: Path = ROOT,
    checkpoint_root: Path | None = None,
) -> dict:
    checkpoint_root = checkpoint_root or root / "data" / "market_history" / "checkpoints"
    points = []
    for path in sorted((checkpoint_root / canonical_id).glob("*.json")):
        record = _load(path)
        point = _market_point(_snapshot_from_record(record, root), record.get("captured_at"))
        if point:
            point["stage"] = record.get("stage") or path.stem
            points.append(point)
    current_point = _market_point(current_snapshot or {})
    if current_point and not any(
        point.get("captured_at") == current_point.get("captured_at") for point in points
    ):
        current_point["stage"] = "current"
        points.append(current_point)
    points.sort(key=lambda row: str(row.get("captured_at") or ""))
    if not points:
        return {
            "snapshot_count": 0,
            "state": "no_usable_market_snapshots",
            "probability_delta": {},
            "leader_reversals": 0,
        }
    first, latest = points[0], points[-1]
    probability_delta = {
        key: round(latest["probabilities"][key] - first["probabilities"][key], 6)
        for key in ("home", "draw", "away")
    }
    reversals = sum(
        points[index]["leader"] != points[index - 1]["leader"]
        for index in range(1, len(points))
    )
    return {
        "snapshot_count": len(points),
        "state": "tracked" if len(points) >= 2 else "single_snapshot",
        "first_stage": first.get("stage"),
        "latest_stage": latest.get("stage"),
        "first_captured_at": first.get("captured_at"),
        "latest_captured_at": latest.get("captured_at"),
        "probability_delta": probability_delta,
        "asian_handicap_delta": (
            round(latest["asian_handicap"] - first["asian_handicap"], 4)
            if latest.get("asian_handicap") is not None and first.get("asian_handicap") is not None else None
        ),
        "total_line_delta": (
            round(latest["total_line"] - first["total_line"], 4)
            if latest.get("total_line") is not None and first.get("total_line") is not None else None
        ),
        "leader_reversals": reversals,
        "latest_leader": latest.get("leader"),
        "latest_company_count": latest.get("company_count"),
        "latest_dispersion": latest.get("dispersion"),
        "points": points[-8:],
    }
