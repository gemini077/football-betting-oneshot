#!/usr/bin/env python3
"""Audit whether current immutable football evidence can support a structural-lambda experiment.

Research-only. Reads existing prospective football evidence and verified
postmatch reviews. It never changes production prediction data.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = ROOT / "data" / "prospective" / "football_evidence"
DEFAULT_REVIEW_ROOT = ROOT / "data" / "postmatch_reviews"
DEFAULT_PINNED_MANIFEST = (
    ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
)
MIN_ROWS_PER_TEAM = 10
MIN_SETTLED_USABLE = 50


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _valid_score_row(row: Any, kickoff: datetime | None) -> bool:
    if not isinstance(row, dict):
        return False
    match_date = str(row.get("match_date") or "").strip()
    try:
        row_date = datetime.fromisoformat(match_date)
    except ValueError:
        return False
    if kickoff is not None and row_date.date() >= kickoff.date():
        return False
    try:
        home_goals = int(row.get("home_goals"))
        away_goals = int(row.get("away_goals"))
    except (TypeError, ValueError):
        return False
    if home_goals < 0 or away_goals < 0:
        return False
    return bool(row.get("home_team_id") and row.get("away_team_id"))


def _infer_subject_team_id(rows: Iterable[dict[str, Any]]) -> tuple[str | None, float]:
    counts: Counter[str] = Counter()
    valid_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        valid_rows += 1
        for key in ("home_team_id", "away_team_id"):
            value = str(row.get(key) or "").strip()
            if value:
                counts[value] += 1
    if not counts or valid_rows <= 0:
        return None, 0.0
    team_id, count = counts.most_common(1)[0]
    return team_id, count / valid_rows


def _evidence_status(payload: dict[str, Any]) -> dict[str, Any]:
    kickoff = _parse_time(payload.get("kickoff_at"))
    captured = _parse_time(payload.get("evidence_captured_at"))
    cutoff = _parse_time(payload.get("source_cutoff_at"))

    reasons: list[str] = []
    if kickoff is None:
        reasons.append("INVALID_KICKOFF")
    if captured is None:
        reasons.append("INVALID_EVIDENCE_CAPTURE_TIME")
    elif kickoff is not None and captured >= kickoff:
        reasons.append("EVIDENCE_NOT_PREMATCH")
    if cutoff is None:
        reasons.append("INVALID_SOURCE_CUTOFF")
    elif kickoff is not None and cutoff >= kickoff:
        reasons.append("SOURCE_CUTOFF_NOT_PREMATCH")

    recent = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), dict) else {}
    home_rows = recent.get("home_team") if isinstance(recent.get("home_team"), list) else []
    away_rows = recent.get("away_team") if isinstance(recent.get("away_team"), list) else []
    home_valid = [row for row in home_rows if _valid_score_row(row, kickoff)]
    away_valid = [row for row in away_rows if _valid_score_row(row, kickoff)]
    if len(home_valid) < MIN_ROWS_PER_TEAM:
        reasons.append("HOME_HISTORY_TOO_SHORT")
    if len(away_valid) < MIN_ROWS_PER_TEAM:
        reasons.append("AWAY_HISTORY_TOO_SHORT")

    home_id, home_identity_share = _infer_subject_team_id(home_valid)
    away_id, away_identity_share = _infer_subject_team_id(away_valid)
    if home_id is None or home_identity_share < 0.8:
        reasons.append("HOME_TEAM_IDENTITY_UNSTABLE")
    if away_id is None or away_identity_share < 0.8:
        reasons.append("AWAY_TEAM_IDENTITY_UNSTABLE")
    if home_id and away_id and home_id == away_id:
        reasons.append("HOME_AWAY_IDENTITY_COLLISION")

    return {
        "usable": not reasons,
        "reasons": reasons,
        "home_valid_rows": len(home_valid),
        "away_valid_rows": len(away_valid),
        "home_subject_team_id": home_id,
        "away_subject_team_id": away_id,
        "home_identity_share": home_identity_share,
        "away_identity_share": away_identity_share,
    }


def _load_reviews(root: Path) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        if path.name == "calibration_status.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        prediction_id = str(payload.get("prediction_id") or "").strip()
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        score = str(result.get("score_90m") or payload.get("实际90分钟比分") or "").strip()
        if prediction_id and "-" in score:
            reviews[prediction_id] = {
                "path": str(path.relative_to(ROOT)),
                "score_90m": score,
                "generated_at": payload.get("generated_at"),
            }
    return reviews


def run(
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    review_root: Path = DEFAULT_REVIEW_ROOT,
    pinned_manifest: Path = DEFAULT_PINNED_MANIFEST,
) -> dict[str, Any]:
    reviews = _load_reviews(review_root)
    reason_counts: Counter[str] = Counter()
    evidence_records: dict[str, dict[str, Any]] = {}
    valid_row_counts: list[int] = []
    provider_counts: Counter[str] = Counter()

    for path in sorted(evidence_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reason_counts["INVALID_EVIDENCE_JSON"] += 1
            continue
        if not isinstance(payload, dict):
            reason_counts["INVALID_EVIDENCE_OBJECT"] += 1
            continue
        prediction_id = str(payload.get("prediction_id") or "").strip()
        if not prediction_id:
            reason_counts["MISSING_PREDICTION_ID"] += 1
            continue
        status = _evidence_status(payload)
        for reason in status["reasons"]:
            reason_counts[reason] += 1
        if status["usable"]:
            valid_row_counts.extend(
                [status["home_valid_rows"], status["away_valid_rows"]]
            )
            provider_counts[str(payload.get("source_provider") or "UNKNOWN")] += 1
        evidence_records[prediction_id] = {
            "path": str(path.relative_to(ROOT)),
            "match_id": str(payload.get("match_id") or ""),
            "match_key": str(payload.get("match_key") or ""),
            "kickoff_at": payload.get("kickoff_at"),
            "usable": status["usable"],
            **status,
        }

    usable_ids = {pid for pid, row in evidence_records.items() if row["usable"]}
    settled_ids = set(reviews)
    settled_with_any_evidence = settled_ids & set(evidence_records)
    settled_usable = settled_ids & usable_ids

    pinned = json.loads(pinned_manifest.read_text(encoding="utf-8"))
    pinned_ids = {
        str(row.get("prediction_id") or "")
        for row in pinned.get("selected_records") or []
    }
    pinned_verified_ids = {
        str(value) for value in pinned.get("verified_prediction_ids") or []
    }

    decision = (
        "STRUCTURAL_OFFLINE_EXPERIMENT_READY"
        if len(settled_usable) >= MIN_SETTLED_USABLE
        else "STRUCTURAL_EVIDENCE_SAMPLE_INSUFFICIENT"
    )

    return {
        "schema_version": "structural_football_evidence_coverage.v1",
        "status": "READY_FOR_ACCEPTANCE",
        "decision": decision,
        "minimum_settled_usable_required": MIN_SETTLED_USABLE,
        "coverage": {
            "football_evidence_files": len(evidence_records),
            "usable_structural_evidence": len(usable_ids),
            "verified_postmatch_reviews": len(settled_ids),
            "settled_with_any_evidence": len(settled_with_any_evidence),
            "settled_with_usable_structural_evidence": len(settled_usable),
            "pinned_unique": len(pinned_ids),
            "pinned_with_any_evidence": len(pinned_ids & set(evidence_records)),
            "pinned_verified": len(pinned_verified_ids),
            "pinned_verified_with_usable_evidence": len(
                pinned_verified_ids & usable_ids
            ),
            "median_valid_rows_per_team_side": (
                median(valid_row_counts) if valid_row_counts else None
            ),
            "provider_counts_for_usable": dict(sorted(provider_counts.items())),
        },
        "failure_reasons": dict(sorted(reason_counts.items())),
        "integrity_contract": {
            "evidence_capture_must_be_prematch": True,
            "source_cutoff_must_be_prematch": True,
            "minimum_valid_rows_per_team": MIN_ROWS_PER_TEAM,
            "subject_team_id_share_minimum": 0.8,
            "postmatch_result_used_for_generation": False,
        },
        "next_step": (
            "build one bounded dynamic attack/defence challenger on the settled usable cohort; no production change"
            if decision == "STRUCTURAL_OFFLINE_EXPERIMENT_READY"
            else "do not backfill or fabricate history; keep prospective structural evidence capture and wait for >=50 settled usable matches"
        ),
        "production_changes": "NO",
        "promotion": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
