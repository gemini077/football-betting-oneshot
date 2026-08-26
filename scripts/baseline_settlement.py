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
SHADOW_MODEL_NAME = "market_direction_fusion_full_v1"


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


def _metric_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return _number(value)


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


def _full_score_rows(prediction: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    rows = _score_rows(prediction)
    if prediction.get("score_matrix_complete") is True:
        return rows, bool(rows)
    if prediction.get("derive_full_matrix") is not True:
        return rows, False
    expected = _expected_goals(prediction)
    if expected is None:
        return rows, False
    try:
        from risk_engine import dixon_coles_score_matrix

        matrix = dixon_coles_score_matrix({
            "lambda_home": expected[0],
            "lambda_away": expected[1],
            "rho": _number(prediction.get("rho")) or 0.0,
        })
    except (ImportError, TypeError, ValueError):
        return rows, False
    return _score_rows({
        "score_matrix": [
            {"score": f"{home}-{away}", "home_goals": home, "away_goals": away, "probability": probability}
            for (home, away), probability in matrix.items()
        ],
    }), bool(matrix)


def _ece(rows: list[dict[str, Any]], model_name: str, bins: int = 10) -> float | None:
    values: list[float] = []
    for outcome in OUTCOMES:
        buckets: dict[int, list[tuple[float, int]]] = {}
        for row in rows:
            metrics = (row.get("metrics") or {}).get(model_name) or {}
            probabilities = metrics.get("outcome_probabilities")
            actual = metrics.get("actual_outcome")
            if not isinstance(probabilities, dict) or actual not in OUTCOMES:
                continue
            probability = _number(probabilities.get(outcome))
            if probability is None:
                continue
            bucket = min(bins - 1, int(probability * bins))
            buckets.setdefault(bucket, []).append((probability, int(actual == outcome)))
        if not buckets:
            continue
        total = sum(len(items) for items in buckets.values())
        values.append(sum(
            len(items) / total
            * abs(fmean(probability for probability, _ in items) - fmean(actual for _, actual in items))
            for items in buckets.values()
        ))
    return fmean(values) if values else None


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


def _prediction_evaluable(prediction: dict[str, Any] | None) -> bool:
    probabilities = _probabilities(prediction or {})
    return probabilities is not None


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
        "outcome_probabilities": None,
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
        "score_top10": None,
        "exact_score_top1": None,
        "exact_score_top3": None,
        "exact_score_top5": None,
        "exact_score_top10": None,
        "actual_score_rank": None,
        "actual_score_probability": None,
        "actual_score_assigned_probability": None,
        "actual_score_nll": None,
        "total_goals_nll": None,
        "lambda_sum": None,
        "lambda_gap": None,
        "lambda_gap_lt_0_5": None,
        "top1_1_1": None,
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
            "outcome_probabilities": probabilities,
        })

    model_name = str(prediction.get("model") or "").lower()
    if model_name in {"market", "market_reference"}:
        return common

    score_rows, full_score_matrix = _full_score_rows(prediction)
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
        common["score_top10"] = any(_row_score(row) == actual_pair for row in score_rows[:10])
        common["exact_score_top1"] = common["score_top1"]
        common["exact_score_top3"] = common["score_top3"]
        common["exact_score_top5"] = common["score_top5"]
        common["exact_score_top10"] = common["score_top10"]
        common["top1_1_1"] = _row_score(score_rows[0]) == (1, 1)
        if full_score_matrix:
            actual_total = actual["home_goals"] + actual["away_goals"]
            total_probability = sum(
                float(row["probability"])
                for row in score_rows
                if (_row_score(row) or (-1, -1))[0] + (_row_score(row) or (-1, -1))[1] == actual_total
            )
            if total_probability > 0:
                common["total_goals_nll"] = -math.log(max(total_probability, 1e-15))
            if matching and matching[0][1] > 0:
                common["actual_score_nll"] = -math.log(max(matching[0][1], 1e-15))

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
            "lambda_sum": expected[0] + expected[1],
            "lambda_gap": abs(expected[0] - expected[1]),
            "lambda_gap_lt_0_5": abs(expected[0] - expected[1]) < 0.5,
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
    evaluable = {
        "market_reference": comparison.get("market_evaluable") is True
        if "market_evaluable" in comparison
        else _prediction_evaluable(predictors.get("market_reference")),
        "simple_poisson": comparison.get("simple_evaluable") is True
        if "simple_evaluable" in comparison
        else _prediction_evaluable(predictors.get("simple_poisson")),
        "champion": comparison.get("champion_evaluable") is True
        if "champion_evaluable" in comparison
        else _prediction_evaluable(predictors.get("champion")),
    }
    if SHADOW_MODEL_NAME in predictors:
        evaluable[SHADOW_MODEL_NAME] = comparison.get("market_direction_fusion_evaluable") is True
    return {
        "comparison_id": comparison.get("comparison_id"),
        "benchmark_contract_version": comparison.get("benchmark_contract_version", BENCHMARK_CONTRACT_VERSION),
        "benchmark_scope": comparison.get("benchmark_scope"),
        "prospective_origin": comparison.get("prospective_origin"),
        "match_key": comparison.get("match_key"),
        "snapshot_id": comparison.get("snapshot_id"),
        "canonical_model_input_sha256": comparison.get("canonical_model_input_sha256"),
        "source_cutoff_at": comparison.get("source_cutoff_at"),
        "market_snapshot_at": comparison.get("market_snapshot_at"),
        "checkpoint_stage": comparison.get("checkpoint_stage"),
        "checkpoint_target_at": comparison.get("checkpoint_target_at"),
        "checkpoint_captured_at": comparison.get("checkpoint_captured_at"),
        "minutes_to_kickoff_at_capture": comparison.get("minutes_to_kickoff_at_capture"),
        "cohort": comparison.get("cohort"),
        "primary_benchmark_eligible": comparison.get("primary_benchmark_eligible") is True,
        "comparison_status": comparison.get("comparison_status"),
        "status_reason": comparison.get("status_reason"),
        "same_snapshot": comparison.get("same_snapshot") is True,
        "snapshot_consistent": comparison.get("snapshot_consistent") is True,
        "market_evaluable": evaluable["market_reference"],
        "market_missing_reason": comparison.get("market_missing_reason"),
        "simple_evaluable": evaluable["simple_poisson"],
        "simple_missing_reason": comparison.get("simple_missing_reason"),
        "champion_evaluable": evaluable["champion"],
        "champion_missing_reason": comparison.get("champion_missing_reason"),
        "market_direction_fusion_evaluable": evaluable.get(SHADOW_MODEL_NAME),
        "market_direction_fusion_missing_reason": comparison.get("shadow_failure_reason"),
        "candidate_id": comparison.get("candidate_id"),
        "candidate_version": comparison.get("candidate_version"),
        "shadow_status": comparison.get("shadow_status"),
        "shadow_created_at": comparison.get("shadow_created_at"),
        "changed_variables": comparison.get("changed_variables"),
        "prospective_shadow": comparison.get("prospective_shadow") is True,
        "user_visible": comparison.get("user_visible") is True,
        "formal_eligible": comparison.get("formal_eligible") is True,
        "promotion_eligible": comparison.get("promotion_eligible") is True,
        "source_champion_prediction_id": comparison.get("source_champion_prediction_id"),
        "source_champion_prediction_ref": comparison.get("source_champion_prediction_ref"),
        "snapshot_hash": comparison.get("snapshot_hash"),
        "champion_total": comparison.get("champion_total"),
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
    values = [_metric_number(row.get(key)) for row in rows]
    clean = [value for value in values if value is not None]
    return fmean(clean) if clean else None


def aggregate_settlements(
    settlements: list[dict[str, Any]],
    *,
    cohort: str | None = None,
    include_excluded: bool = False,
) -> dict[str, Any]:
    records_seen = len(settlements)
    scope_rows = [
        row for row in settlements
        if isinstance(row, dict)
        and row.get("benchmark_scope") == "prospective"
        and (cohort is None or row.get("cohort") == cohort)
    ]

    def formal_candidate(row: dict[str, Any]) -> bool:
        return (
            row.get("benchmark_scope") == "prospective"
            and row.get("prospective_origin") == "production_new_freeze"
            and row.get("comparison_status") == "complete"
            and row.get("same_snapshot") is True
            and row.get("synthetic") is False
            and row.get("excluded_from_formal_metrics") is False
        )

    eligible = [row for row in scope_rows if formal_candidate(row)]
    primary_rows = [
        row for row in eligible
        if row.get("cohort") == "primary" and row.get("primary_benchmark_eligible") is True
    ]

    def grouped(rows: list[dict[str, Any]], key_fn) -> dict[Any, list[dict[str, Any]]]:
        groups: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(key_fn(row), []).append(row)
        return groups

    primary_groups = grouped(primary_rows, lambda row: str(row.get("match_key") or ""))
    duplicate_primary_conflicts = sorted(
        key for key, rows in primary_groups.items() if len(rows) > 1
    )
    primary_clean = [
        row for key, rows in primary_groups.items()
        if key not in duplicate_primary_conflicts
        for row in rows
    ]

    secondary_rows = [row for row in eligible if row.get("cohort") == "secondary"]
    secondary_groups = grouped(
        secondary_rows,
        lambda row: (str(row.get("checkpoint_stage") or "unclassified"), str(row.get("match_key") or "")),
    )
    duplicate_secondary_conflicts = sorted(
        f"{stage}:{match_key}" for (stage, match_key), rows in secondary_groups.items() if len(rows) > 1
    )

    def mean_for(rows: list[dict[str, Any]], model_name: str, key: str) -> float | None:
        return _mean_metric(
            [row.get("metrics", {}).get(model_name, {}) for row in rows],
            key,
        )

    def paired_3way(rows: list[dict[str, Any]]) -> dict[str, Any]:
        paired = [
            row for row in rows
            if row.get("market_evaluable") is True
            and row.get("simple_evaluable") is True
            and row.get("champion_evaluable") is True
        ]
        paired = sorted(paired, key=lambda row: str(row.get("match_key") or ""))
        return {
            "n": len(paired),
            "match_keys": [str(row.get("match_key") or "") for row in paired],
            "market_reference": {
                "brier": mean_for(paired, "market_reference", "brier_score_1x2"),
                "log_loss": mean_for(paired, "market_reference", "log_loss_1x2"),
                "top1": mean_for(paired, "market_reference", "top1_accuracy_1x2"),
            },
            "simple_poisson": {
                "brier": mean_for(paired, "simple_poisson", "brier_score_1x2"),
                "log_loss": mean_for(paired, "simple_poisson", "log_loss_1x2"),
                "top1": mean_for(paired, "simple_poisson", "top1_accuracy_1x2"),
            },
            "champion": {
                "brier": mean_for(paired, "champion", "brier_score_1x2"),
                "log_loss": mean_for(paired, "champion", "log_loss_1x2"),
                "top1": mean_for(paired, "champion", "top1_accuracy_1x2"),
            },
        }

    def paired_model_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
        availability = [
            row for row in rows
            if row.get("simple_evaluable") is True and row.get("champion_evaluable") is True
        ]
        availability = sorted(availability, key=lambda row: str(row.get("match_key") or ""))

        def metric_comparison(metric_key: str) -> dict[str, Any]:
            paired: list[tuple[str, float, float]] = []
            for row in availability:
                metrics = row.get("metrics") or {}
                simple_value = _metric_number((metrics.get("simple_poisson") or {}).get(metric_key))
                champion_value = _metric_number((metrics.get("champion") or {}).get(metric_key))
                if simple_value is not None and champion_value is not None:
                    paired.append((str(row.get("match_key") or ""), simple_value, champion_value))
            paired.sort(key=lambda item: item[0])
            return {
                "n": len(paired),
                "match_keys": [item[0] for item in paired],
                "simple_poisson": fmean(item[1] for item in paired) if paired else None,
                "champion": fmean(item[2] for item in paired) if paired else None,
            }

        unsupported = {
            "actual_score_rank": {
                "status": "unsupported_for_champion_full_distribution",
                "reason": "champion_frozen_distribution_is_top10_only",
                "n": 0,
                "match_keys": [],
                "simple_poisson": None,
                "champion": None,
            },
            "actual_score_probability": {
                "status": "unsupported_until_full_champion_distribution_is_frozen",
                "reason": "champion_frozen_distribution_is_top10_only",
                "n": 0,
                "match_keys": [],
                "simple_poisson": None,
                "champion": None,
            },
        }
        metrics = {
            "btts_accuracy": metric_comparison("btts_hit"),
            "total_goal_absolute_error": metric_comparison("total_goal_absolute_error"),
            "expected_goal_error": metric_comparison("expected_goal_error"),
            "score_top1": metric_comparison("score_top1"),
            "score_top3": metric_comparison("score_top3"),
            "score_top5": metric_comparison("score_top5"),
            "score_top10": metric_comparison("score_top10"),
            **unsupported,
        }
        return {
            "sample_scope": "availability_diagnostic_only",
            "availability": {
                "n": len(availability),
                "match_keys": [str(row.get("match_key") or "") for row in availability],
            },
            "metrics": metrics,
        }

    def paired_shadow_research(rows: list[dict[str, Any]]) -> dict[str, Any]:
        shadow_rows = [
            row for row in rows
            if row.get("prospective_shadow") is True
            and row.get("candidate_id") == "market-direction-fusion-full-v1"
            and row.get("market_direction_fusion_evaluable") is True
            and row.get("champion_evaluable") is True
        ]
        shadow_rows = sorted(shadow_rows, key=lambda row: str(row.get("match_key") or ""))

        def metric_pair(metric_name: str) -> dict[str, Any]:
            candidate_values = []
            champion_values = []
            candidate_keys = []
            champion_keys = []
            for row in shadow_rows:
                metrics = row.get("metrics") or {}
                candidate_value = _metric_number((metrics.get(SHADOW_MODEL_NAME) or {}).get(metric_name))
                champion_value = _metric_number((metrics.get("champion") or {}).get(metric_name))
                key = str(row.get("match_key") or "")
                if candidate_value is not None:
                    candidate_values.append(candidate_value)
                    candidate_keys.append(key)
                if champion_value is not None:
                    champion_values.append(champion_value)
                    champion_keys.append(key)
            result = {
                "candidate": fmean(candidate_values) if candidate_values else None,
                "champion": fmean(champion_values) if champion_values else None,
                "candidate_n": len(candidate_values),
                "champion_n": len(champion_values),
                "candidate_match_keys": candidate_keys,
                "champion_match_keys": champion_keys,
            }
            if not candidate_values or not champion_values:
                result["status"] = "unsupported"
                result["reason"] = "final frozen distribution is unavailable for one side of this metric"
            else:
                result["status"] = "supported"
                result["n"] = min(len(candidate_values), len(champion_values))
            return result

        def quantiles(model_name: str) -> dict[str, float | None]:
            values = [
                _metric_number(((row.get("metrics") or {}).get(model_name) or {}).get("lambda_gap"))
                for row in shadow_rows
            ]
            values = sorted(value for value in values if value is not None)
            if not values:
                return {"p25": None, "median": None, "p75": None}
            def at(fraction: float) -> float:
                index = (len(values) - 1) * fraction
                lower = int(index)
                upper = min(len(values) - 1, lower + 1)
                weight = index - lower
                return values[lower] * (1 - weight) + values[upper] * weight
            return {"p25": at(0.25), "median": at(0.50), "p75": at(0.75)}

        def group_rows(predicate) -> dict[str, Any]:
            selected = []
            for row in shadow_rows:
                actual = row.get("actual_result") or {}
                home = _metric_number(actual.get("home_goals"))
                away = _metric_number(actual.get("away_goals"))
                if home is None or away is None:
                    continue
                if predicate(int(home), int(away)):
                    selected.append(row)
            return {
                "n": len(selected),
                "brier": metric_pair_from(selected, "brier_score_1x2"),
                "log_loss": metric_pair_from(selected, "log_loss_1x2"),
                "total_mae": metric_pair_from(selected, "total_goal_absolute_error"),
                "exact_top1": metric_pair_from(selected, "exact_score_top1"),
                "exact_top3": metric_pair_from(selected, "exact_score_top3"),
            }

        def metric_pair_from(selected: list[dict[str, Any]], metric_name: str) -> dict[str, Any]:
            candidate_values = [_metric_number(((row.get("metrics") or {}).get(SHADOW_MODEL_NAME) or {}).get(metric_name)) for row in selected]
            champion_values = [_metric_number(((row.get("metrics") or {}).get("champion") or {}).get(metric_name)) for row in selected]
            candidate_values = [value for value in candidate_values if value is not None]
            champion_values = [value for value in champion_values if value is not None]
            result = {
                "candidate": fmean(candidate_values) if candidate_values else None,
                "champion": fmean(champion_values) if champion_values else None,
                "candidate_n": len(candidate_values),
                "champion_n": len(champion_values),
            }
            if not candidate_values or not champion_values:
                result.update({"status": "unsupported", "reason": "final frozen distribution is unavailable for one side of this metric"})
            else:
                result.update({"status": "supported", "n": min(len(candidate_values), len(champion_values))})
            return result

        metrics = {
            "brier": metric_pair("brier_score_1x2"),
            "log_loss": metric_pair("log_loss_1x2"),
            "top1": metric_pair("top1_accuracy_1x2"),
            "macro_ece": {"candidate": _ece(shadow_rows, SHADOW_MODEL_NAME), "champion": _ece(shadow_rows, "champion"), "status": "supported" if shadow_rows else "unsupported"},
            "exact_score_nll": metric_pair("actual_score_nll"),
            "exact_top1": metric_pair("exact_score_top1"),
            "exact_top3": metric_pair("exact_score_top3"),
            "total_nll": metric_pair("total_goals_nll"),
            "total_mae": metric_pair("total_goal_absolute_error"),
            "top1_1_1": metric_pair("top1_1_1"),
            "lambda_gap": metric_pair("lambda_gap"),
            "lambda_gap_lt_0_5": metric_pair("lambda_gap_lt_0_5"),
        }
        return {
            "status": "supported" if shadow_rows else "no_shadow_settlements",
            "candidate_id": "market-direction-fusion-full-v1",
            "n": len(shadow_rows),
            "match_keys": [str(row.get("match_key") or "") for row in shadow_rows],
            "metrics": metrics,
            "lambda_gap_quantiles": {
                "candidate": quantiles(SHADOW_MODEL_NAME),
                "champion": quantiles("champion"),
            },
            "groups": {
                "high_score_total_ge_4": group_rows(lambda home, away: home + away >= 4),
                "high_margin_abs_ge_3": group_rows(lambda home, away: abs(home - away) >= 3),
            },
            "unsupported_policy": {
                "actual_score_nll": "Champion frozen comparison stores top10 only; no raw lambda reconstruction is used",
                "total_nll": "only reported when the final frozen score distribution is present",
            },
        }

    def individual_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        model_names = ("market_reference", "simple_poisson", "champion")
        metric_names = (
            "brier_score_1x2", "log_loss_1x2", "top1_accuracy_1x2",
            "btts_hit", "total_goal_error", "total_goal_absolute_error",
            "expected_goal_error", "score_top1", "score_top3", "score_top5", "score_top10",
            "actual_score_rank", "actual_score_probability",
        )
        return {
            model_name: {
                key: mean_for(rows, model_name, key) for key in metric_names
            }
            for model_name in model_names
        }

    paired_3way_result = paired_3way(primary_clean)
    paired_model_result = paired_model_distribution(primary_clean)
    shadow_candidate_result = paired_shadow_research(scope_rows)
    distribution_metric_values = paired_model_result["metrics"]
    paired_metrics = {
        "market_reference": {
            "brier_score_1x2": paired_3way_result["market_reference"]["brier"],
            "log_loss_1x2": paired_3way_result["market_reference"]["log_loss"],
            "top1_accuracy_1x2": paired_3way_result["market_reference"]["top1"],
        },
        "simple_poisson": {
            "brier_score_1x2": paired_3way_result["simple_poisson"]["brier"],
            "log_loss_1x2": paired_3way_result["simple_poisson"]["log_loss"],
            "top1_accuracy_1x2": paired_3way_result["simple_poisson"]["top1"],
            **{
                metric_name: metric_result["simple_poisson"]
                for metric_name, metric_result in distribution_metric_values.items()
            },
        },
        "champion": {
            "brier_score_1x2": paired_3way_result["champion"]["brier"],
            "log_loss_1x2": paired_3way_result["champion"]["log_loss"],
            "top1_accuracy_1x2": paired_3way_result["champion"]["top1"],
            **{
                metric_name: metric_result["champion"]
                for metric_name, metric_result in distribution_metric_values.items()
            },
        },
    }

    availability = {}
    for model_name, flag in (
        ("market_reference", "market_evaluable"),
        ("simple_poisson", "simple_evaluable"),
        ("champion", "champion_evaluable"),
    ):
        evaluable_count = sum(row.get(flag) is True for row in eligible)
        availability[model_name] = {
            "evaluable": evaluable_count,
            "unavailable": max(0, len(eligible) - evaluable_count),
        }

    secondary_summary: dict[str, Any] = {}
    for stage in sorted({str(row.get("checkpoint_stage") or "unclassified") for row in secondary_rows}):
        stage_rows: list[dict[str, Any]] = []
        for (row_stage, row_match), rows in secondary_groups.items():
            if row_stage == stage and f"{row_stage}:{row_match}" not in duplicate_secondary_conflicts:
                stage_rows.extend(rows)
        stage_rows = sorted(stage_rows, key=lambda row: str(row.get("match_key") or ""))
        secondary_summary[stage] = {
            "n": len(stage_rows),
            "match_keys": [str(row.get("match_key") or "") for row in stage_rows],
            "paired_3way_1x2": paired_3way(stage_rows),
            "paired_model_distribution": paired_model_distribution(stage_rows),
        }

    prospective_match_keys = sorted({str(row.get("match_key") or "") for row in scope_rows})
    incomplete_count = sum(row.get("comparison_status") == "incomplete" for row in scope_rows)
    mismatch_count = sum(row.get("comparison_status") == "invalid_snapshot_mismatch" for row in scope_rows)
    duplicate_checkpoint_excluded = max(0, len(eligible) - len(primary_clean)) if cohort != "secondary" else max(
        0, len(secondary_rows) - sum(len(rows) == 1 for rows in secondary_groups.values())
    )
    return {
        "benchmark_contract_version": BENCHMARK_CONTRACT_VERSION,
        "cohort": cohort,
        "records_seen": records_seen,
        "total_prospective_matches": len(prospective_match_keys),
        "prospective_match_keys": prospective_match_keys,
        "formal_records": len(eligible),
        "primary_formal_records": len(primary_rows),
        "primary_unique_match_count": len({str(row.get("match_key") or "") for row in primary_clean}),
        "secondary_formal_records": len(secondary_rows),
        "excluded_records": records_seen - len(eligible),
        "unique_match_count": len({str(row.get("match_key") or "") for row in eligible}),
        "duplicate_checkpoint_records_excluded": duplicate_checkpoint_excluded,
        "duplicate_primary_conflicts": duplicate_primary_conflicts,
        "duplicate_secondary_conflicts": duplicate_secondary_conflicts,
        "incomplete_comparison_count": incomplete_count,
        "snapshot_mismatch_count": mismatch_count,
        "availability": availability,
        "market_unavailable_count": availability["market_reference"]["unavailable"],
        "simple_unavailable_count": availability["simple_poisson"]["unavailable"],
        "champion_unavailable_count": availability["champion"]["unavailable"],
        "paired_3way_1x2": paired_3way_result,
        "paired_model_distribution": paired_model_result,
        "shadow_candidate_vs_champion": shadow_candidate_result,
        "secondary": secondary_summary,
        "individual_metrics": individual_metrics(eligible),
        "metrics": paired_metrics,
        "include_excluded_requested": bool(include_excluded),
    }
