"""Canonical owner for verified-result and shared probabilistic evaluation semantics.

This module deliberately consumes model outputs and frozen Exact contracts.  It
does not build model probabilities, settle wager contracts, or replace the
immutable Exact authority in ``exact_distribution``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from exact_distribution import classify_frozen_exact_score
from score_engine import dixon_coles_score_matrix


OUTCOMES = ("home", "draw", "away")
EPSILON = 1e-15
VERIFIED_RESULT_STATUSES = {"result_verified", "verified", "reviewed"}
LIVE_RESULT_STATUSES = {"live", "in_progress", "scheduled", "pending", "result_pending"}
REGULATION_RESULT_SCOPES = {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_score_pair(value: Any) -> tuple[int, int] | None:
    """Parse a non-negative realized or predicted score pair."""

    if isinstance(value, (tuple, list)) and len(value) == 2:
        left, right = value
    elif isinstance(value, Mapping):
        if value.get("home_goals") is not None or value.get("away_goals") is not None:
            left, right = value.get("home_goals"), value.get("away_goals")
        elif value.get("home_score") is not None or value.get("away_score") is not None:
            left, right = value.get("home_score"), value.get("away_score")
        else:
            return parse_score_pair(value.get("score"))
    else:
        text = str(value or "").strip()
        if "-" not in text:
            return None
        left, right = text.split("-", 1)
    home_number, away_number = _number(left), _number(right)
    if home_number is None or away_number is None:
        return None
    if home_number < 0 or away_number < 0:
        return None
    if int(home_number) != home_number or int(away_number) != away_number:
        return None
    return int(home_number), int(away_number)


def outcome_for_score(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def normalize_verified_result(result: Any) -> dict[str, Any]:
    """Normalize a provider/result payload to the regulation-time fact.

    Status and scope validation are shared, while callers decide separately
    whether a result is sufficiently verified for a formal ledger write.
    """

    source = dict(result) if isinstance(result, Mapping) else {}
    if isinstance(result, (tuple, list)) and len(result) == 2:
        score = result
    elif isinstance(result, Mapping):
        status = str(result.get("status") or "").strip().lower()
        if status in LIVE_RESULT_STATUSES:
            raise ValueError("result is not final")
        if status and status not in VERIFIED_RESULT_STATUSES:
            raise ValueError("result verification status is not final")
        scope = str(result.get("scope") or "regulation_90m_plus_stoppage").strip()
        if scope not in REGULATION_RESULT_SCOPES:
            raise ValueError("result scope is not regulation-only")
        score = result.get("score_90m") or result.get("result_90m")
        if score is None:
            score = (
                result.get("home_score_90m"),
                result.get("away_score_90m"),
            )
            if score == (None, None):
                score = (
                    result.get("home_score"),
                    result.get("away_score"),
                )
            if score == (None, None):
                score = (
                    result.get("home_goals"),
                    result.get("away_goals"),
                )
            if score == (None, None):
                score = (result.get("home"), result.get("away"))
    else:
        raise ValueError("result must be an object or a home/away score pair")

    pair = parse_score_pair(score)
    if pair is None:
        raise ValueError("result has no valid 90-minute score")
    home, away = pair
    scope = str(source.get("scope") or "regulation_90m_plus_stoppage").strip()
    source.update({
        "home_score_90m": home,
        "away_score_90m": away,
        "home_goals": home,
        "away_goals": away,
        "actual_outcome": outcome_for_score(home, away),
        "actual_score": f"{home}-{away}",
        "total_goals": home + away,
        "btts_actual": home > 0 and away > 0,
        "scope": scope,
        "result_verified_at": source.get("result_verified_at") or source.get("verified_at"),
    })
    return source


def is_verified_result_artifact(result: Mapping[str, Any]) -> bool:
    """Return whether a payload can be used for formal post-match scoring."""

    if not isinstance(result, Mapping):
        return False
    status = str(result.get("status") or "").strip().lower()
    if status in LIVE_RESULT_STATUSES:
        return False
    if status and status not in VERIFIED_RESULT_STATUSES:
        return False
    scope = str(result.get("scope") or "").strip()
    if scope not in REGULATION_RESULT_SCOPES:
        return False
    if not (result.get("result_verified_at") or result.get("verified_at")):
        return False
    return any(
        result.get(field) not in (None, "")
        for field in ("score_90m", "result_90m", "home_score_90m", "home_score")
    )


def extract_probabilities(
    prediction: Mapping[str, Any],
    *,
    include_output: bool = True,
) -> dict[str, float] | None:
    """Read a complete 1X2 probability vector without changing its values."""

    output = prediction.get("prediction_output") or {}
    values = prediction.get("probabilities") or prediction.get("outcome_probabilities")
    if include_output and not values and isinstance(output, Mapping):
        values = output.get("probabilities") or output.get("outcome_probabilities")
    if not isinstance(values, Mapping):
        return None
    numbers = {key: _number(values.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0 for value in numbers.values()):
        return None
    return {key: float(numbers[key]) for key in OUTCOMES}


def extract_score_rows(
    prediction: Mapping[str, Any],
    *,
    include_distribution: bool = True,
    preserve_declared_rank: bool = False,
) -> list[dict[str, Any]]:
    """Read and deterministically order stored exact-score rows."""

    output = prediction.get("prediction_output") or {}
    candidates: list[Any] = []
    if include_distribution:
        candidates.extend((prediction.get("score_distribution"), prediction.get("top_scores")))
    candidates.extend((prediction.get("score_matrix"), prediction.get("score_probabilities")))
    if isinstance(output, Mapping):
        candidates.extend((output.get("score_matrix"), output.get("score_probabilities")))
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        rows = [
            row for row in candidate
            if isinstance(row, Mapping) and _number(row.get("probability")) is not None
        ]
        if not rows:
            continue
        if preserve_declared_rank and any(row.get("rank") is not None for row in rows):
            return sorted(rows, key=lambda row: (int(row.get("rank") or 999999), str(row.get("score") or "")))
        return sorted(rows, key=lambda row: (-float(row["probability"]), str(row.get("score") or "")))
    return []


def expected_goals(prediction: Mapping[str, Any]) -> tuple[float, float] | None:
    home = _number(prediction.get("lambda_home"))
    away = _number(prediction.get("lambda_away"))
    expected = prediction.get("expected_goals")
    if isinstance(expected, Mapping):
        home = home if home is not None else _number(expected.get("home"))
        away = away if away is not None else _number(expected.get("away"))
    if home is None or away is None:
        return None
    return home, away


def evaluate_1x2_probabilities(
    probabilities: Mapping[str, Any] | None,
    actual_outcome: str,
    *,
    log_loss_epsilon: float = EPSILON,
) -> dict[str, Any]:
    """Evaluate one 1X2 vector using the project's accepted conventions."""

    result = {
        "actual_outcome_probability": None,
        "brier_score_1x2": None,
        "log_loss_1x2": None,
        "top1_predicted_outcome": None,
        "top1_accuracy_1x2": None,
        "outcome_probabilities": None,
    }
    if not isinstance(probabilities, Mapping):
        return result
    numbers = {key: _number(probabilities.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0 for value in numbers.values()):
        return result
    clean = {key: float(numbers[key]) for key in OUTCOMES}
    actual_probability = max(clean[actual_outcome], log_loss_epsilon)
    top = max(OUTCOMES, key=lambda key: clean[key])
    one_hot = {key: 1.0 if key == actual_outcome else 0.0 for key in OUTCOMES}
    brier = sum((clean[key] - one_hot[key]) ** 2 for key in OUTCOMES)
    result.update({
        "actual_outcome_probability": clean[actual_outcome],
        "brier_score_1x2": brier,
        "log_loss_1x2": -math.log(actual_probability),
        "top1_predicted_outcome": top,
        "top1_accuracy_1x2": int(top == actual_outcome),
        "outcome_probabilities": clean,
    })
    return result


def ranked_probability_score(
    probabilities: Mapping[str, Any] | None,
    actual_outcome: str,
) -> float | None:
    """Return the accepted three-way cumulative ranked probability score."""
    if actual_outcome not in OUTCOMES or not isinstance(probabilities, Mapping):
        return None
    values = {key: _number(probabilities.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0 for value in values.values()):
        return None
    observed = {key: float(key == actual_outcome) for key in OUTCOMES}
    predicted_cumulative = 0.0
    observed_cumulative = 0.0
    score = 0.0
    for key in OUTCOMES[:-1]:
        predicted_cumulative += float(values[key])
        observed_cumulative += observed[key]
        score += (predicted_cumulative - observed_cumulative) ** 2
    return score / (len(OUTCOMES) - 1)


def evaluate_goal_residuals(
    prediction: Mapping[str, Any],
    actual_pair: tuple[int, int],
    *,
    fallback_missing_values: bool = False,
) -> dict[str, Any]:
    """Return the shared signed and absolute lambda/goal residual diagnostics."""

    expected = expected_goals(prediction)
    if expected is None and fallback_missing_values:
        expected = (
            _number(prediction.get("lambda_home")) or 0.0,
            _number(prediction.get("lambda_away")) or 0.0,
        )
    result = {
        "lambda_home_residual": None,
        "lambda_away_residual": None,
        "total_goals_residual": None,
        "total_goal_error": None,
        "total_goal_absolute_error": None,
        "expected_goal_error": None,
        "expected_goal_error_home": None,
        "expected_goal_error_away": None,
        "home_goal_absolute_error": None,
        "away_goal_absolute_error": None,
        "lambda_sum": None,
        "lambda_gap": None,
        "lambda_gap_lt_0_5": None,
    }
    if expected is None:
        return result
    home, away = actual_pair
    home_residual = home - expected[0]
    away_residual = away - expected[1]
    total_residual = home + away - expected[0] - expected[1]
    result.update({
        "lambda_home_residual": home_residual,
        "lambda_away_residual": away_residual,
        "total_goals_residual": total_residual,
        "total_goal_error": total_residual,
        "total_goal_absolute_error": abs(total_residual),
        "expected_goal_error": (abs(home_residual) + abs(away_residual)) / 2.0,
        "expected_goal_error_home": abs(home_residual),
        "expected_goal_error_away": abs(away_residual),
        "home_goal_absolute_error": abs(home_residual),
        "away_goal_absolute_error": abs(away_residual),
        "lambda_sum": expected[0] + expected[1],
        "lambda_gap": abs(expected[0] - expected[1]),
        "lambda_gap_lt_0_5": abs(expected[0] - expected[1]) < 0.5,
    })
    return result


def _score_rows_from_matrix(matrix: Mapping[tuple[int, int], float]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "score": f"{home}-{away}",
                "home_goals": home,
                "away_goals": away,
                "probability": probability,
            }
            for (home, away), probability in matrix.items()
        ],
        key=lambda row: (-float(row["probability"]), str(row["score"])),
    )


