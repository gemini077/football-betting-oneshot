"""The accepted #189 / PR #190 Market-only lambda contract.

This module is deliberately small and read-only.  It is the one Market
lambda implementation used by the solution-first shadow lane; production
serving does not import it.  The numerical routines are adapted from the
accepted research contract at PR #190 commit
``056f868372be31aaade15596981eaa01344a8a32``.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
import statistics
from typing import Any, Iterable, Mapping

try:
    from market_contracts import split_quarter_line
except ModuleNotFoundError:  # package import from the repository root
    from scripts.market_contracts import split_quarter_line


OUTCOMES = ("home", "draw", "away")
EPSILON = 1e-12
MAX_GOALS = 20
OU_SOLVE_LOWER = 0.001
OU_SOLVE_UPPER = 20.0
OU_SOLVE_ITERATIONS = 90
SHARE_SOLVE_LOWER = 0.01
SHARE_SOLVE_UPPER = 0.99
SHARE_SOLVE_ITERATIONS = 70


class MarketContractError(ValueError):
    """Raised when an accepted Market quote or solve is not identifiable."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def water_to_decimal(water: Any) -> float:
    """Convert positive HK net water to decimal odds, fail closed otherwise."""
    value = _number(water)
    if value is None or value <= 0.0:
        raise MarketContractError("INVALID_HK_WATER_DOMAIN")
    result = 1.0 + value
    if not math.isfinite(result) or result <= 1.0:
        raise MarketContractError("INVALID_DECIMAL_ODDS_DOMAIN")
    return result


def proportional_devig(odds: Mapping[str, Any] | Iterable[Any]) -> dict[str, float] | list[float]:
    """The fixed proportional inverse-odds de-vig from the accepted contract."""
    if isinstance(odds, Mapping):
        keys = list(odds)
        values = [odds[key] for key in keys]
    else:
        keys = []
        values = list(odds)
    decimals: list[float] = []
    for value in values:
        number = _number(value)
        if number is None or number <= 1.0:
            raise MarketContractError("INVALID_DECIMAL_ODDS_DOMAIN")
        decimals.append(number)
    inverse = [1.0 / value for value in decimals]
    total = sum(inverse)
    if not math.isfinite(total) or total <= 0.0:
        raise MarketContractError("INVALID_INVERSE_ODDS_SUM")
    probabilities = [value / total for value in inverse]
    return ({key: probability for key, probability in zip(keys, probabilities)} if keys else probabilities)


def _quote_key(row: Mapping[str, Any]) -> str:
    for key in ("cid", "source_company_id", "company_id", "name"):
        value = _text(row.get(key))
        if value:
            return value.casefold()
    return ""


def _valid_quarter_line(value: Any, *, allow_negative: bool = False) -> float | None:
    number = _number(value)
    if number is None or (not allow_negative and number < 0.0):
        return None
    rounded = round(number * 4.0) / 4.0
    return rounded if abs(number - rounded) <= 1e-8 else None


def poisson_pmf(lam: float, max_goals: int = MAX_GOALS) -> list[float]:
    if _number(lam) is None or lam < 0.0 or max_goals < 0:
        raise MarketContractError("INVALID_POISSON_INTENSITY")
    values = [math.exp(-lam)]
    for goal in range(1, max_goals + 1):
        values.append(values[-1] * lam / goal)
    return values


def independent_score_matrix(lambda_home: float, lambda_away: float, *, max_goals: int = MAX_GOALS) -> tuple[dict[tuple[int, int], float], float]:
    """Return a normalized rho=0 matrix and the omitted raw Poisson tail."""
    home = poisson_pmf(lambda_home, max_goals)
    away = poisson_pmf(lambda_away, max_goals)
    raw = {(h, a): home[h] * away[a] for h in range(max_goals + 1) for a in range(max_goals + 1)}
    mass = sum(raw.values())
    if not math.isfinite(mass) or mass <= 0.0:
        raise MarketContractError("SCORE_MATRIX_MASS_INVALID")
    return {score: probability / mass for score, probability in raw.items()}, max(0.0, 1.0 - mass)


def outcome_probabilities(lambda_home: float, lambda_away: float) -> dict[str, float]:
    home = poisson_pmf(lambda_home)
    away = poisson_pmf(lambda_away)
    cumulative_away: list[float] = []
    running = 0.0
    for probability in away:
        cumulative_away.append(running)
        running += probability
    draw = sum(home[goal] * away[goal] for goal in range(min(len(home), len(away))))
    home_win = sum(home[h] * cumulative_away[h] for h in range(len(home)))
    away_win = max(0.0, 1.0 - home_win - draw)
    total = home_win + draw + away_win
    if total <= 0.0 or not math.isfinite(total):
        raise MarketContractError("OUTCOME_PROBABILITIES_INVALID")
    return {"home": home_win / total, "draw": draw / total, "away": away_win / total}


