"""Unified, shadow-only quality gate for Phase 2C challenger evidence.

The gate deliberately evaluates only true same-match pairs.  The existing
Phase 2C metric implementation remains the source of probability losses;
this module only applies the promotion decision policy around those metrics.
It never registers a challenger or changes the Champion.
"""

from __future__ import annotations

from math import isfinite, log
from typing import Any, Iterable, Mapping, Sequence

from .phase2c1_model import evaluate_predictions


MATCH_KEY_FIELDS = ("target_match_id", "canonical_match_id", "match_id", "match_key")
PRIMARY_METRICS = ("one_x_two_brier", "one_x_two_log_loss")
STRUCTURAL_METRICS = (
    "top1_1_to_1_concentration",
    "lambda_separation",
    "score_distribution_concentration",
    "score_distribution_entropy",
)


def _match_key(row: Mapping[str, Any]) -> str | None:
    for field in MATCH_KEY_FIELDS:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return None


def _index_by_match_key(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], str | None]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = _match_key(row)
        if key is None:
            return {}, "missing_match_key"
        if key in indexed:
            return {}, "duplicate_match_key"
        indexed[key] = row
    return indexed, None


def _top_score(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    score = row.get("top_score")
    if isinstance(score, Mapping):
        return score
    scores = row.get("top_scores")
    if isinstance(scores, list) and scores and isinstance(scores[0], Mapping):
        return scores[0]
    matrix = row.get("score_matrix")
    if not isinstance(matrix, Mapping):
        return None
    cells: list[tuple[float, int, int]] = []
    for home_key, away_values in matrix.items():
        if not isinstance(away_values, Mapping):
            continue
        try:
            home_goals = int(home_key)
        except (TypeError, ValueError):
            continue
        for away_key, probability in away_values.items():
            try:
                cells.append((float(probability), home_goals, int(away_key)))
            except (TypeError, ValueError):
                continue
    if not cells:
        return None
    probability, home_goals, away_goals = max(cells, key=lambda cell: (cell[0], -cell[1], -cell[2]))
    return {"home_goals": home_goals, "away_goals": away_goals, "probability": probability}


def _score_distribution_values(row: Mapping[str, Any]) -> list[float]:
    matrix = row.get("score_matrix")
    if not isinstance(matrix, Mapping):
        return []
    values: list[float] = []
    for away_values in matrix.values():
        if not isinstance(away_values, Mapping):
            continue
        for value in away_values.values():
            try:
                probability = float(value)
            except (TypeError, ValueError):
                continue
            if isfinite(probability) and probability > 0:
                values.append(probability)
    return values


def _structural_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    one_to_one = []
    lambda_separation = []
    concentration = []
    entropy = []
    for row in rows:
        score = _top_score(row)
        if score is not None:
            try:
                one_to_one.append(int(int(score["home_goals"]) == 1 and int(score["away_goals"]) == 1))
            except (KeyError, TypeError, ValueError):
                pass
        try:
            separation = abs(float(row["lambda_home"]) - float(row["lambda_away"]))
        except (KeyError, TypeError, ValueError):
            separation = None
        if separation is not None and isfinite(separation):
            lambda_separation.append(separation)
        values = _score_distribution_values(row)
        if values:
            mass = sum(values)
            normalised = [value / mass for value in values] if mass > 0 else []
            if normalised:
                concentration.append(max(normalised))
                entropy.append(-sum(value * log(value) for value in normalised if value > 0))

    def mean(values: Sequence[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "top1_1_to_1_concentration": mean(one_to_one),
        "lambda_separation": mean(lambda_separation),
        "score_distribution_concentration": mean(concentration),
        "score_distribution_entropy": mean(entropy),
    }


def _delta(challenger: Mapping[str, Any], champion: Mapping[str, Any], name: str) -> float | None:
    challenger_value = challenger.get(name)
    champion_value = champion.get(name)
    if challenger_value is None or champion_value is None:
        return None
    return float(challenger_value) - float(champion_value)


def _insufficient_result(reason: str, *, paired: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "mode": "shadow_only",
        "status": "INSUFFICIENT_EVIDENCE",
        "promotion_eligible": False,
        "automatic_promotion": False,
        "blocking_reasons": [reason],
        "paired": dict(paired or {"same_match_keys": False, "sample_count": 0, "match_keys": []}),
    }


def evaluate_shadow_promotion_gate(
    champion_predictions: Sequence[Mapping[str, Any]],
    challenger_predictions: Sequence[Mapping[str, Any]],
    *,
    max_brier_degradation: float = 0.0,
    max_log_loss_degradation: float = 0.0,
    min_paired_matches: int = 1,
    structural_min_deltas: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate a shadow challenger against the Champion on exact paired rows.

    Brier and log-loss are lower-is-better primary gates.  Structural metrics
    are reported for diagnosis and can deny promotion through explicit
    ``structural_min_deltas`` constraints, but they are never allowed to
    override a primary probability-quality failure.
    """

    if max_brier_degradation < 0 or max_log_loss_degradation < 0:
        raise ValueError("probability degradation bounds must be non-negative")
    champion_index, champion_error = _index_by_match_key(champion_predictions)
    challenger_index, challenger_error = _index_by_match_key(challenger_predictions)
    if not champion_index or not challenger_index:
        reason = "true_paired_samples_unavailable"
        if champion_error or challenger_error:
            reason = f"invalid_pair_keys:{champion_error or challenger_error}"
        return _insufficient_result(reason)
    if set(champion_index) != set(challenger_index):
        return _insufficient_result(
            "same_match_keys_required",
            paired={
                "same_match_keys": False,
                "sample_count": 0,
                "champion_match_keys": sorted(champion_index),
                "challenger_match_keys": sorted(challenger_index),
            },
        )

    match_keys = sorted(champion_index)
    sample_count = len(match_keys)
    paired = {"same_match_keys": True, "sample_count": sample_count, "match_keys": match_keys}
    if sample_count < int(min_paired_matches):
        return _insufficient_result("minimum_paired_samples_not_met", paired=paired)

    champion_rows = [champion_index[key] for key in match_keys]
    challenger_rows = [challenger_index[key] for key in match_keys]
    try:
        champion_metrics = evaluate_predictions(champion_rows)
        challenger_metrics = evaluate_predictions(challenger_rows)
    except (KeyError, TypeError, ValueError) as exc:
        return _insufficient_result(f"invalid_prediction_metrics:{type(exc).__name__}", paired=paired)

    brier_delta = float(challenger_metrics["one_x_two_brier"]) - float(champion_metrics["one_x_two_brier"])
    log_loss_delta = float(challenger_metrics["one_x_two_log_loss"]) - float(champion_metrics["one_x_two_log_loss"])
    primary = {
        "brier": {
            "champion": float(champion_metrics["one_x_two_brier"]),
            "challenger": float(challenger_metrics["one_x_two_brier"]),
            "delta": brier_delta,
            "allowed_degradation": float(max_brier_degradation),
            "passed": brier_delta <= float(max_brier_degradation),
        },
        "log_loss": {
            "champion": float(champion_metrics["one_x_two_log_loss"]),
            "challenger": float(challenger_metrics["one_x_two_log_loss"]),
            "delta": log_loss_delta,
            "allowed_degradation": float(max_log_loss_degradation),
            "passed": log_loss_delta <= float(max_log_loss_degradation),
        },
    }

    champion_structural = _structural_diagnostics(champion_rows)
    challenger_structural = _structural_diagnostics(challenger_rows)
    structural_deltas = {
        name: _delta(challenger_structural, champion_structural, name) for name in STRUCTURAL_METRICS
    }
    blocking_reasons: list[str] = []
    if not primary["brier"]["passed"]:
        blocking_reasons.append("brier_degradation_exceeds_bound")
    if not primary["log_loss"]["passed"]:
        blocking_reasons.append("log_loss_degradation_exceeds_bound")
    for name, minimum_delta in (structural_min_deltas or {}).items():
        delta = structural_deltas.get(name)
        if delta is not None and delta < float(minimum_delta):
            blocking_reasons.append(f"structural_{name}_below_bound")

    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    return {
        "mode": "shadow_only",
        "status": "FAIL" if blocking_reasons else "PASS",
        "promotion_eligible": not blocking_reasons,
        "automatic_promotion": False,
        "requires_human_review": True,
        "blocking_reasons": blocking_reasons,
        "paired": paired,
        "primary_probability_quality": primary,
        "champion_metrics": champion_metrics,
        "challenger_metrics": challenger_metrics,
        "structural": {
            "champion": champion_structural,
            "challenger": challenger_structural,
            "deltas": structural_deltas,
            "minimum_deltas": dict(structural_min_deltas or {}),
        },
        "deltas": {
            "one_x_two_brier": brier_delta,
            "one_x_two_log_loss": log_loss_delta,
            **structural_deltas,
        },
    }


evaluate_prediction_quality_gate = evaluate_shadow_promotion_gate


__all__ = ["evaluate_prediction_quality_gate", "evaluate_shadow_promotion_gate"]
