"""FE-DC-1 Sweden Allsvenskan connected-network research model.

The module intentionally uses only the Python standard library.  It is a
research/shadow implementation, separate from the production Champion.  A
model fit is made from the complete eligible league network available before
the target kickoff, rather than from a target team's recent-form aggregate.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence


COMPETITION_ID = "competition:sweden-allsvenskan"
MODEL_ID = "fe_dc_1_sweden_allsvenskan_connected_network"
CONTROL_MODEL_ID = "fe_dc_1_sweden_allsvenskan_rho0_control"

RELIABILITY_BINS: tuple[tuple[str, float, float | None], ...] = (
    ("<0.50", 0.0, 0.50),
    ("0.50-<0.55", 0.50, 0.55),
    ("0.55-<0.60", 0.55, 0.60),
    ("0.60-<0.65", 0.60, 0.65),
    (">=0.65", 0.65, None),
)


@dataclass(frozen=True)
class PreRegisteredConfig:
    """Configuration frozen before the FE-DC-1 backtest is run."""

    competition_id: str = COMPETITION_ID
    warmup_matches: int = 32
    half_life_days: float = 365.0
    max_goals: int = 12
    optimizer_max_iter: int = 500
    optimizer_tolerance: float = 1e-6
    optimizer_memory: int = 10
    parameter_bound: float = 1.5
    base_log_rate_bounds: tuple[float, float] = (-2.0, 1.0)
    home_advantage_bounds: tuple[float, float] = (-0.8, 0.8)
    rho_bounds: tuple[float, float] = (-0.10, 0.10)

    def __post_init__(self) -> None:
        if self.warmup_matches < 1:
            raise ValueError("warmup_matches must be positive")
        if self.half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        if self.max_goals < 4:
            raise ValueError("max_goals must include the four Dixon-Coles cells")
        if self.optimizer_max_iter < 1 or self.optimizer_memory < 1:
            raise ValueError("optimizer limits must be positive")
        if self.optimizer_tolerance <= 0 or self.parameter_bound <= 0:
            raise ValueError("optimizer tolerance and parameter bound must be positive")
        if self.rho_bounds[0] >= self.rho_bounds[1]:
            raise ValueError("rho bounds must be increasing")


@dataclass(frozen=True)
class HistoricalMatch:
    match_id: str
    competition_id: str
    season_id: str
    home_team_id: str
    away_team_id: str
    kickoff_at: str
    kickoff: datetime
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class FittedLeagueModel:
    model_id: str
    rho_mode: str
    teams: tuple[str, ...]
    attack: dict[str, float]
    defense: dict[str, float]
    league_log_rate: float
    home_advantage: float
    rho: float
    objective: float
    log_likelihood: float
    training_match_count: int
    reference_kickoff: str
    weighted_effective_sample_size: float
    optimizer_iterations: int
    optimizer_converged: bool
    optimizer_message: str


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("kickoff_at is required")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def coerce_match(record: HistoricalMatch | Mapping[str, Any]) -> HistoricalMatch:
    if isinstance(record, HistoricalMatch):
        return record
    required = (
        "canonical_match_id",
        "competition_id",
        "season_id",
        "home_team_id",
        "away_team_id",
        "kickoff_at",
        "home_goals",
        "away_goals",
    )
    missing = [field for field in required if record.get(field) in (None, "")]
    if missing:
        raise ValueError(f"historical match missing required fields: {', '.join(missing)}")
    home_goals = record["home_goals"]
    away_goals = record["away_goals"]
    if (
        not isinstance(home_goals, int)
        or isinstance(home_goals, bool)
        or home_goals < 0
        or not isinstance(away_goals, int)
        or isinstance(away_goals, bool)
        or away_goals < 0
    ):
        raise ValueError("goals must be non-negative integers")
    kickoff = _parse_datetime(record["kickoff_at"])
    return HistoricalMatch(
        match_id=str(record["canonical_match_id"]),
        competition_id=str(record["competition_id"]),
        season_id=str(record["season_id"]),
        home_team_id=str(record["home_team_id"]),
        away_team_id=str(record["away_team_id"]),
        kickoff_at=str(record["kickoff_at"]),
        kickoff=kickoff,
        home_goals=home_goals,
        away_goals=away_goals,
    )


def _coerce_sorted_matches(records: Iterable[HistoricalMatch | Mapping[str, Any]]) -> list[HistoricalMatch]:
    matches = [coerce_match(record) for record in records]
    matches.sort(key=lambda row: (row.kickoff, row.match_id))
    if len({row.match_id for row in matches}) != len(matches):
        raise ValueError("duplicate canonical_match_id in model input")
    return matches


def dixon_coles_tau(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
) -> float:
    """Return the standard Dixon-Coles low-score correction multiplier."""

    if home_goals == 0 and away_goals == 0:
        return 1.0 - rho * lambda_home * lambda_away
    if home_goals == 1 and away_goals == 0:
        return 1.0 + rho * lambda_away
    if home_goals == 0 and away_goals == 1:
        return 1.0 + rho * lambda_home
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _poisson_pmf(rate: float, max_goals: int) -> list[float]:
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Poisson rate must be finite and positive")
    values = [math.exp(-rate)]
    for goals in range(1, max_goals + 1):
        values.append(values[-1] * rate / goals)
    return values


def score_distribution(
    lambda_home: float,
    lambda_away: float,
    rho: float,
    *,
    max_goals: int = 12,
    normalize: bool = True,
) -> dict[str, Any]:
    """Build a complete finite score grid and its derived distributions.

    The finite grid is deliberately explicit.  ``grid_mass`` and
    ``tail_mass`` document the small omitted Poisson tail; normalization is
    applied only after the raw mass is recorded.
    """

    if max_goals < 4:
        raise ValueError("max_goals must include the low-score correction cells")
    home_pmf = _poisson_pmf(lambda_home, max_goals)
    away_pmf = _poisson_pmf(lambda_away, max_goals)
    independent_poisson_grid_mass = sum(home_pmf) * sum(away_pmf)
    raw_matrix: list[list[float]] = []
    for home_goals in range(max_goals + 1):
        row: list[float] = []
        for away_goals in range(max_goals + 1):
            tau = dixon_coles_tau(home_goals, away_goals, lambda_home, lambda_away, rho)
            if not math.isfinite(tau) or tau <= 0:
                raise ValueError("Dixon-Coles tau must be positive for every score cell")
            row.append(home_pmf[home_goals] * away_pmf[away_goals] * tau)
        raw_matrix.append(row)
    grid_mass = sum(sum(row) for row in raw_matrix)
    if not math.isfinite(grid_mass) or grid_mass <= 0:
        raise ValueError("score grid has invalid probability mass")
    normalization_factor = 1.0 / grid_mass if normalize else 1.0
    matrix = [[value * normalization_factor for value in row] for row in raw_matrix]
    score_probabilities = {
        f"{home_goals}-{away_goals}": matrix[home_goals][away_goals]
        for home_goals in range(max_goals + 1)
        for away_goals in range(max_goals + 1)
    }
    total_goals_distribution: dict[str, float] = {}
    for total_goals in range(2 * max_goals + 1):
        total_goals_distribution[str(total_goals)] = sum(
            matrix[home_goals][away_goals]
            for home_goals in range(max_goals + 1)
            for away_goals in range(max_goals + 1)
            if home_goals + away_goals == total_goals
        )
    probabilities = {
        "home": sum(
            matrix[home_goals][away_goals]
            for home_goals in range(max_goals + 1)
            for away_goals in range(max_goals + 1)
            if home_goals > away_goals
        ),
        "draw": sum(
            matrix[home_goals][away_goals]
            for home_goals in range(max_goals + 1)
            for away_goals in range(max_goals + 1)
            if home_goals == away_goals
        ),
        "away": sum(
            matrix[home_goals][away_goals]
            for home_goals in range(max_goals + 1)
            for away_goals in range(max_goals + 1)
            if home_goals < away_goals
        ),
    }
    top_scores = [
        {"score": score, "probability": probability}
        for score, probability in sorted(
            score_probabilities.items(),
            key=lambda item: (-item[1], int(item[0].split("-")[0]), int(item[0].split("-")[1])),
        )
    ]
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "rho": rho,
        "max_goals": max_goals,
        "matrix": matrix,
        "grid_mass": grid_mass,
        "independent_poisson_grid_mass": independent_poisson_grid_mass,
        "tail_mass": max(0.0, 1.0 - independent_poisson_grid_mass),
        "normalization_factor": normalization_factor,
        "probabilities": probabilities,
        "score_probabilities": score_probabilities,
        "top_scores": top_scores,
        "total_goals_distribution": total_goals_distribution,
    }


def network_diagnostics(records: Iterable[HistoricalMatch | Mapping[str, Any]]) -> dict[str, Any]:
    """Describe the connected components induced by all supplied matches."""

    matches = [coerce_match(record) for record in records]
    teams = sorted({team for row in matches for team in (row.home_team_id, row.away_team_id)})
    parent = {team: team for team in teams}

    def find(team: str) -> str:
        root = team
        while parent[root] != root:
            root = parent[root]
        while parent[team] != team:
            next_team = parent[team]
            parent[team] = root
            team = next_team
        return root

    for row in matches:
        home_root = find(row.home_team_id)
        away_root = find(row.away_team_id)
        if home_root != away_root:
            parent[home_root] = away_root
    component_sizes: defaultdict[str, int] = defaultdict(int)
    for team in teams:
        component_sizes[find(team)] += 1
    components = sorted(component_sizes.values(), reverse=True)
    return {
        "match_count": len(matches),
        "team_count": len(teams),
        "team_ids": teams,
        "component_count": len(components),
        "component_sizes": components,
        "largest_component_team_count": components[0] if components else 0,
        "connected": bool(teams) and len(components) == 1,
    }


def _time_weight(match: HistoricalMatch, reference_kickoff: datetime, config: PreRegisteredConfig) -> float:
    age_days = (reference_kickoff - match.kickoff).total_seconds() / 86400.0
    if age_days < 0:
        raise ValueError("training match is not strictly before reference kickoff")
    return 0.5 ** (age_days / config.half_life_days)


def _initial_parameters(
    matches: Sequence[HistoricalMatch],
    team_count: int,
    *,
    rho_mode: str,
) -> list[float]:
    home_mean = sum(row.home_goals for row in matches) / max(1, len(matches))
    away_mean = sum(row.away_goals for row in matches) / max(1, len(matches))
    average_rate = max(0.20, (home_mean + away_mean) / 2.0)
    base = math.log(average_rate)
    hfa = math.log((home_mean + 0.10) / (away_mean + 0.10))
    hfa = max(-0.30, min(0.30, hfa))
    free_count = max(0, team_count - 1)
    values = [0.0] * (free_count * 2) + [base, hfa]
    if rho_mode == "fit":
        values.append(-0.05)
    return values


def _unpack_parameters(parameters: Sequence[float], team_count: int, rho_mode: str) -> tuple[list[float], list[float], float, float, float]:
    free_count = team_count - 1
    attacks = list(parameters[:free_count])
    attacks.append(-sum(attacks))
    defense_start = free_count
    defenses = list(parameters[defense_start : defense_start + free_count])
    defenses.append(-sum(defenses))
    base_index = free_count * 2
    base = parameters[base_index]
    hfa = parameters[base_index + 1]
    rho = parameters[base_index + 2] if rho_mode == "fit" else 0.0
    return attacks, defenses, base, hfa, rho


def _negative_log_likelihood_and_gradient(
    parameters: Sequence[float],
    matches: Sequence[HistoricalMatch],
    teams: Sequence[str],
    weights: Sequence[float],
    *,
    rho_mode: str,
) -> tuple[float, list[float]]:
    team_index = {team: index for index, team in enumerate(teams)}
    attacks, defenses, base, hfa, rho = _unpack_parameters(parameters, len(teams), rho_mode)
    full_attack_gradient = [0.0] * len(teams)
    full_defense_gradient = [0.0] * len(teams)
    gradient_base = 0.0
    gradient_hfa = 0.0
    gradient_rho = 0.0
    log_likelihood = 0.0

    for row, weight in zip(matches, weights):
        home_index = team_index[row.home_team_id]
        away_index = team_index[row.away_team_id]
        eta_home = base + hfa + attacks[home_index] + defenses[away_index]
        eta_away = base + attacks[away_index] + defenses[home_index]
        if eta_home < -20.0 or eta_home > 20.0 or eta_away < -20.0 or eta_away > 20.0:
            return 1e100, [0.0] * len(parameters)
        lambda_home = math.exp(eta_home)
        lambda_away = math.exp(eta_away)
        tau = dixon_coles_tau(row.home_goals, row.away_goals, lambda_home, lambda_away, rho)
        if not math.isfinite(tau) or tau <= 1e-12:
            return 1e100, [0.0] * len(parameters)
        log_likelihood += weight * (
            math.log(tau)
            + row.home_goals * math.log(lambda_home)
            - lambda_home
            - math.lgamma(row.home_goals + 1)
            + row.away_goals * math.log(lambda_away)
            - lambda_away
            - math.lgamma(row.away_goals + 1)
        )

        tau_home_derivative = 0.0
        tau_away_derivative = 0.0
        if row.home_goals == 0 and row.away_goals == 0:
            tau_home_derivative = -rho * lambda_home / tau * lambda_away
            tau_away_derivative = -rho * lambda_away / tau * lambda_home
        elif row.home_goals == 1 and row.away_goals == 0:
            tau_away_derivative = rho * lambda_away / tau
        elif row.home_goals == 0 and row.away_goals == 1:
            tau_home_derivative = rho * lambda_home / tau
        elif row.home_goals == 1 and row.away_goals == 1:
            pass
        derivative_home_rate = row.home_goals - lambda_home + tau_home_derivative
        derivative_away_rate = row.away_goals - lambda_away + tau_away_derivative
        full_attack_gradient[home_index] += weight * derivative_home_rate
        full_attack_gradient[away_index] += weight * derivative_away_rate
        full_defense_gradient[away_index] += weight * derivative_home_rate
        full_defense_gradient[home_index] += weight * derivative_away_rate
        gradient_base += weight * (derivative_home_rate + derivative_away_rate)
        gradient_hfa += weight * derivative_home_rate
        if rho_mode == "fit":
            if row.home_goals == 0 and row.away_goals == 0:
                gradient_rho += weight * (-lambda_home * lambda_away / tau)
            elif row.home_goals == 1 and row.away_goals == 0:
                gradient_rho += weight * (lambda_away / tau)
            elif row.home_goals == 0 and row.away_goals == 1:
                gradient_rho += weight * (lambda_home / tau)
            elif row.home_goals == 1 and row.away_goals == 1:
                gradient_rho += weight * (-1.0 / tau)

    free_count = len(teams) - 1
    negative_gradient = [
        -(full_attack_gradient[index] - full_attack_gradient[-1]) for index in range(free_count)
    ]
    negative_gradient.extend(
        -(full_defense_gradient[index] - full_defense_gradient[-1]) for index in range(free_count)
    )
    negative_gradient.extend([-gradient_base, -gradient_hfa])
    if rho_mode == "fit":
        negative_gradient.append(-gradient_rho)
    return -log_likelihood, negative_gradient


def _negative_log_likelihood_gradient_hessian(
    parameters: Sequence[float],
    matches: Sequence[HistoricalMatch],
    teams: Sequence[str],
    weights: Sequence[float],
    *,
    rho_mode: str,
) -> tuple[float, list[float], list[list[float]]]:
    """Return the objective, gradient, and observed Hessian.

    The local Hessian is analytic for the Poisson terms and the four
    Dixon-Coles cells.  The sparse feature vectors below map the two linear
    log-rate predictors into the sum-to-zero parameterization, including the
    eliminated final attack and defense parameters.
    """

    value, gradient = _negative_log_likelihood_and_gradient(
        parameters,
        matches,
        teams,
        weights,
        rho_mode=rho_mode,
    )
    parameter_count = len(parameters)
    hessian = [[0.0] * parameter_count for _ in range(parameter_count)]
    attacks, defenses, base, hfa, rho = _unpack_parameters(parameters, len(teams), rho_mode)
    team_index = {team: index for index, team in enumerate(teams)}
    free_count = len(teams) - 1
    base_index = free_count * 2

    def team_feature(start: int, team_index_value: int) -> dict[int, float]:
        if team_index_value < free_count:
            return {start + team_index_value: 1.0}
        return {start + index: -1.0 for index in range(free_count)}

    def merge_features(*features: Mapping[int, float]) -> dict[int, float]:
        merged: dict[int, float] = defaultdict(float)
        for feature in features:
            for index, coefficient in feature.items():
                merged[index] += coefficient
        return {index: coefficient for index, coefficient in merged.items() if coefficient}

    for row, weight in zip(matches, weights):
        home_index = team_index[row.home_team_id]
        away_index = team_index[row.away_team_id]
        eta_home = base + hfa + attacks[home_index] + defenses[away_index]
        eta_away = base + attacks[away_index] + defenses[home_index]
        if eta_home < -20.0 or eta_home > 20.0 or eta_away < -20.0 or eta_away > 20.0:
            return value, gradient, hessian
        lambda_home = math.exp(eta_home)
        lambda_away = math.exp(eta_away)
        tau = dixon_coles_tau(row.home_goals, row.away_goals, lambda_home, lambda_away, rho)
        if not math.isfinite(tau) or tau <= 1e-12:
            return value, gradient, hessian

        tau_home = 0.0
        tau_away = 0.0
        tau_rho = 0.0
        tau_home_home = 0.0
        tau_away_away = 0.0
        tau_home_away = 0.0
        tau_home_rho = 0.0
        tau_away_rho = 0.0
        if row.home_goals == 0 and row.away_goals == 0:
            tau_home = tau_away = -rho * lambda_home * lambda_away
            tau_rho = -lambda_home * lambda_away
            tau_home_home = tau_away_away = tau_home_away = tau_home
            tau_home_rho = tau_away_rho = -lambda_home * lambda_away
        elif row.home_goals == 1 and row.away_goals == 0:
            tau_away = rho * lambda_away
            tau_rho = lambda_away
            tau_away_away = rho * lambda_away
            tau_away_rho = lambda_away
        elif row.home_goals == 0 and row.away_goals == 1:
            tau_home = rho * lambda_home
            tau_rho = lambda_home
            tau_home_home = rho * lambda_home
            tau_home_rho = lambda_home
        elif row.home_goals == 1 and row.away_goals == 1:
            tau_rho = -1.0

        inverse_tau = 1.0 / tau
        log_tau_hessian = (
            (
                tau_home_home * inverse_tau - tau_home * tau_home * inverse_tau * inverse_tau,
                tau_home_away * inverse_tau - tau_home * tau_away * inverse_tau * inverse_tau,
                tau_home_rho * inverse_tau - tau_home * tau_rho * inverse_tau * inverse_tau,
            ),
            (
                tau_home_away * inverse_tau - tau_away * tau_home * inverse_tau * inverse_tau,
                tau_away_away * inverse_tau - tau_away * tau_away * inverse_tau * inverse_tau,
                tau_away_rho * inverse_tau - tau_away * tau_rho * inverse_tau * inverse_tau,
            ),
            (
                tau_home_rho * inverse_tau - tau_rho * tau_home * inverse_tau * inverse_tau,
                tau_away_rho * inverse_tau - tau_rho * tau_away * inverse_tau * inverse_tau,
                -tau_rho * tau_rho * inverse_tau * inverse_tau,
            ),
        )
        local_hessian = (
            (
                lambda_home - log_tau_hessian[0][0],
                -log_tau_hessian[0][1],
                -log_tau_hessian[0][2],
            ),
            (
                -log_tau_hessian[1][0],
                lambda_away - log_tau_hessian[1][1],
                -log_tau_hessian[1][2],
            ),
            (
                -log_tau_hessian[2][0],
                -log_tau_hessian[2][1],
                -log_tau_hessian[2][2],
            ),
        )

        home_features = merge_features(
            team_feature(0, home_index),
            team_feature(free_count, away_index),
            {base_index: 1.0, base_index + 1: 1.0},
        )
        away_features = merge_features(
            team_feature(0, away_index),
            team_feature(free_count, home_index),
            {base_index: 1.0},
        )
        rho_features = {parameter_count - 1: 1.0} if rho_mode == "fit" else {}
        features = (home_features, away_features, rho_features)
        for local_row, feature_row in zip(local_hessian, features):
            for local_column, feature_column in zip(local_row, features):
                if not local_column:
                    continue
                scale = weight * local_column
                for row_index, row_coefficient in feature_row.items():
                    for column_index, column_coefficient in feature_column.items():
                        hessian[row_index][column_index] += scale * row_coefficient * column_coefficient
    return value, gradient, hessian


def _project(parameters: Sequence[float], bounds: Sequence[tuple[float, float]]) -> list[float]:
    return [max(lower, min(upper, value)) for value, (lower, upper) in zip(parameters, bounds)]


@dataclass(frozen=True)
class _OptimizerResult:
    parameters: list[float]
    objective: float
    gradient: list[float]
    iterations: int
    converged: bool
    message: str


def _solve_linear_system(matrix: Sequence[Sequence[float]], right_hand_side: Sequence[float]) -> list[float] | None:
    """Solve a small dense linear system with partial pivoting."""

    size = len(right_hand_side)
    if not size:
        return []
    augmented = [list(row) + [right_hand_side[index]] for index, row in enumerate(matrix)]
    for pivot_index in range(size):
        pivot_row = max(
            range(pivot_index, size),
            key=lambda index: abs(augmented[index][pivot_index]),
        )
        if abs(augmented[pivot_row][pivot_index]) <= 1e-12:
            return None
        augmented[pivot_index], augmented[pivot_row] = augmented[pivot_row], augmented[pivot_index]
        pivot = augmented[pivot_index][pivot_index]
        for column in range(pivot_index, size + 1):
            augmented[pivot_index][column] /= pivot
        for row in range(size):
            if row == pivot_index:
                continue
            factor = augmented[row][pivot_index]
            if not factor:
                continue
            for column in range(pivot_index, size + 1):
                augmented[row][column] -= factor * augmented[pivot_index][column]
    return [augmented[row][-1] for row in range(size)]


def _projected_newton_minimize(
    objective,
    hessian_objective,
    initial: Sequence[float],
    bounds: Sequence[tuple[float, float]],
    *,
    max_iter: int,
    tolerance: float,
    memory: int,
) -> _OptimizerResult:
    """Minimize a bounded objective with deterministic projected Newton steps.

    ``memory`` is retained in the public configuration for reproducibility and
    compatibility with the preregistration.  The bounded Newton implementation
    uses no external numerical dependency; it resets the active-set curvature
    whenever a step reaches a parameter bound.
    """

    del memory

    def projected_gradient_norm(values: Sequence[float], current_gradient: Sequence[float]) -> float:
        projected = _project(
            [value - gradient_value for value, gradient_value in zip(values, current_gradient)],
            bounds,
        )
        return max(
            (abs(value - projected_value) for value, projected_value in zip(values, projected)),
            default=0.0,
        )

    def line_search(
        values: Sequence[float],
        current_value: float,
        current_gradient: Sequence[float],
        direction: Sequence[float],
    ) -> tuple[list[float], float, list[float]] | None:
        step_size = 1.0
        while step_size >= 1e-12:
            trial = _project(
                [current + step_size * delta for current, delta in zip(values, direction)],
                bounds,
            )
            displacement = [new - old for new, old in zip(trial, values)]
            if max((abs(item) for item in displacement), default=0.0) <= 1e-14:
                step_size *= 0.5
                continue
            trial_value, trial_gradient = objective(trial)
            armijo_rhs = current_value + 1e-4 * sum(
                gradient_value * displacement_value
                for gradient_value, displacement_value in zip(current_gradient, displacement)
            )
            if math.isfinite(trial_value) and trial_value <= armijo_rhs:
                return trial, trial_value, trial_gradient
            step_size *= 0.5
        return None

    parameters = _project(initial, bounds)
    value, gradient = objective(parameters)
    if not math.isfinite(value):
        raise ValueError("optimizer initial objective is not finite")
    for iteration in range(1, max_iter + 1):
        if projected_gradient_norm(parameters, gradient) <= tolerance:
            return _OptimizerResult(parameters, value, gradient, iteration - 1, True, "projected_gradient_tolerance")
        _, _, hessian = hessian_objective(parameters)
        active_indices: set[int] = set()
        for index, (parameter, parameter_gradient, (lower, upper)) in enumerate(
            zip(parameters, gradient, bounds)
        ):
            if parameter <= lower + 1e-8 and parameter_gradient > 0.0:
                active_indices.add(index)
            elif parameter >= upper - 1e-8 and parameter_gradient < 0.0:
                active_indices.add(index)
        free_indices = [index for index in range(len(parameters)) if index not in active_indices]
        direction = [0.0] * len(parameters)
        candidate_result: tuple[list[float], float, list[float]] | None = None

        # Damping is a numerical safeguard for sparse early chronological
        # windows where the observed Hessian can be indefinite or singular.
        for damping in (0.0, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0, 1000.0):
            reduced_hessian = [
                [
                    hessian[row][column] + (damping if row == column else 0.0)
                    for column in free_indices
                ]
                for row in free_indices
            ]
            reduced_direction = _solve_linear_system(
                reduced_hessian,
                [-gradient[index] for index in free_indices],
            )
            if reduced_direction is None:
                continue
            for index, direction_value in zip(free_indices, reduced_direction):
                direction[index] = direction_value
            if sum(parameter_gradient * step for parameter_gradient, step in zip(gradient, direction)) >= 0.0:
                continue
            candidate_result = line_search(parameters, value, gradient, direction)
            if candidate_result is not None:
                break

        if candidate_result is None:
            # Steepest descent is a deterministic fallback for a badly
            # conditioned active set.  It also avoids declaring failure when
            # the remaining numerical gap is below the optimizer tolerance.
            candidate_result = line_search(parameters, value, gradient, [-item for item in gradient])
        if candidate_result is None:
            if projected_gradient_norm(parameters, gradient) <= tolerance * 2.0:
                return _OptimizerResult(parameters, value, gradient, iteration - 1, True, "projected_gradient_numerical_tolerance")
            return _OptimizerResult(
                parameters,
                value,
                gradient,
                iteration - 1,
                False,
                f"line_search_failed: projected_gradient={projected_gradient_norm(parameters, gradient):.6g}",
            )
        parameters, value, gradient = candidate_result
    return _OptimizerResult(parameters, value, gradient, max_iter, False, "max_iterations")


def fit_league_model(
    records: Sequence[HistoricalMatch | Mapping[str, Any]],
    *,
    config: PreRegisteredConfig = PreRegisteredConfig(),
    reference_kickoff: datetime | str | None = None,
    rho_mode: str = "fit",
) -> FittedLeagueModel:
    """Fit a connected-network Maher/Dixon-Coles model on prior matches."""

    if rho_mode not in {"fit", "zero"}:
        raise ValueError("rho_mode must be fit or zero")
    matches = _coerce_sorted_matches(records)
    if not matches:
        raise ValueError("at least one training match is required")
    if any(row.competition_id != config.competition_id for row in matches):
        raise ValueError("FE-DC-1 training input contains another competition")
    if reference_kickoff is None:
        reference = max(row.kickoff for row in matches) + timedelta(microseconds=1)
    else:
        reference = _parse_datetime(reference_kickoff)
    if any(row.kickoff >= reference for row in matches):
        raise ValueError("all training matches must be strictly before reference kickoff")
    teams = tuple(sorted({team for row in matches for team in (row.home_team_id, row.away_team_id)}))
    if len(teams) < 2:
        raise ValueError("at least two teams are required")
    weights = [_time_weight(row, reference, config) for row in matches]
    free_count = len(teams) - 1
    bounds: list[tuple[float, float]] = [(-config.parameter_bound, config.parameter_bound)] * (free_count * 2)
    bounds.extend([config.base_log_rate_bounds, config.home_advantage_bounds])
    if rho_mode == "fit":
        bounds.append(config.rho_bounds)
    initial = _initial_parameters(matches, len(teams), rho_mode=rho_mode)
    objective = lambda values: _negative_log_likelihood_and_gradient(
        values,
        matches,
        teams,
        weights,
        rho_mode=rho_mode,
    )
    hessian_objective = lambda values: _negative_log_likelihood_gradient_hessian(
        values,
        matches,
        teams,
        weights,
        rho_mode=rho_mode,
    )
    result = _projected_newton_minimize(
        objective,
        hessian_objective,
        initial,
        bounds,
        max_iter=config.optimizer_max_iter,
        tolerance=config.optimizer_tolerance,
        memory=config.optimizer_memory,
    )
    if not result.converged:
        raise ValueError(f"FE-DC-1 optimizer did not converge: {result.message}")
    attacks, defenses, base, hfa, rho = _unpack_parameters(result.parameters, len(teams), rho_mode)
    return FittedLeagueModel(
        model_id=MODEL_ID if rho_mode == "fit" else CONTROL_MODEL_ID,
        rho_mode=rho_mode,
        teams=teams,
        attack={team: attacks[index] for index, team in enumerate(teams)},
        defense={team: defenses[index] for index, team in enumerate(teams)},
        league_log_rate=base,
        home_advantage=hfa,
        rho=0.0 if rho_mode == "zero" else rho,
        objective=result.objective,
        log_likelihood=-result.objective,
        training_match_count=len(matches),
        reference_kickoff=_iso_datetime(reference),
        weighted_effective_sample_size=(sum(weights) ** 2 / sum(weight * weight for weight in weights)),
        optimizer_iterations=result.iterations,
        optimizer_converged=result.converged,
        optimizer_message=result.message,
    )


def predict_score_distribution(
    model: FittedLeagueModel,
    home_team_id: str,
    away_team_id: str,
    *,
    max_goals: int = 12,
) -> dict[str, Any]:
    if home_team_id not in model.attack or away_team_id not in model.attack:
        raise ValueError("both target teams must exist in the fitted league network")
    lambda_home = math.exp(
        model.league_log_rate
        + model.home_advantage
        + model.attack[home_team_id]
        + model.defense[away_team_id]
    )
    lambda_away = math.exp(
        model.league_log_rate
        + model.attack[away_team_id]
        + model.defense[home_team_id]
    )
    distribution = score_distribution(
        lambda_home,
        lambda_away,
        model.rho,
        max_goals=max_goals,
        normalize=True,
    )
    distribution["model_id"] = model.model_id
    distribution["rho_mode"] = model.rho_mode
    return distribution


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _quantile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean": _mean(values),
        "min": min(values) if values else None,
        "p05": _quantile(values, 0.05),
        "p25": _quantile(values, 0.25),
        "median": _quantile(values, 0.50),
        "p75": _quantile(values, 0.75),
        "p95": _quantile(values, 0.95),
        "max": max(values) if values else None,
    }


def _calibration_bins(probabilities: Sequence[float], outcomes: Sequence[bool]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for label, lower, upper in RELIABILITY_BINS:
        selected = [index for index, probability in enumerate(probabilities) if probability >= lower and (upper is None or probability < upper)]
        selected_outcomes = [outcomes[index] for index in selected]
        result.append(
            {
                "bin": label,
                "n": len(selected),
                "mean_probability": _mean([probabilities[index] for index in selected]),
                "empirical_rate": _mean([1.0 if value else 0.0 for value in selected_outcomes]),
                "calibration_gap": (
                    _mean([1.0 if value else 0.0 for value in selected_outcomes])
                    - _mean([probabilities[index] for index in selected])
                    if selected
                    else None
                ),
            }
        )
    return result


def _class_calibration(predictions: Sequence[Mapping[str, Any]], model_key: str) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for outcome_name in ("home", "draw", "away"):
        probabilities = [float(row["models"][model_key]["probabilities"][outcome_name]) for row in predictions]
        outcomes = [
            (
                row["actual_home_goals"] > row["actual_away_goals"]
                if outcome_name == "home"
                else row["actual_home_goals"] == row["actual_away_goals"]
                if outcome_name == "draw"
                else row["actual_home_goals"] < row["actual_away_goals"]
            )
            for row in predictions
        ]
        output[outcome_name] = _calibration_bins(probabilities, outcomes)
    return output


def _metric_delta(primary: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, float | None]:
    fields = (
        "brier_1x2",
        "logloss_1x2",
        "goal_mae",
        "total_goal_mae",
        "score_nll",
        "exact_top1",
        "exact_top3",
        "exact_top5",
        "one_one_top1_share",
    )
    return {
        field: (
            float(primary[field]) - float(control[field])
            if primary.get(field) is not None and control.get(field) is not None
            else None
        )
        for field in fields
    }


def evaluate_predictions(predictions: Sequence[Mapping[str, Any]], model_key: str) -> dict[str, Any]:
    """Evaluate one model's full score distribution and diagnostics."""

    sample_size = len(predictions)
    if not sample_size:
        return {"sample_size": 0}
    brier_values: list[float] = []
    logloss_values: list[float] = []
    goal_mae_values: list[float] = []
    total_goal_mae_values: list[float] = []
    score_nll_values: list[float] = []
    exact_hits = {1: 0, 3: 0, 5: 0}
    top1_scores: list[str] = []
    max_probabilities: list[float] = []
    observed_outcome_probabilities: list[float] = []
    total_distribution_accumulator: defaultdict[str, float] = defaultdict(float)
    actual_total_goals: list[int] = []
    actual_one_one = 0
    rho_values: list[float] = []
    grid_tail_values: list[float] = []
    history_counts: list[float] = []
    home_history_counts: list[float] = []
    away_history_counts: list[float] = []

    for row in predictions:
        payload = row["models"][model_key]
        actual_home = int(row["actual_home_goals"])
        actual_away = int(row["actual_away_goals"])
        actual_score = f"{actual_home}-{actual_away}"
        if actual_home > actual_away:
            outcome_name = "home"
            observed_index = 0
        elif actual_home == actual_away:
            outcome_name = "draw"
            observed_index = 1
        else:
            outcome_name = "away"
            observed_index = 2
        probabilities = [payload["probabilities"][name] for name in ("home", "draw", "away")]
        one_hot = [1.0 if index == observed_index else 0.0 for index in range(3)]
        brier_values.append(sum((probability - target) ** 2 for probability, target in zip(probabilities, one_hot)))
        observed_probability = float(payload["probabilities"][outcome_name])
        observed_outcome_probabilities.append(observed_probability)
        if observed_probability > 0:
            logloss_values.append(-math.log(observed_probability))
        goal_mae_values.append(
            (abs(float(payload["lambda_home"]) - actual_home) + abs(float(payload["lambda_away"]) - actual_away)) / 2.0
        )
        total_goal_mae_values.append(abs(float(payload["lambda_home"]) + float(payload["lambda_away"]) - actual_home - actual_away))
        actual_total_goals.append(actual_home + actual_away)
        if actual_home == 1 and actual_away == 1:
            actual_one_one += 1
        score_probability = payload["score_probabilities"].get(actual_score)
        if score_probability is not None and float(score_probability) > 0:
            score_nll_values.append(-math.log(float(score_probability)))
        ranked_scores = [item["score"] for item in payload["top_scores"]]
        top1_scores.append(ranked_scores[0])
        for top_k in exact_hits:
            if actual_score in ranked_scores[:top_k]:
                exact_hits[top_k] += 1
        max_probabilities.append(max(probabilities))
        rho_values.append(float(payload["rho"]))
        grid_tail_values.append(float(payload["tail_mass"]))
        history_counts.append(float(row["history_match_count"]))
        home_history_counts.append(float(row["home_history_match_count"]))
        away_history_counts.append(float(row["away_history_match_count"]))
        for total_goals, probability in payload["total_goals_distribution"].items():
            total_distribution_accumulator[total_goals] += float(probability)

    mean_total_distribution = {
        total: probability / sample_size
        for total, probability in sorted(total_distribution_accumulator.items(), key=lambda item: int(item[0]))
    }
    predicted_ge_5 = sum(probability for total, probability in mean_total_distribution.items() if int(total) >= 5)
    actual_ge_5 = sum(total >= 5 for total in actual_total_goals) / sample_size
    top1_share = sum(score == "1-1" for score in top1_scores) / sample_size
    strong_favourite: dict[str, Any] = {}
    correct_top1 = [
        (
            (
                row["actual_home_goals"] > row["actual_away_goals"]
                and row["models"][model_key]["probabilities"]["home"] == max(row["models"][model_key]["probabilities"].values())
            )
            or (
                row["actual_home_goals"] == row["actual_away_goals"]
                and row["models"][model_key]["probabilities"]["draw"] == max(row["models"][model_key]["probabilities"].values())
            )
            or (
                row["actual_home_goals"] < row["actual_away_goals"]
                and row["models"][model_key]["probabilities"]["away"] == max(row["models"][model_key]["probabilities"].values())
            )
        )
        for row in predictions
    ]
    for threshold in (0.55, 0.60, 0.65):
        selected = [index for index, probability in enumerate(max_probabilities) if probability >= threshold]
        strong_favourite[f"p_ge_{threshold:.2f}"] = {
            "n": len(selected),
            "mean_probability": _mean([max_probabilities[index] for index in selected]),
            "top1_outcome_hit_rate": _mean([1.0 if correct_top1[index] else 0.0 for index in selected]),
        }
    low_observed = [probability for probability in observed_outcome_probabilities if probability < 0.05]
    return {
        "sample_size": sample_size,
        "brier_1x2": _mean(brier_values),
        "brier_convention": "multiclass sum of squared probability errors; lower is better",
        "logloss_1x2": _mean(logloss_values),
        "goal_mae": _mean(goal_mae_values),
        "goal_mae_convention": "mean of home/away absolute goal-rate errors",
        "total_goal_mae": _mean(total_goal_mae_values),
        "exact_top1": exact_hits[1] / sample_size,
        "exact_top3": exact_hits[3] / sample_size,
        "exact_top5": exact_hits[5] / sample_size,
        "score_nll": _mean(score_nll_values),
        "score_nll_sample_size": len(score_nll_values),
        "one_one_top1_share": top1_share,
        "actual_one_one_share": actual_one_one / sample_size,
        "lambda_distribution": {
            "home": _distribution_summary([float(row["models"][model_key]["lambda_home"]) for row in predictions]),
            "away": _distribution_summary([float(row["models"][model_key]["lambda_away"]) for row in predictions]),
            "total": _distribution_summary(
                [float(row["models"][model_key]["lambda_home"]) + float(row["models"][model_key]["lambda_away"]) for row in predictions]
            ),
        },
        "rho_distribution": _distribution_summary(rho_values),
        "score_grid_tail_mass": _distribution_summary(grid_tail_values),
        "total_goals_distribution": {
            "mean_predicted_probability": mean_total_distribution,
            "predicted_ge_5_probability": predicted_ge_5,
            "actual_frequency_ge_5": actual_ge_5,
            "actual_total_goal_distribution": {
                str(total): actual_total_goals.count(total) / sample_size
                for total in sorted(set(actual_total_goals))
            },
        },
        "history_visible_per_prediction": {
            "all_league_match_count": _distribution_summary(history_counts),
            "home_team_match_count": _distribution_summary(home_history_counts),
            "away_team_match_count": _distribution_summary(away_history_counts),
        },
        "calibration": {
            "max_1x2_probability": _calibration_bins(max_probabilities, correct_top1),
            "classwise": _class_calibration(predictions, model_key),
        },
        "extreme_probability_diagnostics": {
            "max_1x2_probability": _distribution_summary(max_probabilities),
            "observed_outcome_probability": _distribution_summary(observed_outcome_probabilities),
            "observed_outcome_probability_below_0.05": {
                "n": len(low_observed),
                "share": len(low_observed) / sample_size,
            },
            "strong_favourite": strong_favourite,
        },
    }


