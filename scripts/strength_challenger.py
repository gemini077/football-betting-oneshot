"""Research-only opponent-adjusted strength challenger.

This module is intentionally separate from the production prediction path.  It
reads historical results and persisted production records, creates shadow
predictions, and writes research artifacts only when invoked by its CLI.  It
does not import or call the production Champion, freeze, prospective, or
automation code.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite, log
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Support both ``python -m scripts.strength_challenger`` and the repository's
# established direct-script invocation form.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.football_data.data_home import resolve_football_data_home
from scripts.football_data.phase2c1_model import InsufficientHistoryError, probability_payload
from scripts.football_data.storage import HistoricalResultStore


CHALLENGER_NAME = "opponent_adjusted_strength_poisson_v1"
SCORE_TOP_K = (1, 3, 5)
_EPSILON = 1e-15


@dataclass(frozen=True)
class ChallengerSpec:
    """Small, pre-registered challenger configuration."""

    regularization: int = 10
    minimum_history: int = 5
    competition_minimum_rows: int = 20
    recency_policy: str = "none"
    rho: float = 0.0
    formula_version: str = CHALLENGER_NAME


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _parse_time(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _sort_key(row: Mapping[str, Any]) -> tuple[datetime, str]:
    return (_parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("canonical_match_id") or ""))


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _score_string(value: Any) -> str | None:
    if isinstance(value, str) and "-" in value:
        left, right = value.split("-", 1)
        if left.strip().isdigit() and right.strip().isdigit():
            return f"{int(left)}-{int(right)}"
    if isinstance(value, Mapping):
        home = value.get("home_goals", value.get("home"))
        away = value.get("away_goals", value.get("away"))
        if str(home).isdigit() and str(away).isdigit():
            return f"{int(home)}-{int(away)}"
    return None


def _score_parts(value: Any) -> tuple[int, int] | None:
    score = _score_string(value)
    if not score:
        return None
    home, away = score.split("-")
    return int(home), int(away)


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def _normalise_probabilities(values: Mapping[str, Any]) -> dict[str, float] | None:
    result = {key: _finite_number(values.get(key)) for key in ("home", "draw", "away")}
    if any(value is None or value < 0 for value in result.values()):
        return None
    total = sum(float(value) for value in result.values())
    if total <= 0:
        return None
    return {key: round(float(value) / total, 12) for key, value in result.items()}


def _required_result_reason(row: Mapping[str, Any]) -> str | None:
    required = ("canonical_match_id", "competition_id", "home_team_id", "away_team_id", "kickoff_at", "home_goals", "away_goals")
    if any(row.get(key) in (None, "") for key in required):
        return "missing_required_result"
    if _parse_time(row.get("kickoff_at")) is None:
        return "invalid_kickoff"
    if _finite_number(row.get("home_goals")) is None or _finite_number(row.get("away_goals")) is None:
        return "missing_required_result"
    if row.get("eligible_for_team_strength") is not True:
        return "not_eligible_for_team_strength"
    if row.get("duplicate_status") not in {"unique", "duplicate_same"}:
        return "duplicate_or_conflicting"
    if row.get("source_conflict") is True:
        return "source_conflict"
    if row.get("entity_type", "club") != "club":
        return "non_club_entity"
    return None


def dataset_gate(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate the historical result contract without changing any row."""

    eligible: list[dict[str, Any]] = []
    excluded = Counter()
    seen: set[str] = set()
    for input_row in records:
        row = dict(input_row)
        reason = _required_result_reason(row)
        match_id = str(row.get("canonical_match_id") or "")
        if reason is None and match_id in seen:
            reason = "duplicate_canonical_match_id"
        if reason is None:
            seen.add(match_id)
            row["home_goals"] = int(row["home_goals"])
            row["away_goals"] = int(row["away_goals"])
            eligible.append(row)
        else:
            excluded[reason] += 1
    eligible.sort(key=_sort_key)
    return {
        "required_fields": ["date/kickoff_at", "competition_id", "home_team_id", "away_team_id", "home_goals", "away_goals"],
        "input_count": len(eligible) + sum(excluded.values()),
        "eligible_count": len(eligible),
        "excluded_count": sum(excluded.values()),
        "excluded_by_reason": dict(sorted(excluded.items())),
        "eligible_records": eligible,
    }


def chronological_split(records: Sequence[Mapping[str, Any]], *, train_fraction: float = 0.6, validation_fraction: float = 0.2) -> dict[str, Any]:
    """Create a deterministic chronological train/validation/holdout split."""

    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 or train_fraction + validation_fraction >= 1:
        raise ValueError("fractions must be positive and leave a holdout")
    ordered = sorted((dict(row) for row in records), key=_sort_key)
    count = len(ordered)
    train_end = max(1, int(count * train_fraction))
    train_end = _time_boundary(ordered, train_end)
    validation_size = max(1, int(count * validation_fraction))
    validation_end = min(count - 1, train_end + validation_size)
    validation_end = _time_boundary(ordered, validation_end)
    if validation_end <= train_end:
        validation_end = min(count - 1, train_end + 1)
    train = ordered[:train_end]
    validation = ordered[train_end:validation_end]
    holdout = ordered[validation_end:]
    return {
        "train": train,
        "validation": validation,
        "holdout": holdout,
        "fractions": {"train": train_fraction, "validation": validation_fraction, "holdout": 1 - train_fraction - validation_fraction},
        "ranges": {name: _range_metadata(rows) for name, rows in (("train", train), ("validation", validation), ("holdout", holdout))},
    }


def _time_boundary(rows: Sequence[Mapping[str, Any]], index: int) -> int:
    """Move a split boundary left so one kickoff timestamp is never split."""

    index = max(1, min(len(rows) - 1, index)) if len(rows) > 1 else len(rows)
    while 0 < index < len(rows) and _parse_time(rows[index - 1].get("kickoff_at")) == _parse_time(rows[index].get("kickoff_at")):
        index -= 1
    return index


