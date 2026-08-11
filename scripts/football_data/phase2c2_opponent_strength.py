"""Offline Phase 2C-2 opponent-adjusted Team Strength research.

This module is deliberately isolated from production model code.  It estimates
venue-specific multiplicative attack/defence strengths with a small regularized
fixed-point solver, compares them with a matched raw Team Strength reference,
and evaluates only the approved development and reused-validation fixtures.
The Phase 2C-1 held-out IDs are treated as spent and are rejected at the data
boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .data_home import resolve_football_data_home
from .phase2c1_experiment import (
    EXPECTED_COHORT_ID,
    EXPECTED_COHORT_MATCH_DIGEST,
    EXPECTED_DATASET_DIGEST,
    load_approved_cohort,
)
from .phase2c1_model import (
    CandidateSpec,
    InsufficientHistoryError,
    _prediction_base,
    _target_time,
    attach_actual,
    build_team_strength_prediction,
    evaluate_predictions,
    metric_loss_values,
    paired_bootstrap_deltas,
    probability_payload,
    shrink_rate,
    spec_from_dict,
)
from .storage import HistoricalResultStore, content_sha256


ROOT = Path(__file__).resolve().parents[2]
PHASE2C2_CONTRACT_VERSION = "phase2c2_opponent_strength.v1"
FORMULA_VERSION = "opponent_adjusted_poisson_fixed_point.v1"
MATCHED_RAW_FORMULA_VERSION = "matched_raw_team_strength.v1"
EXPECTED_POOL_SIZE = 544
EXPECTED_DEVELOPMENT_SIZE = 410
EXPECTED_VALIDATION_SIZE = 134
EXPECTED_SPENT_HELDOUT_SIZE = 144
EXPECTED_SPENT_HELDOUT_DIGEST = "a1b9ec5d0bf57e73b78eb00abffc95f5650ccf496bc8f8449e42040af097afce"
FROZEN_BASIC_SPEC_ID = "basic:last_10:shrink10:venue-fallback"
SOLVER_DEFAULT_TOLERANCE = 1e-8
SOLVER_DEFAULT_MAX_ITERATIONS = 1000
MINIMUM_HISTORY = 5
CORE_METRICS = (
    "one_x_two_log_loss",
    "one_x_two_brier",
    "goal_distribution_nll",
    "over_2_5_log_loss",
    "btts_log_loss",
)


@dataclass(frozen=True)
class OpponentSpec:
    """One pre-registered opponent-adjusted formula candidate."""

    regularization: int
    formula: str = FORMULA_VERSION
    history_policy: str = "target_competition_all_prior"
    home_away_formulation: str = "venue_specific_multiplicative"
    solver: str = "multiplicative_fixed_point"
    convergence_tolerance: float = SOLVER_DEFAULT_TOLERANCE
    max_iterations: int = SOLVER_DEFAULT_MAX_ITERATIONS
    minimum_history: int = MINIMUM_HISTORY

    @property
    def spec_id(self) -> str:
        return f"opponent:fixed-point:prior{self.regularization}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "formula": self.formula,
            "regularization": self.regularization,
            "history_policy": self.history_policy,
            "home_away_formulation": self.home_away_formulation,
            "solver": self.solver,
            "convergence_tolerance": self.convergence_tolerance,
            "max_iterations": self.max_iterations,
            "minimum_history": self.minimum_history,
        }


@dataclass(frozen=True)
class MatchedRawSpec:
    """Reference using the same environment and prior without opponent IDs."""

    regularization: int
    formula: str = MATCHED_RAW_FORMULA_VERSION
    history_policy: str = "target_competition_all_prior"
    home_away_formulation: str = "venue_split_with_overall_fallback"
    minimum_history: int = MINIMUM_HISTORY

    @property
    def spec_id(self) -> str:
        return f"matched-raw:prior{self.regularization}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "formula": self.formula,
            "regularization": self.regularization,
            "history_policy": self.history_policy,
            "home_away_formulation": self.home_away_formulation,
            "minimum_history": self.minimum_history,
        }


def candidate_specs_manifest() -> list[dict[str, Any]]:
    """Return the frozen, deliberately small candidate registry."""

    return [OpponentSpec(regularization=value).to_dict() for value in (5, 10, 20)]


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _sort_key(row: Mapping[str, Any]) -> tuple[datetime, str]:
    return (
        _parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc),
        str(row.get("canonical_match_id") or ""),
    )


def spent_heldout_digest(match_ids: Iterable[str]) -> str:
    """Hash only sorted spent IDs; no held-out result payload is required."""

    return content_sha256(sorted({str(value) for value in match_ids if str(value)}))


def assert_no_spent_heldout(records: Iterable[Mapping[str, Any]], spent_ids: Iterable[str]) -> None:
    """Reject spent fixtures before they can be used by fit or metric code."""

    spent = {str(value) for value in spent_ids}
    overlap = sorted({str(row.get("canonical_match_id")) for row in records} & spent)
    if overlap:
        raise ValueError(f"spent-heldout match IDs are not permitted in Phase 2C-2: {overlap[0]}")


def load_phase2c2_research_pool(
    *,
    root: Path = ROOT,
    data_home: str | Path | None = None,
) -> dict[str, Any]:
    """Load the 410/134 target pool and non-spent history from shared storage."""

    home = Path(data_home).expanduser() if data_home is not None else resolve_football_data_home()
    cohort = load_approved_cohort(data_home=home, root=root)
    spent_ids = set(cohort["split_ids"]["held_out_test"])
    if len(spent_ids) != EXPECTED_SPENT_HELDOUT_SIZE or spent_heldout_digest(spent_ids) != EXPECTED_SPENT_HELDOUT_DIGEST:
        raise ValueError("spent held-out ID lock mismatch")
    development_ids = set(cohort["split_ids"]["development"])
    validation_ids = set(cohort["split_ids"]["validation"])
    if len(development_ids) != EXPECTED_DEVELOPMENT_SIZE or len(validation_ids) != EXPECTED_VALIDATION_SIZE:
        raise ValueError("Phase 2C-2 split count mismatch")
    store = HistoricalResultStore(home / "historical_results.duckdb")
    if store.dataset_digest() != EXPECTED_DATASET_DIGEST:
        raise ValueError("historical dataset digest does not match approved Phase 2C-1 dataset")
    target_ids = development_ids | validation_ids
    target_rows = store.query_by_match_ids(target_ids)
    rows_by_id = {str(row.get("canonical_match_id")): row for row in target_rows}
    if set(rows_by_id) != target_ids:
        raise ValueError("Phase 2C-2 research target pool is incomplete")
    history_rows = list(store.iter_records(exclude_match_ids=spent_ids))
    assert_no_spent_heldout(target_rows, spent_ids)
    assert_no_spent_heldout(history_rows, spent_ids)
    return {
        "data_home": home,
        "cohort_id": EXPECTED_COHORT_ID,
        "cohort_match_digest": EXPECTED_COHORT_MATCH_DIGEST,
        "historical_dataset_digest": EXPECTED_DATASET_DIGEST,
        "spent_heldout_ids": sorted(spent_ids),
        "spent_heldout_digest": EXPECTED_SPENT_HELDOUT_DIGEST,
        "development": sorted((rows_by_id[str(value)] for value in development_ids), key=_sort_key),
        "validation": sorted((rows_by_id[str(value)] for value in validation_ids), key=_sort_key),
        "history_records": history_rows,
    }


def _usable_history(target: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    target_time = _target_time(target)
    competition = str(target.get("competition_id") or "")
    if not competition:
        raise ValueError("target competition_id is required")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for input_row in records:
        row = dict(input_row)
        match_id = str(row.get("canonical_match_id") or "")
        kickoff = _parse_time(row.get("kickoff_at"))
        if not match_id or match_id in seen or kickoff is None or kickoff >= target_time:
            continue
        if row.get("eligible_for_team_strength") is not True:
            continue
        if row.get("duplicate_status") not in {"unique", "duplicate_same"}:
            continue
        if row.get("source_conflict") is True or row.get("entity_type", "club") != "club":
            continue
        if str(row.get("competition_id") or "") != competition:
            continue
        seen.add(match_id)
        output.append(row)
    return sorted(output, key=_sort_key)


def _team_line(row: Mapping[str, Any], team_id: str) -> tuple[int, int, str]:
    if str(row.get("home_team_id")) == team_id:
        return int(row["home_goals"]), int(row["away_goals"]), "home"
    if str(row.get("away_team_id")) == team_id:
        return int(row["away_goals"]), int(row["home_goals"]), "away"
    raise ValueError(f"team {team_id} is not present in {row.get('canonical_match_id')}")


def _team_counts(rows: Sequence[Mapping[str, Any]], team_id: str) -> int:
    return sum(1 for row in rows if str(row.get("home_team_id")) == team_id or str(row.get("away_team_id")) == team_id)


def _teams(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted({str(row.get("home_team_id")) for row in rows} | {str(row.get("away_team_id")) for row in rows})


def fit_opponent_strength(
    records: Sequence[Mapping[str, Any]],
    *,
    regularization: int,
    convergence_tolerance: float = SOLVER_DEFAULT_TOLERANCE,
    max_iterations: int = SOLVER_DEFAULT_MAX_ITERATIONS,
) -> dict[str, Any]:
    """Fit venue-specific attack/defence factors by regularized fixed point."""

    rows = [dict(row) for row in records]
    if not rows:
        raise InsufficientHistoryError("opponent solver has no history")
    if regularization <= 0:
        raise ValueError("regularization must be positive")
    teams = _teams(rows)
    if len(teams) < 2:
        raise InsufficientHistoryError("opponent solver needs at least two teams")
    league_home = sum(int(row["home_goals"]) for row in rows) / len(rows)
    league_away = sum(int(row["away_goals"]) for row in rows) / len(rows)
    league_home = max(league_home, 1e-9)
    league_away = max(league_away, 1e-9)
    home_attack = {team: 1.0 for team in teams}
    away_attack = {team: 1.0 for team in teams}
    home_defence = {team: 1.0 for team in teams}
    away_defence = {team: 1.0 for team in teams}
    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        next_home_attack: dict[str, float] = {}
        next_away_attack: dict[str, float] = {}
        next_home_defence: dict[str, float] = {}
        next_away_defence: dict[str, float] = {}
        for team in teams:
            home_rows = [row for row in rows if str(row.get("home_team_id")) == team]
            away_rows = [row for row in rows if str(row.get("away_team_id")) == team]
            home_scored = sum(int(row["home_goals"]) for row in home_rows)
            away_scored = sum(int(row["away_goals"]) for row in away_rows)
            home_conceded = sum(int(row["away_goals"]) for row in home_rows)
            away_conceded = sum(int(row["home_goals"]) for row in away_rows)
            home_attack_denominator = sum(league_home * away_defence[str(row["away_team_id"])] for row in home_rows)
            away_attack_denominator = sum(league_away * home_defence[str(row["home_team_id"])] for row in away_rows)
            home_defence_denominator = sum(league_away * away_attack[str(row["away_team_id"])] for row in home_rows)
            away_defence_denominator = sum(league_home * home_attack[str(row["home_team_id"])] for row in away_rows)
            next_home_attack[team] = (home_scored + regularization) / (home_attack_denominator + regularization)
            next_away_attack[team] = (away_scored + regularization) / (away_attack_denominator + regularization)
            next_home_defence[team] = (home_conceded + regularization) / (home_defence_denominator + regularization)
            next_away_defence[team] = (away_conceded + regularization) / (away_defence_denominator + regularization)
        # Damping keeps the fixed-point path stable on sparse early windows.
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
        if difference <= convergence_tolerance:
            converged = True
            break
    all_values = [value for mapping in (home_attack, away_attack, home_defence, away_defence) for value in mapping.values()]
    if not all(isfinite(value) and value > 0 for value in all_values):
        raise ValueError("opponent solver produced a non-finite or non-positive strength")
    return {
        "league_home_goal_rate": league_home,
        "league_away_goal_rate": league_away,
        "attack_home": home_attack,
        "attack_away": away_attack,
        "defence_home": home_defence,
        "defence_away": away_defence,
        "regularization": regularization,
        "solver": "multiplicative_fixed_point",
        "converged": converged,
        "iterations": iterations,
        "max_iterations": max_iterations,
        "convergence_tolerance": convergence_tolerance,
        "history_count": len(rows),
        "teams": teams,
    }


def _assert_team_history(history: Sequence[Mapping[str, Any]], target: Mapping[str, Any], minimum_history: int) -> tuple[str, str]:
    home = str(target.get("home_team_id") or "")
    away = str(target.get("away_team_id") or "")
    if not home or not away:
        raise ValueError("target must contain both canonical team IDs")
    home_count = _team_counts(history, home)
    away_count = _team_counts(history, away)
    if home_count < minimum_history or away_count < minimum_history:
        raise InsufficientHistoryError(f"target requires {minimum_history} prior matches per team; got {home_count}/{away_count}")
    return home, away


def _prediction(
    target: Mapping[str, Any],
    *,
    model_name: str,
    model_kind: str,
    lambda_home: float,
    lambda_away: float,
    features: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    return _prediction_base(
        target,
        model_name=model_name,
        model_kind=model_kind,
        lambda_home=max(float(lambda_home), 0.0),
        lambda_away=max(float(lambda_away), 0.0),
        features=features,
        spec=spec,
    )


def build_opponent_adjusted_prediction(
    target: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    spec: OpponentSpec,
    *,
    spent_heldout_ids: Iterable[str] = (),
) -> dict[str, Any]:
    rows = [dict(row) for row in records]
    assert_no_spent_heldout(rows, spent_heldout_ids)
    history = _usable_history(target, rows)
    home, away = _assert_team_history(history, target, spec.minimum_history)
    fitted = fit_opponent_strength(
        history,
        regularization=spec.regularization,
        convergence_tolerance=spec.convergence_tolerance,
        max_iterations=spec.max_iterations,
    )
    if home not in fitted["attack_home"] or away not in fitted["attack_away"]:
        raise InsufficientHistoryError("target team is absent from fitted opponent strength roster")
    lambda_home = fitted["league_home_goal_rate"] * fitted["attack_home"][home] * fitted["defence_away"][away]
    lambda_away = fitted["league_away_goal_rate"] * fitted["attack_away"][away] * fitted["defence_home"][home]
    return _prediction(
        target,
        model_name="opponent_adjusted_team_strength",
        model_kind="opponent_strength_research",
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        features={
            "feature_source": "historical_results_only",
            "history_scope": spec.history_policy,
            "used_match_ids": [str(row["canonical_match_id"]) for row in history],
            "used_kickoffs": [str(row["kickoff_at"]) for row in history],
            "history_count": len(history),
            "league_home_goal_rate": fitted["league_home_goal_rate"],
            "league_away_goal_rate": fitted["league_away_goal_rate"],
            "regularization": spec.regularization,
            "solver": {key: fitted[key] for key in ("solver", "converged", "iterations", "max_iterations", "convergence_tolerance")},
            "attack_home": fitted["attack_home"],
            "attack_away": fitted["attack_away"],
            "defence_home": fitted["defence_home"],
            "defence_away": fitted["defence_away"],
            "target_result_excluded": True,
            "opponent_strength_used": True,
            "market_used": False,
            "xg_used": False,
            "as_of_at": str(target.get("kickoff_at")),
            "formula_version": spec.formula,
        },
        spec=spec.to_dict(),
    )


def _raw_venue_rates(rows: Sequence[Mapping[str, Any]], team: str, venue: str, prior: int, league_for: float, league_against: float) -> dict[str, Any]:
    scoped = [row for row in rows if (venue == "home" and str(row.get("home_team_id")) == team) or (venue == "away" and str(row.get("away_team_id")) == team)]
    fallback = False
    if not scoped:
        scoped = [row for row in rows if str(row.get("home_team_id")) == team or str(row.get("away_team_id")) == team]
        fallback = True
    goals_for = 0
    goals_against = 0
    for row in scoped:
        scored, conceded, _ = _team_line(row, team)
        goals_for += scored
        goals_against += conceded
    return {
        "matches": len(scoped),
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goals_for_rate": shrink_rate(goals_for, len(scoped), prior, league_for),
        "goals_against_rate": shrink_rate(goals_against, len(scoped), prior, league_against),
        "fallback_to_overall": fallback,
        "match_ids": [str(row["canonical_match_id"]) for row in scoped],
    }


def build_matched_raw_prediction(
    target: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    spec: MatchedRawSpec,
    *,
    spent_heldout_ids: Iterable[str] = (),
) -> dict[str, Any]:
    rows = [dict(row) for row in records]
    assert_no_spent_heldout(rows, spent_heldout_ids)
    history = _usable_history(target, rows)
    home, away = _assert_team_history(history, target, spec.minimum_history)
    league_home = sum(int(row["home_goals"]) for row in history) / len(history)
    league_away = sum(int(row["away_goals"]) for row in history) / len(history)
    home_rates = _raw_venue_rates(history, home, "home", spec.regularization, league_home, league_away)
    away_rates = _raw_venue_rates(history, away, "away", spec.regularization, league_away, league_home)
    home_attack = home_rates["goals_for_rate"] / max(league_home, 1e-9)
    away_defence = away_rates["goals_against_rate"] / max(league_home, 1e-9)
    away_attack = away_rates["goals_for_rate"] / max(league_away, 1e-9)
    home_defence = home_rates["goals_against_rate"] / max(league_away, 1e-9)
    return _prediction(
        target,
        model_name="matched_raw_team_strength",
        model_kind="matched_raw_reference",
        lambda_home=league_home * home_attack * away_defence,
        lambda_away=league_away * away_attack * home_defence,
        features={
            "feature_source": "historical_results_only",
            "history_scope": spec.history_policy,
            "used_match_ids": [str(row["canonical_match_id"]) for row in history],
            "used_kickoffs": [str(row["kickoff_at"]) for row in history],
            "history_count": len(history),
            "league_home_goal_rate": league_home,
            "league_away_goal_rate": league_away,
            "regularization": spec.regularization,
            "home_rates": home_rates,
            "away_rates": away_rates,
            "target_result_excluded": True,
            "opponent_strength_used": False,
            "market_used": False,
            "xg_used": False,
            "as_of_at": str(target.get("kickoff_at")),
            "formula_version": spec.formula,
        },
        spec=spec.to_dict(),
    )


def build_frozen_2c1_prediction(target: Mapping[str, Any], records: Iterable[Mapping[str, Any]], *, spent_heldout_ids: Iterable[str] = ()) -> dict[str, Any]:
    rows = [dict(row) for row in records]
    assert_no_spent_heldout(rows, spent_heldout_ids)
    frozen = spec_from_dict({
        "spec_id": FROZEN_BASIC_SPEC_ID,
        "window": "last_10",
        "window_limit": 10,
        "shrinkage": 10,
        "minimum_history": 10,
        "home_away_treatment": "venue_split_with_overall_fallback",
        "formula_version": "basic_team_strength_poisson.v1",
    })
    return build_team_strength_prediction(target, rows, frozen)


def build_rolling_folds(development_targets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted((dict(row) for row in development_targets), key=_sort_key)
    if len(rows) < 6:
        raise ValueError("rolling folds require at least six development fixtures")
    n = len(rows)
    boundaries = [(int(n * 0.4), int(n * 0.6)), (int(n * 0.6), int(n * 0.8)), (int(n * 0.8), n)]
    folds: list[dict[str, Any]] = []
    for index, (train_end, evaluation_end) in enumerate(boundaries, start=1):
        train = rows[:train_end]
        evaluation = rows[train_end:evaluation_end]
        folds.append({
            "fold_id": f"rolling-{index}",
            "train_match_ids": [str(row["canonical_match_id"]) for row in train],
            "evaluation_match_ids": [str(row["canonical_match_id"]) for row in evaluation],
            "train_count": len(train),
            "evaluation_count": len(evaluation),
            "train_max_kickoff": str(train[-1]["kickoff_at"]),
            "evaluation_min_kickoff": str(evaluation[0]["kickoff_at"]),
            "evaluation_max_kickoff": str(evaluation[-1]["kickoff_at"]),
        })
    return folds


def _evaluate_predictions(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return evaluate_predictions(rows) if rows else None


def _prediction_rows(
    targets: Sequence[Mapping[str, Any]],
    fit_records: Sequence[Mapping[str, Any]],
    opponent_spec: OpponentSpec,
    *,
    spent_heldout_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    opponent_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    frozen_rows: list[dict[str, Any]] = []
    for target in sorted(targets, key=_sort_key):
        opponent = build_opponent_adjusted_prediction(target, fit_records, opponent_spec, spent_heldout_ids=spent_heldout_ids)
        raw = build_matched_raw_prediction(target, fit_records, MatchedRawSpec(opponent_spec.regularization), spent_heldout_ids=spent_heldout_ids)
        frozen = build_frozen_2c1_prediction(target, fit_records, spent_heldout_ids=spent_heldout_ids)
        opponent_rows.append(attach_actual(opponent, target))
        raw_rows.append(attach_actual(raw, target))
        frozen_rows.append(attach_actual(frozen, target))
    return {"opponent": opponent_rows, "matched_raw": raw_rows, "frozen_2c1": frozen_rows}


def _metric_summary(rows: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {name: evaluate_predictions(values) for name, values in rows.items() if values}


def _deltas(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, float]:
    names = (
        "one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll",
        "over_2_5_log_loss", "over_2_5_brier", "btts_log_loss", "btts_brier",
        "home_goals_mae", "away_goals_mae", "expected_total_goals_mae",
    )
    return {name: float(left[name]) - float(right[name]) for name in names}


def _bootstrap(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        metric: paired_bootstrap_deltas(
            metric_loss_values(left, metric),
            metric_loss_values(right, metric),
            n_bootstrap=1000,
            seed=20260811,
        )
        for metric in CORE_METRICS
    }


def paired_comparison_bootstrap(opponent: Sequence[Mapping[str, Any]], matched_raw: Sequence[Mapping[str, Any]], frozen_2c1: Sequence[Mapping[str, Any]], *, seed: int = 20260811, n_bootstrap: int = 1000) -> dict[str, Any]:
    metrics = CORE_METRICS
    def values(rows: Sequence[Mapping[str, Any]], metric: str) -> list[float]:
        if rows and all("loss" in row and "actual" not in row for row in rows):
            return [float(row["loss"]) for row in rows]
        return metric_loss_values(rows, metric)

    def comparison(reference: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        result = {
            metric: paired_bootstrap_deltas(
                values(opponent, metric),
                values(reference, metric),
                n_bootstrap=n_bootstrap,
                seed=seed,
            )
            for metric in metrics
        }
        result["sample"] = len(opponent)
        return result
    return {"vs_matched_raw": comparison(matched_raw), "vs_frozen_2c1": comparison(frozen_2c1)}


def evaluate_validation_once(
    opponent_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    guard_path: str | Path,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate reused validation exactly once under a local guard."""

    path = Path(guard_path)
    if path.exists():
        raise RuntimeError("reused validation may be evaluated only once")
    if len(opponent_rows) != len(reference_rows) or not opponent_rows:
        raise ValueError("validation comparison requires aligned non-empty rows")
    def match_id(row: Mapping[str, Any]) -> str:
        return str(row.get("target_match_id") or row.get("canonical_match_id") or "")

    def match_id(row: Mapping[str, Any]) -> str:
        return str(row.get("target_match_id") or row.get("canonical_match_id") or "")

    opponent_match_ids = [match_id(row) for row in opponent_rows]
    reference_match_ids = [match_id(row) for row in reference_rows]
    if not all(opponent_match_ids) or opponent_match_ids != reference_match_ids:
        raise ValueError("validation rows must have aligned match IDs")
    if len(set(opponent_match_ids)) != len(opponent_match_ids):
        raise ValueError("validation rows must have unique match IDs")
    payload = {
        "validation_evaluation_count": 1,
        "sample": len(opponent_rows),
        "opponent_match_ids": opponent_match_ids,
        "reference_match_ids": reference_match_ids,
    }
    if metadata:
        payload.update(dict(metadata))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def select_opponent_spec(rolling_results: Iterable[Mapping[str, Any]], registry: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    registered = {str(row["spec_id"]): dict(row) for row in (registry or candidate_specs_manifest())}
    rows = [dict(row) for row in rolling_results]
    if not rows:
        raise ValueError("rolling evaluation produced no candidate results")
    if any(str(row.get("spec_id")) not in registered for row in rows):
        raise ValueError("rolling result contains an unregistered candidate")
    selected = min(rows, key=lambda row: (
        float(row["aggregate_metrics"]["one_x_two_log_loss"]),
        float(row["aggregate_metrics"]["one_x_two_brier"]),
        float(row["aggregate_metrics"]["goal_distribution_nll"]),
        str(row["spec_id"]),
    ))
    return {
        "selected_spec_id": str(selected["spec_id"]),
        "selection_reason": "minimum rolling development 1X2 log loss, then Brier, then goal NLL; candidates were frozen before rolling evaluation",
        "rolling_metrics": selected,
    }


def classification_from_exploratory_evidence(
    deltas: Mapping[str, float],
    bootstrap: Mapping[str, Mapping[str, Any]],
    *,
    rolling_fold_improvements: int,
    rolling_fold_count: int,
) -> str:
    if not deltas or not bootstrap or rolling_fold_count <= 0:
        return "EXPLORATORY_INCONCLUSIVE"
    if any(metric not in deltas or metric not in bootstrap or len(bootstrap[metric].get("ci_95", ())) != 2 for metric in CORE_METRICS):
        return "EXPLORATORY_INCONCLUSIVE"
    improvements = sum(float(deltas[metric]) < 0 for metric in CORE_METRICS)
    regressions = sum(float(deltas[metric]) > 0 for metric in CORE_METRICS)
    clear_improvement = any(float(bootstrap[metric]["ci_95"][1]) < 0 for metric in CORE_METRICS)
    clear_regression = any(float(bootstrap[metric]["ci_95"][0]) > 0 for metric in CORE_METRICS)
    folds_consistent = rolling_fold_improvements > rolling_fold_count / 2
    if improvements > len(CORE_METRICS) / 2 and clear_improvement and not clear_regression and folds_consistent:
        return "EXPLORATORY_PROMISING"
    if regressions > len(CORE_METRICS) / 2 and clear_regression and not clear_improvement:
        return "EXPLORATORY_NOT_PROMISING"
    return "EXPLORATORY_INCONCLUSIVE"


def phase2c2_research_boundary() -> dict[str, Any]:
    return {
        "research_only": True,
        "formal_benchmark_eligible": False,
        "production_challenger_registration": False,
        "fresh_heldout_available": False,
        "historical_validation_reused": True,
        "market_used": False,
        "xg_used": False,
        "opponent_strength_source": "historical_results_only",
    }


def experiment_id_for(*, pool_digest: str, spent_heldout_digest: str, selected_spec: Mapping[str, Any], candidate_registry_digest: str, historical_dataset_digest: str) -> str:
    payload = {
        "contract_version": PHASE2C2_CONTRACT_VERSION,
        "pool_digest": pool_digest,
        "spent_heldout_digest": spent_heldout_digest,
        "selected_spec": dict(selected_spec),
        "candidate_registry_digest": candidate_registry_digest,
        "historical_dataset_digest": historical_dataset_digest,
    }
    return f"phase2c2:{content_sha256(payload)}"


__all__ = [
    "EXPECTED_SPENT_HELDOUT_DIGEST",
    "FROZEN_BASIC_SPEC_ID",
    "MatchedRawSpec",
    "OpponentSpec",
    "PHASE2C2_CONTRACT_VERSION",
    "assert_no_spent_heldout",
    "build_frozen_2c1_prediction",
    "build_matched_raw_prediction",
    "build_opponent_adjusted_prediction",
    "build_rolling_folds",
    "candidate_specs_manifest",
    "classification_from_exploratory_evidence",
    "evaluate_validation_once",
    "experiment_id_for",
    "fit_opponent_strength",
    "load_phase2c2_research_pool",
    "paired_comparison_bootstrap",
    "phase2c2_research_boundary",
    "select_opponent_spec",
    "spent_heldout_digest",
]