def evaluate_exact_score(
    prediction: Mapping[str, Any],
    actual_pair: tuple[int, int],
    *,
    frozen_record: Mapping[str, Any] | None = None,
    allow_research_reconstruction: bool = False,
    research_source: str = "stored_or_matrix",
    include_distribution: bool = True,
    preserve_declared_rank: bool = False,
    top10_requires_ten: bool = False,
) -> dict[str, Any]:
    """Evaluate exact-score rows while preserving formal authority labels."""

    result: dict[str, Any] = {
        "score_top1": None,
        "score_top3": None,
        "score_top5": None,
        "score_top10": None,
        "exact_score_top1": None,
        "exact_score_top3": None,
        "exact_score_top5": None,
        "exact_score_top10": None,
        "top1_1_1": None,
        "actual_score_rank": None,
        "actual_score_probability": None,
        "actual_score_assigned_probability": None,
        "actual_score_nll": None,
        "total_goals_nll": None,
        "actual_score_nll_status": None,
        "exact_score_authority_status": "RESEARCH_RECONSTRUCTED",
        "FORMAL_EXACT_DISTRIBUTION_FROZEN": False,
        "FINITE_GRID_EXACTLY_REPRESENTED": False,
        "OUT_OF_EXPLICIT_SUPPORT": False,
        "FORMAL_EXACT_LOG_SCORE_ELIGIBLE": False,
        "formal_exact_distribution_status": "MISSING_FROZEN_EXACT_DISTRIBUTION",
        "_score_rows": [],
    }
    formal = classify_frozen_exact_score(frozen_record or {}, *actual_pair) if frozen_record is not None else None
    if formal is not None:
        result.update({
            "exact_score_authority_status": formal["authority_status"],
            "FORMAL_EXACT_DISTRIBUTION_FROZEN": formal["FORMAL_EXACT_DISTRIBUTION_FROZEN"],
            "FINITE_GRID_EXACTLY_REPRESENTED": formal["FINITE_GRID_EXACTLY_REPRESENTED"],
            "OUT_OF_EXPLICIT_SUPPORT": formal["OUT_OF_EXPLICIT_SUPPORT"],
            "FORMAL_EXACT_LOG_SCORE_ELIGIBLE": formal["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"],
            "formal_exact_distribution_status": formal["formal_exact_distribution_status"],
        })

    rows: list[dict[str, Any]] = []
    full_score_matrix = False
    formal_frozen = bool(result["FORMAL_EXACT_DISTRIBUTION_FROZEN"])
    if formal_frozen:
        rows = extract_score_rows(
            prediction,
            include_distribution=include_distribution,
            preserve_declared_rank=preserve_declared_rank,
        )
        if formal is not None:
            result["actual_score_probability"] = formal["probability"]
            result["actual_score_rank"] = formal["rank"]
            result["actual_score_assigned_probability"] = formal["probability"]
            if formal["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"]:
                result["actual_score_nll"] = formal["log_score"]
                result["actual_score_nll_status"] = "FROZEN_EXACT_DISTRIBUTION"
            elif formal["OUT_OF_EXPLICIT_SUPPORT"]:
                result["actual_score_nll_status"] = "OUT_OF_EXPLICIT_SUPPORT"
            else:
                result["actual_score_nll_status"] = formal["formal_exact_distribution_status"]
    else:
        if allow_research_reconstruction and research_source == "matrix":
            expected = expected_goals(prediction)
            if expected is not None and expected[0] > 0 and expected[1] > 0:
                matrix = dixon_coles_score_matrix({
                    "lambda_home": expected[0],
                    "lambda_away": expected[1],
                    "rho": _number(prediction.get("rho")) or 0.0,
                })
                rows = _score_rows_from_matrix(matrix)
                full_score_matrix = bool(matrix)
        else:
            rows = extract_score_rows(
                prediction,
                include_distribution=include_distribution,
                preserve_declared_rank=preserve_declared_rank,
            )
            if (
                allow_research_reconstruction
                and not rows
                and prediction.get("derive_full_matrix") is True
            ):
                expected = expected_goals(prediction)
                if expected is not None:
                    matrix = dixon_coles_score_matrix({
                        "lambda_home": expected[0],
                        "lambda_away": expected[1],
                        "rho": _number(prediction.get("rho")) or 0.0,
                    })
                    rows = _score_rows_from_matrix(matrix)
                    full_score_matrix = bool(matrix)
            if prediction.get("score_matrix_complete") is True:
                full_score_matrix = bool(rows)

        matching = [
            (index + 1, float(row["probability"]))
            for index, row in enumerate(rows)
            if parse_score_pair(row) == actual_pair
        ]
        if matching:
            result["actual_score_rank"] = matching[0][0]
            result["actual_score_probability"] = matching[0][1]
            result["actual_score_assigned_probability"] = matching[0][1]
            result["actual_score_nll"] = -math.log(max(matching[0][1], EPSILON))
            result["actual_score_nll_status"] = "RESEARCH_RECONSTRUCTED_NO_FROZEN_AUTHORITY"
        elif rows:
            result["actual_score_nll_status"] = "UNAVAILABLE_IN_FROZEN_RECORD"

    if rows:
        actual_match = lambda row: parse_score_pair(row) == actual_pair
        top_values = {
            "score_top1": any(actual_match(row) for row in rows[:1]),
            "score_top3": any(actual_match(row) for row in rows[:3]),
            "score_top5": any(actual_match(row) for row in rows[:5]),
            "score_top10": (
                None
                if top10_requires_ten and len(rows) < 10
                else any(actual_match(row) for row in rows[:10])
            ),
        }
        result.update(top_values)
        result.update({
            "exact_score_top1": top_values["score_top1"],
            "exact_score_top3": top_values["score_top3"],
            "exact_score_top5": top_values["score_top5"],
            "exact_score_top10": top_values["score_top10"],
            "top1_1_1": parse_score_pair(rows[0]) == (1, 1),
        })
        if full_score_matrix:
            actual_total = sum(actual_pair)
            total_probability = sum(
                float(row["probability"])
                for row in rows
                if (parse_score_pair(row) or (-1, -1))[0] + (parse_score_pair(row) or (-1, -1))[1] == actual_total
            )
            if total_probability > 0:
                result["total_goals_nll"] = -math.log(max(total_probability, EPSILON))
    else:
        top1 = parse_score_pair(prediction.get("score_top1"))
        top3 = [parse_score_pair(value) for value in prediction.get("score_top3") or []]
        top5 = [parse_score_pair(value) for value in prediction.get("score_top5") or []]
        result.update({
            "exact_score_top1": top1 == actual_pair if top1 else None,
            "exact_score_top3": actual_pair in {value for value in top3 if value},
            "exact_score_top5": actual_pair in {value for value in top5 if value},
        })
        if result["actual_score_nll_status"] is None:
            result["actual_score_nll_status"] = "UNAVAILABLE_IN_FROZEN_RECORD"
    result["_score_rows"] = rows
    return result


