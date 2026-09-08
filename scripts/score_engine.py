#!/usr/bin/env python3
"""Canonical score-matrix construction and derived-market projections."""

from __future__ import annotations

import math
from typing import Any, Mapping

from market_contracts import settle_asian_contract


SCORE_ENGINE_VERSION = "score_engine.v1"
OUTCOMES = ("home", "draw", "away")


def dixon_coles_score_matrix(model: dict | None, max_goals: int = 12) -> dict[tuple[int, int], float]:
    """Build the normalized score matrix from explicit model parameters."""
    model = (model or {}).get("model", model or {})
    lambda_home = model.get("lambda_home")
    lambda_away = model.get("lambda_away")
    if lambda_home is None or lambda_away is None:
        return {}
    lambda_home = float(lambda_home)
    lambda_away = float(lambda_away)
    if lambda_home <= 0 or lambda_away <= 0:
        return {}
    rho = float(model.get("rho") or 0.0)
    matrix = {}
    for home_goals in range(max_goals + 1):
        home_probability = math.exp(-lambda_home) * lambda_home ** home_goals / math.factorial(home_goals)
        for away_goals in range(max_goals + 1):
            away_probability = math.exp(-lambda_away) * lambda_away ** away_goals / math.factorial(away_goals)
            probability = home_probability * away_probability
            if (home_goals, away_goals) == (0, 0):
                probability *= 1 - lambda_home * lambda_away * rho
            elif (home_goals, away_goals) == (0, 1):
                probability *= 1 + lambda_home * rho
            elif (home_goals, away_goals) == (1, 0):
                probability *= 1 + lambda_away * rho
            elif (home_goals, away_goals) == (1, 1):
                probability *= 1 - rho
            matrix[(home_goals, away_goals)] = max(0.0, probability)
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()} if total else {}


def outcome_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    result = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home, away), probability in matrix.items():
        result["home" if home > away else "draw" if home == away else "away"] += probability
    return result


def btts_yes_probability(matrix: Mapping[tuple[int, int], float]) -> float:
    return sum(probability for (home, away), probability in matrix.items() if home > 0 and away > 0)


def btts_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    yes = btts_yes_probability(matrix)
    return {"yes": round(yes, 6), "no": round(1 - yes, 6)}


def total_goals_buckets(matrix: Mapping[tuple[int, int], float]) -> list[dict[str, Any]]:
    exact_totals: dict[int, float] = {}
    for (home, away), probability in matrix.items():
        exact_totals[home + away] = exact_totals.get(home + away, 0.0) + probability
    return [
        {
            "goals": str(goals) if goals < 6 else "6+",
            "probability": round(
                probability if goals < 6 else sum(value for key, value in exact_totals.items() if key >= 6),
                6,
            ),
        }
        for goals, probability in sorted(exact_totals.items())
        if goals <= 6
    ]


def ranked_exact_score_rows(
    matrix: Mapping[tuple[int, int], float], *, limit: int = 10
) -> list[dict[str, Any]]:
    scores = sorted(matrix.items(), key=lambda item: item[1], reverse=True)
    return [
        {
            "score": f"{home}-{away}",
            "probability": round(probability, 6),
            "fair_odds": round(1 / probability, 4) if probability > 0 else None,
            "rank": rank,
        }
        for rank, ((home, away), probability) in enumerate(scores[:limit], 1)
    ]


def project_score_matrix(
    matrix: Mapping[tuple[int, int], float], *, exact_score_limit: int = 10
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    return (
        ranked_exact_score_rows(matrix, limit=exact_score_limit),
        total_goals_buckets(matrix),
        btts_probabilities(matrix),
    )


def score_matrix_rows(matrix: Mapping[tuple[int, int], float]) -> list[dict[str, Any]]:
    rows = [
        {
            "score": f"{home}-{away}",
            "home_goals": home,
            "away_goals": away,
            "probability": float(probability),
        }
        for (home, away), probability in matrix.items()
    ]
    return sorted(rows, key=lambda row: (-row["probability"], row["home_goals"], row["away_goals"]))


def independent_poisson_score_matrix(
    lambda_home: float, lambda_away: float, *, max_goals_per_team: int = 12
) -> dict[tuple[int, int], float]:
    matrix, _ = independent_poisson_score_matrix_with_tail(
        lambda_home,
        lambda_away,
        max_goals_per_team=max_goals_per_team,
    )
    return matrix


def independent_poisson_score_matrix_with_tail(
    lambda_home: float, lambda_away: float, *, max_goals_per_team: int = 12
) -> tuple[dict[tuple[int, int], float], float]:
    """Build the canonical independent-Poisson matrix and expose omitted mass."""
    raw: dict[tuple[int, int], float] = {}
    for home_goals in range(max_goals_per_team + 1):
        home_probability = math.exp(-lambda_home) * lambda_home ** home_goals / math.factorial(home_goals)
        for away_goals in range(max_goals_per_team + 1):
            away_probability = math.exp(-lambda_away) * lambda_away ** away_goals / math.factorial(away_goals)
            raw[(home_goals, away_goals)] = home_probability * away_probability
    total = sum(raw.values())
    if total <= 0 or not math.isfinite(total):
        return {}, 1.0
    return (
        {score: probability / total for score, probability in raw.items()},
        max(0.0, 1.0 - total),
    )


def independent_poisson_score_rows(
    lambda_home: float, lambda_away: float, *, max_goals_per_team: int = 12
) -> list[dict[str, Any]]:
    return score_matrix_rows(
        independent_poisson_score_matrix(
            lambda_home,
            lambda_away,
            max_goals_per_team=max_goals_per_team,
        )
    )


def total_goal_distribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, float] = {}
    for row in rows:
        total = int(row["home_goals"]) + int(row["away_goals"])
        buckets[total] = buckets.get(total, 0.0) + float(row["probability"])
    return [
        {"goals": goals, "probability": probability}
        for goals, probability in sorted(buckets.items())
    ]


