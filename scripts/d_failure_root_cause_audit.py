#!/usr/bin/env python3
"""Read-only audit of why Challenger D was an invalid research transfer."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import fmean, median

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prospective_settlement import normalize_result  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
PRED_TRUST_1 = ROOT / "data" / "prediction_quality" / "pred_trust_1" / "audit_2026-08-30.json"
RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"


def _quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _score_summary(scores: list[tuple[int, int]]) -> dict:
    totals = [home + away for home, away in scores]
    counts = Counter(f"{home}-{away}" for home, away in scores)
    return {
        "sample_count": len(scores),
        "score_counts_top20": dict(counts.most_common(20)),
        "zero_zero_count": counts.get("0-0", 0),
        "zero_zero_share": counts.get("0-0", 0) / len(scores) if scores else None,
        "mean_total_goals": fmean(totals) if totals else None,
        "median_total_goals": median(totals) if totals else None,
        "over_2_5_share": sum(value >= 3 for value in totals) / len(totals) if totals else None,
        "total_ge_4_share": sum(value >= 4 for value in totals) / len(totals) if totals else None,
        "total_ge_5_share": sum(value >= 5 for value in totals) / len(totals) if totals else None,
        "btts_share": (
            sum(home > 0 and away > 0 for home, away in scores) / len(scores)
            if scores else None
        ),
    }


def _all_verified_results() -> tuple[list[tuple[int, int]], list[dict]]:
    scores = []
    zero_zero_rows = []
    for path in sorted(RESULT_ROOT.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = normalize_result(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        verified_at = result.get("result_verified_at") or result.get("verified_at")
        if not verified_at:
            continue
        pair = (int(result["home_score_90m"]), int(result["away_score_90m"]))
        scores.append(pair)
        if pair == (0, 0):
            zero_zero_rows.append({
                "file": path.name,
                "match_id": result.get("match_id"),
                "match_key": result.get("match_key"),
                "provider_match_id": result.get("provider_match_id"),
                "verified_at": verified_at,
            })
    return scores, zero_zero_rows


def _hours_before(kickoff: str, cutoff: str) -> float | None:
    try:
        left = datetime.fromisoformat(kickoff)
        right = datetime.fromisoformat(cutoff)
        return (left - right).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None


def _valid_total_line(value) -> float | None:
    try:
        line = float(value)
    except (TypeError, ValueError):
        return None
    return line if math.isfinite(line) and 1.0 <= line <= 5.0 else None


def _market_surface(manifest: dict) -> dict:
    verified_ids = set(manifest.get("verified_prediction_ids") or [])
    rows = [
        row for row in manifest.get("selected_records") or []
        if row.get("prediction_id") in verified_ids
    ]
    horizons = []
    line_counts = []
    quote_counts = []
    pinnacle_total = 0
    pinnacle_1x2 = 0
    single_line = 0
    multi_line = 0
    no_line = 0
    line_frequency = Counter()
    source_frequency = Counter()
    samples = []

    for row in rows:
        path = ROOT / str(row.get("input_snapshot_ref") or "")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        context = snapshot.get("input") or {}
        source_snapshots = context.get("source_snapshots") or {}
        nowscore = (source_snapshots.get("nowscore") or {}).get("snapshots") or []
        fallback = (source_snapshots.get("500_deep") or {}).get("snapshots") or []
        deep = nowscore[0] if nowscore and isinstance(nowscore[0], dict) else (
            fallback[0] if fallback and isinstance(fallback[0], dict) else {}
        )

        totals = (deep.get("daxiao") or {}).get("companies") or []
        books = (deep.get("ouzhi") or {}).get("bookmakers") or []
        lines = sorted({
            round(line, 2)
            for line in (_valid_total_line(item.get("current_line")) for item in totals if isinstance(item, dict))
            if line is not None
        })
        for line in lines:
            line_frequency[str(line)] += 1
        if len(lines) == 0:
            no_line += 1
        elif len(lines) == 1:
            single_line += 1
        else:
            multi_line += 1
        line_counts.append(len(lines))
        quote_counts.append(len(totals))
        if any(str(item.get("cid") or "") == "1055" or str(item.get("name") or "").lower() == "pinnacle" for item in totals if isinstance(item, dict)):
            pinnacle_total += 1
        if any(str(item.get("cid") or "") == "1055" or str(item.get("name") or "").lower() == "pinnacle" for item in books if isinstance(item, dict)):
            pinnacle_1x2 += 1
        for item in totals:
            if isinstance(item, dict) and item.get("source_provider"):
                source_frequency[str(item["source_provider"])] += 1

        cutoff = snapshot.get("source_cutoff_at") or snapshot.get("captured_at")
        horizon = _hours_before(row.get("kickoff_at"), cutoff)
        if horizon is not None:
            horizons.append(horizon)
        if len(samples) < 8:
            samples.append({
                "prediction_id": row.get("prediction_id"),
                "kickoff_at": row.get("kickoff_at"),
                "source_cutoff_at": cutoff,
                "hours_before_kickoff": horizon,
                "distinct_current_ou_lines": lines,
                "ou_quote_count": len(totals),
            })

    return {
        "verified_records": len(rows),
        "hours_before_kickoff": {
            "p10": _quantile(horizons, 0.10),
            "p25": _quantile(horizons, 0.25),
            "p50": _quantile(horizons, 0.50),
            "p75": _quantile(horizons, 0.75),
            "p90": _quantile(horizons, 0.90),
            "min": min(horizons) if horizons else None,
            "max": max(horizons) if horizons else None,
        },
        "distinct_ou_line_count": {
            "median": median(line_counts) if line_counts else None,
            "single_line_matches": single_line,
            "multi_line_matches": multi_line,
            "no_line_matches": no_line,
        },
        "ou_quote_count": {
            "median": median(quote_counts) if quote_counts else None,
            "p25": _quantile([float(x) for x in quote_counts], 0.25),
            "p75": _quantile([float(x) for x in quote_counts], 0.75),
        },
        "pinnacle_presence": {
            "ou_matches": pinnacle_total,
            "one_x_two_matches": pinnacle_1x2,
        },
        "line_frequency_by_match": dict(line_frequency.most_common()),
        "source_provider_quote_frequency": dict(source_frequency.most_common()),
        "examples": samples,
    }


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(PRED_TRUST_1.read_text(encoding="utf-8"))

    all_scores, zero_zero_rows = _all_verified_results()
    evaluated = audit.get("prospective_evaluation", {}).get("evaluated_rows") or []
    cohort_scores = []
    for row in evaluated:
        score = str(row.get("actual_score") or "")
        if "-" not in score:
            continue
        left, right = score.split("-", 1)
        cohort_scores.append((int(left), int(right)))

    output = {
        "schema_version": "exact_score_d_failure_root_cause_audit.v1",
        "milestone": "EXACT-SCORE-D-FAILURE-ROOT-CAUSE-AUDIT-1",
        "read_only": True,
        "result_integrity": {
            "all_verified_result_artifacts": _score_summary(all_scores),
            "pred_trust_verified_cohort": _score_summary(cohort_scores),
            "global_zero_zero_rows": zero_zero_rows,
            "interpretation_guardrail": (
                "zero 0-0 in the 181-match cohort is not by itself proof of a parser bug; "
                "compare against the full verified result store before drawing a pipeline conclusion"
            ),
        },
        "market_surface": _market_surface(manifest),
        "existing_audit_boundary": {
            "input_football_evidence_assessment": (
                audit.get("root_cause", {})
                .get("not_established", {})
                .get("A. INPUT / FOOTBALL EVIDENCE", {})
            ),
            "selector_assessment": (
                audit.get("root_cause", {})
                .get("not_established", {})
                .get("D. SCORE_SELECTOR", {})
            ),
        },
        "production_changes": "NO",
        "model_changes": "NO",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
