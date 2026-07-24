#!/usr/bin/env python3
"""Build a versioned, walk-forward calibration artifact from settled reviews."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "data" / "postmatch_reviews"
OUTPUT = ROOT / "data" / "model_calibration" / "latest.json"
HISTORY_ROOT = ROOT / "data" / "model_calibration" / "history"
OUTCOMES = ("home", "draw", "away")
ACTUAL_KEYS = {"主胜": "home", "平局": "draw", "客胜": "away"}


def _load(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _row(review: dict) -> dict | None:
    source = Path(str(review.get("source_report") or ""))
    source = source if source.is_absolute() else ROOT / source
    report = _load(source)
    if not report:
        return None
    probabilities = (report.get("model") or {}).get("probabilities") or {}
    if not all(isinstance(probabilities.get(key), (int, float)) for key in OUTCOMES):
        return None
    actual = ACTUAL_KEYS.get(str((review.get("result") or {}).get("outcome") or ""))
    expected = ((review.get("settlement") or {}).get("expected_goals") or {}).get("pick")
    actual_total = (review.get("result") or {}).get("total_goals")
    if actual is None or not isinstance(expected, (int, float)) or not isinstance(actual_total, (int, float)):
        return None
    quality = review.get("data_quality_review") or {}
    return {
        "kickoff": str((review.get("match") or {}).get("kickoff_local") or ""),
        "model_version": str((report.get("report") or {}).get("model_version") or "unknown"),
        "model_family": str((report.get("model") or {}).get("method") or "unknown"),
        "probabilities": {key: float(probabilities[key]) for key in OUTCOMES},
        "actual": actual,
        "expected_goals": float(expected),
        "actual_total": float(actual_total),
        "weight": float(review.get("calibration_weight") or quality.get("calibration_weight") or 0.4),
    }


def load_rows(review_root: Path = REVIEW_ROOT) -> list[dict]:
    rows = []
    for path in review_root.glob("*.json"):
        review = _load(path)
        if not review or not review.get("result"):
            continue
        row = _row(review)
        if row:
            rows.append(row)
    rows.sort(key=lambda value: value["kickoff"])
    if not rows:
        return []
    latest_family = rows[-1]["model_family"]
    return [row for row in rows if row["model_family"] == latest_family]


def _weighted_mean(rows: list[dict], value) -> float:
    total = sum(row["weight"] for row in rows)
    return sum(row["weight"] * float(value(row)) for row in rows) / total if total else 0.0


def fit_direction_offsets(rows: list[dict]) -> dict[str, float]:
    predicted = {key: _weighted_mean(rows, lambda row, key=key: row["probabilities"][key]) for key in OUTCOMES}
    actual = {key: _weighted_mean(rows, lambda row, key=key: row["actual"] == key) for key in OUTCOMES}
    raw = {
        key: math.log((actual[key] + 0.03) / (predicted[key] + 0.03))
        for key in OUTCOMES
    }
    centre = sum(raw.values()) / len(raw)
    return {key: round(max(-0.35, min(0.35, raw[key] - centre)), 6) for key in OUTCOMES}


def apply_direction(probabilities: dict, offsets: dict, strength: float) -> dict:
    adjusted = {
        key: max(1e-9, float(probabilities[key])) * math.exp(float(offsets.get(key) or 0) * strength)
        for key in OUTCOMES
    }
    total = sum(adjusted.values())
    return {key: adjusted[key] / total for key in OUTCOMES}


def _brier(rows: list[dict], offsets: dict | None = None, strength: float = 0.0) -> float:
    return _weighted_mean(rows, lambda row: sum(
        (
            (apply_direction(row["probabilities"], offsets or {}, strength)[key]
             if offsets else row["probabilities"][key])
            - (1.0 if row["actual"] == key else 0.0)
        ) ** 2
        for key in OUTCOMES
    ))


def _mae(rows: list[dict], shift: float = 0.0, strength: float = 0.0) -> float:
    return _weighted_mean(
        rows,
        lambda row: abs(row["actual_total"] - (row["expected_goals"] + shift * strength)),
    )


def build_calibration(review_root: Path = REVIEW_ROOT) -> dict:
    rows = load_rows(review_root)
    now = datetime.now(timezone.utc)
    if len(rows) < 18:
        return {
            "schema_version": "1.0",
            "generated_at": now.isoformat(),
            "status": "observing",
            "active": False,
            "reason": "fewer than 18 compatible settled samples",
            "sample": {"compatible": len(rows)},
        }
    holdout_size = min(8, max(5, len(rows) // 3))
    train, holdout = rows[:-holdout_size], rows[-holdout_size:]
    strength = 0.3 if len(rows) < 40 else 0.6
    offsets = fit_direction_offsets(train)
    total_shift = max(-0.5, min(0.5, _weighted_mean(
        train, lambda row: row["actual_total"] - row["expected_goals"]
    )))
    before_brier = _brier(holdout)
    after_brier = _brier(holdout, offsets, strength)
    before_mae = _mae(holdout)
    after_mae = _mae(holdout, total_shift, strength)
    minimum_relative_improvement = 0.01
    direction_improvement = (before_brier - after_brier) / before_brier if before_brier else 0.0
    total_improvement = (before_mae - after_mae) / before_mae if before_mae else 0.0
    direction_approved = direction_improvement >= minimum_relative_improvement
    total_approved = total_improvement >= minimum_relative_improvement
    residual_variance = _weighted_mean(
        train,
        lambda row: (row["actual_total"] - row["expected_goals"]) ** 2,
    )
    tail_mix = max(0.0, min(0.15, (residual_variance - 2.5) * 0.03))
    versions = sorted({row["model_version"] for row in rows})
    return {
        "schema_version": "1.0",
        "generated_at": now.isoformat(),
        "status": "partial_active" if direction_approved or total_approved else "shadow_only",
        "active": direction_approved or total_approved,
        "model_family": rows[-1]["model_family"],
        "compatible_model_versions": versions,
        "sample": {
            "compatible": len(rows),
            "training": len(train),
            "holdout": len(holdout),
            "effective_weight": round(sum(row["weight"] for row in rows), 4),
            "through": rows[-1]["kickoff"],
        },
        "policy": {
            "strength": strength,
            "minimum_compatible_samples": 18,
            "full_review_samples": 40,
            "walk_forward_holdout": holdout_size,
            "single_match_updates_forbidden": True,
            "minimum_relative_holdout_improvement": minimum_relative_improvement,
        },
        "direction": {
            "approved": direction_approved,
            "logit_offsets": offsets,
            "validation": {
                "brier_before": round(before_brier, 6),
                "brier_after": round(after_brier, 6),
                "relative_improvement": round(direction_improvement, 6),
            },
        },
        "total_goals": {
            "approved": total_approved,
            "lambda_shift": round(total_shift, 6),
            "validation": {
                "mae_before": round(before_mae, 6),
                "mae_after": round(after_mae, 6),
                "relative_improvement": round(total_improvement, 6),
            },
        },
        "dispersion": {
            "approved": len(rows) >= 40 and tail_mix > 0,
            "tail_mixture_weight": round(tail_mix, 6),
            "state": "shadow_until_40_samples",
        },
    }


def write_calibration(payload: dict, output: Path = OUTPUT, history_root: Path | None = HISTORY_ROOT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if history_root is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        history_root.mkdir(parents=True, exist_ok=True)
        (history_root / f"{stamp}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-root", type=Path, default=REVIEW_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args()
    review_root = args.review_root if args.review_root.is_absolute() else ROOT / args.review_root
    output = args.output if args.output.is_absolute() else ROOT / args.output
    payload = build_calibration(review_root)
    write_calibration(payload, output, HISTORY_ROOT if not args.no_history else None)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
