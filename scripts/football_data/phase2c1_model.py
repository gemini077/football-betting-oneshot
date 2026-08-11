"""Research-only basic Team Strength Poisson model and evaluation helpers.

The module deliberately contains no production model hooks.  Every feature is
constructed from normalized results strictly before the target kickoff, and
all probabilities are derived from one independent-Poisson score distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, factorial, isfinite, log
from random import Random
from typing import Any, Iterable, Mapping, Sequence


MODEL_CONTRACT_VERSION = "phase2c1_basic_team_strength.v1"
FORMULA_VERSION = "basic_team_strength_poisson.v1"
SCORE_MATRIX_MAX_GOAL = 8
EVALUATION_MAX_GOAL = 40
_EPSILON = 1e-15


class InsufficientHistoryError(ValueError):
    """Raised when a target cannot satisfy a candidate's minimum history."""


@dataclass(frozen=True)
class CandidateSpec:
    """A pre-registered, deliberately small model specification."""

    window: str = "last_10"
    shrinkage: int = 3
    window_limit: int | None = None
    minimum_history: int = 10
    home_away_treatment: str = "venue_split_with_overall_fallback"
    formula_version: str = FORMULA_VERSION

    @property
    def effective_window_limit(self) -> int | None:
        if self.window == "last_10":
            return 10
        if self.window == "last_20":
            return 20
        if self.window == "all_available_with_cap":
            return self.window_limit or 20
        raise ValueError(f"unsupported Phase 2C-1 window: {self.window}")

    @property
    def spec_id(self) -> str:
        suffix = f":cap{self.effective_window_limit}" if self.window == "all_available_with_cap" else ""
        return f"basic:{self.window}{suffix}:shrink{self.shrinkage}:venue-fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "window": self.window,
            "window_limit": self.effective_window_limit,
            "shrinkage": self.shrinkage,
            "minimum_history": self.minimum_history,
            "home_away_treatment": self.home_away_treatment,
            "formula_version": self.formula_version,
        }


# Six candidates is intentionally small: two recent windows plus a capped
# all-available option, each with one weak and one stronger prior.
CANDIDATE_SPECS: tuple[CandidateSpec, ...] = (
    CandidateSpec(window="last_10", shrinkage=3),
    CandidateSpec(window="last_10", shrinkage=10),
    CandidateSpec(window="last_20", shrinkage=3),
    CandidateSpec(window="last_20", shrinkage=10),
    CandidateSpec(window="all_available_with_cap", window_limit=50, shrinkage=3),
    CandidateSpec(window="all_available_with_cap", window_limit=50, shrinkage=10),
)


def candidate_specs_manifest() -> list[dict[str, Any]]:
    """Return the frozen candidate registry in deterministic order."""

    return [spec.to_dict() for spec in CANDIDATE_SPECS]


def spec_from_dict(value: Mapping[str, Any]) -> CandidateSpec:
    """Reconstruct a registered specification and reject unknown fields softly."""

    spec = CandidateSpec(
        window=str(value.get("window") or ""),
        shrinkage=int(value.get("shrinkage")),
        window_limit=int(value["window_limit"]) if value.get("window_limit") is not None else None,
        minimum_history=int(value.get("minimum_history", 10)),
        home_away_treatment=str(value.get("home_away_treatment") or "venue_split_with_overall_fallback"),
        formula_version=str(value.get("formula_version") or FORMULA_VERSION),
    )
    if spec.spec_id != value.get("spec_id"):
        raise ValueError("candidate specification identity does not match its fields")
    if spec.spec_id not in {item["spec_id"] for item in candidate_specs_manifest()}:
        raise ValueError(f"candidate specification is not registered: {spec.spec_id}")
    return spec