def _settlement_weights(matrix: Mapping[tuple[int, int], float], line: float, family: str, selection: str) -> tuple[float, float]:
    components = split_quarter_line(line)
    win_weight = 0.0
    loss_weight = 0.0
    for score, probability in matrix.items():
        score_win = 0.0
        score_loss = 0.0
        for component in components:
            if family == "total":
                delta = score[0] + score[1] - component
                if selection == "under":
                    delta = -delta
            elif family == "asian_handicap":
                delta = score[0] - score[1] + component
                if selection == "away":
                    delta = -delta
            else:
                raise MarketContractError("UNSUPPORTED_SETTLEMENT_FAMILY")
            if delta > 1e-9:
                score_win += 1.0
            elif delta < -1e-9:
                score_loss += 1.0
        win_weight += probability * score_win / len(components)
        loss_weight += probability * score_loss / len(components)
    return win_weight, loss_weight


def fair_probability_from_matrix(matrix: Mapping[tuple[int, int], float], line: float, family: str, selection: str) -> float:
    win_weight, loss_weight = _settlement_weights(matrix, line, family, selection)
    denominator = win_weight + loss_weight
    if win_weight <= EPSILON or loss_weight <= EPSILON or denominator <= EPSILON:
        raise MarketContractError("SETTLEMENT_PRICE_NOT_IDENTIFIABLE")
    return win_weight / denominator


def solve_total_lambda(line: float, target_over_probability: float) -> dict[str, float]:
    """Solve total intensity using exact integer/half/quarter Asian settlement."""
    line = _valid_quarter_line(line)
    target = _number(target_over_probability)
    if line is None or target is None or not (EPSILON < target < 1.0 - EPSILON):
        raise MarketContractError("OU_SOLVE_DOMAIN_INVALID")

    def model_probability(lam: float) -> float:
        # For the fixed 2.5 line there is no push state, so the accepted
        # settlement probability is exactly one minus the Poisson CDF at 2.
        # This is algebraically identical to the finite score-matrix solve and
        # avoids rebuilding a 21x21 matrix for every bisection step.
        if abs(line - 2.5) <= 1e-8:
            return 1.0 - math.exp(-lam) * (1.0 + lam + (lam * lam) / 2.0)
        matrix, _ = independent_score_matrix(lam, 0.0, max_goals=MAX_GOALS)
        return fair_probability_from_matrix(matrix, line, "total", "over")

    lower, upper = OU_SOLVE_LOWER, OU_SOLVE_UPPER
    try:
        low_probability = model_probability(lower)
        high_probability = model_probability(upper)
    except MarketContractError as error:
        raise MarketContractError("OU_SOLVE_DOMAIN_INVALID") from error
    if target < low_probability - 1e-10 or target > high_probability + 1e-10:
        raise MarketContractError("OU_SOLVE_NOT_IDENTIFIABLE")
    for _ in range(OU_SOLVE_ITERATIONS):
        middle = (lower + upper) / 2.0
        if model_probability(middle) < target:
            lower = middle
        else:
            upper = middle
    lam = (lower + upper) / 2.0
    residual = model_probability(lam) - target
    if not math.isfinite(residual) or abs(residual) > 1e-7:
        raise MarketContractError("OU_SOLVE_NO_CONVERGENCE")
    return {"lambda_total": lam, "target_probability": target, "model_probability": target + residual, "residual": residual}


def solve_home_share(lambda_total: float, target_probabilities: Mapping[str, float]) -> dict[str, float]:
    """Fit home share by the accepted deterministic bounded golden search."""
    target = {key: _number(target_probabilities.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0.0 for value in target.values()):
        raise MarketContractError("HOME_SHARE_TARGET_INVALID")
    total = sum(float(value) for value in target.values())
    if total <= 0.0:
        raise MarketContractError("HOME_SHARE_TARGET_INVALID")
    target = {key: float(value) / total for key, value in target.items()}

    def evaluate(share: float) -> float:
        probabilities = outcome_probabilities(lambda_total * share, lambda_total * (1.0 - share))
        return sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES)

    left, right = SHARE_SOLVE_LOWER, SHARE_SOLVE_UPPER
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - golden * (right - left)
    x2 = left + golden * (right - left)
    f1, f2 = evaluate(x1), evaluate(x2)
    for _ in range(SHARE_SOLVE_ITERATIONS):
        if f1 > f2:
            left, x1, f1 = x1, x2, f2
            x2 = left + golden * (right - left)
            f2 = evaluate(x2)
        else:
            right, x2, f2 = x2, x1, f1
            x1 = right - golden * (right - left)
            f1 = evaluate(x1)
    share = (left + right) / 2.0
    probabilities = outcome_probabilities(lambda_total * share, lambda_total * (1.0 - share))
    return {
        "share": share,
        "lambda_home": lambda_total * share,
        "lambda_away": lambda_total * (1.0 - share),
        "loss": sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES),
        "iterations": SHARE_SOLVE_ITERATIONS,
    }


