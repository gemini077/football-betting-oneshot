#!/usr/bin/env python3
"""Frozen-snapshot market and simple-Poisson benchmark baselines.

This module deliberately has no dependency on the Champion implementation.  A
caller passes one already-frozen pre-match snapshot and receives an auditable
baseline result carrying the snapshot identity fields unchanged.
"""

from __future__ import annotations

import math
from typing import Any

from market_engine import MARKET_REFERENCE_VERSION, SNAPSHOT_FIELDS, build_market_reference
from score_engine import (
    btts_yes_probability,
    independent_poisson_score_rows,
    outcome_probabilities,
    total_goal_distribution,
)

SIMPLE_POISSON_VERSION = "simple_poisson.v1"
MIN_LAMBDA = 0.15
MAX_LAMBDA = 4.0
MAX_GOALS_PER_TEAM = 12
def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {field: snapshot.get(field) for field in SNAPSHOT_FIELDS}


def _with_metadata(result: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {**_metadata(snapshot), **result}


def _model_input(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Read the exact deterministic input for formal benchmark snapshots."""
    nested = snapshot.get("model_input")
    return nested if isinstance(nested, dict) else snapshot


def _recent_form(snapshot: dict[str, Any]) -> dict[str, Any]:
    source = _model_input(snapshot)
    source_snapshots = source.get("source_snapshots")
    if isinstance(source_snapshots, dict):
        for provider_name in ("nowscore", "500_deep"):
            provider = source_snapshots.get(provider_name)
            if not isinstance(provider, dict):
                continue
            rows = provider.get("snapshots")
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    shuju = row.get("shuju")
                    nested = shuju.get("recent_form") if isinstance(shuju, dict) else None
                    if isinstance(nested, dict):
                        return nested
    prematch = source.get("prematch_fundamentals")
    if isinstance(prematch, dict) and isinstance(prematch.get("recent_form"), dict):
        return prematch["recent_form"]

    # Legacy flattened snapshots remain available to unit tests/research CLI.
    candidates = [snapshot]
    for key in ("prematch_fundamentals", "input", "projection"):
        value = snapshot.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        direct = candidate.get("recent_form")
        if isinstance(direct, dict):
            return direct
        shuju = candidate.get("shuju")
        nested = shuju.get("recent_form") if isinstance(shuju, dict) else None
        if isinstance(nested, dict):
            return nested
    return {}


def _valid_form_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    matches = _number(row.get("matches"))
    goals_for = _number(row.get("goals_for"))
    goals_against = _number(row.get("goals_against"))
    return bool(
        matches is not None and matches > 0
        and goals_for is not None and goals_for >= 0
        and goals_against is not None and goals_against >= 0
    )


def build_simple_poisson_baseline(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build the fixed independent-Poisson baseline from recent goals only."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")

    form = _recent_form(snapshot)
    home_venue = form.get("home_home")
    away_venue = form.get("away_away")
    home_overall = form.get("home_overall")
    away_overall = form.get("away_overall")
    home_venue_valid = _valid_form_row(home_venue)
    away_venue_valid = _valid_form_row(away_venue)
    home_overall_valid = _valid_form_row(home_overall)
    away_overall_valid = _valid_form_row(away_overall)
    home_source = "home_home" if home_venue_valid else "home_overall" if home_overall_valid else None
    away_source = "away_away" if away_venue_valid else "away_overall" if away_overall_valid else None
    home = home_venue if home_source == "home_home" else home_overall if home_source == "home_overall" else None
    away = away_venue if away_source == "away_away" else away_overall if away_source == "away_overall" else None
    if home_source == "home_home" and away_source == "away_away":
        input_source = "venue"
    elif home_source == "home_overall" and away_source == "away_overall":
        input_source = "overall_fallback"
    else:
        input_source = "mixed"

    result: dict[str, Any] = {
        "model": "simple_poisson",
        "version": SIMPLE_POISSON_VERSION,
        "status": "not_evaluable",
        "reason": "insufficient_recent_form",
        "input_source": input_source,
        "input_sources": {"home": home_source, "away": away_source},
        "simple_evaluable": False,
        "simple_missing_reason": "insufficient_recent_form",
        "lambda_home": None,
        "lambda_away": None,
        "expected_goals": None,
        "rho": 0.0,
        "probabilities": None,
        "outcome_probabilities": None,
        "btts": None,
        "total_goals_distribution": [],
        "score_matrix": [],
        "score_probabilities": [],
        "score_matrix_by_score": {},
        "score_matrix_complete": False,
        "top1": None,
        "top3": [],
        "top5": [],
        "score_top1": None,
        "score_top3": [],
        "score_top5": [],
        "market_read": False,
        "champion_read": False,
    }
    if home is None or away is None:
        return _with_metadata(result, snapshot)

    home_attack = float(home["goals_for"]) / float(home["matches"])
    away_defence = float(away["goals_against"]) / float(away["matches"])
    away_attack = float(away["goals_for"]) / float(away["matches"])
    home_defence = float(home["goals_against"]) / float(home["matches"])
    lambda_home = (home_attack + away_defence) / 2.0
    lambda_away = (away_attack + home_defence) / 2.0
    result.update({
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "rate_inputs": {
            "home_attack": home_attack,
            "away_defence": away_defence,
            "away_attack": away_attack,
            "home_defence": home_defence,
        },
    })
    if not all(MIN_LAMBDA <= value <= MAX_LAMBDA for value in (lambda_home, lambda_away)):
        result["reason"] = "lambda_out_of_bounds"
        result["simple_missing_reason"] = "lambda_out_of_bounds"
        return _with_metadata(result, snapshot)

    matrix = independent_poisson_score_rows(
        lambda_home,
        lambda_away,
        max_goals_per_team=MAX_GOALS_PER_TEAM,
    )
    matrix_map = {
        (int(row["home_goals"]), int(row["away_goals"])): float(row["probability"])
        for row in matrix
    }
    probabilities = outcome_probabilities(matrix_map)
    total_distribution = total_goal_distribution(matrix)
    btts_yes = btts_yes_probability(matrix_map)
    result.update({
        "status": "evaluable",
        "reason": None,
        "simple_evaluable": True,
        "simple_missing_reason": None,
        "expected_goals": {"home": lambda_home, "away": lambda_away, "total": lambda_home + lambda_away},
        "probabilities": probabilities,
        "outcome_probabilities": probabilities,
        "btts": {"yes": btts_yes, "no": 1.0 - btts_yes},
        "total_goals_distribution": total_distribution,
        "score_matrix": matrix,
        "score_probabilities": matrix,
        "score_matrix_by_score": {row["score"]: row["probability"] for row in matrix},
        "score_matrix_complete": True,
        "top1": matrix[0],
        "top3": matrix[:3],
        "top5": matrix[:5],
        "score_top1": matrix[0],
        "score_top3": matrix[:3],
        "score_top5": matrix[:5],
    })
    return _with_metadata(result, snapshot)


# Descriptive aliases keep the public surface discoverable for callers that
# use the noun rather than the ``build_`` verb.
market_reference = build_market_reference
simple_poisson_baseline = build_simple_poisson_baseline
