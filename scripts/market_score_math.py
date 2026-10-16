"""Pure GF106-original Poisson market math for research-only use.

These helpers do not load data, capture odds, write archives, or participate in
any live/serving model. They reproduce the frozen GF106 market-only calculation.
"""

import math
from collections.abc import Mapping, Sequence


_GOLDEN = 0.618033988749895


def _finite_nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite nonnegative number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


def _poisson_pmf(lam: float, count: int) -> float:
    probability = math.exp(-lam)
    for k in range(1, count + 1):
        probability *= lam / k
    return probability


def _half_line(line: object) -> tuple[float, int]:
    if isinstance(line, bool) or not isinstance(line, (int, float)):
        raise TypeError("line must be a finite x.5 half-line")
    value = float(line)
    if not math.isfinite(value) or value < 0 or value % 1 != 0.5:
        raise ValueError("line must be a nonnegative x.5 half-line")
    return value, math.floor(value)


def over_half_line_probability(total_lambda: float, line: float) -> float:
    """Return research-only P(Poisson(total_lambda) > x.5).

    For 2.5 this is P(N >= 3): the complementary sum includes terms 0..2.
    Whole and quarter lines (which have push/settlement complexity) are rejected.
    """
    lam = _finite_nonnegative(total_lambda, "total_lambda")
    _, floor_line = _half_line(line)
    return 1.0 - sum(_poisson_pmf(lam, k) for k in range(floor_line + 1))


def market_wdl_probs(lambda_home: float, lambda_away: float) -> tuple[float, float, float]:
    """Return research-only (home, draw, away) probabilities from GF106's 0..12 ladder."""
    home = _finite_nonnegative(lambda_home, "lambda_home")
    away = _finite_nonnegative(lambda_away, "lambda_away")
    home_p = [_poisson_pmf(home, i) for i in range(13)]
    away_p = [_poisson_pmf(away, i) for i in range(13)]
    h = d = a = 0.0
    for i, pi in enumerate(home_p):
        for j, pj in enumerate(away_p):
            if i > j:
                h += pi * pj
            elif i == j:
                d += pi * pj
            else:
                a += pi * pj
    return h, d, a


def _targets(wdl_target: Sequence[float], ou_targets: Mapping[str, float]):
    if isinstance(wdl_target, (str, bytes)) or not isinstance(wdl_target, Sequence) or len(wdl_target) != 3:
        raise ValueError("wdl_target must contain exactly three probabilities")
    wdl = tuple(_probability(x, "WDL target") for x in wdl_target)
    if not math.isclose(sum(wdl), 1.0, rel_tol=0.0, abs_tol=1e-8):
        raise ValueError("WDL target probabilities must sum to 1")
    if not isinstance(ou_targets, Mapping) or not ou_targets:
        raise ValueError("ou_targets must be a nonempty mapping")
    ou = []
    for line, probability in ou_targets.items():
        if not isinstance(line, str):
            raise TypeError("OU line keys must be strings")
        _half_line(float(line))
        ou.append((float(line), _probability(probability, "OU target")))
    return wdl, tuple(ou)


def _probability(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite probability")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite probability in [0, 1]")
    return value


def fit_market_lambdas(wdl_target: Sequence[float], ou_targets: Mapping[str, float]) -> tuple[float, float]:
    """Fit GF106-original independent Poisson lambdas to market targets (research only).

    Uses 0.1..5.0 bounded golden-section coordinate search, 23 iterations per
    coordinate, 5 home/away cycles, starting at (1.4, 1.4). Targets are not mutated.
    """
    wdl, ou = _targets(wdl_target, ou_targets)

    def objective(home: float, away: float) -> float:
        modeled_wdl = market_wdl_probs(home, away)
        loss = sum((modeled_wdl[i] - wdl[i]) ** 2 for i in range(3))
        loss += sum((over_half_line_probability(home + away, line) - target) ** 2
                    for line, target in ou) / len(ou)
        return loss

    def optimize(axis: int, home: float, away: float) -> float:
        left, right = 0.1, 5.0
        x1 = right - _GOLDEN * (right - left)
        x2 = left + _GOLDEN * (right - left)
        for _ in range(23):
            f1 = objective(x1, away) if axis == 0 else objective(home, x1)
            f2 = objective(x2, away) if axis == 0 else objective(home, x2)
            if f1 < f2:
                right, x2 = x2, x1
                x1 = right - _GOLDEN * (right - left)
            else:
                left, x1 = x1, x2
                x2 = left + _GOLDEN * (right - left)
        return (left + right) / 2.0

    home = away = 1.4
    for _ in range(5):
        home = optimize(0, home, away)
        away = optimize(1, home, away)
    return home, away
