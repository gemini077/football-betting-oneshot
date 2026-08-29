"""Bounded, research-only dynamic attack/defence baseline.

The module consumes already captured pre-match football evidence and produces a
single fixed specification.  It is intentionally independent of the
production Champion and has no write path into production or frozen
prediction records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_CONTRACT_VERSION = "prospective_football_evidence.v1"
MODEL_CONTRACT_VERSION = "dynamic_attack_defense_baseline.v1"
MODEL_NAME = "dynamic_attack_defense_bounded_baseline_v1"
MODEL_SPEC_ID = "dynamic-attack-defense:bounded-v1"
SCORE_MATRIX_MAX_GOAL = 8
_EPSILON = 1e-15


class InsufficientHistoryError(ValueError):
    """Raised when a target has no usable pre-kickoff team history."""


@dataclass(frozen=True)
class DynamicAttackDefenseSpec:
    """The one pre-declared configuration used by FE-DA-1.

    ``learning_rate`` is an online state-update constant, not a candidate
    family.  FE-DA-1 deliberately does not sweep it or any recent-form weight.
    """

    learning_rate: float = 0.12
    residual_clip: float = 0.75
    goal_pseudocount: float = 0.50
    minimum_history: int = 10
    minimum_team_history: int = 5
    goal_rate_floor: float = 0.20
    lambda_floor: float = 0.15
    lambda_ceiling: float = 4.80
    score_matrix_max_goal: int = SCORE_MATRIX_MAX_GOAL

    @property
    def spec_id(self) -> str:
        return MODEL_SPEC_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "learning_rate": self.learning_rate,
            "residual_clip": self.residual_clip,
            "goal_pseudocount": self.goal_pseudocount,
            "minimum_history": self.minimum_history,
            "minimum_team_history": self.minimum_team_history,
            "goal_rate_floor": self.goal_rate_floor,
            "lambda_floor": self.lambda_floor,
            "lambda_ceiling": self.lambda_ceiling,
            "score_matrix_max_goal": self.score_matrix_max_goal,
            "parameter_policy": "single_predeclared_spec",
            "weight_sweep": False,
        }


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _team_id(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _score(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _row_identity(row: Mapping[str, Any]) -> str:
    explicit = row.get("match_id") or row.get("canonical_match_id")
    if explicit not in (None, ""):
        return str(explicit)
    return "|".join(
        str(row.get(field) or "")
        for field in ("kickoff_at", "home_team_id", "away_team_id", "home_goals", "away_goals")
    )


def _target_team_from_group(rows: Sequence[Mapping[str, Any]], label: str) -> str:
    counts: Counter[str] = Counter()
    for row in rows:
        for field in ("home_team_id", "away_team_id"):
            value = _team_id(row.get(field))
            if value:
                counts[value] += 1
    if not counts:
        raise ValueError(f"{label} evidence has no stable team identity")
    team_id, frequency = counts.most_common(1)[0]
    if frequency != len(rows):
        raise ValueError(f"{label} evidence does not identify one team in every row")
    return team_id


def _normalise_sidecar_history(
    target: Mapping[str, Any], evidence: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if evidence.get("contract_version") != EVIDENCE_CONTRACT_VERSION:
        raise ValueError("unsupported football evidence contract")
    recent = evidence.get("recent_matches")
    if not isinstance(recent, Mapping):
        raise ValueError("football evidence recent_matches is required")
    home_rows = recent.get("home_team")
    away_rows = recent.get("away_team")
    if not isinstance(home_rows, list) or not isinstance(away_rows, list):
        raise ValueError("football evidence must contain home_team and away_team lists")
    if not home_rows or not away_rows:
        raise InsufficientHistoryError("both target teams need historical evidence")

    inferred_home = _target_team_from_group(home_rows, "home_team")
    inferred_away = _target_team_from_group(away_rows, "away_team")
    expected_home = _team_id(target.get("home_team_id")) or inferred_home
    expected_away = _team_id(target.get("away_team_id")) or inferred_away
    if expected_home != inferred_home or expected_away != inferred_away:
        raise ValueError("target team identity conflicts with football evidence")
    if expected_home == expected_away:
        raise ValueError("home and away target team identities must differ")

    target_time = _parse_datetime(target.get("kickoff_at"))
    captured_at = _parse_datetime(evidence.get("evidence_captured_at"))
    cutoff_at = _parse_datetime(evidence.get("source_cutoff_at"))
    if target_time is None or captured_at is None or cutoff_at is None:
        raise ValueError("target kickoff and evidence cutoff timestamps are required")
    if captured_at >= target_time or cutoff_at >= target_time:
        raise ValueError("football evidence was captured after target kickoff")

    normalised: list[dict[str, Any]] = []
    for group in (home_rows, away_rows):
        for raw in group:
            if not isinstance(raw, Mapping):
                continue
            kickoff = _parse_datetime(raw.get("match_date") or raw.get("kickoff_at"))
            home_id = _team_id(raw.get("home_team_id"))
            away_id = _team_id(raw.get("away_team_id"))
            home_goals = _score(raw.get("home_goals"))
            away_goals = _score(raw.get("away_goals"))
            if kickoff is None or not home_id or not away_id or home_goals is None or away_goals is None:
                continue
            # Date-only recent-match rows cannot prove a same-day event was
            # before the target kickoff, so they are admitted only on an
            # earlier calendar date.
            raw_date = str(raw.get("match_date") or "")
            if len(raw_date) == 10 and kickoff.date() >= target_time.date():
                continue
            if kickoff >= target_time:
                continue
            normalised.append(
                {
                    "match_id": _row_identity(
                        {
                            "kickoff_at": _iso(kickoff),
                            "home_team_id": home_id,
                            "away_team_id": away_id,
                            "home_goals": home_goals,
                            "away_goals": away_goals,
                        }
                    ),
                    "kickoff_at": _iso(kickoff),
                    "kickoff_precision": "date" if len(raw_date) == 10 else "datetime",
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "source_provider": evidence.get("source_provider") or "unknown",
                    "source_as_of_at": _iso(kickoff),
                    "captured_at": _iso(captured_at),
                    "source_cutoff_at": _iso(cutoff_at),
                    "provenance": {
                        "contract_version": EVIDENCE_CONTRACT_VERSION,
                        "provider": evidence.get("source_provider") or "unknown",
                        "captured_at": _iso(captured_at),
                        "source_cutoff_at": _iso(cutoff_at),
                        "nowscore_id": evidence.get("nowscore_id"),
                        "prediction_id": evidence.get("prediction_id"),
                    },
                }
            )
    return _deduplicate_history(normalised), {
        "source_contract": EVIDENCE_CONTRACT_VERSION,
        "source_provider": evidence.get("source_provider") or "unknown",
        "source_cutoff_at": _iso(cutoff_at),
        "evidence_captured_at": _iso(captured_at),
        "target_home_team_id": expected_home,
        "target_away_team_id": expected_away,
    }


def _normalise_history_records(
    target: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_time = _parse_datetime(target.get("kickoff_at"))
    if target_time is None:
        raise ValueError("target kickoff_at is required")
    target_match_id = str(target.get("match_id") or target.get("canonical_match_id") or target.get("match_key") or "")
    rows: list[dict[str, Any]] = []
    for raw in records:
        kickoff = _parse_datetime(raw.get("kickoff_at") or raw.get("match_date"))
        home_id = _team_id(raw.get("home_team_id"))
        away_id = _team_id(raw.get("away_team_id"))
        home_goals = _score(raw.get("home_goals"))
        away_goals = _score(raw.get("away_goals"))
        match_id = str(raw.get("canonical_match_id") or raw.get("match_id") or "")
        if kickoff is None or not match_id or not home_id or not away_id or home_goals is None or away_goals is None:
            continue
        if match_id == target_match_id or kickoff >= target_time:
            continue
        if raw.get("eligible_for_team_strength", True) is not True:
            continue
        if raw.get("duplicate_status", "unique") not in {"unique", "duplicate_same"}:
            continue
        if raw.get("source_conflict", False) is True or raw.get("entity_type", "club") != "club":
            continue
        rows.append(
            {
                "match_id": match_id,
                "kickoff_at": _iso(kickoff),
                "kickoff_precision": raw.get("kickoff_precision") or "datetime",
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "source_provider": raw.get("provider") or raw.get("source") or "historical_results",
                "source_as_of_at": raw.get("source_as_of_at"),
                "captured_at": raw.get("captured_at"),
                "source_cutoff_at": raw.get("source_as_of_at"),
                "provenance": dict(raw.get("provenance") or {}),
            }
        )
    return _deduplicate_history(rows), {
        "source_contract": "historical_match_result.v1",
        "source_provider": "historical_results",
        "target_home_team_id": _team_id(target.get("home_team_id")),
        "target_away_team_id": _team_id(target.get("away_team_id")),
    }


def _deduplicate_history(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        identity = _row_identity(row)
        existing = unique.get(identity)
        if existing is None:
            unique[identity] = row
            continue
        # Same source row can occur once in each target-side list.  A
        # conflicting duplicate is excluded rather than averaged.
        facts = tuple(row.get(field) for field in ("home_team_id", "away_team_id", "home_goals", "away_goals"))
        existing_facts = tuple(existing.get(field) for field in ("home_team_id", "away_team_id", "home_goals", "away_goals"))
        if facts != existing_facts:
            unique.pop(identity, None)
    return sorted(unique.values(), key=lambda row: (str(row.get("kickoff_at") or ""), str(row.get("match_id") or "")))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _poisson_probability(mean: float, goals: int) -> float:
    return math.exp(-mean) * mean**goals / math.factorial(goals)


def _probability_payload(lambda_home: float, lambda_away: float, max_goal: int) -> dict[str, Any]:
    cells = [
        {
            "score": f"{home}-{away}",
            "home_goals": home,
            "away_goals": away,
            "probability": _poisson_probability(lambda_home, home) * _poisson_probability(lambda_away, away),
        }
        for home in range(max_goal + 1)
        for away in range(max_goal + 1)
    ]
    cells.sort(key=lambda row: (-float(row["probability"]), int(row["home_goals"]), int(row["away_goals"])))
    outcome = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for home in range(41):
        home_probability = _poisson_probability(lambda_home, home)
        for away in range(41):
            probability = home_probability * _poisson_probability(lambda_away, away)
            key = "home" if home > away else "draw" if home == away else "away"
            outcome[key] += probability
    total = sum(outcome.values()) or 1.0
    matrix = {
        str(home): {
            str(away): _poisson_probability(lambda_home, home) * _poisson_probability(lambda_away, away)
            for away in range(max_goal + 1)
        }
        for home in range(max_goal + 1)
    }
    matrix_mass = sum(float(row["probability"]) for row in cells)
    return {
        "1x2": {key: value / total for key, value in outcome.items()},
        "score_matrix": matrix,
        "score_matrix_max_goal": max_goal,
        "score_matrix_mass": matrix_mass,
        "score_matrix_tail_probability": max(0.0, 1.0 - matrix_mass),
        "top_scores": cells[:10],
    }


def _fit_dynamic_state(
    history: Sequence[Mapping[str, Any]], spec: DynamicAttackDefenseSpec
) -> tuple[dict[str, float], dict[str, float], float, float, dict[str, int]]:
    if len(history) < spec.minimum_history:
        raise InsufficientHistoryError(
            f"history count {len(history)} is below minimum {spec.minimum_history}"
        )
    base_home = max(spec.goal_rate_floor, fmean(float(row["home_goals"]) for row in history))
    base_away = max(spec.goal_rate_floor, fmean(float(row["away_goals"]) for row in history))
    attack: defaultdict[str, float] = defaultdict(float)
    defence: defaultdict[str, float] = defaultdict(float)
    appearances: Counter[str] = Counter()
    team_ids = {
        _team_id(row.get("home_team_id"))
        for row in history
    } | {
        _team_id(row.get("away_team_id"))
        for row in history
    }
    team_ids.discard("")
    for row in history:
        home_id = _team_id(row["home_team_id"])
        away_id = _team_id(row["away_team_id"])
        expected_home = _clamp(
            base_home * math.exp(attack[home_id] + defence[away_id]),
            spec.lambda_floor,
            spec.lambda_ceiling,
        )
        expected_away = _clamp(
            base_away * math.exp(attack[away_id] + defence[home_id]),
            spec.lambda_floor,
            spec.lambda_ceiling,
        )
        home_residual = math.log(
            (float(row["home_goals"]) + spec.goal_pseudocount)
            / (expected_home + spec.goal_pseudocount)
        )
        away_residual = math.log(
            (float(row["away_goals"]) + spec.goal_pseudocount)
            / (expected_away + spec.goal_pseudocount)
        )
        home_residual = _clamp(home_residual, -spec.residual_clip, spec.residual_clip)
        away_residual = _clamp(away_residual, -spec.residual_clip, spec.residual_clip)
        rate = spec.learning_rate
        attack[home_id] += rate * home_residual
        defence[away_id] += rate * home_residual
        attack[away_id] += rate * away_residual
        defence[home_id] += rate * away_residual
        appearances[home_id] += 1
        appearances[away_id] += 1
        # Keep the latent factors identifiable around the league mean after
        # every observation; no target result or future row is involved.
        attack_mean = fmean(attack[team] for team in team_ids)
        defence_mean = fmean(defence[team] for team in team_ids)
        for team in team_ids:
            attack[team] -= attack_mean
            defence[team] -= defence_mean
    return dict(attack), dict(defence), base_home, base_away, dict(appearances)


def build_dynamic_prediction(
    target: Mapping[str, Any],
    evidence_or_history: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    spec: DynamicAttackDefenseSpec | None = None,
) -> dict[str, Any]:
    """Build one research-only dynamic attack/defence prediction.

    The target mapping is metadata only.  Its result fields, if present, are
    never inspected.  Evidence is filtered strictly before ``target``
    kickoff, then processed in chronological order.
    """

    selected = spec or DynamicAttackDefenseSpec()
    if isinstance(evidence_or_history, Mapping):
        history, source = _normalise_sidecar_history(target, evidence_or_history)
    else:
        history, source = _normalise_history_records(target, evidence_or_history)
    if len(history) < selected.minimum_history:
        raise InsufficientHistoryError(
            f"usable history count {len(history)} is below minimum {selected.minimum_history}"
        )
    home_id = _team_id(target.get("home_team_id")) or _team_id(source.get("target_home_team_id"))
    away_id = _team_id(target.get("away_team_id")) or _team_id(source.get("target_away_team_id"))
    if not home_id or not away_id:
        raise ValueError("target home_team_id and away_team_id are required")
    attack, defence, base_home, base_away, appearances = _fit_dynamic_state(history, selected)
    home_count = appearances.get(home_id, 0)
    away_count = appearances.get(away_id, 0)
    if home_count < selected.minimum_team_history or away_count < selected.minimum_team_history:
        raise InsufficientHistoryError("both target teams need the minimum historical appearances")
    lambda_home = _clamp(
        base_home * math.exp(attack.get(home_id, 0.0) + defence.get(away_id, 0.0)),
        selected.lambda_floor,
        selected.lambda_ceiling,
    )
    lambda_away = _clamp(
        base_away * math.exp(attack.get(away_id, 0.0) + defence.get(home_id, 0.0)),
        selected.lambda_floor,
        selected.lambda_ceiling,
    )
    payload = _probability_payload(lambda_home, lambda_away, selected.score_matrix_max_goal)
    top_scores = payload["top_scores"]
    target_time = _parse_datetime(target.get("kickoff_at"))
    if target_time is None:
        raise ValueError("target kickoff_at is required")
    return {
        "contract_version": MODEL_CONTRACT_VERSION,
        "model_name": MODEL_NAME,
        "model_kind": "dynamic_attack_defense",
        "research_only": True,
        "validated_for_model": False,
        "formal_benchmark_eligible": False,
        "target_match_id": str(target.get("match_id") or target.get("match_key") or ""),
        "target_match_key": str(target.get("match_key") or ""),
        "target_kickoff": _iso(target_time),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "rho": 0.0,
        "probabilities": payload["1x2"],
        "score_matrix": payload["score_matrix"],
        "score_matrix_max_goal": payload["score_matrix_max_goal"],
        "score_matrix_mass": payload["score_matrix_mass"],
        "score_matrix_tail_probability": payload["score_matrix_tail_probability"],
        "score_distribution": top_scores,
        "score_top1": top_scores[0]["score"],
        "score_top3": [row["score"] for row in top_scores[:3]],
        "score_top5": [row["score"] for row in top_scores[:5]],
        "features": {
            "feature_source": source.get("source_contract"),
            "source_provider": source.get("source_provider"),
            "source_cutoff_at": source.get("source_cutoff_at"),
            "evidence_captured_at": source.get("evidence_captured_at"),
            "history_scope": "strictly_before_target_kickoff",
            "history_identity_scope": "provider_scoped_team_id",
            "history_count": len(history),
            "home_history_count": home_count,
            "away_history_count": away_count,
            "base_home_goal_rate": base_home,
            "base_away_goal_rate": base_away,
            "home_attack_factor": math.exp(attack.get(home_id, 0.0)),
            "away_attack_factor": math.exp(attack.get(away_id, 0.0)),
            "home_defence_factor": math.exp(defence.get(home_id, 0.0)),
            "away_defence_factor": math.exp(defence.get(away_id, 0.0)),
            "state_update_count": len(history),
            "target_result_excluded": True,
            "used_match_ids": [str(row["match_id"]) for row in history],
            "used_kickoffs": [str(row["kickoff_at"]) for row in history],
            "provenance": [dict(row.get("provenance") or {}) for row in history],
        },
        "spec": selected.to_dict(),
    }


def _extract_1x2(prediction: Mapping[str, Any]) -> dict[str, float]:
    raw = prediction.get("probabilities")
    if isinstance(raw, Mapping) and isinstance(raw.get("1x2"), Mapping):
        raw = raw["1x2"]
    if not isinstance(raw, Mapping):
        nested = prediction.get("prediction_output")
        raw = nested.get("probabilities") if isinstance(nested, Mapping) else None
    if not isinstance(raw, Mapping):
        raise ValueError("prediction does not contain 1X2 probabilities")
    try:
        result = {key: float(raw[key]) for key in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError):
        raise ValueError("prediction has incomplete 1X2 probabilities") from None
    if any(not math.isfinite(value) or value < 0 for value in result.values()) or sum(result.values()) <= 0:
        raise ValueError("prediction has invalid 1X2 probabilities")
    total = sum(result.values())
    return {key: value / total for key, value in result.items()}


def _extract_lambda(prediction: Mapping[str, Any], key: str) -> float | None:
    value = prediction.get(key)
    if value is None and isinstance(prediction.get("prediction_output"), Mapping):
        value = prediction["prediction_output"].get(key)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _score_list(prediction: Mapping[str, Any], field: str) -> list[str]:
    value = prediction.get(field)
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    if isinstance(prediction.get("prediction_output"), Mapping):
        return _score_list(prediction["prediction_output"], field)
    rows = prediction.get("score_distribution") or prediction.get("top_scores")
    if isinstance(rows, Sequence):
        values = [row.get("score") for row in rows if isinstance(row, Mapping)]
        limit = {"score_top1": 1, "score_top3": 3, "score_top5": 5}.get(field, 10)
        return [str(item) for item in values[:limit] if item not in (None, "")]
    return []


def _actual_score(actual: Mapping[str, Any]) -> tuple[int, int]:
    home = _score(actual.get("home_score", actual.get("home_goals")))
    away = _score(actual.get("away_score", actual.get("away_goals")))
    if home is None or away is None:
        raise ValueError("actual result must contain non-negative home and away scores")
    return home, away


def _outcome(actual: Mapping[str, Any]) -> str:
    value = actual.get("outcome")
    if value in {"HOME", "DRAW", "AWAY"}:
        return str(value).lower()
    home, away = _actual_score(actual)
    return "home" if home > away else "draw" if home == away else "away"


def _score_nll_from_lambda(prediction: Mapping[str, Any], actual: Mapping[str, Any]) -> float | None:
    home_lambda = _extract_lambda(prediction, "lambda_home")
    away_lambda = _extract_lambda(prediction, "lambda_away")
    rho = prediction.get("rho")
    if home_lambda is None or away_lambda is None or rho not in (None, 0, 0.0):
        return None
    home, away = _actual_score(actual)
    probability = _poisson_probability(home_lambda, home) * _poisson_probability(away_lambda, away)
    return -math.log(max(probability, _EPSILON))


def _distribution(values: Iterable[float]) -> dict[str, float | None]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None, "mean": None}
    ordered = sorted(clean)

    def percentile(fraction: float) -> float:
        index = (len(ordered) - 1) * fraction
        lower = math.floor(index)
        upper = math.ceil(index)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

    return {
        "n": len(clean),
        "min": min(clean),
        "p25": percentile(0.25),
        "median": median(clean),
        "p75": percentile(0.75),
        "max": max(clean),
        "mean": fmean(clean),
    }


def _model_metrics(rows: Sequence[Mapping[str, Any]], model_key: str) -> dict[str, Any]:
    brier: list[float] = []
    logloss: list[float] = []
    goal_mae: list[float] = []
    home_mae: list[float] = []
    away_mae: list[float] = []
    exact_hits = {1: [], 3: [], 5: []}
    nll: list[float] = []
    top1_scores: list[str] = []
    lambdas_home: list[float] = []
    lambdas_away: list[float] = []
    large_score_top1: list[bool] = []
    large_score_probability: list[float] = []
    for row in rows:
        prediction = row[model_key]
        actual = row["actual"]
        probabilities = _extract_1x2(prediction)
        outcome = _outcome(actual)
        brier.append(sum((probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in probabilities))
        logloss.append(-math.log(max(probabilities[outcome], _EPSILON)))
        actual_home, actual_away = _actual_score(actual)
        lambda_home = _extract_lambda(prediction, "lambda_home")
        lambda_away = _extract_lambda(prediction, "lambda_away")
        if lambda_home is None or lambda_away is None:
            raise ValueError(f"{model_key} prediction is missing lambdas")
        home_mae.append(abs(lambda_home - actual_home))
        away_mae.append(abs(lambda_away - actual_away))
        goal_mae.append((home_mae[-1] + away_mae[-1]) / 2.0)
        score = f"{actual_home}-{actual_away}"
        for limit in exact_hits:
            exact_hits[limit].append(score in _score_list(prediction, f"score_top{limit}"))
        score_loss = _score_nll_from_lambda(prediction, actual)
        if score_loss is not None:
            nll.append(score_loss)
        top1 = _score_list(prediction, "score_top1")
        top1_score = top1[0] if top1 else ""
        top1_scores.append(top1_score)
        large_score_top1.append(
            bool(top1_score) and sum(int(part) for part in top1_score.split("-")) >= 5
        )
        if model_key == "dynamic_prediction":
            matrix = prediction.get("score_matrix") or {}
            tail = 0.0
            for home_text, away_values in matrix.items():
                if not isinstance(away_values, Mapping):
                    continue
                for away_text, probability in away_values.items():
                    if int(home_text) + int(away_text) >= 5:
                        tail += float(probability)
            large_score_probability.append(tail)
        lambdas_home.append(lambda_home)
        lambdas_away.append(lambda_away)
    score_status = "REAL" if nll else "UNAVAILABLE"
    return {
        "n": len(rows),
        "brier_1x2": fmean(brier) if brier else None,
        "logloss_1x2": fmean(logloss) if logloss else None,
        "goal_mae": fmean(goal_mae) if goal_mae else None,
        "home_goal_mae": fmean(home_mae) if home_mae else None,
        "away_goal_mae": fmean(away_mae) if away_mae else None,
        "exact_top1": fmean(exact_hits[1]) if exact_hits[1] else None,
        "exact_top3": fmean(exact_hits[3]) if exact_hits[3] else None,
        "exact_top5": fmean(exact_hits[5]) if exact_hits[5] else None,
        "score_nll": {
            "status": score_status,
            "n": len(nll),
            "value": fmean(nll) if nll else None,
            "reason": None if nll else "full score probability unavailable",
        },
        "one_to_one_share": fmean(score == "1-1" for score in top1_scores) if top1_scores else None,
        "lambda_home_distribution": _distribution(lambdas_home),
        "lambda_away_distribution": _distribution(lambdas_away),
        "large_score_tail": {
            "threshold_total_goals": 5,
            "actual_share": fmean(sum(_actual_score(row["actual"])) >= 5 for row in rows) if rows else None,
            "predicted_top1_share": fmean(large_score_top1) if large_score_top1 else None,
            "predicted_probability_share": fmean(large_score_probability) if large_score_probability else None,
            "predicted_probability_status": "REAL" if large_score_probability else "UNAVAILABLE",
        },
    }


def evaluate_paired_sample(
    rows: Sequence[Mapping[str, Any]], champion_match_keys: Sequence[str] | None = None
) -> dict[str, Any]:
    """Evaluate dynamic and Champion records only on one exact match-key set."""

    dynamic_keys = [str(row.get("match_key") or "") for row in rows]
    champion_keys = list(champion_match_keys) if champion_match_keys is not None else dynamic_keys.copy()
    actual_keys = [str(row.get("match_key") or "") for row in rows if row.get("actual") is not None]
    if len(dynamic_keys) != len(set(dynamic_keys)) or len(champion_keys) != len(set(champion_keys)):
        raise ValueError("strict paired sample requires unique match keys")
    if set(dynamic_keys) != set(champion_keys) or set(dynamic_keys) != set(actual_keys):
        raise ValueError("strict paired sample requires identical match keys")
    if any(not row.get("dynamic_prediction") or not row.get("champion_prediction") for row in rows):
        raise ValueError("strict paired sample requires both model predictions")
    dynamic = _model_metrics(rows, "dynamic_prediction")
    champion = _model_metrics(rows, "champion_prediction")
    history_pre_kickoff = []
    source_cutoff_pre_kickoff = []
    evidence_capture_pre_kickoff = []
    target_result_excluded = []
    for row in rows:
        prediction = row["dynamic_prediction"]
        features = prediction.get("features") or {}
        target_time = _parse_datetime(prediction.get("target_kickoff"))
        used_times = [_parse_datetime(value) for value in features.get("used_kickoffs") or []]
        history_pre_kickoff.append(
            target_time is not None and all(value is not None and value < target_time for value in used_times)
        )
        cutoff = _parse_datetime(features.get("source_cutoff_at"))
        captured = _parse_datetime(features.get("evidence_captured_at"))
        source_cutoff_pre_kickoff.append(target_time is not None and cutoff is not None and cutoff < target_time)
        evidence_capture_pre_kickoff.append(target_time is not None and captured is not None and captured < target_time)
        target_result_excluded.append(features.get("target_result_excluded") is True)
    # Frozen Champion records expose only top-10 score cells.  Reconstructing
    # a tail from lambdas would not preserve any approved calibration overlay,
    # so its score NLL and tail probability remain explicitly unavailable.
    champion["score_nll"] = {
        "status": "UNAVAILABLE",
        "n": 0,
        "value": None,
        "reason": "champion_frozen_distribution_top10_only",
    }
    champion["large_score_tail"]["predicted_probability_share"] = None
    champion["large_score_tail"]["predicted_probability_status"] = "UNAVAILABLE"
    delta_metrics = {}
    for key in ("brier_1x2", "logloss_1x2", "goal_mae", "exact_top1", "exact_top3", "exact_top5", "one_to_one_share"):
        delta_metrics[key] = (
            dynamic[key] - champion[key]
            if dynamic.get(key) is not None and champion.get(key) is not None
            else None
        )
    return {
        "model_metrics": {
            "dynamic_attack_defense": dynamic,
            "champion": champion,
        },
        "paired_deltas_dynamic_minus_champion": delta_metrics,
        "paired_sample_integrity": {
            "same_match_keys": True,
            "n": len(rows),
            "match_keys": sorted(dynamic_keys),
            "dynamic_unique": len(dynamic_keys) == len(set(dynamic_keys)),
            "champion_unique": len(champion_keys) == len(set(champion_keys)),
            "actual_present_for_each_match": len(actual_keys) == len(dynamic_keys),
            "history_pre_kickoff_for_each_match": all(history_pre_kickoff),
            "source_cutoff_pre_kickoff_for_each_match": all(source_cutoff_pre_kickoff),
            "evidence_capture_pre_kickoff_for_each_match": all(evidence_capture_pre_kickoff),
            "target_result_excluded_for_each_match": all(target_result_excluded),
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _timestamp_sort_value(value: Any) -> datetime:
    parsed = _parse_datetime(value)
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


def _compact_case(case: Mapping[str, Any]) -> dict[str, Any]:
    dynamic = case["dynamic_prediction"]
    champion = case["champion_prediction"]
    features = dynamic["features"]
    history_ids = [str(value) for value in features["used_match_ids"]]
    history_digest = hashlib.sha256(
        json.dumps(sorted(history_ids), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "match_key": case["match_key"],
        "prediction_id": case["prediction_id"],
        "target_kickoff": dynamic["target_kickoff"],
        "actual": case["actual"],
        "dynamic": {
            "lambda_home": dynamic["lambda_home"],
            "lambda_away": dynamic["lambda_away"],
            "probabilities": dynamic["probabilities"],
            "score_top5": dynamic["score_top5"],
            "history_count": features["history_count"],
            "used_match_ids_sha256": history_digest,
            "history_kickoff_first": features["used_kickoffs"][0],
            "history_kickoff_last": features["used_kickoffs"][-1],
            "source_cutoff_at": features.get("source_cutoff_at"),
        },
        "champion": {
            "model_family": champion.get("model_family"),
            "lambda_home": champion.get("lambda_home"),
            "lambda_away": champion.get("lambda_away"),
            "probabilities": champion.get("probabilities"),
            "score_top5": champion.get("score_top5"),
            "source_cutoff_at": champion.get("source_cutoff_at"),
        },
    }


def load_current_champion_paired_sample(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the current frozen Champion and pre-match evidence by match key.

    Duplicate prediction records for one match are reduced to the latest
    valid pre-kickoff freeze that has a matching evidence sidecar.  No result
    payload is passed into ``build_dynamic_prediction``.
    """

    ledger_path = root / "data" / "prospective" / "ledger.jsonl"
    prediction_root = root / "data" / "model_governance" / "predictions"
    evidence_root = root / "data" / "prospective" / "football_evidence"
    ledger_by_id: dict[str, dict[str, Any]] = {}
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict) and row.get("prediction_id"):
                    ledger_by_id[str(row["prediction_id"])] = row

    candidates: list[dict[str, Any]] = []
    excluded = Counter()
    for evidence_path in sorted(evidence_root.glob("*.json")):
        prediction_id = evidence_path.stem
        ledger = ledger_by_id.get(prediction_id)
        if ledger is None:
            excluded["no_ledger_record"] += 1
            continue
        prediction_path = prediction_root / f"{prediction_id}.json"
        if not prediction_path.is_file():
            excluded["no_champion_record"] += 1
            continue
        prediction = _read_json(prediction_path)
        evidence = _read_json(evidence_path)
        if (
            prediction.get("model_role") != "champion"
            or prediction.get("model_family") != "recent_form_market_calibrated_poisson_v2"
            or prediction.get("prediction_variant") != "model_only"
            or prediction.get("prediction_status") != "formal"
            or prediction.get("formal_eligible") is not True
            or ledger.get("formal_prospective_eligible") is not True
        ):
            excluded["not_formal_current_champion"] += 1
            continue
        actual = ledger.get("actual")
        if not isinstance(actual, Mapping):
            excluded["actual_missing"] += 1
            continue
        match_key = str(prediction.get("match_key") or (prediction.get("match_identity") or {}).get("match_key") or "")
        if not match_key or evidence.get("match_key") != match_key:
            excluded["match_key_mismatch"] += 1
            continue
        kickoff = _parse_datetime(prediction.get("kickoff_at"))
        cutoff = _parse_datetime(prediction.get("source_cutoff_at"))
        freeze = _parse_datetime(prediction.get("freeze_created_at") or prediction.get("created_at"))
        if kickoff is None or cutoff is None or freeze is None or cutoff >= kickoff or freeze >= kickoff:
            excluded["not_pre_kickoff"] += 1
            continue
        try:
            _actual_score(actual)
        except ValueError:
            excluded["actual_invalid"] += 1
            continue
        candidates.append(
            {
                "match_key": match_key,
                "prediction_id": prediction_id,
                "ledger": ledger,
                "champion_prediction": prediction,
                "evidence": evidence,
                "sort_at": cutoff,
            }
        )

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["match_key"]].append(candidate)
    selected: list[dict[str, Any]] = []
    duplicate_records = 0
    for match_key, group in sorted(grouped.items()):
        actual_facts = {_actual_score(candidate["ledger"]["actual"]) for candidate in group}
        if len(actual_facts) != 1:
            excluded["duplicate_actual_conflict"] += 1
            continue
        ordered = sorted(group, key=lambda row: (row["sort_at"], row["prediction_id"]))
        chosen = ordered[-1]
        duplicate_records += len(group) - 1
        selected.append(chosen)

    cases: list[dict[str, Any]] = []
    for item in selected:
        prediction = item["champion_prediction"]
        evidence = item["evidence"]
        target = {
            "prediction_id": item["prediction_id"],
            "match_key": item["match_key"],
            "match_id": prediction.get("match_id") or (prediction.get("match_identity") or {}).get("match_id"),
            "kickoff_at": prediction.get("kickoff_at"),
        }
        dynamic = build_dynamic_prediction(target, evidence)
        cases.append(
            {
                "match_key": item["match_key"],
                "prediction_id": item["prediction_id"],
                "dynamic_prediction": dynamic,
                "champion_prediction": prediction,
                "actual": dict(item["ledger"]["actual"]),
            }
        )
    cases.sort(key=lambda row: row["match_key"])
    metadata = {
        "ledger_path": "data/prospective/ledger.jsonl",
        "champion_path": "data/model_governance/predictions",
        "evidence_path": "data/prospective/football_evidence",
        "candidate_evidence_files": len(list(evidence_root.glob("*.json"))),
        "candidate_records": len(candidates),
        "selected_unique_matches": len(cases),
        "duplicate_records_excluded": duplicate_records,
        "excluded": dict(sorted(excluded.items())),
        "champion_model_family": "recent_form_market_calibrated_poisson_v2",
        "selection_policy": "latest valid pre-kickoff frozen Champion per match_key with matching evidence",
    }
    return cases, metadata