def _btts_probability(prediction: Mapping[str, Any], rows: list[dict[str, Any]]) -> float | None:
    btts = prediction.get("btts")
    if isinstance(btts, Mapping):
        yes = _number(btts.get("yes"))
        if yes is not None:
            return yes
    if rows and (prediction.get("score_matrix_complete") is True or len(rows) >= 100):
        return sum(
            float(row["probability"])
            for row in rows
            if (parse_score_pair(row) or (-1, -1))[0] > 0
            and (parse_score_pair(row) or (-1, -1))[1] > 0
        )
    return None


def evaluate_prediction_common(
    prediction: Mapping[str, Any],
    result: Any,
    *,
    frozen_record: Mapping[str, Any] | None = None,
    allow_research_reconstruction: bool = False,
    research_source: str = "stored_or_matrix",
    include_distribution: bool = True,
    preserve_declared_rank: bool = False,
    top10_requires_ten: bool = False,
    log_loss_epsilon: float = EPSILON,
    fallback_missing_values: bool = False,
    include_output_probabilities: bool = True,
) -> dict[str, Any]:
    """Evaluate the common result/probability/Exact/lambda contract."""

    prediction = prediction if isinstance(prediction, Mapping) else {}
    normalized = normalize_verified_result(result)
    actual_pair = (normalized["home_score_90m"], normalized["away_score_90m"])
    probabilities = extract_probabilities(prediction, include_output=include_output_probabilities)
    if probabilities is None and fallback_missing_values:
        raw = prediction.get("probabilities") or prediction.get("outcome_probabilities") or {}
        probabilities = {
            key: float(_number(raw.get(key)) or 0.0)
            for key in OUTCOMES
        } if isinstance(raw, Mapping) else {key: 0.0 for key in OUTCOMES}
    one_x_two = evaluate_1x2_probabilities(
        probabilities,
        normalized["actual_outcome"],
        log_loss_epsilon=log_loss_epsilon,
    )
    exact = evaluate_exact_score(
        prediction,
        actual_pair,
        frozen_record=frozen_record,
        allow_research_reconstruction=allow_research_reconstruction,
        research_source=research_source,
        include_distribution=include_distribution,
        preserve_declared_rank=preserve_declared_rank,
        top10_requires_ten=top10_requires_ten,
    )
    residuals = evaluate_goal_residuals(
        prediction,
        actual_pair,
        fallback_missing_values=fallback_missing_values,
    )
    rows = exact.pop("_score_rows")
    common = {
        "actual_outcome": normalized["actual_outcome"],
        "actual_score": normalized["actual_score"],
        **one_x_two,
        **exact,
        **residuals,
        "btts_probability": _btts_probability(prediction, rows),
        "btts_actual": normalized["btts_actual"],
    }
    if common["btts_probability"] is not None:
        common.update({
            "btts_hit": bool(common["btts_probability"] >= 0.5) == common["btts_actual"],
            "btts_accuracy": bool(common["btts_probability"] >= 0.5) == common["btts_actual"],
        })
    else:
        common.update({"btts_hit": None, "btts_accuracy": None})
    return common
