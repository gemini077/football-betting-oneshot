#!/usr/bin/env python3
"""Post-match settlement and proper-scoring metrics for benchmark records."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

from baseline_shadow_runner import (
    BENCHMARK_CONTRACT_VERSION,
    BenchmarkConflictError,
)


OUTCOMES = ("home", "draw", "away")
DEFAULT_SETTLEMENT_ROOT = Path(__file__).resolve().parents[1] / "data" / "model_benchmarks" / "settlements"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _actual_result(result: Any) -> dict[str, int]:
    if isinstance(result, (tuple, list)) and len(result) == 2:
        home_goals, away_goals = result
    elif isinstance(result, dict):
        home_goals = result.get("home_goals", result.get("home"))
        away_goals = result.get("away_goals", result.get("away"))
    else:
        raise ValueError("actual result must contain home and away goals")
    home_number = _number(home_goals)
    away_number = _number(away_goals)
    if home_number is None or away_number is None or home_number < 0 or away_number < 0:
        raise ValueError("actual goals must be finite non-negative numbers")
    if int(home_number) != home_number or int(away_number) != away_number:
        raise ValueError("actual goals must be whole numbers")
    return {"home_goals": int(home_number), "away_goals": int(away_number)}


def _outcome(actual: dict[str, int]) -> str:
    if actual["home_goals"] > actual["away_goals"]:
        return "home"
    if actual["home_goals"] < actual["away_goals"]:
        return "away"
    return "draw"


def _probabilities(prediction: dict[str, Any]) -> dict[str, float] | None:
    values = prediction.get("probabilities") or prediction.get("outcome_probabilities")
    if not isinstance(values, dict):
        return None
    numbers = {key: _number(values.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0 for value in numbers.values()):
        return None
    return {key: float(numbers[key]) for key in OUTCOMES}


def _score_rows(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [prediction.get("score_matrix"), prediction.get("score_probabilities")]
    output = prediction.get("prediction_output")
    if isinstance(output, dict):
        candidates.extend((output.get("score_matrix"), output.get("score_probabilities")))
    for candidate in candidates:
        if isinstance(candidate, list):
            rows = [row for row in candidate if isinstance(row, dict) and _number(row.get("probability")) is not None]
            if rows:
                return sorted(rows, key=lambda row: (-float(row["probability"]), str(row.get("score") or "")))
    return []


def _row_score(row: dict[str, Any]) -> tuple[int, int] | None:
    score = str(row.get("score") or "")
    if "-" in score:
        left, right = score.split("-", 1)
        try:
            return int(left), int(right)
        except ValueError:
            pass
    home = _number(row.get("home_goals"))
    away = _number(row.get("away_goals"))
    if home is not None and away is not None and int(home) == home and int(away) == away:
        return int(home), int(away)
    return None


def _expected_goals(prediction: dict[str, Any]) -> tuple[float, float] | None:
    home = _number(prediction.get("lambda_home"))
    away = _number(prediction.get("lambda_away"))
    expected = prediction.get("expected_goals")
    if isinstance(expected, dict):
        home = home if home is not None else _number(expected.get("home"))
        away = away if away is not None else _number(expected.get("away"))
    if home is None or away is None:
        return None
    return home, away


def _btts_probability(prediction: dict[str, Any], score_rows: list[dict[str, Any]]) -> float | None:
    btts = prediction.get("btts")
    if isinstance(btts, dict):
        yes = _number(btts.get("yes"))
        if yes is not None:
            return yes
    if score_rows and (prediction.get("score_matrix_complete") is True or len(score_rows) >= 100):
        return sum(
            float(row["probability"])
            for row in score_rows
            if (_row_score(row) or (-1, -1))[0] > 0 and (_row_score(row) or (-1, -1))[1] > 0
        )
    return None


def calculate_metrics(prediction: dict[str, Any], result: Any) -> dict[str, Any]:
    """Return common 1X2 metrics plus model-only score/goal diagnostics."""
    actual = _actual_result(result)
    actual_outcome = _outcome(actual)
    probabilities = _probabilities(prediction)
    common: dict[str, Any] = {
        "actual_outcome": actual_outcome,
        "actual_score": f"{actual['home_goals']}-{actual['away_goals']}",
        "brier_score_1x2": None,
        "log_loss_1x2": None,
        "top1_accuracy_1x2": None,
        "brier": None,
        "log_loss": None,
        "top1": None,
        "top1_accuracy": None,
        "btts_probability": None,
        "btts_actual": None,
        "btts_hit": None,
        "btts_accuracy": None,
        "total_goal_error": None,
        "total_goal_absolute_error": None,
        "expected_goal_error": None,
        "expected_goal_error_home": None,
        "expected_goal_error_away": None,
        "score_top1": None,
        "score_top3": None,
        "score_top5": None,
        "exact_score_top1": None,
        "exact_score_top3": None,
        "exact_score_top5": None,
        "actual_score_rank": None,
        "actual_score_probability": None,
        "actual_score_assigned_probability": None,
        "roi": None,
        "clv": None,
    }
    if probabilities is not None:
        one_hot = {key: 1.0 if key == actual_outcome else 0.0 for key in OUTCOMES}
        brier = sum((probabilities[key] - one_hot[key]) ** 2 for key in OUTCOMES)
        actual_probability = max(probabilities[actual_outcome], 1e-15)
        log_loss = -math.log(actual_probability)
        top = max(OUTCOMES, key=lambda key: probabilities[key])
        common.update({
            "brier_score_1x2": brier,
            "log_loss_1x2": log_loss,
            "top1_accuracy_1x2": int(top == actual_outcome),
            "brier": brier,
            "log_loss": log_loss,
            "top1": int(top == actual_outcome),
            "top1_accuracy": int(top == actual_outcome),
        })

    model_name = str(prediction.get("model") or "").lower()
    if model_name in {"market", "market_reference"}:
        return common

    score_rows = _score_rows(prediction)
    actual_pair = (actual["home_goals"], actual["away_goals"])
    if score_rows:
        matching = [(index + 1, float(row["probability"])) for index, row in enumerate(score_rows) if _row_score(row) == actual_pair]
        if matching:
            common["actual_score_rank"] = matching[0][0]
            common["actual_score_probability"] = matching[0][1]
            common["actual_score_assigned_probability"] = matching[0][1]
        common["score_top1"] = any(_row_score(row) == actual_pair for row in score_rows[:1])
        common["score_top3"] = any(_row_score(row) == actual_pair for row in score_rows[:3])
        common["score_top5"] = any(_row_score(row) == actual_pair for row in score_rows[:5])
        common["exact_score_top1"] = common["score_top1"]
        common["exact_score_top3"] = common["score_top3"]
        common["exact_score_top5"] = common["score_top5"]

    btts_probability = _btts_probability(prediction, score_rows)
    if btts_probability is not None:
        btts_actual = actual["home_goals"] > 0 and actual["away_goals"] > 0
        common.update({
            "btts_probability": btts_probability,
            "btts_actual": btts_actual,
            "btts_hit": bool(btts_probability >= 0.5) == btts_actual,
            "btts_accuracy": bool(btts_probability >= 0.5) == btts_actual,
        })

    expected = _expected_goals(prediction)
    if expected is not None:
        home_error = actual["home_goals"] - expected[0]
        away_error = actual["away_goals"] - expected[1]
        total_error = actual["home_goals"] + actual["away_goals"] - expected[0] - expected[1]
        common.update({
            "total_goal_error": total_error,
            "total_goal_absolute_error": abs(total_error),
            "expected_goal_error": (abs(home_error) + abs(away_error)) / 2.0,
            "expected_goal_error_home": abs(home_error),
            "expected_goal_error_away": abs(away_error),
        })
    return common


def settle_comparison(
    comparison: dict[str, Any],
    actual_result: Any,
    *,
    settled_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(comparison, dict):
        raise ValueError("comparison must be an object")
    actual = _actual_result(actual_result)
    if isinstance(actual_result, dict):
        actual.update({key: actual_result[key] for key in ("regulation_minutes", "synthetic") if key in actual_result})
    predictors = comparison.get("predictors") or {}
    metrics = {
        name: calculate_metrics(prediction, actual)
        for name, prediction in predictors.items()
        if isinstance(prediction, dict)
    }
    synthetic = bool(comparison.get("synthetic") or actual.get("synthetic"))
    excluded = bool(comparison.get("excluded_from_formal_metrics") or synthetic)
    return {
        "comparison_id": comparison.get("comparison_id"),
        "benchmark_contract_version": comparison.get("benchmark_contract_version", BENCHMARK_CONTRACT_VERSION),
        "benchmark_scope": comparison.get("benchmark_scope"),
        "match_key": comparison.get("match_key"),
        "snapshot_id": comparison.get("snapshot_id"),
        "canonical_model_input_sha256": comparison.get("canonical_model_input_sha256"),
        "source_cutoff_at": comparison.get("source_cutoff_at"),
        "market_snapshot_at": comparison.get("market_snapshot_at"),
        "checkpoint_stage": comparison.get("checkpoint_stage"),
        "cohort": comparison.get("cohort"),
        "primary_benchmark_eligible": comparison.get("primary_benchmark_eligible") is True,
        "comparison_status": comparison.get("comparison_status"),
        "synthetic": synthetic,
        "excluded_from_formal_metrics": excluded,
        "actual_result": actual,
        "settled_at": settled_at,
        "metrics": metrics,
    }


def freeze_settlement(settlement: dict[str, Any], settlement_root: Path = DEFAULT_SETTLEMENT_ROOT) -> dict[str, Any]:
    comparison_id = str(settlement.get("comparison_id") or "")
    if not comparison_id:
        raise ValueError("settlement is missing comparison_id")
    root = Path(settlement_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{comparison_id}.json"
    serialized = canonical_json(settlement)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(settlement, ensure_ascii=False, indent=2) + "\n")
        return {"status": "created", "path": target, "settlement": deepcopy(settlement)}
    except FileExistsError:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BenchmarkConflictError(f"existing settlement is unreadable: {target}") from error
        if canonical_json(existing) != serialized:
            raise BenchmarkConflictError(f"settlement content conflict: {comparison_id}")
        return {"status": "existing", "path": target, "settlement": existing}


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) if isinstance(row.get(key), bool) else _number(row.get(key)) for row in rows]
    clean = [value for value in values if value is not None]
    return fmean(clean) if clean else None


def aggregate_settlements(
    settlements: list[dict[str, Any]],
    *,
    cohort: str | None = None,
    include_excluded: bool = False,
) -> dict[str, Any]:
    records_seen = len(settlements)
    eligible = [
        row for row in settlements
        if isinstance(row, dict)
        and (include_excluded or row.get("excluded_from_formal_metrics") is not True)
        and row.get("benchmark_scope") == "prospective"
        and (cohort is None or row.get("cohort") == cohort)
    ]
    by_match: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for row in eligible:
        key = str(row.get("match_key") or "")
        if key in by_match:
            duplicates += 1
            continue
        by_match[key] = row
    unique_rows = list(by_match.values())
    model_names = ("market_reference", "simple_poisson", "champion")
    metric_names = (
        "brier_score_1x2", "log_loss_1x2", "top1_accuracy_1x2",
        "btts_hit", "total_goal_error", "total_goal_absolute_error",
        "expected_goal_error", "score_top1", "score_top3", "score_top5",
        "actual_score_rank", "actual_score_probability",
    )
    aggregate: dict[str, dict[str, Any]] = {}
    for model_name in model_names:
        rows = [row.get("metrics", {}).get(model_name, {}) for row in unique_rows]
        aggregate[model_name] = {key: _mean_metric(rows, key) for key in metric_names}
    return {
        "benchmark_contract_version": BENCHMARK_CONTRACT_VERSION,
        "cohort": cohort,
        "records_seen": records_seen,
        "formal_records": len(eligible),
        "excluded_records": records_seen - len(eligible),
        "unique_match_count": len(unique_rows),
        "duplicate_checkpoint_records_excluded": duplicates,
        "metrics": aggregate,
    }