def run_fe_da1(root: Path = ROOT, output_root: Path | None = None) -> dict[str, Any]:
    cases, sample_metadata = load_current_champion_paired_sample(root)
    if not cases:
        raise ValueError("FE-DA-1 has no strict paired current Champion sample")
    evaluated = evaluate_paired_sample(cases)
    dynamic_rows = [_compact_case(case) for case in cases]
    target_kickoffs = [case["dynamic_prediction"]["target_kickoff"] for case in cases]
    history_kickoffs = [kickoff for case in cases for kickoff in case["dynamic_prediction"]["features"]["used_kickoffs"]]
    output_dir = output_root or (root / "data" / "football_data")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "milestone": "FE-DA-1",
        "contract_version": MODEL_CONTRACT_VERSION,
        "model_name": MODEL_NAME,
        "status": "READY_FOR_ACCEPTANCE",
        "research_only": True,
        "production_mutation": False,
        "champion_mutation": False,
        "frozen_prediction_mutation": False,
        "provider_expansion": False,
        "recent_form_weight_sweep": False,
        "spec": DynamicAttackDefenseSpec().to_dict(),
        "sample": {
            **sample_metadata,
            "target_kickoff_min": min(target_kickoffs),
            "target_kickoff_max": max(target_kickoffs),
            "history_kickoff_min": min(history_kickoffs),
            "history_kickoff_max": max(history_kickoffs),
            "history_source": EVIDENCE_CONTRACT_VERSION,
            "actual_source": "settled prospective ledger actual fields",
        },
        "evaluation": evaluated,
        "known_limitations": [
            "paired sample is small and limited to matches with an existing evidence sidecar",
            "Champion frozen score output is top-10 only; Champion Score NLL and full tail probability are not reported",
            "provider-scoped recent-match team IDs are not promoted to canonical identity by this research module",
            "no promotion or production serving decision is made",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "fe_da1_results_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "fe_da1_paired_predictions.json").write_text(
        json.dumps(dynamic_rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FE-DA-1 research-only evaluation")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    summary = run_fe_da1(args.root.resolve(), args.output_root.resolve() if args.output_root else None)
    print(json.dumps({
        "milestone": summary["milestone"],
        "status": summary["status"],
        "sample_n": summary["evaluation"]["paired_sample_integrity"]["n"],
        "dynamic": summary["evaluation"]["model_metrics"]["dynamic_attack_defense"],
        "champion": summary["evaluation"]["model_metrics"]["champion"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