def run_chronological_backtest(
    records: Sequence[HistoricalMatch | Mapping[str, Any]],
    *,
    config: PreRegisteredConfig = PreRegisteredConfig(),
) -> dict[str, Any]:
    """Run expanding-window held-out evaluation for the entire league graph."""

    matches = _coerce_sorted_matches(records)
    if not matches:
        raise ValueError("at least one match is required")
    if any(row.competition_id != config.competition_id for row in matches):
        raise ValueError("FE-DC-1 backtest input contains another competition")
    expected_teams = sorted({team for row in matches for team in (row.home_team_id, row.away_team_id)})
    predictions: list[dict[str, Any]] = []
    skipped: defaultdict[str, int] = defaultdict(int)
    for target in matches:
        training = [row for row in matches if row.kickoff < target.kickoff]
        if len(training) < config.warmup_matches:
            skipped["warmup"] += 1
            continue
        network = network_diagnostics(training)
        if network["team_ids"] != expected_teams:
            skipped["not_all_teams_seen"] += 1
            continue
        if network["component_count"] != 1:
            skipped["network_not_connected"] += 1
            continue
        if target.home_team_id not in network["team_ids"] or target.away_team_id not in network["team_ids"]:
            skipped["target_team_missing"] += 1
            continue
        primary_model = fit_league_model(
            training,
            config=config,
            reference_kickoff=target.kickoff,
            rho_mode="fit",
        )
        control_model = fit_league_model(
            training,
            config=config,
            reference_kickoff=target.kickoff,
            rho_mode="zero",
        )
        primary_distribution = predict_score_distribution(
            primary_model,
            target.home_team_id,
            target.away_team_id,
            max_goals=config.max_goals,
        )
        control_distribution = predict_score_distribution(
            control_model,
            target.home_team_id,
            target.away_team_id,
            max_goals=config.max_goals,
        )
        home_history_count = sum(target.home_team_id in (row.home_team_id, row.away_team_id) for row in training)
        away_history_count = sum(target.away_team_id in (row.home_team_id, row.away_team_id) for row in training)
        predictions.append(
            {
                "match_id": target.match_id,
                "competition_id": target.competition_id,
                "season_id": target.season_id,
                "kickoff_at": target.kickoff_at,
                "home_team_id": target.home_team_id,
                "away_team_id": target.away_team_id,
                "actual_home_goals": target.home_goals,
                "actual_away_goals": target.away_goals,
                "history_match_count": len(training),
                "home_history_match_count": home_history_count,
                "away_history_match_count": away_history_count,
                "network_team_count": network["team_count"],
                "network_component_count": network["component_count"],
                "training_max_kickoff": max(row.kickoff_at for row in training),
                "used_history_match_ids": [row.match_id for row in training],
                "used_history_kickoffs": [row.kickoff_at for row in training],
                "models": {
                    "dixon_coles": {
                        **primary_distribution,
                        "fit_diagnostics": {
                            "objective": primary_model.objective,
                            "log_likelihood": primary_model.log_likelihood,
                            "training_match_count": primary_model.training_match_count,
                            "reference_kickoff": primary_model.reference_kickoff,
                            "weighted_effective_sample_size": primary_model.weighted_effective_sample_size,
                            "optimizer_iterations": primary_model.optimizer_iterations,
                            "optimizer_converged": primary_model.optimizer_converged,
                            "optimizer_message": primary_model.optimizer_message,
                            "attack": primary_model.attack,
                            "defense": primary_model.defense,
                            "league_log_rate": primary_model.league_log_rate,
                            "home_advantage": primary_model.home_advantage,
                        },
                    },
                    "rho0_control": {
                        **control_distribution,
                        "fit_diagnostics": {
                            "objective": control_model.objective,
                            "log_likelihood": control_model.log_likelihood,
                            "training_match_count": control_model.training_match_count,
                            "reference_kickoff": control_model.reference_kickoff,
                            "weighted_effective_sample_size": control_model.weighted_effective_sample_size,
                            "optimizer_iterations": control_model.optimizer_iterations,
                            "optimizer_converged": control_model.optimizer_converged,
                            "optimizer_message": control_model.optimizer_message,
                            "attack": control_model.attack,
                            "defense": control_model.defense,
                            "league_log_rate": control_model.league_log_rate,
                            "home_advantage": control_model.home_advantage,
                        },
                    },
                },
            }
        )
    primary_metrics = evaluate_predictions(predictions, "dixon_coles")
    control_metrics = evaluate_predictions(predictions, "rho0_control")
    return {
        "model_id": MODEL_ID,
        "control_model_id": CONTROL_MODEL_ID,
        "status": "READY_FOR_ACCEPTANCE",
        "research_scope": "research_shadow_only",
        "config": {
            "competition_id": config.competition_id,
            "warmup_matches": config.warmup_matches,
            "half_life_days": config.half_life_days,
            "max_goals": config.max_goals,
            "optimizer_max_iter": config.optimizer_max_iter,
            "optimizer_tolerance": config.optimizer_tolerance,
            "optimizer_memory": config.optimizer_memory,
            "parameter_bound": config.parameter_bound,
            "base_log_rate_bounds": list(config.base_log_rate_bounds),
            "home_advantage_bounds": list(config.home_advantage_bounds),
            "rho_bounds": list(config.rho_bounds),
            "rho_policy": "fit primary; fixed zero internal control",
            "time_weight_policy": "fixed exponential half-life; no sweep",
            "network_policy": "all eligible Sweden Allsvenskan matches strictly before target kickoff",
        },
        "data_scope": {
            "input_match_count": len(matches),
            "input_team_count": len(expected_teams),
            "input_team_ids": expected_teams,
            "input_kickoff_min": min(row.kickoff_at for row in matches),
            "input_kickoff_max": max(row.kickoff_at for row in matches),
            "heldout_prediction_count": len(predictions),
            "skipped_target_counts": dict(sorted(skipped.items())),
            "same_target_set_for_primary_and_control": True,
        },
        "metrics": {
            "dixon_coles": primary_metrics,
            "rho0_control": control_metrics,
            "dixon_coles_minus_rho0_control": _metric_delta(primary_metrics, control_metrics),
        },
        "predictions": predictions,
    }
