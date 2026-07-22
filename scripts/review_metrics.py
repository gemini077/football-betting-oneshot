"""Build a deduplicated, weighted post-match calibration status artifact."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data" / "postmatch_reviews"
DEFAULT_OUTPUT = DEFAULT_ROOT / "calibration_status.json"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _canonical_key(payload: dict[str, Any], path: Path) -> str:
    match = payload.get("match") or {}
    match_id = str(payload.get("MatchID") or "").strip()
    if match_id.startswith("FBOS-"):
        return match_id
    return "|".join(str(match.get(key) or "").strip().lower() for key in ("home", "away", "kickoff_local")) or path.stem


def _quality_rank(payload: dict[str, Any], path: Path) -> tuple[int, int, str]:
    match_id = str(payload.get("MatchID") or "")
    return (1 if match_id.startswith("FBOS-") else 0, int(payload.get("calibration_weight") or 0), str(path))


def _hit(payload: dict[str, Any], key: str) -> bool | None:
    value = ((payload.get("settlement") or {}).get(key) or {}).get("hit")
    return value if isinstance(value, bool) else None


def _tags(payload: dict[str, Any]) -> list[str]:
    tags = list(payload.get("error_tags") or [])
    score_miss = _hit(payload, "exact_score") is False
    if score_miss:
        diagnostics = payload.get("model_diagnostics") or {}
        trace = payload.get("score_selection_audit") or {}
        rank = diagnostics.get("actual_score_rank")
        if rank is not None:
            tags = [tag for tag in tags if tag != "score_selector_error"]
            if int(rank) <= 5:
                selected = trace.get("selected_score")
                mathematical = trace.get("mathematical_first_score")
                tags.append("selector_override_error" if selected and mathematical and selected != mathematical else "score_matrix_top5_miss")
            elif int(rank) <= 10:
                tags.append("score_matrix_rank_error")
            else:
                tags.append("score_matrix_tail_error")
    if tags:
        return list(dict.fromkeys(tags))
    settlement = payload.get("settlement") or {}
    if _hit(payload, "primary") is False:
        tags.append("direction_error")
        if (settlement.get("primary") or {}).get("actual") == "平局":
            tags.append("draw_underestimated")
        elif (settlement.get("primary") or {}).get("actual") == "客胜":
            tags.append("away_tail_missed")
    if score_miss:
        tags.append("score_selector_error")
    if _hit(payload, "total_goals_mode") is False:
        tags.append("goal_total_error")
    if _hit(payload, "btts") is False:
        tags.append("btts_error")
    quality = payload.get("data_quality_review") or {}
    if not ((payload.get("_timeline") or {}).get("蹇収瑕嗙洊") or quality.get("checkpoint_count")):
        tags.append("insufficient_snapshots")
    return list(dict.fromkeys(tags))


def build_metrics(review_root: Path = DEFAULT_ROOT, output: Path = DEFAULT_OUTPUT,
                  since: str | None = None) -> dict[str, Any]:
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    raw_count = 0
    for path in sorted(review_root.glob("*.json")):
        payload = _load(path)
        if not payload or not payload.get("result"):
            continue
        raw_count += 1
        kickoff = str((payload.get("match") or {}).get("kickoff_local") or "")
        if since and kickoff[:10] < since:
            continue
        key = _canonical_key(payload, path)
        previous = selected.get(key)
        if previous is None or _quality_rank(payload, path) > _quality_rank(previous[1], previous[0]):
            selected[key] = (path, payload)

    rows = []
    for _, payload in selected.values():
        if not payload.get("data_grade"):
            quality = payload.get("data_quality_review") or {}
            payload["data_grade"] = "D" if (payload.get("postmatch_evidence") or {}).get("status") == "score_conflict" else "C"
            payload["calibration_weight"] = 0.0 if payload["data_grade"] == "D" else 0.4
        rows.append(payload)
    metrics: dict[str, Any] = {}
    for label, key in (("model_1x2", "model_1x2"), ("primary", "primary"),
                       ("exact_score", "exact_score"), ("total_goals", "total_goals_mode"),
                       ("btts", "btts")):
        values = [_hit(payload, key) for payload in rows]
        values = [value for value in values if value is not None]
        metrics[label] = {"settled": len(values), "hits": sum(values),
                          "hit_rate": round(sum(values) / len(values), 6) if values else None}

    grades = Counter(str(payload.get("data_grade") or "C") for payload in rows)
    tags = Counter(tag for payload in rows for tag in _tags(payload))
    trigger = {}
    for tag, count in tags.items():
        trigger[tag] = {"count": count, "state": "candidate_review" if count >= 10 else "watch" if count >= 5 else "observe"}
    weighted_total = sum(float(payload.get("calibration_weight") or 0) for payload in rows)
    weighted_hits = sum(float(payload.get("calibration_weight") or 0) for payload in rows if _hit(payload, "primary") is True)
    result = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"since": since, "raw_reviews": raw_count, "deduplicated_matches": len(rows)},
        "quality_distribution": dict(sorted(grades.items())),
        "metrics": metrics,
        "error_tags": dict(tags.most_common()),
        "triggers": trigger,
        "weighted_primary": {"weight": round(weighted_total, 6), "hits_weighted": round(weighted_hits, 6),
                             "hit_rate": round(weighted_hits / weighted_total, 6) if weighted_total else None},
        "policy": {"research_all_matches": True, "formal_pick_grades": ["A", "B"],
                   "execution_requires_formal_pick": True, "trigger_thresholds": {"watch": 5, "candidate_review": 10, "upgrade_review": 20}},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--since")
    args = parser.parse_args()
    root = args.review_root if args.review_root.is_absolute() else ROOT / args.review_root
    output = args.output if args.output.is_absolute() else ROOT / args.output
    print(json.dumps(build_metrics(root, output, args.since), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
