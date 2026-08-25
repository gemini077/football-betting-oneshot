"""Research-only pre-screen for the first bounded Challenger candidate.

This module evaluates already-frozen, settled prediction records.  It does
not create predictions, select a production model, register a Challenger, or
replace Champion.  The current candidate under review is the existing
Phase2C1 basic-team-strength output; the pre-screen only decides whether that
output has enough same-match evidence to enter a future prospective shadow.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


CHALLENGER_ID = "research:phase2c1-basic-team-strength:last10-shrink10:v1"
QUALIFIED_FOR_PROSPECTIVE_SHADOW = "QUALIFIED_FOR_PROSPECTIVE_SHADOW"
NOT_QUALIFIED = "NOT_QUALIFIED"
METRIC_TOLERANCE = 1e-9
_OUTCOME_KEYS = ("home", "draw", "away")


def _as_records(records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if records is None:
        return []
    if isinstance(records, Mapping):
        nested = records.get("records")
        if isinstance(nested, Iterable) and not isinstance(nested, (str, bytes, Mapping)):
            return [record for record in nested]
        return [records]
    return [record for record in records]


def _match_key(record: Mapping[str, Any]) -> str:
    value = record.get("match_key")
    if not isinstance(value, str) or not value:
        raise ValueError("MISSING_MATCH_KEY")
    return value


def _parse_score(value: Any) -> tuple[int, int] | None:
    if isinstance(value, str):
        parts = value.split("-", 1)
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None
    if isinstance(value, Mapping):
        home = value.get("home_goals", value.get("home"))
        away = value.get("away_goals", value.get("away"))
        if isinstance(home, int) and isinstance(away, int):
            return home, away
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        if all(isinstance(part, int) for part in value):
            return int(value[0]), int(value[1])
    return None


def _settled_score(record: Mapping[str, Any]) -> tuple[int, int]:
    if "actual_home_goals" in record and "actual_away_goals" in record:
        home = record["actual_home_goals"]
        away = record["actual_away_goals"]
        if isinstance(home, int) and isinstance(away, int):
            return home, away
    for key in ("settled_score", "actual_score", "final_score"):
        parsed = _parse_score(record.get(key))
        if parsed is not None:
            return parsed
    raise ValueError("SETTLED_OUTCOME_MISSING")


def _probabilities(record: Mapping[str, Any]) -> tuple[float, float, float]:
    value = record.get("probabilities", record.get("one_x_two_probabilities"))
    if isinstance(value, Mapping) and isinstance(value.get("one_x_two"), Mapping):
        value = value["one_x_two"]
    if not isinstance(value, Mapping):
        raise ValueError("ONE_X_TWO_PROBABILITIES_MISSING")
    try:
        values = tuple(float(value[key]) for key in _OUTCOME_KEYS)
    except (KeyError, TypeError, ValueError):
        raise ValueError("ONE_X_TWO_PROBABILITIES_MISSING") from None
    if any(not math.isfinite(item) or item < 0.0 for item in values):
        raise ValueError("ONE_X_TWO_PROBABILITIES_INVALID")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-6):
        raise ValueError("ONE_X_TWO_PROBABILITIES_NOT_NORMALIZED")
    return values


def _top1_score(record: Mapping[str, Any]) -> tuple[int, int] | None:
    for key in ("score_top1", "exact_score_top1", "unique_score"):
        if key in record:
            parsed = _parse_score(record[key])
            if parsed is not None:
                return parsed
    top3 = record.get("score_top3")
    if isinstance(top3, Sequence) and not isinstance(top3, (str, bytes)) and top3:
        return _parse_score(top3[0])
    return None


def _lambda_gap(record: Mapping[str, Any]) -> float:
    try:
        home = float(record["lambda_home"])
        away = float(record["lambda_away"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("LAMBDA_MISSING") from None
    if not math.isfinite(home) or not math.isfinite(away) or home < 0.0 or away < 0.0:
        raise ValueError("LAMBDA_INVALID")
    return abs(home - away)


def _empty_metric() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "one_x_two": {"brier": None, "log_loss": None},
        "exact_score_top1": {"available": False, "count": 0, "share": 0.0},
        "one_to_one_top1": {"available": False, "count": 0, "share": 0.0},
        "mean_abs_lambda_gap": None,
        "lambda_gap_below_0_5": {"available": False, "count": 0, "share": 0.0},
    }


def _summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        return _empty_metric()

    brier_total = 0.0
    log_loss_total = 0.0
    lambda_gaps: list[float] = []
    top1_scores: list[tuple[int, int] | None] = []
    top1_correct = 0
    one_to_one_count = 0
    lambda_below_count = 0

    for record in records:
        home_goals, away_goals = _settled_score(record)
        actual_index = 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2
        probabilities = _probabilities(record)
        brier_total += sum(
            (probability - (1.0 if index == actual_index else 0.0)) ** 2
            for index, probability in enumerate(probabilities)
        )
        actual_probability = probabilities[actual_index]
        log_loss_total += -math.log(actual_probability) if actual_probability > 0.0 else math.inf

        gap = _lambda_gap(record)
        lambda_gaps.append(gap)
        lambda_below_count += int(gap < 0.5)

        top1 = _top1_score(record)
        top1_scores.append(top1)
        if top1 is not None:
            top1_correct += int(top1 == (home_goals, away_goals))
            one_to_one_count += int(top1 == (1, 1))

    sample_count = len(records)
    top1_available = all(score is not None for score in top1_scores)
    top1_observed = sum(score is not None for score in top1_scores)
    return {
        "sample_count": sample_count,
        "one_x_two": {
            "brier": brier_total / sample_count,
            "log_loss": log_loss_total / sample_count,
        },
        "exact_score_top1": {
            "available": top1_available,
            "count": top1_correct,
            "share": top1_correct / top1_observed if top1_observed else 0.0,
            "observed_count": top1_observed,
        },
        "one_to_one_top1": {
            "available": top1_available,
            "count": one_to_one_count,
            "share": one_to_one_count / top1_observed if top1_observed else 0.0,
            "observed_count": top1_observed,
        },
        "mean_abs_lambda_gap": sum(lambda_gaps) / sample_count,
        "lambda_gap_below_0_5": {
            "available": True,
            "count": lambda_below_count,
            "share": lambda_below_count / sample_count,
        },
    }


def _empty_result(*, blocking_reasons: list[str], paired_sample_count: int = 0) -> dict[str, Any]:
    return {
        "candidate_id": CHALLENGER_ID,
        "research_only": True,
        "production_registration": False,
        "evidence_scope": "same_settled_match_keys_only",
        "status": NOT_QUALIFIED,
        "paired_sample_count": paired_sample_count,
        "metrics": {"baseline": _empty_metric(), "challenger": _empty_metric()},
        "metric_deltas": {"brier": None, "log_loss": None},
        "structure": {
            "one_to_one_top1_share": {"available": False, "improved": False},
            "lambda_gap_below_0_5_share": {"available": False, "improved": False},
            "improved": False,
        },
        "blocking_reasons": blocking_reasons,
    }


def evaluate_challenger_prescreen(
    baseline_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    challenger_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    metric_tolerance: float = METRIC_TOLERANCE,
) -> dict[str, Any]:
    """Compare two independently frozen prediction sets on exact settled keys."""

    baseline = _as_records(baseline_records)
    challenger = _as_records(challenger_records)
    if not baseline and not challenger:
        return _empty_result(
            blocking_reasons=["NO_PAIRED_SETTLED_EVIDENCE", "HISTORICAL_STRUCTURE_EVIDENCE_MISSING"]
        )
    if not baseline or not challenger:
        return _empty_result(blocking_reasons=["UNPAIRED_OR_MISMATCHED_SAMPLE"])

    try:
        baseline_by_key = {_match_key(record): record for record in baseline}
        challenger_by_key = {_match_key(record): record for record in challenger}
    except ValueError as error:
        return _empty_result(blocking_reasons=[f"INVALID_RECORD:{error.args[0]}"])
    if len(baseline_by_key) != len(baseline) or len(challenger_by_key) != len(challenger):
        return _empty_result(blocking_reasons=["DUPLICATE_MATCH_KEY"])
    if set(baseline_by_key) != set(challenger_by_key):
        return _empty_result(blocking_reasons=["UNPAIRED_OR_MISMATCHED_SAMPLE"])

    paired_keys = sorted(baseline_by_key)
    paired_baseline = [baseline_by_key[key] for key in paired_keys]
    paired_challenger = [challenger_by_key[key] for key in paired_keys]
    for left, right in zip(paired_baseline, paired_challenger):
        try:
            if _settled_score(left) != _settled_score(right):
                return _empty_result(
                    blocking_reasons=["SETTLED_OUTCOME_MISMATCH"],
                    paired_sample_count=0,
                )
        except ValueError as error:
            return _empty_result(
                blocking_reasons=[f"INVALID_RECORD:{error.args[0]}"],
                paired_sample_count=0,
            )

    try:
        baseline_metrics = _summarize(paired_baseline)
        challenger_metrics = _summarize(paired_challenger)
    except ValueError as error:
        return _empty_result(
            blocking_reasons=[f"INVALID_RECORD:{error.args[0]}"],
            paired_sample_count=0,
        )

    brier_delta = challenger_metrics["one_x_two"]["brier"] - baseline_metrics["one_x_two"]["brier"]
    log_loss_delta = challenger_metrics["one_x_two"]["log_loss"] - baseline_metrics["one_x_two"]["log_loss"]
    structure = {
        "one_to_one_top1_share": {
            "available": baseline_metrics["one_to_one_top1"]["available"]
            and challenger_metrics["one_to_one_top1"]["available"],
            "baseline": baseline_metrics["one_to_one_top1"]["share"],
            "challenger": challenger_metrics["one_to_one_top1"]["share"],
            "improved": False,
        },
        "lambda_gap_below_0_5_share": {
            "available": baseline_metrics["lambda_gap_below_0_5"]["available"]
            and challenger_metrics["lambda_gap_below_0_5"]["available"],
            "baseline": baseline_metrics["lambda_gap_below_0_5"]["share"],
            "challenger": challenger_metrics["lambda_gap_below_0_5"]["share"],
            "improved": False,
        },
        "improved": False,
    }
    blockers: list[str] = []
    available_structure = [
        structure["one_to_one_top1_share"]["available"],
        structure["lambda_gap_below_0_5_share"]["available"],
    ]
    if not any(available_structure):
        blockers.append("HISTORICAL_STRUCTURE_EVIDENCE_MISSING")
    else:
        for metric in ("one_to_one_top1_share", "lambda_gap_below_0_5_share"):
            item = structure[metric]
            if item["available"]:
                item["improved"] = item["challenger"] < item["baseline"] - metric_tolerance
        structure["improved"] = any(
            structure[metric]["improved"]
            for metric in ("one_to_one_top1_share", "lambda_gap_below_0_5_share")
        )

    if brier_delta > metric_tolerance:
        blockers.append("ONE_X_TWO_BRIER_REGRESSION")
    if log_loss_delta > metric_tolerance:
        blockers.append("ONE_X_TWO_LOG_LOSS_REGRESSION")
    if not structure["improved"] and "HISTORICAL_STRUCTURE_EVIDENCE_MISSING" not in blockers:
        blockers.append("NO_REQUIRED_STRUCTURE_IMPROVEMENT")

    return {
        "candidate_id": CHALLENGER_ID,
        "research_only": True,
        "production_registration": False,
        "evidence_scope": "same_settled_match_keys_only",
        "status": QUALIFIED_FOR_PROSPECTIVE_SHADOW if not blockers else NOT_QUALIFIED,
        "paired_sample_count": len(paired_keys),
        "metrics": {"baseline": baseline_metrics, "challenger": challenger_metrics},
        "metric_deltas": {"brier": brier_delta, "log_loss": log_loss_delta},
        "structure": structure,
        "blocking_reasons": blockers,
    }


def _summary_metric(summary_metrics: Mapping[str, Any]) -> dict[str, Any]:
    sample = int(summary_metrics.get("sample", 0))
    exact = summary_metrics.get("exact_score", {})
    top1 = exact.get("top1")
    return {
        "sample_count": sample,
        "one_x_two": {
            "brier": summary_metrics.get("one_x_two_brier"),
            "log_loss": summary_metrics.get("one_x_two_log_loss"),
        },
        "exact_score_top1": {
            "available": isinstance(top1, (int, float)),
            "count": None,
            "share": float(top1) if isinstance(top1, (int, float)) else 0.0,
            "source": "aggregate_summary",
        },
        "one_to_one_top1": {
            "available": False,
            "count": None,
            "share": None,
            "source": "per_match_records_missing",
        },
        "mean_abs_lambda_gap": None,
        "lambda_gap_below_0_5": {
            "available": False,
            "count": None,
            "share": None,
            "source": "per_match_records_missing",
        },
    }


def prescreen_phase2c1_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Use only aggregate Phase2C1 evidence; never infer missing structure data."""

    heldout = summary.get("heldout_evaluation")
    if not isinstance(heldout, Mapping):
        return _empty_result(blocking_reasons=["HISTORICAL_STRUCTURE_EVIDENCE_MISSING"])
    baseline_raw = heldout.get("baseline_a")
    challenger_raw = heldout.get("team_strength")
    if not isinstance(baseline_raw, Mapping) or not isinstance(challenger_raw, Mapping):
        return _empty_result(blocking_reasons=["HISTORICAL_STRUCTURE_EVIDENCE_MISSING"])

    baseline_metrics = _summary_metric(baseline_raw)
    challenger_metrics = _summary_metric(challenger_raw)
    baseline_sample = baseline_metrics["sample_count"]
    challenger_sample = challenger_metrics["sample_count"]
    same_sample = baseline_sample > 0 and baseline_sample == challenger_sample
    brier_delta = challenger_metrics["one_x_two"]["brier"] - baseline_metrics["one_x_two"]["brier"]
    log_loss_delta = challenger_metrics["one_x_two"]["log_loss"] - baseline_metrics["one_x_two"]["log_loss"]
    blockers = [] if same_sample else ["SUMMARY_SAMPLE_COUNT_MISMATCH"]
    blockers.append("HISTORICAL_STRUCTURE_EVIDENCE_MISSING")
    return {
        "candidate_id": CHALLENGER_ID,
        "research_only": True,
        "production_registration": False,
        "evidence_scope": "phase2c1_aggregate_summary_only",
        "status": NOT_QUALIFIED,
        "paired_sample_count": baseline_sample if same_sample else 0,
        "metrics": {"baseline": baseline_metrics, "challenger": challenger_metrics},
        "metric_deltas": {"brier": brier_delta, "log_loss": log_loss_delta},
        "structure": {
            "one_to_one_top1_share": {"available": False, "improved": False},
            "lambda_gap_below_0_5_share": {"available": False, "improved": False},
            "improved": False,
        },
        "blocking_reasons": blockers,
    }


__all__ = [
    "CHALLENGER_ID",
    "METRIC_TOLERANCE",
    "NOT_QUALIFIED",
    "QUALIFIED_FOR_PROSPECTIVE_SHADOW",
    "evaluate_challenger_prescreen",
    "prescreen_phase2c1_summary",
]