def _market_rows(snapshot: Mapping[str, Any], family: str) -> list[dict[str, Any]]:
    market = snapshot.get(family)
    if not isinstance(market, Mapping):
        return []
    key = "bookmakers" if family == "ouzhi" else "companies"
    rows = market.get(key)
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def live_quotes(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read legal same-time frozen quotes without changing #189 semantics."""
    one_x2: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _market_rows(snapshot, "ouzhi"):
        key = _quote_key(row)
        odds = row.get("spf_current")
        if not key or key in seen or not isinstance(odds, Mapping):
            continue
        values = {outcome: _number(odds.get(outcome)) for outcome in OUTCOMES}
        if any(value is None or value <= 1.0 for value in values.values()):
            continue
        seen.add(key)
        one_x2.append({"key": key, "fair": proportional_devig(values)})
    if not one_x2:
        raise MarketContractError("NO_VALID_SAME_TIME_1X2")
    consensus = {outcome: statistics.fmean(row["fair"][outcome] for row in one_x2) for outcome in OUTCOMES}
    total = sum(consensus.values())
    consensus = {outcome: value / total for outcome, value in consensus.items()}

    ou: list[dict[str, Any]] = []
    seen = set()
    for row in _market_rows(snapshot, "daxiao"):
        key = _quote_key(row)
        line = _valid_quarter_line(row.get("current_line"))
        if not key or key in seen or line is None:
            continue
        try:
            fair = proportional_devig((water_to_decimal(row.get("current_over_water")), water_to_decimal(row.get("current_under_water"))))
        except MarketContractError:
            continue
        seen.add(key)
        ou.append({"key": key, "line": line, "over": fair[0], "under": fair[1]})
    if not ou:
        raise MarketContractError("NO_VALID_SAME_TIME_TOTAL")
    return {"consensus": consensus, "valid_count": len(one_x2)}, {"quotes": ou}


def _solve_live(one_x2: Mapping[str, Any], total_quotes: Mapping[str, Any]) -> dict[str, Any]:
    solved: list[dict[str, Any]] = []
    for quote in total_quotes["quotes"]:
        try:
            total_lambda = solve_total_lambda(float(quote["line"]), float(quote["over"]))
        except MarketContractError:
            continue
        solved.append({**quote, **total_lambda})
    if not solved:
        raise MarketContractError("NO_VALID_TOTAL_LAMBDA")
    lambda_total = statistics.median(row["lambda_total"] for row in solved)
    share = solve_home_share(lambda_total, one_x2["consensus"])
    return {
        "lambda_home": share["lambda_home"],
        "lambda_away": share["lambda_away"],
        "lambda_total": lambda_total,
        "one_x2_consensus": dict(one_x2["consensus"]),
        "one_x2_quote_count": int(one_x2["valid_count"]),
        "total_quote_count": len(solved),
        "total_lambda_quotes": [{"line": row["line"], "lambda_total": row["lambda_total"], "key": row["key"]} for row in solved],
        "contract": "accepted_same_time_market_lambda_v1",
        "contract_source": "Issue #189 / PR #190",
    }


def market_lambdas_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    one_x2, total_quotes = live_quotes(snapshot)
    return _solve_live(one_x2, total_quotes)


def external_market_lambdas(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Apply the same #189 solve to source-published historical odds."""
    def pick(*keys: str) -> float | None:
        for key in keys:
            value = _number(row.get(key))
            if value is not None and value > 1.0:
                return value
        return None

    one = [pick("AvgH", "B365H"), pick("AvgD", "B365D"), pick("AvgA", "B365A")]
    over = pick("Avg>2.5", "B365>2.5")
    under = pick("Avg<2.5", "B365<2.5")
    if any(value is None for value in one) or over is None or under is None:
        return None
    try:
        fair = proportional_devig(one)
        target = dict(zip(OUTCOMES, fair))
        fair_over = proportional_devig((over, under))[0]
        solved = solve_total_lambda(2.5, fair_over)
        share = solve_home_share(solved["lambda_total"], target)
    except (MarketContractError, ValueError):
        return None
    return {
        "lambda_home": share["lambda_home"],
        "lambda_away": share["lambda_away"],
        "lambda_total": solved["lambda_total"],
        "one_x2_consensus": target,
        "one_x2_quote_count": 1,
        "total_quote_count": 1,
        "contract": "accepted_same_time_market_lambda_v1",
        "contract_source": "Issue #189 / PR #190 adapted to Football-Data historical odds",
        "odds_semantics": "source_published_historical_odds; timing_not_equal_to_FBOS_horizon",
    }