def matrix_settlement_probability(
    matrix: Mapping[tuple[int, int], float], *, family: str, side: str, line: float
) -> dict[str, float | None]:
    win = push = loss = 0.0
    contract = {
        "family": "total" if family == "total" else "asian_handicap",
        "selection": side,
        "line": line,
    }
    for (home, away), probability in matrix.items():
        units = settle_asian_contract(contract, (home, away))["units"]
        if units > 0:
            win += probability * units
            if units < 1:
                push += probability * (1 - units)
        elif units < 0:
            loss += probability * -units
            if units > -1:
                push += probability * (1 + units)
        else:
            push += probability
    fair_odds = 1 + loss / win if win > 0 else None
    return {"win": win, "push": push, "loss": loss, "fair_odds": fair_odds}


def _settlement_categories(matrix: Mapping[tuple[int, int], float], *, family: str, line: float, side: str = "home") -> dict:
    categories = {"full_win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "full_loss": 0.0}
    contract = {
        "family": "total" if family == "total" else "asian_handicap",
        "selection": side if family == "total" else "home",
        "line": line,
    }
    for (home_goals, away_goals), probability in matrix.items():
        category = settle_asian_contract(contract, (home_goals, away_goals))["category"]
        categories[category] += probability
    win_units = categories["full_win"] + 0.5 * categories["half_win"]
    loss_units = categories["full_loss"] + 0.5 * categories["half_loss"]
    return {**categories, "win_units": win_units, "loss_units": loss_units}


def asian_handicap_settlement(matrix: Mapping[tuple[int, int], float], handicap: float) -> dict:
    """Price a home-side Asian handicap with full/half win-loss and push handling."""
    categories = _settlement_categories(matrix, family="handicap", line=handicap)
    win_units = categories["win_units"]
    loss_units = categories["loss_units"]
    fair_odds = 1 + loss_units / win_units if win_units else None
    return {
        "handicap": float(handicap),
        "parts": list(settle_asian_contract(
            {"family": "asian_handicap", "selection": "home", "line": handicap}, (0, 0)
        )["parts"]),
        "full_win": categories["full_win"],
        "half_win": categories["half_win"],
        "push": categories["push"],
        "half_loss": categories["half_loss"],
        "full_loss": categories["full_loss"],
        "win_units": win_units,
        "loss_units": loss_units,
        "fair_decimal_odds": fair_odds,
        "expected_net_at_2_00": win_units - loss_units,
    }


def asian_total_settlement(matrix: Mapping[tuple[int, int], float], total_line: float, side: str) -> dict:
    """Price an Asian goal total, including quarter-line half settlements."""
    if side not in {"over", "under"}:
        raise ValueError("side must be 'over' or 'under'")
    categories = _settlement_categories(matrix, family="total", line=total_line, side=side)
    win_units = categories["win_units"]
    loss_units = categories["loss_units"]
    fair_odds = 1 + loss_units / win_units if win_units else None
    return {
        "total_line": float(total_line),
        "side": side,
        "parts": list(settle_asian_contract(
            {"family": "total", "selection": side, "line": total_line}, (0, 0)
        )["parts"]),
        "full_win": categories["full_win"],
        "half_win": categories["half_win"],
        "push": categories["push"],
        "half_loss": categories["half_loss"],
        "full_loss": categories["full_loss"],
        "win_units": win_units,
        "loss_units": loss_units,
        "fair_decimal_odds": fair_odds,
        "expected_net_at_2_00": win_units - loss_units,
    }


def exact_total_goals_set(matrix: Mapping[tuple[int, int], float], totals) -> dict:
    """Price a discrete set of exact total-goal outcomes."""
    normalized = sorted({int(total) for total in totals})
    if not normalized or any(total < 0 for total in normalized):
        raise ValueError("totals must contain at least one non-negative integer")
    per_total = {
        total: sum(
            probability
            for (home_goals, away_goals), probability in matrix.items()
            if home_goals + away_goals == total
        )
        for total in normalized
    }
    probability = sum(per_total.values())
    return {
        "totals": normalized,
        "per_total_probability": per_total,
        "probability": probability,
        "fair_decimal_odds": 1 / probability if probability else None,
        "break_even_probability_at_2_00": 0.5,
        "edge_at_2_00": 2 * probability - 1,
    }