def _range_metadata(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "start": _iso(rows[0].get("kickoff_at")) if rows else None,
        "end": _iso(rows[-1].get("kickoff_at")) if rows else None,
        "min_date": _iso(rows[0].get("kickoff_at"))[:10] if rows and _iso(rows[0].get("kickoff_at")) else None,
        "max_date": _iso(rows[-1].get("kickoff_at"))[:10] if rows and _iso(rows[-1].get("kickoff_at")) else None,
    }


def assert_evaluation_ids_not_in_history(history: Iterable[Mapping[str, Any]], evaluation_ids: Iterable[str]) -> None:
    overlap = {str(row.get("canonical_match_id")) for row in history} & {str(value) for value in evaluation_ids}
    if overlap:
        raise ValueError(f"evaluation IDs must not be in training history: {sorted(overlap)[0]}")


def _canonical_value(record: Mapping[str, Any], key: str) -> Any:
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), Mapping) else {}
    return record.get(key) if record.get(key) not in (None, "") else identity.get(key)


def prediction_record_target(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only explicit canonical identity; never fuzzy-resolve names."""

    match_id = _canonical_value(record, "canonical_match_id") or _canonical_value(record, "match_id") or _canonical_value(record, "match_key")
    competition = _canonical_value(record, "competition_id")
    home_id = _canonical_value(record, "home_team_id")
    away_id = _canonical_value(record, "away_team_id")
    kickoff = _canonical_value(record, "kickoff_at") or record.get("kickoff")
    if not all((match_id, competition, home_id, away_id, _parse_time(kickoff))):
        return {
            "status": "IDENTITY_UNAVAILABLE",
            "target": None,
            "reason": "canonical home/away team IDs and competition are not explicitly persisted; names are not fuzzy-resolved",
        }
    return {
        "status": "AVAILABLE",
        "target": {
            "canonical_match_id": str(match_id),
            "competition_id": str(competition),
            "season_id": str(_canonical_value(record, "season_id") or "unknown"),
            "home_team_id": str(home_id),
            "away_team_id": str(away_id),
            "kickoff_at": _iso(kickoff),
        },
        "reason": None,
    }


def _eligible_prior(target: Mapping[str, Any], records: Iterable[Mapping[str, Any]], *, competition: str | None = None) -> list[dict[str, Any]]:
    target_time = _parse_time(target.get("kickoff_at"))
    if target_time is None:
        raise ValueError("target kickoff_at is required")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for input_row in records:
        row = dict(input_row)
        match_id = str(row.get("canonical_match_id") or "")
        kickoff = _parse_time(row.get("kickoff_at"))
        if not match_id or match_id in seen or kickoff is None or kickoff >= target_time:
            continue
        if _required_result_reason(row) is not None:
            continue
        if competition is not None and str(row.get("competition_id")) != competition:
            continue
        seen.add(match_id)
        rows.append(row)
    return sorted(rows, key=_sort_key)


def _team_count(rows: Sequence[Mapping[str, Any]], team_id: str) -> int:
    return sum(1 for row in rows if str(row.get("home_team_id")) == team_id or str(row.get("away_team_id")) == team_id)


def _fit_opponent_strength_fast(records: Sequence[Mapping[str, Any]], *, regularization: int, tolerance: float = 1e-8, max_iterations: int = 200) -> dict[str, Any]:
    """Efficient equivalent of the existing research fixed-point equations.

    The older exploratory implementation repeatedly rebuilt four filtered row
    lists inside each team iteration.  This local research implementation
    keeps the same multiplicative equations but accumulates denominators in a
    single pass per iteration, which makes walk-forward evaluation practical.
    """

    if not records:
        raise InsufficientHistoryError("opponent solver has no history")
    teams = sorted({str(row["home_team_id"]) for row in records} | {str(row["away_team_id"]) for row in records})
    if len(teams) < 2:
        raise InsufficientHistoryError("opponent solver needs at least two teams")
    league_home = max(sum(int(row["home_goals"]) for row in records) / len(records), 1e-9)
    league_away = max(sum(int(row["away_goals"]) for row in records) / len(records), 1e-9)
    home_attack = {team: 1.0 for team in teams}
    away_attack = {team: 1.0 for team in teams}
    home_defence = {team: 1.0 for team in teams}
    away_defence = {team: 1.0 for team in teams}
    observed = {team: {"home_scored": 0, "away_scored": 0, "home_conceded": 0, "away_conceded": 0} for team in teams}
    for row in records:
        home, away = str(row["home_team_id"]), str(row["away_team_id"])
        home_goals, away_goals = int(row["home_goals"]), int(row["away_goals"])
        observed[home]["home_scored"] += home_goals
        observed[home]["home_conceded"] += away_goals
        observed[away]["away_scored"] += away_goals
        observed[away]["away_conceded"] += home_goals
    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        home_attack_denominator = {team: 0.0 for team in teams}
        away_attack_denominator = {team: 0.0 for team in teams}
        home_defence_denominator = {team: 0.0 for team in teams}
        away_defence_denominator = {team: 0.0 for team in teams}
        for row in records:
            home, away = str(row["home_team_id"]), str(row["away_team_id"])
            home_attack_denominator[home] += league_home * away_defence[away]
            away_attack_denominator[away] += league_away * home_defence[home]
            home_defence_denominator[home] += league_away * away_attack[away]
            away_defence_denominator[away] += league_home * home_attack[home]
        next_home_attack = {team: (observed[team]["home_scored"] + regularization) / (home_attack_denominator[team] + regularization) for team in teams}
        next_away_attack = {team: (observed[team]["away_scored"] + regularization) / (away_attack_denominator[team] + regularization) for team in teams}
        next_home_defence = {team: (observed[team]["home_conceded"] + regularization) / (home_defence_denominator[team] + regularization) for team in teams}
        next_away_defence = {team: (observed[team]["away_conceded"] + regularization) / (away_defence_denominator[team] + regularization) for team in teams}
        damping = 0.5
        updated = {
            "attack_home": {team: damping * next_home_attack[team] + (1 - damping) * home_attack[team] for team in teams},
            "attack_away": {team: damping * next_away_attack[team] + (1 - damping) * away_attack[team] for team in teams},
            "defence_home": {team: damping * next_home_defence[team] + (1 - damping) * home_defence[team] for team in teams},
            "defence_away": {team: damping * next_away_defence[team] + (1 - damping) * away_defence[team] for team in teams},
        }
        difference = max(
            max(abs(updated["attack_home"][team] - home_attack[team]) for team in teams),
            max(abs(updated["attack_away"][team] - away_attack[team]) for team in teams),
            max(abs(updated["defence_home"][team] - home_defence[team]) for team in teams),
            max(abs(updated["defence_away"][team] - away_defence[team]) for team in teams),
        )
        home_attack, away_attack = updated["attack_home"], updated["attack_away"]
        home_defence, away_defence = updated["defence_home"], updated["defence_away"]
        iterations = iteration
        if difference <= tolerance:
            converged = True
            break
    all_values = [value for mapping in (home_attack, away_attack, home_defence, away_defence) for value in mapping.values()]
    if not all(isfinite(value) and value > 0 for value in all_values):
        raise ValueError("opponent solver produced a non-finite or non-positive strength")
    return {"league_home_goal_rate": league_home, "league_away_goal_rate": league_away, "attack_home": home_attack, "attack_away": away_attack, "defence_home": home_defence, "defence_away": away_defence, "solver": "multiplicative_fixed_point", "converged": converged, "iterations": iterations, "max_iterations": max_iterations, "convergence_tolerance": tolerance}


def build_opponent_adjusted_shadow(target: Mapping[str, Any], records: Iterable[Mapping[str, Any]], spec: ChallengerSpec) -> dict[str, Any]:
    """Fit the research formula on strict prior results and return a shadow prediction."""

    all_prior = _eligible_prior(target, records)
    competition = str(target.get("competition_id") or "")
    competition_prior = [row for row in all_prior if str(row.get("competition_id")) == competition]
    home_id, away_id = str(target.get("home_team_id") or ""), str(target.get("away_team_id") or "")
    if not home_id or not away_id:
        return {"status": "IDENTITY_UNAVAILABLE", "reason": "canonical target team IDs are required"}
    if len(competition_prior) >= spec.competition_minimum_rows and _team_count(competition_prior, home_id) >= spec.minimum_history and _team_count(competition_prior, away_id) >= spec.minimum_history:
        history = competition_prior
        history_scope = "competition_prior"
    else:
        history = all_prior
        history_scope = "global_fallback"
    if _team_count(history, home_id) < spec.minimum_history or _team_count(history, away_id) < spec.minimum_history:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": f"target requires {spec.minimum_history} prior matches per team",
            "features": {"history_scope": history_scope, "history_count": len(history), "target_result_excluded": True},
        }
    try:
        fitted = _fit_opponent_strength_fast(history, regularization=spec.regularization)
        lambda_home = fitted["league_home_goal_rate"] * fitted["attack_home"][home_id] * fitted["defence_away"][away_id]
        lambda_away = fitted["league_away_goal_rate"] * fitted["attack_away"][away_id] * fitted["defence_home"][home_id]
        payload = probability_payload(lambda_home, lambda_away)
    except (KeyError, InsufficientHistoryError, ValueError) as exc:
        return {"status": "INSUFFICIENT_HISTORY", "reason": str(exc), "features": {"history_scope": history_scope, "history_count": len(history), "target_result_excluded": True}}
    features = {
        "history_scope": history_scope,
        "history_count": len(history),
        "used_match_ids": [str(row["canonical_match_id"]) for row in history],
        "used_kickoffs": [str(row["kickoff_at"]) for row in history],
        "target_result_excluded": True,
        "opponent_strength_used": True,
        "market_used": False,
        "xg_used": False,
        "recency_policy": spec.recency_policy,
        "rho": spec.rho,
        "regularization": spec.regularization,
        "league_home_goal_rate": fitted["league_home_goal_rate"],
        "league_away_goal_rate": fitted["league_away_goal_rate"],
        "home_advantage_goal_rate": fitted["league_home_goal_rate"] - fitted["league_away_goal_rate"],
        "home_advantage_ratio": fitted["league_home_goal_rate"] / fitted["league_away_goal_rate"] if fitted["league_away_goal_rate"] else None,
        "solver": {key: fitted[key] for key in ("solver", "converged", "iterations", "max_iterations", "convergence_tolerance")},
        "as_of_at": str(target.get("kickoff_at")),
        "formula_version": spec.formula_version,
    }
    return {
        "status": "AVAILABLE",
        "model_name": CHALLENGER_NAME,
        "model_kind": "research_shadow_only",
        "lambda_home": float(lambda_home),
        "lambda_away": float(lambda_away),
        "probabilities": payload,
        "top_scores": payload["top_scores"],
        "score_matrix": payload["score_matrix"],
        "features": features,
        "spec": asdict(spec),
    }


def market_only_from_record(record: Mapping[str, Any]) -> dict[str, float] | None:
    candidates: list[Any] = [record.get("market_only_baseline")]
    for container_key in ("prediction_output", "prediction"):
        container = record.get(container_key)
        if isinstance(container, Mapping):
            candidates.append(container.get("market_only_baseline"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            result = _normalise_probabilities(candidate)
            if result is not None:
                return result
    return None


def blend_one_x_two(football: Mapping[str, Any], market: Mapping[str, Any], *, weight: float = 0.5) -> dict[str, float]:
    if not 0 <= weight <= 1:
        raise ValueError("weight must be between 0 and 1")
    left = _normalise_probabilities(football)
    right = _normalise_probabilities(market)
    if left is None or right is None:
        raise ValueError("both probability vectors must be valid")
    return _normalise_probabilities({key: round((1 - weight) * left[key] + weight * right[key], 12) for key in left}) or {}


def uniform_one_x_two() -> dict[str, float]:
    return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


def _prediction_probabilities(prediction: Mapping[str, Any]) -> dict[str, float] | None:
    value = prediction.get("probabilities")
    if isinstance(value, Mapping) and isinstance(value.get("1x2"), Mapping):
        return _normalise_probabilities(value["1x2"])
    if isinstance(value, Mapping):
        return _normalise_probabilities(value)
    return None


def _row_score_probability(prediction: Mapping[str, Any], actual_score: str) -> float | None:
    explicit = _finite_number(prediction.get("actual_score_probability"))
    if explicit is not None and explicit > 0:
        return explicit
    parts = _score_parts(actual_score)
    if parts is None:
        return None
    home, away = parts
    matrix = prediction.get("score_matrix")
    if isinstance(matrix, Mapping):
        row = matrix.get(str(home))
        if isinstance(row, Mapping):
            value = _finite_number(row.get(str(away)))
            if value is not None and value > 0:
                return value
    for candidate_key in ("top_scores", "score_distribution"):
        values = prediction.get(candidate_key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, Mapping) and _score_string(item) == actual_score:
                    value = _finite_number(item.get("probability"))
                    if value is not None and value > 0:
                        return value
    return None


def _prediction_top_scores(prediction: Mapping[str, Any]) -> list[str]:
    values = prediction.get("top_scores") or prediction.get("score_distribution") or []
    output: list[str] = []
    if isinstance(values, list):
        for item in values:
            score = _score_string(item.get("score")) if isinstance(item, Mapping) else _score_string(item)
            if score is None and isinstance(item, Mapping):
                score = _score_string(item)
            if score and score not in output:
                output.append(score)
    return output


def _actual_score_from_row(row: Mapping[str, Any]) -> str | None:
    return _score_string(row.get("actual_score"))


def summarise_prediction_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate paired metrics for rows with explicit actual outcomes."""

    available = [row for row in rows if str(row.get("status", "AVAILABLE")) == "AVAILABLE" and _actual_score_from_row(row)]
    brier_values: list[float] = []
    logloss_values: list[float] = []
    home_errors: list[float] = []
    away_errors: list[float] = []
    total_errors: list[float] = []
    top_hits = {key: 0 for key in SCORE_TOP_K}
    outcome_hits = 0
    score_nll: list[float] = []
    entropy_values: list[float] = []
    one_one = 0
    draw_score = 0
    predicted_one_one = 0
    lambda_gaps: list[float] = []
    ranked_score_rows = 0
    reliability: dict[str, dict[str, Any]] = {}
    for row in available:
        actual_score = _actual_score_from_row(row)
        actual_parts = _score_parts(actual_score)
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        probabilities = _prediction_probabilities(prediction)
        if actual_parts is None or probabilities is None:
            continue
        actual_home, actual_away = actual_parts
        actual_outcome = _outcome(actual_home, actual_away)
        target = {key: 1.0 if key == actual_outcome else 0.0 for key in probabilities}
        brier_values.append(sum((probabilities[key] - target[key]) ** 2 for key in probabilities))
        logloss_values.append(-log(max(probabilities[actual_outcome], _EPSILON)))
        lambda_home = _finite_number(prediction.get("lambda_home"))
        lambda_away = _finite_number(prediction.get("lambda_away"))
        if lambda_home is not None and lambda_away is not None:
            home_errors.append(abs(lambda_home - actual_home))
            away_errors.append(abs(lambda_away - actual_away))
            total_errors.append(abs(lambda_home + lambda_away - actual_home - actual_away))
            lambda_gaps.append(abs(lambda_home - lambda_away))
        ranked = _prediction_top_scores(prediction)
        if ranked:
            ranked_score_rows += 1
            predicted_one_one += int(ranked[0] == "1-1")
        for key in SCORE_TOP_K:
            if actual_score in ranked[:key]:
                top_hits[key] += 1
        if max(probabilities, key=probabilities.get) == actual_outcome:
            outcome_hits += 1
        stored_nll = _finite_number(prediction.get("actual_score_nll"))
        stored_nll_status = str(prediction.get("actual_score_nll_status") or "")
        if stored_nll is not None and stored_nll_status != "UNAVAILABLE_IN_FROZEN_RECORD":
            score_nll.append(stored_nll)
        else:
            probability = _row_score_probability(prediction, actual_score)
            if probability is not None and probability > 0:
                score_nll.append(-log(probability))
        matrix = prediction.get("score_matrix")
        if isinstance(matrix, Mapping):
            score_values = [float(value) for nested in matrix.values() if isinstance(nested, Mapping) for value in nested.values() if _finite_number(value) is not None and float(value) > 0]
            score_total = sum(score_values)
            if score_total > 0:
                entropy_values.append(-sum((value / score_total) * log(max(value / score_total, _EPSILON)) for value in score_values))
        one_one += actual_score == "1-1"
        draw_score += actual_home == actual_away
        favourite = max(probabilities.values())
        bucket = _reliability_bucket(favourite)
        item = reliability.setdefault(bucket, {"count": 0, "predicted_sum": 0.0, "actual_win_count": 0})
        item["count"] += 1
        item["predicted_sum"] += favourite
        item["actual_win_count"] += int(actual_outcome == max(probabilities, key=probabilities.get))
    sample = len(available)
    result = {
        "sample": sample,
        "one_x_two_brier": _mean(brier_values),
        "one_x_two_log_loss": _mean(logloss_values),
        "top1_outcome_accuracy": outcome_hits / sample if sample else None,
        "home_goals_mae": _mean(home_errors),
        "away_goals_mae": _mean(away_errors),
        "expected_total_goals_mae": _mean(total_errors),
        "exact_top1_accuracy": top_hits[1] / sample if sample and ranked_score_rows else None,
        "exact_top3_accuracy": top_hits[3] / sample if sample and ranked_score_rows else None,
        "exact_top5_accuracy": top_hits[5] / sample if sample and ranked_score_rows else None,
        "score_nll_available_count": len(score_nll),
        "score_nll_unavailable_count": max(0, sample - len(score_nll)),
        "mean_score_nll_available_only": _mean(score_nll),
        "unique_score_entropy": _mean(entropy_values),
        "predicted_top1_one_one_share": predicted_one_one / ranked_score_rows if ranked_score_rows else None,
        "actual_one_one_share": one_one / sample if sample else None,
        "actual_draw_score_share": draw_score / sample if sample else None,
        "mean_abs_lambda_gap": _mean(lambda_gaps),
        "reliability_buckets": _finish_reliability(reliability),
    }
    return result


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 12) if values else None