def select_spec(validation_results: Iterable[Mapping[str, Any]], registry: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Select exactly one registered spec using validation metrics only."""

    registered = {str(item.get("spec_id")): dict(item) for item in (registry or candidate_specs_manifest())}
    rows = [dict(row) for row in validation_results]
    if not rows:
        raise ValueError("validation produced no candidate results")
    unknown = sorted({str(row.get("spec_id")) for row in rows} - set(registered))
    if unknown:
        raise ValueError(f"validation result contains unregistered candidate: {unknown[0]}")

    def key(row: Mapping[str, Any]) -> tuple[float, float, float, str]:
        return (
            float(row.get("one_x_two_log_loss")),
            float(row.get("one_x_two_brier")),
            float(row.get("goal_distribution_nll")),
            str(row.get("spec_id")),
        )

    selected = min(rows, key=key)
    return {
        "selected_spec_id": str(selected["spec_id"]),
        "selection_reason": "minimum validation 1X2 log loss, then Brier, then goal NLL; candidates were frozen before validation",
        "validation_metrics": dict(selected),
    }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _target_time(target: Mapping[str, Any]) -> datetime:
    value = target.get("kickoff_at") or target.get("kickoff")
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError("target kickoff is required and must be ISO-8601")
    return parsed


def _target_competition(target: Mapping[str, Any]) -> str:
    value = target.get("competition_id")
    if not value:
        raise ValueError("target competition_id is required")
    return str(value)


def _usable_prior_records(
    target: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    *,
    scope: str,
    allowed_competitions: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    target_time = _target_time(target)
    competition = _target_competition(target)
    allowed = {str(value) for value in allowed_competitions} if allowed_competitions is not None else None
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for input_record in records:
        record = dict(input_record)
        match_id = str(record.get("canonical_match_id") or "")
        kickoff = _parse_time(record.get("kickoff_at"))
        if not match_id or match_id in seen or kickoff is None or kickoff >= target_time:
            continue
        if record.get("eligible_for_team_strength") is not True:
            continue
        if record.get("duplicate_status") not in {"unique", "duplicate_same"}:
            continue
        if record.get("source_conflict") is True or record.get("entity_type", "club") != "club":
            continue
        record_competition = str(record.get("competition_id") or "")
        if scope == "competition" and record_competition != competition:
            continue
        if allowed is not None and record_competition not in allowed:
            continue
        seen.add(match_id)
        output.append(record)
    return sorted(output, key=lambda row: (_parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("canonical_match_id"))))


def _team_line(record: Mapping[str, Any], team_id: str) -> tuple[int, int, str]:
    if record.get("home_team_id") == team_id:
        return int(record["home_goals"]), int(record["away_goals"]), "home"
    if record.get("away_team_id") == team_id:
        return int(record["away_goals"]), int(record["home_goals"]), "away"
    raise ValueError(f"team {team_id} is not present in match {record.get('canonical_match_id')}")


def shrink_rate(goals: int | float, matches: int, prior_weight: int | float, league_rate: float) -> float:
    """Shrink a team's observed per-match rate toward the league mean."""

    if matches < 0 or prior_weight < 0:
        raise ValueError("matches and prior_weight must be non-negative")
    denominator = matches + prior_weight
    if denominator == 0:
        return float(league_rate)
    return (float(goals) + float(prior_weight) * float(league_rate)) / denominator


def _mean_goals(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    if not rows:
        raise InsufficientHistoryError("competition has no pre-match scoring history")
    return sum(float(row[field]) for row in rows) / len(rows)


def _poisson_pmf(lam: float, goal: int) -> float:
    if goal < 0:
        return 0.0
    return exp(-lam) * (lam**goal) / factorial(goal)


def _safe_log(value: float) -> float:
    return log(max(float(value), _EPSILON))


def probability_payload(lambda_home: float, lambda_away: float) -> dict[str, Any]:
    """Build one coherent independent-Poisson probability distribution."""

    if not isfinite(lambda_home) or not isfinite(lambda_away) or lambda_home < 0 or lambda_away < 0:
        raise ValueError("Poisson lambdas must be finite and non-negative")
    home_lambda = max(float(lambda_home), 0.0)
    away_lambda = max(float(lambda_away), 0.0)
    home_eval = [_poisson_pmf(home_lambda, goal) for goal in range(EVALUATION_MAX_GOAL + 1)]
    away_eval = [_poisson_pmf(away_lambda, goal) for goal in range(EVALUATION_MAX_GOAL + 1)]
    outcome = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for home_goals, home_probability in enumerate(home_eval):
        for away_goals, away_probability in enumerate(away_eval):
            probability = home_probability * away_probability
            if home_goals > away_goals:
                outcome["home"] += probability
            elif home_goals == away_goals:
                outcome["draw"] += probability
            else:
                outcome["away"] += probability
    outcome_total = sum(outcome.values()) or 1.0
    outcome = {key: value / outcome_total for key, value in outcome.items()}

    score_matrix: dict[str, dict[str, float]] = {}
    matrix_mass = 0.0
    score_cells: list[dict[str, Any]] = []
    for home_goals in range(SCORE_MATRIX_MAX_GOAL + 1):
        row: dict[str, float] = {}
        for away_goals in range(SCORE_MATRIX_MAX_GOAL + 1):
            probability = _poisson_pmf(home_lambda, home_goals) * _poisson_pmf(away_lambda, away_goals)
            row[str(away_goals)] = probability
            matrix_mass += probability
            score_cells.append({"home_goals": home_goals, "away_goals": away_goals, "probability": probability})
        score_matrix[str(home_goals)] = row
    score_cells.sort(key=lambda item: (-float(item["probability"]), int(item["home_goals"]), int(item["away_goals"])))
    total_lambda = home_lambda + away_lambda
    under_probability = exp(-total_lambda) * (1.0 + total_lambda + (total_lambda**2) / 2.0)
    over_probability = 1.0 - under_probability
    btts_no = exp(-home_lambda) + exp(-away_lambda) - exp(-total_lambda)
    return {
        "1x2": outcome,
        "totals": {"over_2_5": over_probability, "under_2_5": under_probability},
        "btts": {"yes": 1.0 - btts_no, "no": btts_no},
        "score_matrix": score_matrix,
        "score_matrix_max_goal": SCORE_MATRIX_MAX_GOAL,
        "score_matrix_mass": matrix_mass,
        "score_matrix_tail_probability": max(0.0, 1.0 - matrix_mass),
        "top_scores": score_cells[:10],
        "top_score": score_cells[0],
    }


def _team_recent_rows(rows: Sequence[Mapping[str, Any]], team_id: str, limit: int | None) -> list[dict[str, Any]]:
    team_rows = [dict(row) for row in rows if row.get("home_team_id") == team_id or row.get("away_team_id") == team_id]
    return team_rows[-limit:] if limit is not None else team_rows


def _venue_rows(rows: Sequence[Mapping[str, Any]], team_id: str, venue: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if (row.get("home_team_id") == team_id and venue == "home")
        or (row.get("away_team_id") == team_id and venue == "away")
    ]


def _venue_rates(
    rows: Sequence[Mapping[str, Any]],
    team_id: str,
    venue: str,
    *,
    prior_weight: int,
    league_for_rate: float,
    league_against_rate: float,
) -> dict[str, Any]:
    scoped = _venue_rows(rows, team_id, venue)
    fallback = False
    if not scoped:
        scoped = list(rows)
        fallback = True
    scored = 0
    conceded = 0
    for record in scoped:
        team_scored, team_conceded, _ = _team_line(record, team_id)
        scored += team_scored
        conceded += team_conceded
    return {
        "matches": len(scoped),
        "goals_for": scored,
        "goals_against": conceded,
        "goals_for_rate": shrink_rate(scored, len(scoped), prior_weight, league_for_rate),
            "goals_against_rate": shrink_rate(conceded, len(scoped), prior_weight, league_against_rate),
        "fallback_to_overall": fallback,
        "match_ids": [str(row.get("canonical_match_id")) for row in scoped],
    }


def _prediction_base(
    target: Mapping[str, Any],
    *,
    model_name: str,
    model_kind: str,
    lambda_home: float,
    lambda_away: float,
    features: Mapping[str, Any],
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target_id = target.get("canonical_match_id") or target.get("target_match_id") or target.get("id")
    payload = probability_payload(lambda_home, lambda_away)
    return {
        "model_name": model_name,
        "model_kind": model_kind,
        "contract_version": MODEL_CONTRACT_VERSION,
        "target_match_id": str(target_id),
        "target_kickoff": str(target.get("kickoff_at") or target.get("kickoff")),
        "competition_id": str(target.get("competition_id")),
        "season_id": str(target.get("season_id")),
        "home_team_id": str(target.get("home_team_id")),
        "away_team_id": str(target.get("away_team_id")),
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": payload,
        "features": dict(features),
        "candidate_spec": dict(spec) if spec else None,
        "validated_for_model": False,
        "formal_benchmark_eligible": False,
    }


def build_team_strength_prediction(
    target: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    spec: CandidateSpec,
) -> dict[str, Any]:
    """Build the transparent Basic Team Strength prediction for one target."""

    home_team = str(target.get("home_team_id") or "")
    away_team = str(target.get("away_team_id") or "")
    if not home_team or not away_team:
        raise ValueError("target must contain both canonical team IDs")
    history = _usable_prior_records(target, records, scope="competition")
    target_time = _target_time(target)
    if not history:
        raise InsufficientHistoryError("target has no pre-match competition history")
    competition_home_rate = _mean_goals(history, "home_goals")
    competition_away_rate = _mean_goals(history, "away_goals")
    limit = spec.effective_window_limit
    home_history = _team_recent_rows(history, home_team, limit)
    away_history = _team_recent_rows(history, away_team, limit)
    if len(home_history) < spec.minimum_history or len(away_history) < spec.minimum_history:
        raise InsufficientHistoryError(
            f"target requires {spec.minimum_history} prior matches per team; got {len(home_history)}/{len(away_history)}"
        )
    home_rates = _venue_rates(
        home_history,
        home_team,
        "home",
        prior_weight=spec.shrinkage,
        league_for_rate=competition_home_rate,
        league_against_rate=competition_away_rate,
    )
    away_rates = _venue_rates(
        away_history,
        away_team,
        "away",
        prior_weight=spec.shrinkage,
        league_for_rate=competition_away_rate,
        league_against_rate=competition_home_rate,
    )
    home_attack = home_rates["goals_for_rate"] / max(competition_home_rate, _EPSILON)
    home_defence = home_rates["goals_against_rate"] / max(competition_away_rate, _EPSILON)
    away_attack = away_rates["goals_for_rate"] / max(competition_away_rate, _EPSILON)
    away_defence = away_rates["goals_against_rate"] / max(competition_home_rate, _EPSILON)
    lambda_home = competition_home_rate * home_attack * away_defence
    lambda_away = competition_away_rate * away_attack * home_defence
    used = {str(row.get("canonical_match_id")): row for row in history if row.get("canonical_match_id")}
    used.update({str(row.get("canonical_match_id")): row for row in home_history if row.get("canonical_match_id")})
    used.update({str(row.get("canonical_match_id")): row for row in away_history if row.get("canonical_match_id")})
    features = {
        "feature_source": "historical_results_only",
        "history_scope": "target_competition_before_kickoff",
        "used_match_ids": sorted(used),
        "used_kickoffs": sorted(str(row.get("kickoff_at")) for row in used.values()),
        "league_history_count": len(history),
        "league_home_goal_rate": competition_home_rate,
        "league_away_goal_rate": competition_away_rate,
        "home_history_count": len(home_history),
        "away_history_count": len(away_history),
        "home_rates": home_rates,
        "away_rates": away_rates,
        "home_attack_strength": home_attack,
        "home_defence_strength": home_defence,
        "away_attack_strength": away_attack,
        "away_defence_strength": away_defence,
        "target_result_excluded": True,
        "opponent_strength_used": False,
        "market_used": False,
        "xg_used": False,
        "as_of_at": _iso(target_time),
        "formula_version": spec.formula_version,
    }
    return _prediction_base(
        target,
        model_name="basic_team_strength",
        model_kind="team_strength",
        lambda_home=max(lambda_home, 0.0),
        lambda_away=max(lambda_away, 0.0),
        features=features,
        spec=spec.to_dict(),
    )


def build_baseline_prediction(
    target: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    *,
    baseline_kind: str = "competition_poisson",
    allowed_competitions: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a simple historical independent-Poisson research baseline."""

    if baseline_kind == "competition_poisson":
        history = _usable_prior_records(target, records, scope="competition")
        name = "research_baseline_a_competition_poisson"
        scope = "target_competition_before_kickoff"
    elif baseline_kind == "global_poisson":
        history = _usable_prior_records(target, records, scope="global", allowed_competitions=allowed_competitions)
        name = "research_baseline_b_global_poisson"
        scope = "recommended_competitions_before_kickoff"
    else:
        raise ValueError(f"unsupported research baseline: {baseline_kind}")
    if not history:
        raise InsufficientHistoryError(f"baseline has no pre-match history: {baseline_kind}")
    lambda_home = _mean_goals(history, "home_goals")
    lambda_away = _mean_goals(history, "away_goals")
    features = {
        "feature_source": "historical_results_only",
        "history_scope": scope,
        "used_match_ids": sorted(str(row.get("canonical_match_id")) for row in history),
        "used_kickoffs": sorted(str(row.get("kickoff_at")) for row in history),
        "history_count": len(history),
        "league_home_goal_rate": lambda_home,
        "league_away_goal_rate": lambda_away,
        "target_result_excluded": True,
        "opponent_strength_used": False,
        "market_used": False,
        "xg_used": False,
    }
    return _prediction_base(
        target,
        model_name=name,
        model_kind="baseline",
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        features=features,
    )


def attach_actual(prediction: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    """Attach the observed outcome only at evaluation time, never as a feature."""

    result = dict(prediction)
    result["actual"] = {
        "home_goals": int(target["home_goals"]),
        "away_goals": int(target["away_goals"]),
    }
    return result


def _outcome_label(home_goals: int, away_goals: int) -> str:
    return "home" if home_goals > away_goals else "away" if home_goals < away_goals else "draw"


def _binary_calibration(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 5) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    total = len(probabilities)
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [position for position, probability in enumerate(probabilities) if (lower <= probability < upper) or (index == bins - 1 and probability == upper)]
        if not members:
            continue
        mean_probability = sum(probabilities[position] for position in members) / len(members)
        mean_outcome = sum(outcomes[position] for position in members) / len(members)
        ece += len(members) / max(total, 1) * abs(mean_probability - mean_outcome)
        groups.append({"lower": lower, "upper": upper, "count": len(members), "mean_probability": mean_probability, "observed_rate": mean_outcome})
    return {"ece": ece, "bins": groups}


def _score_probability(lambda_home: float, lambda_away: float, home_goals: int, away_goals: int) -> float:
    return _poisson_pmf(max(lambda_home, 0.0), home_goals) * _poisson_pmf(max(lambda_away, 0.0), away_goals)


def _row_losses(row: Mapping[str, Any]) -> dict[str, float]:
    actual = row["actual"]
    home_goals = int(actual["home_goals"])
    away_goals = int(actual["away_goals"])
    probabilities = row["probabilities"]
    outcome = _outcome_label(home_goals, away_goals)
    one_x_two = probabilities["1x2"]
    one_x_two_brier = sum((float(one_x_two[label]) - (1.0 if label == outcome else 0.0)) ** 2 for label in ("home", "draw", "away"))
    total_actual = home_goals + away_goals
    over = int(total_actual >= 3)
    over_probability = float(probabilities["totals"]["over_2_5"])
    btts = int(home_goals > 0 and away_goals > 0)
    btts_probability = float(probabilities["btts"]["yes"])
    return {
        "one_x_two_log_loss": -_safe_log(float(one_x_two[outcome])),
        "one_x_two_brier": one_x_two_brier,
        "goal_distribution_nll": -_safe_log(_score_probability(row["lambda_home"], row["lambda_away"], home_goals, away_goals)),
        "home_goals_mae": abs(float(row["lambda_home"]) - home_goals),
        "away_goals_mae": abs(float(row["lambda_away"]) - away_goals),
        "expected_total_goals_mae": abs(float(row["lambda_home"]) + float(row["lambda_away"]) - total_actual),
        "over_2_5_log_loss": -_safe_log(over_probability if over else 1.0 - over_probability),
        "over_2_5_brier": (over_probability - over) ** 2,
        "btts_log_loss": -_safe_log(btts_probability if btts else 1.0 - btts_probability),
        "btts_brier": (btts_probability - btts) ** 2,
    }


def evaluate_predictions(predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate predictions against outcomes using only the same fixture set."""

    rows = [dict(row) for row in predictions]
    if not rows:
        raise ValueError("cannot evaluate an empty prediction set")
    losses = [_row_losses(row) for row in rows]
    metrics = {key: sum(item[key] for item in losses) / len(losses) for key in losses[0]}
    one_x_two_probabilities = [float(row["probabilities"]["1x2"]["home"]) for row in rows]
    one_x_two_outcomes = [int(row["actual"]["home_goals"]) > int(row["actual"]["away_goals"]) for row in rows]
    over_probabilities = [float(row["probabilities"]["totals"]["over_2_5"]) for row in rows]
    over_outcomes = [int(row["actual"]["home_goals"]) + int(row["actual"]["away_goals"]) >= 3 for row in rows]
    btts_probabilities = [float(row["probabilities"]["btts"]["yes"]) for row in rows]
    btts_outcomes = [int(row["actual"]["home_goals"]) > 0 and int(row["actual"]["away_goals"]) > 0 for row in rows]
    exact_rows: list[dict[str, Any]] = []
    for row in rows:
        home_goals = int(row["actual"]["home_goals"])
        away_goals = int(row["actual"]["away_goals"])
        actual_probability = _score_probability(row["lambda_home"], row["lambda_away"], home_goals, away_goals)
        cells = [
            (h, a, _score_probability(row["lambda_home"], row["lambda_away"], h, a))
            for h in range(SCORE_MATRIX_MAX_GOAL + 1)
            for a in range(SCORE_MATRIX_MAX_GOAL + 1)
        ]
        rank = 1 + sum(probability > actual_probability for _, _, probability in cells)
        exact_rows.append({
            "actual_score_log_probability": -_safe_log(actual_probability),
            "actual_score_rank": rank,
            "top1": home_goals <= SCORE_MATRIX_MAX_GOAL and away_goals <= SCORE_MATRIX_MAX_GOAL and rank <= 1,
            "top3": home_goals <= SCORE_MATRIX_MAX_GOAL and away_goals <= SCORE_MATRIX_MAX_GOAL and rank <= 3,
            "top5": home_goals <= SCORE_MATRIX_MAX_GOAL and away_goals <= SCORE_MATRIX_MAX_GOAL and rank <= 5,
            "top10": home_goals <= SCORE_MATRIX_MAX_GOAL and away_goals <= SCORE_MATRIX_MAX_GOAL and rank <= 10,
        })
    metrics.update({
        "sample": len(rows),
        "calibration": {
            "one_x_two_home": _binary_calibration(one_x_two_probabilities, [int(value) for value in one_x_two_outcomes]),
            "over_2_5": _binary_calibration(over_probabilities, [int(value) for value in over_outcomes]),
            "btts": _binary_calibration(btts_probabilities, [int(value) for value in btts_outcomes]),
        },
        "exact_score": {
            "actual_score_log_probability": sum(item["actual_score_log_probability"] for item in exact_rows) / len(exact_rows),
            "actual_score_rank": sum(item["actual_score_rank"] for item in exact_rows) / len(exact_rows),
            "top1": sum(bool(item["top1"]) for item in exact_rows) / len(exact_rows),
            "top3": sum(bool(item["top3"]) for item in exact_rows) / len(exact_rows),
            "top5": sum(bool(item["top5"]) for item in exact_rows) / len(exact_rows),
            "top10": sum(bool(item["top10"]) for item in exact_rows) / len(exact_rows),
        },
    })
    return metrics


def metric_loss_values(predictions: Iterable[Mapping[str, Any]], metric: str) -> list[float]:
    """Return fixture-level losses for a paired comparison."""

    rows = [dict(row) for row in predictions]
    values = [_row_losses(row) for row in rows]
    if not values or metric not in values[0]:
        raise ValueError(f"unsupported paired metric: {metric}")
    return [float(value[metric]) for value in values]


def paired_bootstrap_deltas(
    challenger_values: Sequence[float],
    baseline_values: Sequence[float],
    *,
    n_bootstrap: int = 1000,
    seed: int = 20260811,
) -> dict[str, Any]:
    """Bootstrap paired challenger-minus-baseline fixture loss deltas."""

    if len(challenger_values) != len(baseline_values) or not challenger_values:
        raise ValueError("paired bootstrap requires equally sized non-empty inputs")
    deltas = [float(left) - float(right) for left, right in zip(challenger_values, baseline_values)]
    rng = Random(seed)
    samples = []
    for _ in range(int(n_bootstrap)):
        samples.append(sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas))
    samples.sort()
    lower_index = max(0, int(0.025 * len(samples)) - 1)
    upper_index = min(len(samples) - 1, int(0.975 * len(samples)))
    return {
        "sample": len(deltas),
        "n_bootstrap": int(n_bootstrap),
        "seed": int(seed),
        "mean_delta": sum(deltas) / len(deltas),
        "ci_95": [samples[lower_index], samples[upper_index]],
        "direction": "lower_is_better",
    }


def classification_from_deltas(deltas: Mapping[str, float]) -> str:
    """Conservative three-way research classification."""

    primary = [
        deltas.get("one_x_two_log_loss", 0.0),
        deltas.get("one_x_two_brier", 0.0),
        deltas.get("goal_distribution_nll", 0.0),
        deltas.get("over_2_5_log_loss", 0.0),
        deltas.get("btts_log_loss", 0.0),
    ]
    improvements = sum(value < 0 for value in primary)
    regressions = sum(value > 0 for value in primary)
    if improvements >= 4 and regressions <= 1:
        return "RESEARCH_PROMISING"
    if regressions >= 4:
        return "RESEARCH_NOT_PROMISING"
    return "INCONCLUSIVE"


__all__ = [
    "CANDIDATE_SPECS",
    "CandidateSpec",
    "FORMULA_VERSION",
    "InsufficientHistoryError",
    "MODEL_CONTRACT_VERSION",
    "attach_actual",
    "build_baseline_prediction",
    "build_team_strength_prediction",
    "candidate_specs_manifest",
    "classification_from_deltas",
    "evaluate_predictions",
    "metric_loss_values",
    "paired_bootstrap_deltas",
    "probability_payload",
    "select_spec",
    "shrink_rate",
    "spec_from_dict",
]
