#!/usr/bin/env python3
"""Evaluate the defined trap registry and the upstream continuous 6D score."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import fmean, median, pstdev


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = PROJECT_ROOT / "config" / "trap_rules.json"
OUTCOMES = ("home", "draw", "away")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _pct_change(opening: float | None, current: float | None) -> float | None:
    if opening in (None, 0) or current is None:
        return None
    return (float(current) - float(opening)) / float(opening)


def _bookmaker_map(deep: dict) -> dict[int, dict]:
    return {int(item.get("cid") or 0): item for item in deep.get("ouzhi", {}).get("bookmakers", [])}


def _asian_map(deep: dict) -> dict[int, dict]:
    return {int(item.get("cid") or 0): item for item in deep.get("yazhi", {}).get("companies", [])}


def dixon_coles_score_matrix(model: dict | None, max_goals: int = 12) -> dict[tuple[int, int], float]:
    """Build a normalized score matrix from explicit model parameters."""
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


def lambdas_from_home_away_rates(
    *,
    home_for: float,
    home_against: float,
    away_for: float,
    away_against: float,
    league_home_average: float,
    league_away_average: float,
    metric: str = "xg",
) -> dict:
    """Convert home/away attack and defence rates into league-normalized scoring intensities."""
    values = {
        "home_for": float(home_for),
        "home_against": float(home_against),
        "away_for": float(away_for),
        "away_against": float(away_against),
        "league_home_average": float(league_home_average),
        "league_away_average": float(league_away_average),
    }
    if any(value <= 0 for value in values.values()):
        raise ValueError("all rate inputs must be positive")
    home_attack_strength = values["home_for"] / values["league_home_average"]
    away_defence_strength = values["away_against"] / values["league_home_average"]
    away_attack_strength = values["away_for"] / values["league_away_average"]
    home_defence_strength = values["home_against"] / values["league_away_average"]
    lambda_home = values["league_home_average"] * home_attack_strength * away_defence_strength
    lambda_away = values["league_away_average"] * away_attack_strength * home_defence_strength
    return {
        "method": "league_normalized_home_away_attack_defence_rates",
        "metric": metric,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "strengths": {
            "home_attack": home_attack_strength,
            "away_defence": away_defence_strength,
            "away_attack": away_attack_strength,
            "home_defence": home_defence_strength,
        },
        "inputs": values,
        "limitations": [
            "requires opponent adjustment and time weighting upstream",
            "does not include lineup weather tactical or market calibration",
            "historical xg rates are not themselves pre-match shot xg forecasts",
        ],
    }


def apply_log_lambda_corrections(
    lambda_home_base: float,
    lambda_away_base: float,
    *,
    home_log_adjustments: dict[str, float] | None = None,
    away_log_adjustments: dict[str, float] | None = None,
) -> dict:
    """Apply explicit, auditable log-link adjustments to positive base lambdas."""
    lambda_home_base = float(lambda_home_base)
    lambda_away_base = float(lambda_away_base)
    if not math.isfinite(lambda_home_base) or not math.isfinite(lambda_away_base):
        raise ValueError("base lambdas must be finite")
    if lambda_home_base <= 0 or lambda_away_base <= 0:
        raise ValueError("base lambdas must be positive")

    def normalize(adjustments: dict[str, float] | None, label: str) -> dict[str, float]:
        normalized = {}
        for name, value in (adjustments or {}).items():
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"{label} adjustment {name!r} must be finite")
            normalized[str(name)] = numeric
        return normalized

    home = normalize(home_log_adjustments, "home")
    away = normalize(away_log_adjustments, "away")
    delta_home = sum(home.values())
    delta_away = sum(away.values())
    return {
        "method": "separate_auditable_log_link_lambda_corrections",
        "lambda_home_base": lambda_home_base,
        "lambda_away_base": lambda_away_base,
        "home_log_adjustments": home,
        "away_log_adjustments": away,
        "delta_home": delta_home,
        "delta_away": delta_away,
        "home_multiplier": math.exp(delta_home),
        "away_multiplier": math.exp(delta_away),
        "lambda_home": lambda_home_base * math.exp(delta_home),
        "lambda_away": lambda_away_base * math.exp(delta_away),
        "limitations": [
            "adjustment contributions require pre-match as-of features and out-of-sample fitted coefficients",
            "home and away deltas are separate and are never assumed to be exact opposites",
            "correlated or overlapping features require collinearity control before summing",
        ],
    }


def poisson_truncation_audit(lambda_home: float, lambda_away: float, max_goals: int) -> dict:
    """Report probability mass omitted by a finite independent-Poisson score grid."""
    lambda_home = float(lambda_home)
    lambda_away = float(lambda_away)
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError("lambda_home and lambda_away must be positive")
    if not isinstance(max_goals, int) or isinstance(max_goals, bool) or max_goals < 0:
        raise ValueError("max_goals must be a non-negative integer")

    home_probabilities = [
        math.exp(-lambda_home) * lambda_home ** goals / math.factorial(goals)
        for goals in range(max_goals + 1)
    ]
    away_probabilities = [
        math.exp(-lambda_away) * lambda_away ** goals / math.factorial(goals)
        for goals in range(max_goals + 1)
    ]
    raw_outcomes = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for home_goals, home_probability in enumerate(home_probabilities):
        for away_goals, away_probability in enumerate(away_probabilities):
            outcome = "home" if home_goals > away_goals else "draw" if home_goals == away_goals else "away"
            raw_outcomes[outcome] += home_probability * away_probability
    retained_mass = sum(raw_outcomes.values())
    normalized_outcomes = {
        outcome: probability / retained_mass
        for outcome, probability in raw_outcomes.items()
    } if retained_mass else {}
    return {
        "method": "independent_poisson_finite_grid_audit",
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "max_goals_per_team": max_goals,
        "retained_probability_mass": retained_mass,
        "omitted_probability_mass": 1.0 - retained_mass,
        "raw_truncated_outcome_probabilities": raw_outcomes,
        "normalized_within_grid_outcome_probabilities": normalized_outcomes,
        "pricing_allowed_without_overflow": 1.0 - retained_mass <= 1e-6,
        "warning": "raw truncated probabilities must not be converted directly to fair odds",
    }


def half_full_time_probabilities(
    *,
    lambda_home_first_half: float,
    lambda_away_first_half: float,
    lambda_home_second_half: float,
    lambda_away_second_half: float,
    max_goals_per_half: int = 10,
) -> dict:
    """Build a nine-outcome half-time/full-time baseline from phase-specific Poisson rates."""
    rates = {
        "home_first_half": float(lambda_home_first_half),
        "away_first_half": float(lambda_away_first_half),
        "home_second_half": float(lambda_home_second_half),
        "away_second_half": float(lambda_away_second_half),
    }
    if any(not math.isfinite(rate) or rate < 0 for rate in rates.values()):
        raise ValueError("all half-specific lambdas must be finite and non-negative")
    if not isinstance(max_goals_per_half, int) or isinstance(max_goals_per_half, bool) or max_goals_per_half < 0:
        raise ValueError("max_goals_per_half must be a non-negative integer")

    def probabilities(rate: float) -> list[float]:
        return [math.exp(-rate) * rate ** goals / math.factorial(goals) for goals in range(max_goals_per_half + 1)]

    home_first = probabilities(rates["home_first_half"])
    away_first = probabilities(rates["away_first_half"])
    home_second = probabilities(rates["home_second_half"])
    away_second = probabilities(rates["away_second_half"])
    labels = ("H", "D", "A")
    joint = {f"{half}/{full}": 0.0 for half in labels for full in labels}

    def result_label(home_goals: int, away_goals: int) -> str:
        return "H" if home_goals > away_goals else "D" if home_goals == away_goals else "A"

    for first_home_goals, first_home_probability in enumerate(home_first):
        for first_away_goals, first_away_probability in enumerate(away_first):
            half_label = result_label(first_home_goals, first_away_goals)
            first_probability = first_home_probability * first_away_probability
            for second_home_goals, second_home_probability in enumerate(home_second):
                for second_away_goals, second_away_probability in enumerate(away_second):
                    full_label = result_label(
                        first_home_goals + second_home_goals,
                        first_away_goals + second_away_goals,
                    )
                    joint[f"{half_label}/{full_label}"] += (
                        first_probability * second_home_probability * second_away_probability
                    )

    retained_mass = sum(joint.values())
    normalized = {outcome: probability / retained_mass for outcome, probability in joint.items()} if retained_mass else {}
    half_marginal = {
        label: sum(probability for outcome, probability in normalized.items() if outcome.startswith(f"{label}/"))
        for label in labels
    }
    full_marginal = {
        label: sum(probability for outcome, probability in normalized.items() if outcome.endswith(f"/{label}"))
        for label in labels
    }
    conditional_full_given_half = {}
    for half_label in labels:
        denominator = half_marginal[half_label]
        conditional_full_given_half[half_label] = {
            full_label: normalized[f"{half_label}/{full_label}"] / denominator if denominator else None
            for full_label in labels
        }
    pricing_allowed = 1.0 - retained_mass <= 1e-6
    return {
        "method": "independent_phase_poisson_half_full_time_baseline",
        "rates": rates,
        "max_goals_per_half": max_goals_per_half,
        "retained_probability_mass": retained_mass,
        "omitted_probability_mass": 1.0 - retained_mass,
        "joint_probabilities": normalized,
        "half_time_marginal": half_marginal,
        "full_time_marginal": full_marginal,
        "conditional_full_time_given_half_time": conditional_full_given_half,
        "fair_decimal_odds": {
            outcome: 1.0 / probability if pricing_allowed and probability > 0 else None
            for outcome, probability in normalized.items()
        },
        "pricing_allowed_without_overflow": pricing_allowed,
        "limitations": [
            "second-half scoring rates are assumed independent of the half-time score state",
            "requires phase-specific opponent-adjusted and time-weighted rate estimates upstream",
            "red cards substitutions tactical switches and score effects require conditional calibration",
        ],
    }


def _asian_line_parts(handicap: float) -> list[float]:
    quarter_units = round(float(handicap) * 4)
    if quarter_units % 2 == 0:
        return [quarter_units / 4]
    return [(quarter_units - 1) / 4, (quarter_units + 1) / 4]


def asian_handicap_settlement(matrix: dict[tuple[int, int], float], handicap: float) -> dict:
    """Price a home-side Asian handicap with full/half win-loss and push handling."""
    categories = {"full_win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "full_loss": 0.0}
    parts = _asian_line_parts(handicap)
    for (home_goals, away_goals), probability in matrix.items():
        component_results = []
        for part in parts:
            adjusted_margin = home_goals - away_goals + part
            component_results.append(1 if adjusted_margin > 1e-9 else -1 if adjusted_margin < -1e-9 else 0)
        net = sum(component_results) / len(component_results)
        category = {
            1.0: "full_win",
            0.5: "half_win",
            0.0: "push",
            -0.5: "half_loss",
            -1.0: "full_loss",
        }[net]
        categories[category] += probability
    win_units = categories["full_win"] + 0.5 * categories["half_win"]
    loss_units = categories["full_loss"] + 0.5 * categories["half_loss"]
    fair_odds = 1 + loss_units / win_units if win_units else None
    return {
        "handicap": float(handicap),
        "parts": parts,
        **categories,
        "win_units": win_units,
        "loss_units": loss_units,
        "fair_decimal_odds": fair_odds,
        "expected_net_at_2_00": win_units - loss_units,
    }


def asian_total_settlement(matrix: dict[tuple[int, int], float], total_line: float, side: str) -> dict:
    """Price an Asian goal total, including quarter-line half settlements."""
    if side not in {"over", "under"}:
        raise ValueError("side must be 'over' or 'under'")
    categories = {"full_win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "full_loss": 0.0}
    parts = _asian_line_parts(total_line)
    for (home_goals, away_goals), probability in matrix.items():
        goals = home_goals + away_goals
        component_results = []
        for part in parts:
            margin = goals - part if side == "over" else part - goals
            component_results.append(1 if margin > 1e-9 else -1 if margin < -1e-9 else 0)
        net = sum(component_results) / len(component_results)
        category = {
            1.0: "full_win",
            0.5: "half_win",
            0.0: "push",
            -0.5: "half_loss",
            -1.0: "full_loss",
        }[net]
        categories[category] += probability
    win_units = categories["full_win"] + 0.5 * categories["half_win"]
    loss_units = categories["full_loss"] + 0.5 * categories["half_loss"]
    fair_odds = 1 + loss_units / win_units if win_units else None
    return {
        "total_line": float(total_line),
        "side": side,
        "parts": parts,
        **categories,
        "win_units": win_units,
        "loss_units": loss_units,
        "fair_decimal_odds": fair_odds,
        "expected_net_at_2_00": win_units - loss_units,
    }


def exact_total_goals_set(matrix: dict[tuple[int, int], float], totals) -> dict:
    """Price a discrete set of exact total-goal outcomes, such as 1-or-3 goals."""
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


def mutually_exclusive_coverage_ev(
    probabilities: dict[str, float],
    decimal_odds: dict[str, float],
    stake_per_ticket: float = 2.0,
    independent_legs: int = 1,
) -> dict:
    """Audit equal-stake coverage of selected mutually exclusive outcomes.

    For multiple legs this prices the complete Cartesian product of the same
    selected outcomes.  That projection is diagnostic only: it requires the
    legs to be independent and to share the supplied probability/price vector.
    Unselected outcomes correctly contribute zero gross return.
    """
    if not probabilities or set(probabilities) != set(decimal_odds):
        raise ValueError("probabilities and decimal_odds must have the same non-empty keys")
    probabilities = {str(outcome): float(value) for outcome, value in probabilities.items()}
    decimal_odds = {str(outcome): float(value) for outcome, value in decimal_odds.items()}
    if any(not math.isfinite(value) or value < 0 for value in probabilities.values()):
        raise ValueError("probabilities must be finite and non-negative")
    covered_probability = sum(probabilities.values())
    if covered_probability > 1.0 + 1e-12:
        raise ValueError("mutually exclusive probabilities cannot sum above 1")
    if any(not math.isfinite(price) or price <= 1.0 for price in decimal_odds.values()):
        raise ValueError("all decimal odds must be finite and greater than 1.0")
    stake_per_ticket = float(stake_per_ticket)
    if not math.isfinite(stake_per_ticket) or stake_per_ticket <= 0:
        raise ValueError("stake_per_ticket must be a positive finite number")
    if isinstance(independent_legs, bool) or not isinstance(independent_legs, int) or independent_legs < 1:
        raise ValueError("independent_legs must be a positive integer")

    outcome_count = len(probabilities)
    single_leg_expected_gross_factor = sum(
        probabilities[outcome] * decimal_odds[outcome]
        for outcome in probabilities
    )
    ticket_count = outcome_count ** independent_legs
    total_stake = stake_per_ticket * ticket_count
    expected_gross = stake_per_ticket * single_leg_expected_gross_factor ** independent_legs
    expected_net = expected_gross - total_stake
    return {
        "method": "mutually_exclusive_equal_stake_cartesian_coverage",
        "probabilities": probabilities,
        "decimal_odds": decimal_odds,
        "covered_probability_single_leg": covered_probability,
        "uncovered_probability_single_leg": max(0.0, 1.0 - covered_probability),
        "independent_legs": independent_legs,
        "ticket_count": ticket_count,
        "stake_per_ticket": stake_per_ticket,
        "total_stake": total_stake,
        "expected_gross": expected_gross,
        "expected_net": expected_net,
        "expected_roi": expected_net / total_stake,
        "single_leg_expected_gross_factor": single_leg_expected_gross_factor,
        "assumptions": [
            "selected outcomes are mutually exclusive within each match",
            "unselected outcomes return zero",
            "all supplied prices are executable for the stated stake",
            "multi-leg projection assumes independent identically priced legs",
        ],
        "execution_status": "diagnostic_only",
    }


def binary_kelly_diagnostic(
    probability: float,
    decimal_odds: float,
    fraction_multiplier: float = 0.5,
) -> dict:
    """Calculate binary Kelly as a diagnostic, never as automatic stake authority."""
    probability = float(probability)
    decimal_odds = float(decimal_odds)
    fraction_multiplier = float(fraction_multiplier)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be finite and between 0 and 1")
    if not math.isfinite(decimal_odds) or decimal_odds <= 1.0:
        raise ValueError("decimal_odds must be finite and greater than 1.0")
    if not math.isfinite(fraction_multiplier) or not 0.0 <= fraction_multiplier <= 1.0:
        raise ValueError("fraction_multiplier must be finite and between 0 and 1")

    net_odds = decimal_odds - 1.0
    expected_value = probability * decimal_odds - 1.0
    full_kelly_fraction = expected_value / net_odds
    scaled_fraction = fraction_multiplier * full_kelly_fraction
    return {
        "method": "binary_kelly_diagnostic",
        "probability": probability,
        "decimal_odds": decimal_odds,
        "expected_value": expected_value,
        "full_kelly_fraction": full_kelly_fraction,
        "fraction_multiplier": fraction_multiplier,
        "scaled_kelly_fraction": scaled_fraction,
        "stake_fraction_after_no_negative_gate": max(0.0, scaled_fraction),
        "positive_ev": expected_value > 0.0,
        "execution_status": "diagnostic_only",
        "scope": "binary_no_push_market_with_calibrated_probability_only",
    }


def annualized_return(starting_value: float, ending_value: float, elapsed_days: float) -> dict:
    """Separate holding-period return from geometrically annualized return."""
    starting_value = float(starting_value)
    ending_value = float(ending_value)
    elapsed_days = float(elapsed_days)
    if any(not math.isfinite(value) for value in (starting_value, ending_value, elapsed_days)):
        raise ValueError("values and elapsed_days must be finite")
    if starting_value <= 0 or ending_value <= 0 or elapsed_days <= 0:
        raise ValueError("values and elapsed_days must be positive")
    holding_period_return = ending_value / starting_value - 1.0
    annualized = (ending_value / starting_value) ** (365.0 / elapsed_days) - 1.0
    return {
        "method": "geometric_365_day_annualization",
        "starting_value": starting_value,
        "ending_value": ending_value,
        "elapsed_days": elapsed_days,
        "holding_period_return": holding_period_return,
        "annualized_return": annualized,
    }


def fixed_odds_arbitrage(best_decimal_odds: dict[str, float], total_stake: float = 100.0) -> dict:
    """Diagnose pure fixed-odds arbitrage for exhaustive, mutually exclusive outcomes.

    This is a mathematical quote check only. It intentionally does not claim
    executability because limits, rejected bets, price movement, commissions,
    void rules, rounding and settlement-scope mismatches are external inputs.
    """
    if len(best_decimal_odds) < 2:
        raise ValueError("at least two exhaustive outcomes are required")
    total_stake = float(total_stake)
    if not math.isfinite(total_stake) or total_stake <= 0:
        raise ValueError("total_stake must be a positive finite number")
    odds = {str(outcome): float(price) for outcome, price in best_decimal_odds.items()}
    if any(not math.isfinite(price) or price <= 1.0 for price in odds.values()):
        raise ValueError("all decimal odds must be finite and greater than 1.0")

    inverse_sum = sum(1.0 / price for price in odds.values())
    stakes = {
        outcome: total_stake * (1.0 / price) / inverse_sum
        for outcome, price in odds.items()
    }
    gross_payout = total_stake / inverse_sum
    guaranteed_profit = gross_payout - total_stake
    return {
        "method": "cross_book_best_price_inverse_sum",
        "best_decimal_odds": odds,
        "inverse_sum": inverse_sum,
        "theoretical_arbitrage": inverse_sum < 1.0,
        "arbitrage_gap": 1.0 - inverse_sum,
        "total_stake": total_stake,
        "equal_payout_stakes": stakes,
        "gross_payout_each_outcome": gross_payout,
        "guaranteed_profit_before_costs": guaranteed_profit,
        "roi_before_costs": guaranteed_profit / total_stake,
        "assumptions": [
            "outcomes are mutually exclusive and collectively exhaustive",
            "all quotes are simultaneously executable for the calculated stakes",
            "all books use the same settlement scope and void rules",
            "no commission tax currency fee stake rounding or withdrawal cost",
        ],
        "execution_status": "mathematical_quote_check_only",
    }


def theoretical_asian_handicap(model: dict | None) -> dict | None:
    """Find the quarter-goal line whose fair home price is closest to decimal 2.00."""
    matrix = dixon_coles_score_matrix(model)
    if not matrix:
        return None
    candidates = [asian_handicap_settlement(matrix, quarter / 4) for quarter in range(-20, 21)]
    valid = [item for item in candidates if item["fair_decimal_odds"] is not None]
    selected = min(valid, key=lambda item: (abs(item["fair_decimal_odds"] - 2.0), abs(item["handicap"])))
    return {
        "method": "poisson_dixon_coles_asian_settlement",
        "line": selected["handicap"],
        "depth": abs(selected["handicap"]),
        "fair_decimal_odds": selected["fair_decimal_odds"],
        "settlement": selected,
        "candidate_range": [-5.0, 5.0],
    }


def theoretical_asian_total(model: dict | None) -> dict | None:
    """Find the quarter-goal total whose fair over price is closest to decimal 2.00."""
    matrix = dixon_coles_score_matrix(model)
    if not matrix:
        return None
    model_values = (model or {}).get("model", model or {})
    expected_total = float(model_values["lambda_home"]) + float(model_values["lambda_away"])
    candidates = [asian_total_settlement(matrix, quarter / 4, "over") for quarter in range(2, 29)]
    valid = [item for item in candidates if item["fair_decimal_odds"] is not None]
    selected = min(
        valid,
        key=lambda item: (
            abs(item["fair_decimal_odds"] - 2.0),
            abs(item["total_line"] - expected_total),
        ),
    )
    return {
        "method": "poisson_dixon_coles_asian_total_settlement",
        "line": selected["total_line"],
        "fair_over_decimal_odds": selected["fair_decimal_odds"],
        "expected_total_goals": expected_total,
        "settlement": selected,
        "candidate_range": [0.5, 7.0],
    }


def market_metrics(deep: dict, mbi: dict, model: dict | None = None) -> dict:
    books = _bookmaker_map(deep)
    asian = _asian_map(deep)
    pin = books.get(1055, {})
    pin_open = pin.get("spf_open") or {}
    pin_current = pin.get("spf_current") or {}
    pin_ah = asian.get(1055, {})
    shin = mbi.get("consensus", {}).get("shin", {}).get("probabilities") or mbi.get("consensus", {}).get("proportional_no_vig") or {}
    theory_panel = theoretical_asian_handicap(model)
    total_theory_panel = theoretical_asian_total(model)
    score_matrix = dixon_coles_score_matrix(model)
    model_values = (model or {}).get("model", model or {})
    truncation_audit = (
        poisson_truncation_audit(float(model_values["lambda_home"]), float(model_values["lambda_away"]), 12)
        if score_matrix and model_values.get("lambda_home") is not None and model_values.get("lambda_away") is not None
        else None
    )
    exact_total_combinations = (
        {
            "1_or_3": exact_total_goals_set(score_matrix, (1, 3)),
            "3_or_4": exact_total_goals_set(score_matrix, (3, 4)),
        }
        if score_matrix else {}
    )
    theoretical_ah = theory_panel.get("depth") if theory_panel else None
    current_lines = [abs(float(item["current_handicap"])) for item in asian.values() if item.get("current_handicap") is not None]
    open_lines = [abs(float(item["open_handicap"])) for item in asian.values() if item.get("open_handicap") is not None]
    actual_ah = median(current_lines) if current_lines else None
    opening_ah = median(open_lines) if open_lines else None
    core_cids = (1055, 3, 5)
    core_lines = [abs(float(asian[cid]["current_handicap"])) for cid in core_cids if cid in asian and asian[cid].get("current_handicap") is not None]
    core_home_odds = [float((books[cid].get("spf_current") or {})["home"]) for cid in core_cids if cid in books and (books[cid].get("spf_current") or {}).get("home")]
    all_home_odds = [float((item.get("spf_current") or {})["home"]) for item in books.values() if (item.get("spf_current") or {}).get("home")]
    home_waters = [float(item["current_water_home"]) for item in asian.values() if item.get("current_water_home") is not None]

    sharp_lines = [abs(float(asian[cid]["current_handicap"])) for cid in (1055, 3) if cid in asian and asian[cid].get("current_handicap") is not None]
    asian_lines = [abs(float(asian[cid]["current_handicap"])) for cid in (5, 280, 651, 9, 16) if cid in asian and asian[cid].get("current_handicap") is not None]
    sharp_asian_gap = abs(median(sharp_lines) - median(asian_lines)) if sharp_lines and asian_lines else None

    return {
        "shin_probabilities": shin,
        "theoretical_ah": theoretical_ah,
        "theoretical_ah_signed": theory_panel.get("line") if theory_panel else None,
        "theoretical_ah_detail": theory_panel,
        "theoretical_total_line": total_theory_panel.get("line") if total_theory_panel else None,
        "theoretical_total_fair_over_odds": total_theory_panel.get("fair_over_decimal_odds") if total_theory_panel else None,
        "theoretical_total_detail": total_theory_panel,
        "exact_total_goal_combinations": exact_total_combinations,
        "score_matrix_truncation_audit": truncation_audit,
        "actual_ah": actual_ah,
        "opening_ah": opening_ah,
        "ah_gap": abs(theoretical_ah - actual_ah) if theoretical_ah is not None and actual_ah is not None else None,
        "ah_change": (
            abs(float(pin_ah["current_handicap"])) - abs(float(pin_ah["open_handicap"]))
            if pin_ah.get("current_handicap") is not None and pin_ah.get("open_handicap") is not None else None
        ),
        "pin_home_change": _pct_change(pin_open.get("home"), pin_current.get("home")),
        "pin_draw_change": _pct_change(pin_open.get("draw"), pin_current.get("draw")),
        "pin_away_change": _pct_change(pin_open.get("away"), pin_current.get("away")),
        "pin_open_home": pin_open.get("home"),
        "pin_current_home": pin_current.get("home"),
        "core_lines": core_lines,
        "core_line_spread": max(core_lines) - min(core_lines) if len(core_lines) >= 2 else None,
        "core_home_odds": core_home_odds,
        "core_home_odds_spread": max(core_home_odds) - min(core_home_odds) if len(core_home_odds) >= 2 else None,
        "all_home_odds": all_home_odds,
        "water_sigma": pstdev(home_waters) if len(home_waters) >= 2 else None,
        "sharp_asian_line_gap": sharp_asian_gap,
        "bookmakers": books,
        "asian": asian,
    }


def evaluate_traps(deep: dict, mbi: dict, registry: dict, model: dict | None = None) -> dict:
    metrics = market_metrics(deep, mbi, model)
    books = metrics["bookmakers"]
    asian = metrics["asian"]
    home_change = metrics["pin_home_change"]
    draw_change = metrics["pin_draw_change"]
    ah_change = metrics["ah_change"]
    actual = metrics["actual_ah"]
    theory = metrics["theoretical_ah"]
    opening = metrics["opening_ah"]
    probability = metrics["shin_probabilities"]

    def movement(cid):
        book = books.get(cid, {})
        return _pct_change((book.get("spf_open") or {}).get("home"), (book.get("spf_current") or {}).get("home"))

    def water_change(cid):
        item = asian.get(cid, {})
        if item.get("open_handicap") != item.get("current_handicap"):
            return None
        if item.get("open_water_home") is None or item.get("current_water_home") is None:
            return None
        return float(item["current_water_home"]) - float(item["open_water_home"])

    pin_move = movement(1055)
    bet365_move = movement(3)
    core_pairwise_diverge = False
    if len(metrics["core_lines"]) == 3:
        values = metrics["core_lines"]
        core_pairwise_diverge = all(abs(values[i] - values[j]) >= 0.25 for i in range(3) for j in range(i + 1, 3))
    same_water = [water_change(cid) for cid in (1055, 3, 5)]
    same_water_trigger = (
        len(same_water) == 3 and all(value is not None for value in same_water)
        and all(abs(value) >= 0.15 for value in same_water)
        and (all(value > 0 for value in same_water) or all(value < 0 for value in same_water))
    )
    mean_home = fmean(metrics["all_home_odds"]) if metrics["all_home_odds"] else None
    outlier_count = sum(abs(value - mean_home) >= 0.10 for value in metrics["all_home_odds"]) if mean_home else 0
    scs_tiers = ((mbi.get("modules", {}).get("scs") or {}).get("per_outcome", {}).get("home") or {}).get("tier_scores", {})
    tier_signals = [value for value in scs_tiers.values() if value is not None and value != 0]
    exchange_growth = (mbi.get("modules", {}).get("exchange") or {}).get("volume_growth_ratio", {})
    exchange_spike = any(value is not None and value > 2 for value in exchange_growth.values())

    evaluations = {
        "EA01": (theory - actual >= 0.25 if theory is not None and actual is not None else None, "比分矩阵理论盘与实际盘已比较"),
        "EA03": (draw_change <= -0.08 and actual - theory >= 0.25 if draw_change is not None and actual is not None and theory is not None else None, "平赔与盘差已比较"),
        "EA04": (home_change <= -0.05 and ah_change <= -0.25 if home_change is not None and ah_change is not None else None, "Pinnacle欧亚变动已比较"),
        "EA08": (home_change <= -0.05 and abs(ah_change) < 0.01 if home_change is not None and ah_change is not None else None, "Pinnacle欧亚变动已比较"),
        "EA09": (((home_change < 0 and ah_change < 0) or (home_change > 0 and ah_change > 0)) if home_change is not None and ah_change is not None else None, "欧赔支持方向与亚洲盘深浅已比较"),
        "EA12": (opening >= 1.5 if opening is not None else None, "开盘中位盘口已比较"),
        "EA14": (core_pairwise_diverge if len(metrics["core_lines"]) == 3 else None, "Pinnacle/bet365/澳门三方盘口已比较"),
        "U04": (all(value > 0 for value in tier_signals) or all(value < 0 for value in tier_signals) if len(tier_signals) >= 2 else None, "使用三层SCS方向"),
        "U06": (outlier_count == 1 if mean_home is not None else None, "按30家公司主胜均值检查单点偏离"),
        "U08": (home_change <= -0.05 and ah_change <= -0.25 if home_change is not None and ah_change is not None else None, "同EA04"),
        "U09": (pin_move * bet365_move < 0 if pin_move not in (None, 0) and bet365_move not in (None, 0) else None, "bet365与Pinnacle主胜变化已比较"),
        "U16": (((home_change < 0 and ah_change <= 0) or (home_change > 0 and ah_change >= 0)) if home_change is not None and ah_change is not None else None, "欧亚方向一致性已检查；触发表示未获同向确认"),
        "U17": (metrics["core_line_spread"] <= 0.15 if metrics["core_line_spread"] is not None else None, "三家公司亚洲盘跨度已检查"),
        "U18": (float(probability.get("home") or 0) > 0.75 if probability else None, "Shin主胜概率已检查"),
        "U19": (float(probability.get("draw") or 0) > 0.30 if probability else None, "Shin平局概率已检查"),
        "U20": (float(probability.get("away") or 0) > 0.40 if probability else None, "Shin客胜概率已检查"),
        "U21": (abs(home_change) > 0.15 if home_change is not None else None, "Pinnacle主胜压缩已检查"),
        "U22": (metrics["core_home_odds_spread"] > 0.30 if metrics["core_home_odds_spread"] is not None else None, "三家公司主胜赔率跨度已检查"),
        "U23": (metrics["core_line_spread"] > 0.50 if metrics["core_line_spread"] is not None else None, "三家公司亚洲盘跨度已检查"),
        "U25": (same_water_trigger if all(value is not None for value in same_water) else None, "三家公司主水变化已检查"),
        "U26": (float(mbi.get("consensus", {}).get("current", {}).get("home") or 99) < 1.25, "30家公司主胜均值已检查"),
        "MBI16": (metrics["sharp_asian_line_gap"] >= 0.25 if metrics["sharp_asian_line_gap"] is not None else None, "Sharp与Asian层盘口中位数已比较"),
        "MBI17": (exchange_spike if exchange_growth else None, "使用历史快照成交量增长比"),
    }

    unavailable_reasons = {
        "EA02": "SBO/IBC cid尚未确认", "EA05": "SBO/IBC cid尚未确认", "EA06": "缺结构化基本面反证",
        "EA07": "缺结构化新闻叙事标签", "EA10": "SBO/IBC cid尚未确认", "EA11": "页面无bet365限额",
        "EA13": "缺监管与停盘字段", "EA15": "缺裁判结构化数据", "U01": "缺结构化基本面反证",
        "U02": "历史不足24小时或中间帧不足", "U03": "缺纸面实力量化", "U05": "缺完整首次变动链",
        "U07": "缺最后2小时连续反转序列", "U10": "历史水位帧不足", "U11": "缺叙事标签",
        "U12": "缺停赛战术响应标签", "U13": "缺非法公司监管字段", "U14": "缺裁判数据",
        "U15": "缺新闻事件审计", "U24": "非世界杯首秀字段缺失", "U27": "缺零封和失球结构化数据",
        "U28": "缺天气结构化输入", "MBI18": "缺焦点赛阶段和第三家Sharp确认", "MBI19": "缺Pinnacle连续静止4小时验证"
    }

    results = []
    for rule in registry.get("rules", []):
        rule_id = rule["id"]
        if rule_id in evaluations:
            value, evidence = evaluations[rule_id]
            status = "triggered" if value is True else "not_triggered" if value is False else "not_evaluable"
            reason = evidence if value is not None else "所需字段不足"
        else:
            status = "not_evaluable"
            reason = unavailable_reasons.get(rule_id, "尚未实现可靠自动判定")
        results.append({**rule, "status": status, "reason": reason})

    evaluated = [item for item in results if item["status"] != "not_evaluable"]
    triggered = [item for item in results if item["status"] == "triggered"]
    category_counts = {
        category: sum(item["category"] == category for item in triggered)
        for category in ("A", "B", "C")
    }
    return {
        "registry_version": registry.get("version"),
        "upstream_claimed_total": registry.get("upstream_claimed_total"),
        "defined_total": len(results),
        "unresolved_upstream_rules": registry.get("unresolved_upstream_rules", []),
        "calculation_status": "completed" if len(evaluated) == len(results) and len(results) == registry.get("upstream_claimed_total") else "degraded",
        "evaluated_count": len(evaluated),
        "not_evaluable_count": len(results) - len(evaluated),
        "triggered_count": len(triggered),
        "triggered_by_category": category_counts,
        "triggered": triggered,
        "results": results,
        "metrics": {key: value for key, value in metrics.items() if key not in ("bookmakers", "asian", "all_home_odds")},
    }


def score_six_d(deep: dict, mbi: dict, traps: dict, fundamentals: dict | None = None) -> dict:
    metrics = traps["metrics"]
    fundamentals = fundamentals or {}
    aligned = fundamentals.get("aligned_subfactors")
    total_subfactors = fundamentals.get("total_subfactors")
    d1 = clamp(float(aligned) / float(total_subfactors)) if aligned is not None and total_subfactors else 0.5
    d1_reason = "基本面子因子量化" if aligned is not None and total_subfactors else "shuju/基本面结构化不足，按KB-4取中性0.5"

    gap = float(metrics.get("ah_gap") or 0.5)
    dri = mbi.get("modules", {}).get("dri", {})
    dri_value = dri.get("calibrated") if dri.get("calibrated") is not None else dri.get("raw")
    dri_norm = clamp(float(dri_value or 60) / 60)
    spread_norm = clamp(float(metrics.get("core_line_spread") or 0) / 0.50)
    d2 = clamp(1 - (gap / 0.50 + dri_norm / 2 + spread_norm) / 3)
    d3 = clamp(1 - gap / 0.50)
    d4 = clamp(1 - traps.get("triggered_count", 0) / 4)
    water_sigma = metrics.get("water_sigma")
    draw_probability = float(metrics.get("shin_probabilities", {}).get("draw") or 0.30)
    d5 = clamp(fmean([
        1 - float(water_sigma if water_sigma is not None else 0.08) / 0.08,
        1 - draw_probability / 0.30,
    ]))
    dimensions = {
        "D1": {"score": d1, "weight": 0.25, "reason": d1_reason},
        "D2": {"score": d2, "weight": 0.25, "reason": "盘差、DRI与三公司盘口跨度连续映射"},
        "D3": {"score": d3, "weight": 0.15, "reason": "开盘/实际盘口相对理论盘偏差"},
        "D4": {"score": d4, "weight": 0.15, "reason": "按当前可评估陷阱触发数映射；覆盖不足"},
        "D5": {"score": d5, "weight": 0.20, "reason": "水位离散与Shin平局概率"},
    }
    weighted = sum(item["score"] * item["weight"] for item in dimensions.values()) / sum(item["weight"] for item in dimensions.values())
    legacy = weighted * 6
    if legacy >= 4.5:
        action = "confidence_plus_3pp"
    elif legacy >= 3.0:
        action = "neutral"
    elif legacy >= 2.0:
        action = "confidence_minus_3pp"
    else:
        action = "skip"
    return {
        "calculation_status": "completed" if d1_reason == "基本面子因子量化" and traps.get("calculation_status") == "completed" and dri.get("calibrated") is not None else "degraded",
        "dimensions": dimensions,
        "weighted_0_to_1": weighted,
        "legacy_0_to_6": legacy,
        "action": action,
        "limitations": [
            reason for condition, reason in (
                (d1_reason != "基本面子因子量化", "D1使用中性值"),
                (dri.get("calibrated") is None, "D2使用未校准DRI"),
                (traps.get("calculation_status") != "completed", "D4陷阱覆盖不完整"),
            ) if condition
        ],
    }


def analyze(deep: dict, mbi: dict, registry: dict, fundamentals: dict | None = None, model: dict | None = None) -> dict:
    traps = evaluate_traps(deep, mbi, registry, model)
    six_d = score_six_d(deep, mbi, traps, fundamentals)
    return {"traps": traps, "six_d": six_d}


def main() -> int:
    parser = argparse.ArgumentParser(description="执行陷阱注册表和连续6D评分")
    parser.add_argument("--deep-json", required=True)
    parser.add_argument("--mbi-json", required=True)
    parser.add_argument("--rules", default=str(DEFAULT_RULES))
    parser.add_argument("--fundamentals-json")
    parser.add_argument("--model-json", help="包含lambda_home/lambda_away/rho的模型JSON，或含model对象的分析JSON")
    parser.add_argument("--output")
    args = parser.parse_args()
    fundamentals = load_json(Path(args.fundamentals_json)) if args.fundamentals_json else None
    model = load_json(Path(args.model_json)) if args.model_json else None
    result = analyze(load_json(Path(args.deep_json)), load_json(Path(args.mbi_json)), load_json(Path(args.rules)), fundamentals, model)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