def _reliability_bucket(value: float) -> str:
    for threshold in (0.65, 0.60, 0.55, 0.50):
        if value >= threshold:
            return f">={threshold:.2f}"
    return "<0.50"


def _finish_reliability(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(values):
        item = values[key]
        count = int(item["count"])
        result[key] = {
            "count": count,
            "predicted_favourite_probability": item["predicted_sum"] / count if count else None,
            "actual_favourite_win_rate": item["actual_win_count"] / count if count else None,
            "small_sample": count < 10,
        }
    return result


def _actual_score(row: Mapping[str, Any]) -> str | None:
    if _score_string(row.get("actual_score")):
        return _score_string(row.get("actual_score"))
    home = _finite_number(row.get("home_goals"))
    away = _finite_number(row.get("away_goals"))
    return f"{int(home)}-{int(away)}" if home is not None and away is not None else None


def _make_historical_row(target: Mapping[str, Any], prediction: Mapping[str, Any]) -> dict[str, Any]:
    return {"status": prediction.get("status"), "match_id": target.get("canonical_match_id"), "actual_score": _actual_score(target), "prediction": prediction}


def _walk_forward_predictions(targets: Sequence[Mapping[str, Any]], all_history: Sequence[Mapping[str, Any]], spec: ChallengerSpec) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    leakage: list[dict[str, Any]] = []
    for target in sorted(targets, key=_sort_key):
        prediction = build_opponent_adjusted_shadow(target, all_history, spec)
        target_time = _parse_time(target.get("kickoff_at"))
        used = prediction.get("features", {}).get("used_kickoffs", []) if isinstance(prediction.get("features"), Mapping) else []
        training_times = [_parse_time(value) for value in used]
        training_times = [value for value in training_times if value]
        training_max = max(training_times) if training_times else None
        if target_time and training_max and not training_max < target_time:
            leakage.append({"match_id": target.get("canonical_match_id"), "training_max": _iso(training_max), "target": _iso(target_time)})
        rows.append(_make_historical_row(target, prediction))
    return rows, leakage


def evaluate_historical_walk_forward(records: Sequence[Mapping[str, Any]], *, specs: Sequence[ChallengerSpec] | None = None) -> dict[str, Any]:
    split = chronological_split(records)
    candidates = list(specs or [ChallengerSpec(regularization=value) for value in (5, 10, 20)])
    validation_results: list[dict[str, Any]] = []
    validation_rows_by_id: dict[str, list[dict[str, Any]]] = {}
    leakage: list[dict[str, Any]] = []
    for spec in candidates:
        rows, errors = _walk_forward_predictions(split["validation"], records, spec)
        metrics = summarise_prediction_rows(rows)
        validation_results.append({"spec_id": f"regularization:{spec.regularization}", "regularization": spec.regularization, **metrics})
        validation_rows_by_id[str(spec.regularization)] = rows
        leakage.extend(errors)
    usable_candidates = [row for row in validation_results if row.get("one_x_two_log_loss") is not None]
    selected_result = min(usable_candidates, key=lambda row: (row["one_x_two_log_loss"], row.get("one_x_two_brier") or float("inf"), row.get("mean_score_nll_available_only") or float("inf"), row["regularization"])) if usable_candidates else None
    selected_spec = next((spec for spec in candidates if selected_result and spec.regularization == selected_result["regularization"]), candidates[0])
    holdout_rows, errors = _walk_forward_predictions(split["holdout"], records, selected_spec)
    leakage.extend(errors)
    return {
        "split": {"ranges": split["ranges"], "counts": {key: len(split[key]) for key in ("train", "validation", "holdout")}},
        "candidate_validation_metrics": validation_results,
        "selected_spec": asdict(selected_spec),
        "selection_reason": "minimum validation 1X2 log loss, then Brier, then score NLL; deterministic tie-break by regularization",
        "holdout_metrics": summarise_prediction_rows(holdout_rows),
        "holdout_rows": holdout_rows,
        "leakage_audit": {"status": "LEAKAGE_FAIL" if leakage else "PASS", "violations": leakage, "every_training_max_before_target": not leakage},
    }


def _json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _load_prediction_records(root: Path) -> list[dict[str, Any]]:
    directory = root / "data" / "model_governance" / "predictions"
    output: list[dict[str, Any]] = []
    if not directory.exists():
        return output
    for path in sorted(directory.glob("*.json")):
        value = _json_load(path)
        if isinstance(value, Mapping):
            item = dict(value)
            item["_artifact_path"] = str(path.relative_to(root))
            output.append(item)
    return output


def _load_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "prospective" / "ledger.jsonl"
    output: list[dict[str, Any]] = []
    if not path.exists():
        return output
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            output.append(dict(value))
    return output


def _load_exclusion_ids(root: Path) -> set[str]:
    output: set[str] = set()
    directory = root / "data" / "model_governance" / "prediction_exclusions"
    for path in directory.glob("*.json") if directory.exists() else []:
        value = _json_load(path)
        if not isinstance(value, Mapping):
            continue
        for key in ("prediction_ids", "excluded_prediction_ids"):
            if isinstance(value.get(key), list):
                output.update(str(item) for item in value[key])
        if isinstance(value.get("exclusions"), list):
            for item in value["exclusions"]:
                output.add(str(item.get("prediction_id"))) if isinstance(item, Mapping) and item.get("prediction_id") else None
    return output


def _record_prediction_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("prediction_output", "prediction"):
        value = record.get(key)
        if isinstance(value, Mapping):
            return value
    return record


def _record_probabilities(record: Mapping[str, Any]) -> dict[str, float] | None:
    for value in (record.get("probabilities"), record.get("fusion_1X2"), _record_prediction_payload(record).get("probabilities")):
        if isinstance(value, Mapping):
            result = _normalise_probabilities(value.get("1x2") if isinstance(value.get("1x2"), Mapping) else value)
            if result is not None:
                return result
    return None


def _record_top_scores(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("score_distribution", "top_scores"):
        value = record.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping) and _score_string(item.get("score"))]
    payload = _record_prediction_payload(record)
    for key in ("score_distribution", "top_scores"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping) and _score_string(item.get("score"))]
    return []


