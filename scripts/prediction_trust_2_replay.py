"""Run the bounded PRED-TRUST-2 strength/lambda challenger shootout.

The replay is deliberately research-only.  It reads a pinned list of final
prematch prediction IDs, loads each frozen input snapshot, and evaluates at
most the current Champion plus two pre-registered deterministic challengers.
No result is used to derive a lambda or tune a parameter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from automatic_model_core import (  # noqa: E402
    _consensus_probabilities,
    _deep_snapshot,
    _market_share,
    _market_total,
    _mean,
    _rate,
    build_automatic_model,
)
from prediction_trust_audit import (  # noqa: E402
    _is_formally_eligible,
    _load_exclusion_ids,
    _load_prediction_records,
    _normalise_text,
    build_unique_match_cohort,
)
from risk_engine import dixon_coles_score_matrix  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "data" / "prediction_quality" / "pred_trust_1" / "audit_2026-08-30.json"
DEFAULT_MANIFEST = ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
DEFAULT_OUTPUT = ROOT / "data" / "prediction_quality" / "pred_trust_2" / "replay_2026-08-30.json"
DEFAULT_REPORT = ROOT / "docs" / "prediction-quality" / "PRED-TRUST-2_FINAL_REPORT.md"
ACCEPTED_WRITEBACK_COMMIT = "73994d32fc148da49295a5bfef2e1e42e042a22e"
ACCEPTED_PRODUCTION_RUN = "33294381128"
PINNED_PRED_TRUST_1_HEAD = "599e7d82b1938e564d2f622c0eb412dd537d2662"
MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
OUTCOMES = ("home", "draw", "away")
EPSILON = 1e-15
SAME_TOLERANCE = 0.005


# This is the complete candidate registry.  It is intentionally not a grid.
CANDIDATE_SPECS = (
    {
        "candidate_id": "champion",
        "label": "Champion",
        "hypothesis": "current_recent_form_market_calibrated_poisson_v2",
        "formula_version": "champion_replay.v1",
        "boundary_changed": "none; replay stored Champion from frozen input",
    },
    {
        "candidate_id": "challenger_a_strength_separation",
        "label": "Challenger A",
        "hypothesis": "recent_form_strength_separation",
        "formula_version": "strength_separation_recent_form.v1",
        "boundary_changed": "lambda side share only",
    },
    {
        "candidate_id": "challenger_b_market_to_goal_separation",
        "label": "Challenger B",
        "hypothesis": "market_to_goal_separation",
        "formula_version": "market_to_goal_separation.v1",
        "boundary_changed": "lambda total and side share",
    },
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 6) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


def _form_share(form_home: float, form_away: float) -> float:
    total = float(form_home) + float(form_away)
    if total <= 0:
        raise ValueError("recent-form strength total must be positive")
    return _clamp(float(form_home) / total, 0.15, 0.85)


def derive_candidate_lambdas(
    candidate_id: str,
    *,
    form_home: float,
    form_away: float,
    market_total: float | None,
    market_share: float | None,
    form_total: float,
) -> dict[str, float | str]:
    """Derive the three pre-registered lambda states without fitting."""

    form_share = _form_share(form_home, form_away)
    target_total = float(market_total) if market_total is not None else float(form_total)
    market_side_share = float(market_share) if market_share is not None else form_share
    champion_total = _clamp(0.60 * float(form_total) + 0.40 * target_total, 1.0, 4.8)
    if candidate_id == "champion":
        total, share = champion_total, 0.65 * form_share + 0.35 * market_side_share
    elif candidate_id == "challenger_a_strength_separation":
        # Hold total fixed; remove the market share blend to test the
        # strength-differential boundary represented by frozen recent form.
        total, share = champion_total, form_share
    elif candidate_id == "challenger_b_market_to_goal_separation":
        # Let the frozen market total and market 1X2 side share define the
        # scoring state.  Form remains only the deterministic missing-data
        # fallback, which is unused by the accepted 217-row cohort.
        total, share = _clamp(target_total, 1.0, 4.8), market_side_share
    else:
        raise ValueError(f"unknown PRED-TRUST-2 candidate: {candidate_id}")
    return {
        "candidate_id": candidate_id,
        "form_share": form_share,
        "market_share": market_side_share,
        "target_total": target_total,
        "total": total,
        "share": _clamp(share, 0.15, 0.85),
        "lambda_home": total * _clamp(share, 0.15, 0.85),
        "lambda_away": total * (1.0 - _clamp(share, 0.15, 0.85)),
    }


def build_score_matrix(lambda_home: float, lambda_away: float) -> dict[tuple[int, int], float]:
    """Build the same independent-Poisson score state used by the Champion."""

    return dixon_coles_score_matrix(
        {"lambda_home": float(lambda_home), "lambda_away": float(lambda_away), "rho": 0.0}
    )


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        left, right = value
    elif isinstance(value, dict):
        left, right = value.get("home_score"), value.get("away_score")
    elif isinstance(value, str) and "-" in value:
        left, right = value.split("-", 1)
    else:
        return None
    try:
        home, away = int(left), int(right)
    except (TypeError, ValueError):
        return None
    return (home, away) if home >= 0 and away >= 0 else None


def _score_text(pair: tuple[int, int]) -> str:
    return f"{pair[0]}-{pair[1]}"


def _sorted_scores(matrix: Mapping[tuple[int, int], float]) -> list[tuple[tuple[int, int], float]]:
    return sorted(matrix.items(), key=lambda item: (-float(item[1]), item[0][0], item[0][1]))


def _outcome_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    output = {key: 0.0 for key in OUTCOMES}
    for (home, away), probability in matrix.items():
        output["home" if home > away else "draw" if home == away else "away"] += float(probability)
    return output


def _btts_probability(matrix: Mapping[tuple[int, int], float]) -> float:
    return sum(float(value) for (home, away), value in matrix.items() if home > 0 and away > 0)


def _over_probability(matrix: Mapping[tuple[int, int], float], line: int = 2) -> float:
    return sum(float(value) for (home, away), value in matrix.items() if home + away > line)


def _matrix_summary(matrix: Mapping[tuple[int, int], float]) -> dict[str, Any]:
    ordered = _sorted_scores(matrix)
    top = ordered[0][0]
    top3 = [score for score, _ in ordered[:3]]
    return {
        "top1_score": _score_text(top),
        "top3_scores": [_score_text(score) for score in top3],
        "top1_probability": float(ordered[0][1]),
        "probability_total_ge_4": sum(value for (home, away), value in matrix.items() if home + away >= 4),
        "probability_total_ge_5": sum(value for (home, away), value in matrix.items() if home + away >= 5),
        "probability_total_ge_6": sum(value for (home, away), value in matrix.items() if home + away >= 6),
    }


def _prediction_record_hash(record: Mapping[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(dict(record)))


def _digest_ids(values: Iterable[str]) -> str:
    return _sha256_bytes(_json_bytes(sorted(str(value) for value in values)))


def write_cohort_manifest(
    *,
    root: Path,
    audit_path: Path,
    output: Path,
    accepted_writeback_commit: str = ACCEPTED_WRITEBACK_COMMIT,
) -> dict[str, Any]:
    """Materialize a small ID/hash lock from the accepted PRED-TRUST-1 tree."""

    records = _load_prediction_records(root)
    cohort = build_unique_match_cohort(records, excluded_ids=_load_exclusion_ids(root))
    selected = cohort["selected_records"]
    if len(selected) != 217:
        raise ValueError(f"accepted PRED-TRUST-1 source must select 217 matches, got {len(selected)}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    evaluated = audit.get("prospective_evaluation", {}).get("evaluated_rows") or []
    verified_ids = sorted(str(row["prediction_id"]) for row in evaluated if row.get("prediction_id"))
    selected_ids = [str(row["prediction_id"]) for row in selected]
    if len(verified_ids) != 181 or not set(verified_ids).issubset(selected_ids):
        raise ValueError("PRED-TRUST-1 verified IDs do not match the pinned selected cohort")
    entries = []
    for record in selected:
        reference = str(record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or "")
        snapshot_path = root / reference
        if not reference or not snapshot_path.is_file():
            raise ValueError(f"selected record has no readable input snapshot: {record.get('prediction_id')}")
        entries.append(
            {
                "prediction_id": str(record["prediction_id"]),
                "match_id": str(record.get("match_id") or ""),
                "match_key": str(record.get("match_key") or ""),
                "kickoff_at": str(record.get("kickoff_at") or ""),
                "record_sha256": _prediction_record_hash(record),
                "input_snapshot_ref": reference,
                "input_snapshot_sha256": _sha256_file(snapshot_path),
            }
        )
    manifest = {
        "schema_version": "pred_trust_2.cohort_manifest.v1",
        "milestone": "PRED-TRUST-2",
        "accepted_writeback_commit": accepted_writeback_commit,
        "accepted_production_run": ACCEPTED_PRODUCTION_RUN,
        "pred_trust_1_head": PINNED_PRED_TRUST_1_HEAD,
        "audit_artifact_sha256": _sha256_file(audit_path),
        "selection_policy": "PRED-TRUST-1 final legal prematch version per unique match; evaluation-only",
        "selected_match_count": len(entries),
        "verified_match_count": len(verified_ids),
        "selected_prediction_digest": _digest_ids(selected_ids),
        "verified_prediction_digest": _digest_ids(verified_ids),
        "selected_records": entries,
        "verified_prediction_ids": verified_ids,
    }
    _write_json(output, manifest)
    return manifest


def _load_pinned_records(root: Path, manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("selected_records") or []
    if manifest.get("accepted_writeback_commit") != ACCEPTED_WRITEBACK_COMMIT:
        raise ValueError("cohort manifest accepted write-back pin mismatch")
    if len(entries) != 217 or manifest.get("selected_match_count") != 217:
        raise ValueError("PRED-TRUST-2 requires the pinned 217-match cohort")
    raw = {str(record.get("prediction_id")): record for record in _load_prediction_records(root)}
    selected: list[dict[str, Any]] = []
    for entry in entries:
        prediction_id = str(entry.get("prediction_id") or "")
        record = raw.get(prediction_id)
        if record is None:
            raise ValueError(f"pinned prediction is missing from current raw store: {prediction_id}")
        if _prediction_record_hash(record) != entry.get("record_sha256"):
            raise ValueError(f"pinned prediction content changed: {prediction_id}")
        snapshot_path = root / str(entry.get("input_snapshot_ref") or "")
        if not snapshot_path.is_file() or _sha256_file(snapshot_path) != entry.get("input_snapshot_sha256"):
            raise ValueError(f"pinned input snapshot changed or is missing: {prediction_id}")
        if not _is_formally_eligible(record):
            raise ValueError(f"pinned prediction is no longer formally eligible: {prediction_id}")
        selected.append(dict(record))
    match_ids = {str(record.get("match_id") or record.get("match_key") or "") for record in selected}
    if len(match_ids) != len(selected):
        raise ValueError("pinned selected cohort contains duplicate match identities")
    return selected, manifest


def _form_and_market_inputs(context: Mapping[str, Any]) -> dict[str, Any]:
    deep = _deep_snapshot(dict(context))
    deep_form = (deep.get("shuju") or {}).get("recent_form") or {}
    prematch = context.get("prematch_fundamentals") or {}
    form = deep_form or prematch.get("recent_form") or {}
    home_home = form.get("home_home") or {}
    away_away = form.get("away_away") or {}
    home_overall = form.get("home_overall") or {}
    away_overall = form.get("away_overall") or {}
    effective_home_home = home_home if home_home.get("matches") else home_overall
    effective_away_away = away_away if away_away.get("matches") else away_overall
    home_venue = _mean([_rate(effective_home_home, "goals_for"), _rate(effective_away_away, "goals_against")])
    away_venue = _mean([_rate(effective_away_away, "goals_for"), _rate(effective_home_home, "goals_against")])
    home_general = _mean([_rate(home_overall, "goals_for"), _rate(away_overall, "goals_against")])
    away_general = _mean([_rate(away_overall, "goals_for"), _rate(home_overall, "goals_against")])
    home_form = _mean([home_venue, home_venue, home_general])
    away_form = _mean([away_venue, away_venue, away_general])
    market_probabilities = _consensus_probabilities(deep) or (context.get("official_market_baseline") or {}).get("fair_probabilities")
    market_total = _market_total(deep)
    if home_form is None or away_form is None or not isinstance(market_probabilities, dict):
        raise ValueError("frozen input is missing the form or 1X2 market fields required by all candidates")
    market_probabilities = {
        key: float(market_probabilities[key])
        for key in OUTCOMES
        if _number(market_probabilities.get(key)) is not None
    }
    if set(market_probabilities) != set(OUTCOMES):
        raise ValueError("frozen input has incomplete market probabilities")
    form_total = _clamp(float(home_form) + float(away_form), 1.2, 4.2)
    target_total = float(market_total) if market_total is not None else form_total
    market_share = _market_share(target_total, market_probabilities)
    return {
        "form_home": float(home_form),
        "form_away": float(away_form),
        "form_total": form_total,
        "market_total": float(market_total) if market_total is not None else None,
        "target_total": target_total,
        "market_share": market_share,
        "market_probabilities": market_probabilities,
        "deep_form_available": bool(deep_form),
        "venue_proxy_used": not bool(home_home.get("matches") and away_away.get("matches")),
    }


def _actual_outcome(score: tuple[int, int]) -> str:
    return "home" if score[0] > score[1] else "draw" if score[0] == score[1] else "away"


def _bin_ece(probabilities: Iterable[float], observed: Iterable[bool]) -> float:
    pairs = [(float(probability), bool(value)) for probability, value in zip(probabilities, observed)]
    if not pairs:
        return float("nan")
    total = len(pairs)
    error = 0.0
    for index in range(5):
        lower, upper = index / 5, (index + 1) / 5
        bucket = [pair for pair in pairs if lower <= pair[0] < upper or (index == 4 and pair[0] <= upper)]
        if bucket:
            error += len(bucket) / total * abs(fmean(pair[0] for pair in bucket) - fmean(pair[1] for pair in bucket))
    return error


def _probability_metrics(probabilities: list[dict[str, float]], actuals: list[str]) -> dict[str, float | int]:
    sample = len(actuals)
    accuracy = sum(max(row, key=row.get) == actual for row, actual in zip(probabilities, actuals)) / sample
    brier = fmean(sum((row[key] - float(key == actual)) ** 2 for key in OUTCOMES) for row, actual in zip(probabilities, actuals))
    log_loss = fmean(-math.log(max(min(row[actual], 1.0 - EPSILON), EPSILON)) for row, actual in zip(probabilities, actuals))
    ece = fmean(_bin_ece([row[key] for row in probabilities], [actual == key for actual in actuals]) for key in OUTCOMES)
    return {"sample_count": sample, "accuracy": accuracy, "brier": brier, "log_loss": log_loss, "ece": ece}


def _binary_metrics(probabilities: list[float], actuals: list[bool]) -> dict[str, float | int]:
    sample = len(actuals)
    accuracy = sum((probability >= 0.5) == actual for probability, actual in zip(probabilities, actuals)) / sample
    brier = fmean((probability - float(actual)) ** 2 for probability, actual in zip(probabilities, actuals))
    return {
        "sample_count": sample,
        "accuracy": accuracy,
        "brier": brier,
        "ece": _bin_ece(probabilities, actuals),
    }


def _quantiles(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {key: float("nan") for key in ("P10", "P25", "P50", "P75", "P90")}
    def q(probability: float) -> float:
        position = (len(ordered) - 1) * probability
        lower, upper = math.floor(position), math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {key: q(probability) for key, probability in (("P10", 0.10), ("P25", 0.25), ("P50", 0.50), ("P75", 0.75), ("P90", 0.90))}


def _distribution_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [abs(row["lambda_home"] - row["lambda_away"]) for row in rows]
    totals = [row["lambda_home"] + row["lambda_away"] for row in rows]
    top1 = [row["top1_pair"] for row in rows]
    top1_scores = Counter(_score_text(pair) for pair in top1)
    count = len(rows)
    return {
        "sample_count": count,
        "lambda_home": _quantiles(row["lambda_home"] for row in rows),
        "lambda_away": _quantiles(row["lambda_away"] for row in rows),
        "lambda_total": _quantiles(totals),
        "absolute_gap": _quantiles(gaps),
        "gap_lt_0_25": sum(gap < 0.25 for gap in gaps),
        "gap_lt_0_5": sum(gap < 0.5 for gap in gaps),
        "gap_lt_0_25_share": sum(gap < 0.25 for gap in gaps) / count,
        "gap_lt_0_5_share": sum(gap < 0.5 for gap in gaps) / count,
        "top1_score_counts": dict(sorted(top1_scores.items(), key=lambda item: (-item[1], item[0]))),
        "one_one_top1_share": top1_scores.get("1-1", 0) / count,
        "top1_support_size": len(top1_scores),
        "high_score_top1_share": sum(home + away >= 4 for home, away in top1) / count,
        "home_margin_top1_share": sum(home > away for home, away in top1) / count,
        "draw_top1_share": sum(home == away for home, away in top1) / count,
        "away_margin_top1_share": sum(home < away for home, away in top1) / count,
        "mean_probability_total_ge_4": fmean(row["tail"]["probability_total_ge_4"] for row in rows),
        "mean_probability_total_ge_5": fmean(row["tail"]["probability_total_ge_5"] for row in rows),
        "mean_probability_total_ge_6": fmean(row["tail"]["probability_total_ge_6"] for row in rows),
    }


def _evaluate_candidate(
    rows: list[dict[str, Any]],
    verified_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    evaluated = [row for row in rows if row["prediction_id"] in verified_by_id]
    outcome_probabilities = []
    outcome_actuals = []
    btts_probabilities, btts_actuals = [], []
    ou_probabilities, ou_actuals = [], []
    top1_hits, top3_hits, actual_score_probabilities, score_nll = [], [], [], []
    evaluated_rows = []
    for row in evaluated:
        actual = _score_pair(verified_by_id[row["prediction_id"]].get("actual_score"))
        if actual is None:
            raise ValueError(f"verified row has invalid actual score: {row['prediction_id']}")
        actual_score = _score_text(actual)
        actual_outcome = _actual_outcome(actual)
        outcome_probabilities.append(row["probabilities"])
        outcome_actuals.append(actual_outcome)
        btts_probability = row["btts_probability"]
        over_probability = row["over_2_5_probability"]
        btts_actual = actual[0] > 0 and actual[1] > 0
        ou_actual = actual[0] + actual[1] > 2
        btts_probabilities.append(btts_probability)
        btts_actuals.append(btts_actual)
        ou_probabilities.append(over_probability)
        ou_actuals.append(ou_actual)
        actual_probability = row["matrix"].get(actual)
        if actual_probability is not None:
            actual_score_probabilities.append(actual_probability)
            score_nll.append(-math.log(max(actual_probability, EPSILON)))
        top1_hits.append(row["top1_pair"] == actual)
        top3_hits.append(actual in row["top3_pairs"])
        evaluated_rows.append(
            {
                "prediction_id": row["prediction_id"],
                "match_id": row["match_id"],
                "actual_score": actual_score,
                "actual_outcome": actual_outcome,
                "probabilities": {key: _round(row["probabilities"][key], 9) for key in OUTCOMES},
                "btts_probability": _round(btts_probability, 9),
                "over_2_5_probability": _round(over_probability, 9),
                "top1_score": _score_text(row["top1_pair"]),
                "top3_scores": [_score_text(pair) for pair in row["top3_pairs"]],
                "actual_score_probability": _round(actual_probability, 9),
            }
        )
    return {
        "sample_count": len(evaluated),
        "one_x_two": _probability_metrics(outcome_probabilities, outcome_actuals),
        "exact_score": {
            "sample_count": len(evaluated),
            "top1_hit_rate": fmean(top1_hits),
            "top3_hit_rate": fmean(top3_hits),
            "actual_score_probability_sample_count": len(actual_score_probabilities),
            "mean_probability_assigned_to_actual_score": fmean(actual_score_probabilities),
            "nll": fmean(score_nll),
        },
        "btts": _binary_metrics(btts_probabilities, btts_actuals),
        "ou_2_5": _binary_metrics(ou_probabilities, ou_actuals),
        "distribution": _distribution_metrics(rows),
        "evaluated_rows": evaluated_rows,
    }


def _metric_value(metrics: Mapping[str, Any], path: str) -> float:
    value: Any = metrics
    for part in path.split("."):
        value = value[part]
    return float(value)


TRADEOFF_METRICS = (
    ("1X2 accuracy", "one_x_two.accuracy", "higher"),
    ("1X2 Brier", "one_x_two.brier", "lower"),
    ("1X2 LogLoss", "one_x_two.log_loss", "lower"),
    ("Exact Score Top1 hit", "exact_score.top1_hit_rate", "higher"),
    ("Exact Score Top3 hit", "exact_score.top3_hit_rate", "higher"),
    ("Actual-score probability", "exact_score.mean_probability_assigned_to_actual_score", "higher"),
    ("Exact Score NLL", "exact_score.nll", "lower"),
    ("BTTS accuracy", "btts.accuracy", "higher"),
    ("BTTS Brier", "btts.brier", "lower"),
    ("O/U 2.5 accuracy", "ou_2_5.accuracy", "higher"),
    ("O/U 2.5 Brier", "ou_2_5.brier", "lower"),
    ("1X2 macro ECE", "one_x_two.ece", "lower"),
    ("BTTS ECE", "btts.ece", "lower"),
    ("O/U 2.5 ECE", "ou_2_5.ece", "lower"),
    ("1-1 Top1 share", "distribution.one_one_top1_share", "lower"),
    ("Top1 support size", "distribution.top1_support_size", "higher"),
    ("High-score Top1 share", "distribution.high_score_top1_share", "higher"),
    ("Gap <0.5 share", "distribution.gap_lt_0_5_share", "lower"),
    ("Median absolute lambda gap", "distribution.absolute_gap.P50", "higher"),
    ("Mean P(total >=4)", "distribution.mean_probability_total_ge_4", "higher"),
)


def _tradeoff_status(value: float, champion: float, direction: str) -> str:
    delta = value - champion
    if abs(delta) <= SAME_TOLERANCE:
        return "SAME"
    better = delta > 0 if direction == "higher" else delta < 0
    return "BETTER" if better else "WORSE"


def _tradeoff_table(metrics_by_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    champion = metrics_by_id["champion"]
    table = []
    for label, path, direction in TRADEOFF_METRICS:
        row = {
            "metric": label,
            "path": path,
            "direction": f"{direction}_is_better",
            "champion": _round(_metric_value(champion, path), 9),
        }
        for candidate_id in ("challenger_a_strength_separation", "challenger_b_market_to_goal_separation"):
            value = _metric_value(metrics_by_id[candidate_id], path)
            row[candidate_id] = {
                "value": _round(value, 9),
                "status": _tradeoff_status(value, _metric_value(champion, path), direction),
                "delta_vs_champion": _round(value - _metric_value(champion, path), 9),
            }
        table.append(row)
    return table


def _actual_tail_reference(verified_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    scores = [_score_pair(row.get("actual_score")) for row in verified_by_id.values()]
    scores = [score for score in scores if score is not None]
    count = len(scores)
    return {
        "sample_count": count,
        "actual_total_ge_4_share": sum(home + away >= 4 for home, away in scores) / count,
        "actual_total_ge_5_share": sum(home + away >= 5 for home, away in scores) / count,
        "actual_total_ge_6_share": sum(home + away >= 6 for home, away in scores) / count,
        "actual_score_support_size": len({_score_text(score) for score in scores}),
    }


def _qualification(
    candidate_id: str,
    metrics: Mapping[str, Any],
    champion: Mapping[str, Any],
    actual_tail: Mapping[str, Any],
) -> dict[str, Any]:
    c = metrics["distribution"]
    b = champion["distribution"]
    exact = metrics["exact_score"]
    exact_base = champion["exact_score"]
    one = metrics["one_x_two"]
    one_base = champion["one_x_two"]
    btts = metrics["btts"]
    btts_base = champion["btts"]
    ou = metrics["ou_2_5"]
    ou_base = champion["ou_2_5"]
    tail_error = abs(c["mean_probability_total_ge_4"] - actual_tail["actual_total_ge_4_share"])
    base_tail_error = abs(b["mean_probability_total_ge_4"] - actual_tail["actual_total_ge_4_share"])
    checks = {
        "concentration_materially_improves": c["one_one_top1_share"] <= b["one_one_top1_share"] - 0.10,
        "top1_support_expands": c["top1_support_size"] >= b["top1_support_size"] + 1,
        "exact_top1_not_unacceptable": exact["top1_hit_rate"] >= exact_base["top1_hit_rate"] - 0.03,
        "exact_top3_not_unacceptable": exact["top3_hit_rate"] >= exact_base["top3_hit_rate"] - 0.03,
        "actual_score_probability_not_unacceptable": exact["mean_probability_assigned_to_actual_score"] >= exact_base["mean_probability_assigned_to_actual_score"] - 0.01,
        "one_x_two_brier_not_materially_worse": one["brier"] <= one_base["brier"] + 0.01,
        "one_x_two_log_loss_not_materially_worse": one["log_loss"] <= one_base["log_loss"] + 0.02,
        "btts_not_materially_worse": btts["brier"] <= btts_base["brier"] + 0.01 and btts["accuracy"] >= btts_base["accuracy"] - 0.03,
        "ou_not_materially_worse": ou["brier"] <= ou_base["brier"] + 0.01 and ou["accuracy"] >= ou_base["accuracy"] - 0.03,
        "lambda_gap_distribution_separates": c["gap_lt_0_5_share"] <= b["gap_lt_0_5_share"] - 0.05 and c["absolute_gap"]["P50"] >= b["absolute_gap"]["P50"] + 0.05,
        "right_tail_probability_not_worse": tail_error <= base_tail_error + 0.02,
    }
    return {
        "candidate_id": candidate_id,
        "checks": checks,
        "qualified_for_shadow": all(checks.values()),
        "right_tail": {
            "candidate_mean_p_total_ge_4": c["mean_probability_total_ge_4"],
            "actual_total_ge_4_share": actual_tail["actual_total_ge_4_share"],
            "absolute_error": tail_error,
            "champion_absolute_error": base_tail_error,
        },
        "thresholds": {
            "one_one_share_reduction": 0.10,
            "top1_support_increase": 1,
            "lambda_gap_lt_0_5_reduction": 0.05,
            "median_gap_increase": 0.05,
            "proper_metric_tolerance": 0.01,
            "hit_rate_tolerance": 0.03,
            "log_loss_tolerance": 0.02,
            "right_tail_error_tolerance": 0.02,
        },
    }


def _prepare_row(record: Mapping[str, Any], model: Mapping[str, Any], candidate: Mapping[str, Any], matrix: dict[tuple[int, int], float]) -> dict[str, Any]:
    ordered = _sorted_scores(matrix)
    summary = _matrix_summary(matrix)
    return {
        "prediction_id": str(record["prediction_id"]),
        "match_id": str(record.get("match_id") or ""),
        "kickoff_at": str(record.get("kickoff_at") or ""),
        "lambda_home": float(candidate["lambda_home"]),
        "lambda_away": float(candidate["lambda_away"]),
        "top1_pair": ordered[0][0],
        "top3_pairs": [score for score, _ in ordered[:3]],
        "probabilities": _outcome_probabilities(matrix),
        "btts_probability": _btts_probability(matrix),
        "over_2_5_probability": _over_probability(matrix),
        "tail": summary,
        "matrix": matrix,
        "champion_model": model,
    }


def run_replay(
    *,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    audit_path: Path = DEFAULT_AUDIT,
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    records, manifest = _load_pinned_records(root, manifest_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    verified_rows = audit.get("prospective_evaluation", {}).get("evaluated_rows") or []
    verified_by_id = {str(row["prediction_id"]): row for row in verified_rows if row.get("prediction_id")}
    if len(verified_by_id) != 181 or not set(verified_by_id).issubset({record["prediction_id"] for record in records}):
        raise ValueError("PRED-TRUST-1 verified prospective pin must contain 181 selected matches")

    candidate_rows: dict[str, list[dict[str, Any]]] = {spec["candidate_id"]: [] for spec in CANDIDATE_SPECS}
    champion_lambda_deltas = []
    input_status = Counter()
    calibration_states = Counter()
    for record in records:
        snapshot_ref = str(record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or "")
        snapshot = json.loads((root / snapshot_ref).read_text(encoding="utf-8"))
        context = snapshot.get("input") or {}
        model_result = build_automatic_model(context)
        champion_model = model_result.get("model") if isinstance(model_result, dict) else None
        if not isinstance(champion_model, dict):
            raise ValueError(f"Champion replay returned no model for {record['prediction_id']}")
        inputs = _form_and_market_inputs(context)
        input_status["venue_proxy_used" if inputs["venue_proxy_used"] else "venue_split"] += 1
        closed_loop = ((champion_model.get("calibration") or {}).get("closed_loop") or {})
        calibration_states["active" if closed_loop.get("active") else "inactive"] += 1
        derived_champion = derive_candidate_lambdas(
            "champion",
            form_home=inputs["form_home"],
            form_away=inputs["form_away"],
            market_total=inputs["market_total"],
            market_share=inputs["market_share"],
            form_total=inputs["form_total"],
        )
        champion_lambda_deltas.extend(
            [
                abs(float(champion_model["lambda_home"]) - float(derived_champion["lambda_home"])),
                abs(float(champion_model["lambda_away"]) - float(derived_champion["lambda_away"])),
            ]
        )
        for spec in CANDIDATE_SPECS:
            candidate_id = spec["candidate_id"]
            if candidate_id == "champion":
                candidate = {
                    **derived_champion,
                    "lambda_home": float(champion_model["lambda_home"]),
                    "lambda_away": float(champion_model["lambda_away"]),
                }
            else:
                candidate = derive_candidate_lambdas(
                    candidate_id,
                    form_home=inputs["form_home"],
                    form_away=inputs["form_away"],
                    market_total=inputs["market_total"],
                    market_share=inputs["market_share"],
                    form_total=inputs["form_total"],
                )
            matrix = build_score_matrix(float(candidate["lambda_home"]), float(candidate["lambda_away"]))
            candidate_rows[candidate_id].append(_prepare_row(record, champion_model, candidate, matrix))

    max_absolute_lambda_delta = max(champion_lambda_deltas) if champion_lambda_deltas else None
    if max_absolute_lambda_delta is None or max_absolute_lambda_delta > 1e-6:
        raise ValueError(
            "Champion replay did not reproduce the frozen lambda chain within 1e-6: "
            f"max_delta={max_absolute_lambda_delta}"
        )

    metrics_by_id = {
        candidate_id: _evaluate_candidate(rows, verified_by_id)
        for candidate_id, rows in candidate_rows.items()
    }
    actual_tail = _actual_tail_reference(verified_by_id)
    champion = metrics_by_id["champion"]
    qualifications = [
        _qualification(candidate_id, metrics_by_id[candidate_id], champion, actual_tail)
        for candidate_id in ("challenger_a_strength_separation", "challenger_b_market_to_goal_separation")
    ]
    qualified = [row["candidate_id"] for row in qualifications if row["qualified_for_shadow"]]
    if qualified:
        decision = "PROMISING_FOR_SHADOW"
        next_milestone = "bounded prospective shadow"
    else:
        decision = "NO_CHALLENGER_BEATS_CHAMPION"
        next_milestone = "return to inputs / football evidence / market fusion; do not continue lambda patch series"
    result = {
        "schema_version": "pred_trust_2.replay.v1",
        "milestone": "PRED-TRUST-2",
        "status": "READY_FOR_ACCEPTANCE",
        "decision": decision,
        "generated_at": "2026-08-30T00:00:00+08:00",
        "source": {
            "accepted_production_run": ACCEPTED_PRODUCTION_RUN,
            "accepted_writeback_commit": ACCEPTED_WRITEBACK_COMMIT,
            "pred_trust_1_head": PINNED_PRED_TRUST_1_HEAD,
            "audit_artifact_sha256": _sha256_file(audit_path),
            "cohort_manifest_sha256": _sha256_file(manifest_path),
            "no_new_data": True,
            "post_match_fields_used_only_for_evaluation": True,
        },
        "cohort": {
            "raw_prediction_rows_loaded_from_current_tree": len(_load_prediction_records(root)),
            "pinned_unique_final_legal_prematch_matches": len(records),
            "verified_90m_matches": len(verified_by_id),
            "unverified_pinned_matches": len(records) - len(verified_by_id),
            "selected_prediction_digest": manifest["selected_prediction_digest"],
            "verified_prediction_digest": manifest["verified_prediction_digest"],
            "integrity": "record and input snapshot hashes matched the accepted write-back pin",
        },
        "dependency_map": {
            "football_evidence": "frozen source_snapshots.shuju.recent_form",
            "recent_form": "venue-specific and overall goals for/against -> form_home/form_away",
            "market_baseline": "frozen multi-book 1X2 consensus + total line",
            "strength_representation": "form_share = clipped form_home / (form_home + form_away)",
            "calibration": "embedded Champion calibration is inactive/shadow_only in the pinned inputs",
            "lambda_home_away": "total * side_share; Champion total=0.60 form + 0.40 market, share=0.65 form + 0.35 market",
            "probability_state": "independent Poisson score matrix with rho=0 -> 1X2, BTTS, totals, exact score",
        },
        "candidate_specs": list(CANDIDATE_SPECS),
        "reproduction": {
            "candidate_count": len(CANDIDATE_SPECS),
            "champion_formula_replay_rows": len(candidate_rows["champion"]),
            "max_absolute_lambda_delta": max_absolute_lambda_delta,
            "selector_recomputed": False,
            "post_match_parameter_input": False,
            "input_status": dict(sorted(input_status.items())),
            "calibration_state": dict(sorted(calibration_states.items())),
        },
        "actual_tail_reference": actual_tail,
        "metrics_by_candidate": {
            candidate_id: {
                key: value
                for key, value in metrics.items()
                if key != "evaluated_rows"
            }
            for candidate_id, metrics in metrics_by_id.items()
        },
        "tradeoff_table": _tradeoff_table(metrics_by_id),
        "qualification": qualifications,
        "product_interpretation": {
            "recommended_choice": "D. single Top1 + uncertainty warning",
            "reason": "Keep the current exact-score contract while explicitly warning that the single Top1 is concentrated and not a high-confidence claim; do not change frontend in this milestone.",
        },
        "next_single_milestone": next_milestone,
        "stop_state": {
            "champion_modified": False,
            "production_enabled": False,
            "shadow_enabled": False,
            "frozen_predictions_rewritten": False,
            "prospective_ledger_rewritten": False,
            "health_monitor_modified": False,
            "health_gate_modified": False,
            "new_provider_added": False,
            "parameter_sweep": False,
            "offline_batches": 1,
        },
    }
    _write_json(output_path, result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(result), encoding="utf-8")
    return result


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "—"
        return f"{value:.4f}"
    return str(value)


def render_markdown(result: Mapping[str, Any]) -> str:
    metrics = result["metrics_by_candidate"]
    labels = {
        "champion": "Champion",
        "challenger_a_strength_separation": "Challenger A",
        "challenger_b_market_to_goal_separation": "Challenger B",
    }
    lines = [
        "# PRED-TRUST-2 — Strength/Lambda Challenger Shootout",
        "",
        f"Status: `{result['status']}`  ",
        f"Decision: `{result['decision']}`",
        "",
        "## Scope and pinned evidence",
        "",
        f"- Accepted production run: `{result['source']['accepted_production_run']}`",
        f"- Accepted write-back commit: `{result['source']['accepted_writeback_commit']}`",
        f"- PRED-TRUST-1 head: `{result['source']['pred_trust_1_head']}`",
        f"- Replay cohort: `{result['cohort']['pinned_unique_final_legal_prematch_matches']}` unique final legal prematch matches; `{result['cohort']['verified_90m_matches']}` verified 90m results",
        "- No new data, no parameter fitting, and no post-match field entered lambda generation.",
        "",
        "## Short dependency map",
        "",
        "```text",
        "football evidence → recent form → form_home/form_away → strength share",
        "market baseline → frozen 1X2 + total line → market share/target total",
        "strength + market boundary → lambda_home/lambda_away",
        "lambda → independent Poisson matrix (rho=0) → 1X2 / BTTS / totals / exact score",
        "calibration is present in the contract but inactive/shadow_only in this pin",
        "```",
        "",
        "## Candidate registry",
        "",
        "| Candidate | Fixed hypothesis | Changed boundary |",
        "|---|---|---|",
    ]
    for spec in result["candidate_specs"]:
        lines.append(f"| {spec['label']} | `{spec['hypothesis']}` | {spec['boundary_changed']} |")
    lines.extend(["", "## Verified 90m metrics", "", "| Metric | Champion | Challenger A | Challenger B |", "|---|---:|---:|---:|"])
    paths = (
        ("1X2 accuracy", "one_x_two.accuracy"),
        ("1X2 Brier", "one_x_two.brier"),
        ("1X2 LogLoss", "one_x_two.log_loss"),
        ("Exact Top1 hit", "exact_score.top1_hit_rate"),
        ("Exact Top3 hit", "exact_score.top3_hit_rate"),
        ("Actual-score probability", "exact_score.mean_probability_assigned_to_actual_score"),
        ("BTTS accuracy", "btts.accuracy"),
        ("BTTS Brier", "btts.brier"),
        ("O/U 2.5 accuracy", "ou_2_5.accuracy"),
        ("O/U 2.5 Brier", "ou_2_5.brier"),
        ("1X2 macro ECE", "one_x_two.ece"),
    )
    for label, path in paths:
        values = [_metric_value(metrics[candidate], path) for candidate in labels]
        lines.append(f"| {label} | " + " | ".join(_fmt(value) for value in values) + " |")
    lines.extend(["", "## Lambda and score diversity", "", "| Metric | Champion | Challenger A | Challenger B |", "|---|---:|---:|---:|"])
    paths = (
        ("1-1 Top1 share", "distribution.one_one_top1_share"),
        ("Top1 support size", "distribution.top1_support_size"),
        ("High-score Top1 share", "distribution.high_score_top1_share"),
        ("Gap <0.5 share", "distribution.gap_lt_0_5_share"),
        ("Median absolute lambda gap", "distribution.absolute_gap.P50"),
        ("Mean P(total >=4)", "distribution.mean_probability_total_ge_4"),
        ("Mean P(total >=5)", "distribution.mean_probability_total_ge_5"),
        ("Mean P(total >=6)", "distribution.mean_probability_total_ge_6"),
    )
    for label, path in paths:
        values = [_metric_value(metrics[candidate], path) for candidate in labels]
        lines.append(f"| {label} | " + " | ".join(_fmt(value) for value in values) + " |")
    actual = result["actual_tail_reference"]
    lines.extend([
        "",
        f"Actual verified tail reference: `P(total>=4)={actual['actual_total_ge_4_share']:.4f}`, `P(total>=5)={actual['actual_total_ge_5_share']:.4f}`, `P(total>=6)={actual['actual_total_ge_6_share']:.4f}` over `n={actual['sample_count']}`.",
        "",
        "## Machine trade-off table",
        "",
        "Every challenger cell is marked against Champion using the pre-registered `±0.005` SAME tolerance.",
        "",
        "| Metric | Champion | Challenger A value/status | Challenger B value/status |",
        "|---|---:|---:|---:|",
    ])
    for row in result["tradeoff_table"]:
        a, b = row["challenger_a_strength_separation"], row["challenger_b_market_to_goal_separation"]
        lines.append(f"| {row['metric']} | {_fmt(row['champion'])} | {_fmt(a['value'])} / **{a['status']}** | {_fmt(b['value'])} / **{b['status']}** |")
    lines.extend(["", "## Qualification and decision", ""])
    for row in result["qualification"]:
        failed = [key for key, value in row["checks"].items() if not value]
        lines.append(f"- `{row['candidate_id']}`: `{'PASS' if row['qualified_for_shadow'] else 'FAIL'}`; failed checks: `{', '.join(failed) if failed else 'none'}`.")
    lines.extend([
        "",
        f"Final bounded decision: **{result['decision']}**.",
        f"Unique next milestone: **{result['next_single_milestone']}**.",
        "",
        "## Product interpretation",
        "",
        f"Preferred option: **{result['product_interpretation']['recommended_choice']}**.",
        result["product_interpretation"]["reason"],
        "",
        "## STOP state",
        "",
        "Champion, production, shadow, frozen predictions, prospective ledger, health monitor, health gate, providers, UI, and parameter sweeps were not changed.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="root containing frozen inputs")
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--cohort-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--write-cohort-manifest", action="store_true")
    args = parser.parse_args(argv)
    if args.write_cohort_manifest:
        manifest = write_cohort_manifest(root=args.root, audit_path=args.audit, output=args.cohort_manifest)
        print(json.dumps({"status": "OK", "selected_match_count": manifest["selected_match_count"], "verified_match_count": manifest["verified_match_count"], "output": str(args.cohort_manifest)}, ensure_ascii=False))
        return 0
    result = run_replay(root=args.root, manifest_path=args.cohort_manifest, audit_path=args.audit, output_path=args.output, report_path=args.report)
    print(json.dumps({"status": result["status"], "decision": result["decision"], "output": str(args.output), "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