def _persisted_prediction(record: Mapping[str, Any], *, ledger_metrics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = _record_prediction_payload(record)
    probabilities = _record_probabilities(record)
    lambda_home = _finite_number(record.get("lambda_home", payload.get("lambda_home")))
    lambda_away = _finite_number(record.get("lambda_away", payload.get("lambda_away")))
    result = {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": probabilities or {},
        "top_scores": _record_top_scores(record),
        "score_distribution": _record_top_scores(record),
    }
    metrics = ledger_metrics if isinstance(ledger_metrics, Mapping) else {}
    nll = _finite_number(metrics.get("actual_score_nll"))
    probability = _finite_number(metrics.get("actual_score_probability"))
    if nll is not None:
        result["actual_score_nll"] = nll
    if probability is not None and probability > 0:
        result["actual_score_probability"] = probability
    result["actual_score_nll_status"] = metrics.get("actual_score_nll_status")
    return result


def _record_actual(entry: Mapping[str, Any]) -> str | None:
    actual = entry.get("actual") if isinstance(entry.get("actual"), Mapping) else {}
    home = _finite_number(actual.get("home_score"))
    away = _finite_number(actual.get("away_score"))
    return f"{int(home)}-{int(away)}" if home is not None and away is not None else None


def _formal_rows(root: Path, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(record.get("prediction_id")): record for record in records if record.get("prediction_id")}
    exclusions = _load_exclusion_ids(root)
    output: list[dict[str, Any]] = []
    for entry in _load_ledger(root):
        if not entry.get("formal_prospective_eligible"):
            continue
        prediction_id = str(entry.get("prediction_id") or "")
        if not prediction_id or prediction_id in exclusions or prediction_id not in by_id:
            continue
        actual_score = _record_actual(entry)
        if not actual_score:
            continue
        record = by_id[prediction_id]
        output.append({"prediction_id": prediction_id, "record": record, "entry": entry, "actual_score": actual_score})
    return output


def _record_date(record: Mapping[str, Any]) -> str | None:
    value = record.get("business_date")
    return str(value) if value else None


def _current_records(records: Sequence[Mapping[str, Any]], business_date: str) -> list[dict[str, Any]]:
    return [dict(record) for record in records if _record_date(record) == business_date]


def _method_rows(records: Sequence[Mapping[str, Any]], *, method: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if method == "CURRENT_BASELINE":
            prediction = _persisted_prediction(record)
        elif method == "MARKET_ONLY":
            market = market_only_from_record(record)
            if market is None:
                continue
            prediction = {"probabilities": market, "top_scores": []}
        elif method == "UNIFORM_1X2":
            prediction = {"probabilities": uniform_one_x_two(), "top_scores": []}
        else:
            continue
        rows.append({"status": "AVAILABLE", "prediction_id": record.get("prediction_id"), "actual_score": None, "prediction": prediction})
    return rows


def _paired_method_rows(formal: Sequence[Mapping[str, Any]], *, method: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in formal:
        record = item["record"]
        if method == "CURRENT_BASELINE":
            prediction = _persisted_prediction(record, ledger_metrics=item.get("entry", {}).get("metrics") if isinstance(item.get("entry"), Mapping) else None)
        elif method == "MARKET_ONLY":
            market = market_only_from_record(record)
            if market is None:
                continue
            prediction = {"probabilities": market, "top_scores": []}
        elif method == "UNIFORM_1X2":
            prediction = {"probabilities": uniform_one_x_two(), "top_scores": []}
        else:
            continue
        rows.append({"status": "AVAILABLE", "prediction_id": item["prediction_id"], "actual_score": item["actual_score"], "prediction": prediction})
    return rows


def _identity_gate_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = Counter(prediction_record_target(record)["status"] for record in records)
    return {"counts": dict(statuses), "available_count": statuses.get("AVAILABLE", 0), "identity_unavailable_count": statuses.get("IDENTITY_UNAVAILABLE", 0), "fuzzy_resolution_used": False}


def _one_one_count(records: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for record in records:
        if _score_string(record.get("unique_score")) == "1-1":
            count += 1
    return count


def _leader_counts(records: Sequence[Mapping[str, Any]], *, market: bool = False) -> dict[str, int]:
    counts = Counter()
    for record in records:
        probabilities = market_only_from_record(record) if market else _record_probabilities(record)
        if probabilities:
            counts[max(probabilities, key=probabilities.get)] += 1
    return {key: counts.get(key, 0) for key in ("home", "draw", "away")}


def _record_lambda_gap_stats(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: list[float] = []
    for record in records:
        home = _finite_number(record.get("lambda_home"))
        away = _finite_number(record.get("lambda_away"))
        if home is not None and away is not None:
            values.append(abs(home - away))
    return {"count": len(values), "mean": _mean(values), "min": min(values) if values else None, "max": max(values) if values else None, "lt_0_5_count": sum(value < 0.5 for value in values)}


def _strong_favourite_diagnostics(formal: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for threshold in (0.55, 0.60, 0.65):
        rows: list[dict[str, Any]] = []
        for item in formal:
            market = market_only_from_record(item["record"])
            if not market:
                continue
            favourite = max(market.values())
            if favourite < threshold:
                continue
            actual = _score_parts(item["actual_score"])
            rows.append({"prediction_id": item["prediction_id"], "market_leader": max(market, key=market.get), "market_leader_probability": favourite, "actual_outcome": _outcome(*actual) if actual else None})
        result[f">={threshold:.2f}"] = {"count": len(rows), "rows": rows, "small_sample": len(rows) < 10}
    return result


def _representative_rows(holdout_rows: Sequence[Mapping[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in [item for item in holdout_rows if item.get("status") == "AVAILABLE"][:limit]:
        target_id = row.get("match_id")
        actual = row.get("actual_score")
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        result.append({"match_id": target_id, "actual": actual, "challenger_top1": _prediction_top_scores(prediction)[:1], "challenger_lambda": [prediction.get("lambda_home"), prediction.get("lambda_away")], "current": "UNAVAILABLE_IN_HISTORICAL_STORE", "market": "UNAVAILABLE_IN_HISTORICAL_STORE"})
    return result


def _dataset_summary(records: Sequence[Mapping[str, Any]], gate: Mapping[str, Any], store: HistoricalResultStore) -> dict[str, Any]:
    competitions = Counter(str(row.get("competition_id")) for row in records)
    qualities = Counter(str(row.get("quality")) for row in records)
    duplicates = Counter(str(row.get("duplicate_status")) for row in records)
    kickoff_values = [_parse_time(row.get("kickoff_at")) for row in records]
    kickoff_values = [value for value in kickoff_values if value]
    return {"record_count": len(records), "eligible_count": gate["eligible_count"], "excluded_count": gate["excluded_count"], "excluded_by_reason": gate["excluded_by_reason"], "date_range": {"start": _iso(min(kickoff_values)) if kickoff_values else None, "end": _iso(max(kickoff_values)) if kickoff_values else None}, "competitions": dict(sorted(competitions.items())), "quality": dict(sorted(qualities.items())), "duplicates": dict(sorted(duplicates.items())), "dataset_digest": store.dataset_digest()}


def run_research(*, root: Path, data_home: Path, business_date: str, output_dir: Path) -> dict[str, Any]:
    """Run the complete shadow study and write only to ``output_dir``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    store = HistoricalResultStore(data_home / "historical_results.duckdb")
    raw_records = list(store.iter_records())
    gate = dataset_gate(raw_records)
    records = gate["eligible_records"]
    historical = evaluate_historical_walk_forward(records)
    production_records = _load_prediction_records(root)
    current = _current_records(production_records, business_date)
    formal = _formal_rows(root, production_records)
    selected_spec = ChallengerSpec(**historical["selected_spec"])
    current_identity = _identity_gate_summary(current)
    formal_identity = _identity_gate_summary([item["record"] for item in formal])
    historical_metrics = historical["holdout_metrics"]
    formal_current_metrics = summarise_prediction_rows(_paired_method_rows(formal, method="CURRENT_BASELINE"))
    formal_market_metrics = summarise_prediction_rows(_paired_method_rows(formal, method="MARKET_ONLY"))
    formal_uniform_metrics = summarise_prediction_rows(_paired_method_rows(formal, method="UNIFORM_1X2"))
    formal_challenger_rows: list[dict[str, Any]] = []
    formal_replay_status = Counter()
    for item in formal:
        target_info = prediction_record_target(item["record"])
        if target_info["status"] != "AVAILABLE":
            formal_replay_status["IDENTITY_UNAVAILABLE"] += 1
            continue
        prediction = build_opponent_adjusted_shadow(target_info["target"], records, selected_spec)
        formal_replay_status[prediction.get("status", "UNKNOWN")] += 1
        if prediction.get("status") == "AVAILABLE":
            formal_challenger_rows.append({"status": "AVAILABLE", "prediction_id": item["prediction_id"], "actual_score": item["actual_score"], "prediction": prediction})
    current_shadow_rows: list[dict[str, Any]] = []
    current_challenger_status = Counter()
    current_challenger_one_one = 0
    for record in current:
        target_info = prediction_record_target(record)
        if target_info["status"] != "AVAILABLE":
            current_challenger_status["IDENTITY_UNAVAILABLE"] += 1
            continue
        prediction = build_opponent_adjusted_shadow(target_info["target"], records, selected_spec)
        current_challenger_status[prediction.get("status", "UNKNOWN")] += 1
        if prediction.get("status") == "AVAILABLE":
            current_shadow_rows.append({"prediction_id": record.get("prediction_id"), "prediction": prediction})
            if _prediction_top_scores(prediction)[:1] == ["1-1"]:
                current_challenger_one_one += 1
    paired_methods = {"CURRENT_BASELINE": formal_current_metrics, "MARKET_ONLY": formal_market_metrics, "NEW_FOOTBALL_ONLY": None, "NEW_FUSION_CHALLENGER": None, "UNIFORM_1X2": formal_uniform_metrics}
    production_comparison = {
        "business_date": business_date,
        "current_total": len(current),
        "current_one_one_count": _one_one_count(current),
        "current_probability_leader_counts": _leader_counts(current),
        "current_market_leader_counts": _leader_counts(current, market=True),
        "current_lambda_gap": _record_lambda_gap_stats(current),
        "current_identity_gate": current_identity,
        "formal_sample_count": len(formal),
        "formal_identity_gate": formal_identity,
        "formal_methods": paired_methods,
        "formal_challenger_metrics": summarise_prediction_rows(formal_challenger_rows) if formal_challenger_rows else {"sample": 0, "unavailable_reason": "IDENTITY_UNAVAILABLE"},
        "formal_challenger_status": dict(formal_replay_status),
        "current_challenger_status": dict(current_challenger_status),
        "current_challenger_available": len(current_shadow_rows),
        "current_challenger_one_one_count": current_challenger_one_one if current_shadow_rows else None,
        "paired_comparison_sample": len(formal_challenger_rows),
        "strong_favourite_diagnostics": _strong_favourite_diagnostics(formal),
    }
    uniform_holdout_rows = [{"status": "AVAILABLE", "actual_score": row.get("actual_score"), "prediction": {"probabilities": uniform_one_x_two(), "top_scores": []}} for row in historical["holdout_rows"] if row.get("actual_score")]
    uniform_holdout_metrics = summarise_prediction_rows(uniform_holdout_rows)
    uniform_holdout_paired_rows = [{"status": "AVAILABLE", "actual_score": row.get("actual_score"), "prediction": {"probabilities": uniform_one_x_two(), "top_scores": []}} for row in historical["holdout_rows"] if row.get("status") == "AVAILABLE" and row.get("actual_score")]
    uniform_holdout_paired_metrics = summarise_prediction_rows(uniform_holdout_paired_rows)
    benchmarks = {
        "CURRENT_BASELINE": {"scope": "formal_prospective_14", "metrics": formal_current_metrics},
        "MARKET_ONLY": {"scope": "formal_prospective_14", "metrics": formal_market_metrics},
        "NEW_FOOTBALL_ONLY": {"scope": "historical_holdout", "metrics": historical_metrics},
        "NEW_FUSION_CHALLENGER": {"scope": "formal_prospective_14", "metrics": {"sample": 0, "unavailable_reason": "IDENTITY_UNAVAILABLE: current/formal records lack explicit canonical team and competition IDs"}},
        "UNIFORM_1X2": {"scope": "formal_prospective_14", "metrics": formal_uniform_metrics},
        "UNIFORM_1X2_HISTORICAL_HOLDOUT": {"scope": "historical_holdout", "metrics": uniform_holdout_metrics},
        "UNIFORM_1X2_HISTORICAL_HOLDOUT_ON_CHALLENGER_SAMPLE": {"scope": "same_available_sample_as_new_football_only", "metrics": uniform_holdout_paired_metrics},
    }
    summary = {
        "schema_version": "pa2_strength_challenger.v1",
        "result": "INCOMPLETE" if not formal_challenger_rows or not current_shadow_rows else "COMPLETE_RESEARCH",
        "challenger_name": CHALLENGER_NAME,
        "research_only": True,
        "production_mutation": False,
        "promotion_status": "SHADOW_ONLY",
        "ca1_status": "KEEP_PAUSED",
        "dataset": _dataset_summary(raw_records, gate, store),
        "historical_split": historical["split"],
        "parameters": {"selected": asdict(selected_spec), "candidate_regularizations": [5, 10, 20], "market_fusion": "not evaluated without current canonical target identity", "rho": 0.0, "randomness": "none"},
        "leakage_audit": historical["leakage_audit"],
        "benchmarks": benchmarks,
        "production_comparison": production_comparison,
        "representative_matches": _representative_rows(historical["holdout_rows"], limit=10),
        "verdict": "FAIL" if historical_metrics.get("one_x_two_log_loss") is None else "NEUTRAL",
        "next_step": "MORE_DATA" if not formal_challenger_rows else "PA-3_SHADOW_PROSPECTIVE_ONLY",
        "limitations": [
            "Current/formal production records do not persist canonical team IDs and competition IDs; names were not fuzzy-resolved.",
            "Historical store has no corresponding freeze-time market prior, so market-only is unavailable on historical holdout.",
            "The challenger is not written into Champion or production prediction records.",
        ],
    }
    (output_dir / "challenger_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "walk_forward_metrics.json").write_text(json.dumps(historical, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    prediction_rows: list[dict[str, Any]] = []
    for row in historical["holdout_rows"]:
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        prediction_rows.append({"scope": "historical_holdout", "match_id": row.get("match_id"), "actual_score": row.get("actual_score"), "status": row.get("status"), "lambda_home": prediction.get("lambda_home"), "lambda_away": prediction.get("lambda_away"), "top1": (_prediction_top_scores(prediction) or [None])[0], "top3": "|".join(_prediction_top_scores(prediction)[:3])})
    with (output_dir / "challenger_predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scope", "match_id", "actual_score", "status", "lambda_home", "lambda_away", "top1", "top3"])
        writer.writeheader()
        writer.writerows(prediction_rows)
    return summary


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Run the PA-2 opponent-adjusted strength challenger as a read-only shadow study")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path, default=None)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data_home = args.data_home or resolve_football_data_home()
    summary = run_research(root=args.root, data_home=data_home, business_date=args.business_date, output_dir=args.output_dir)
    print(json.dumps({"result": summary["result"], "challenger": summary["challenger_name"], "holdout": summary["benchmarks"]["NEW_FOOTBALL_ONLY"]["metrics"], "formal_challenger_sample": summary["production_comparison"]["paired_comparison_sample"], "production_mutation": summary["production_mutation"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
