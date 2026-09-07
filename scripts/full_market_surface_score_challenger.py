#!/usr/bin/env python3
"""Research-only full-market-surface score challenger.

This route reuses the accepted #189 market snapshot reader, quote parsing,
de-vig and quarter-line settlement contract.  It fits one bounded pair of
independent-Poisson intensities from the frozen 1X2, O/U and AH surfaces.  All
historical outcome access happens after every market projection is frozen.
The module never writes Champion, C, serving, UI, ledger, result or snapshot
truth.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from market_contracts import split_quarter_line  # noqa: E402
from market_implied_score_baseline_audit import (  # noqa: E402
    AuditError,
    _champion_probabilities,
    _champion_score_list,
    _identity_key,
    _ledger_keys,
    _load_snapshot_for_record,
    _metric_row,
    _number,
    _repo_relative,
    _score_rank,
    _score_pair,
    _summary_numbers,
    _text,
    actual_outcome,
    build_market_baseline,
    canonical_json,
    champion_btts_probability,
    extract_1x2_quotes,
    extract_ah_quotes,
    extract_ou_quotes,
    independent_score_matrix,
    load_prediction_rows,
    load_verified_results,
    load_legal_market_snapshot,
    proportional_devig,
    select_unique_legal_versions,
    score_text,
    fair_probability_from_matrix,
    _verified_result_for_record,
)
from model_governance import DEFAULT_INPUT_SNAPSHOT_ROOT  # noqa: E402


MILESTONE = "FULL-MARKET-SURFACE-SCORE-CHALLENGER-1"
SCHEMA_VERSION = "full_market_surface_score_challenger_1.v1"
MODEL_FAMILY = "full_market_surface_score_v1"
OUTPUT_ROOT = ROOT / "data" / "prediction_quality" / "full_market_surface_score_challenger_1"
DEFAULT_SUMMARY = OUTPUT_ROOT / "summary.json"
DEFAULT_MODEL = OUTPUT_ROOT / "model.json"
DEFAULT_SHADOW = OUTPUT_ROOT / "latest.json"
DEFAULT_REPORT = OUTPUT_ROOT / "report.md"
DEFAULT_PROSPECTIVE_AFTER = datetime(2026, 9, 7, 14, 0, tzinfo=timezone(timedelta(hours=8)))

OUTCOMES = ("home", "draw", "away")
EPSILON = 1e-12
MAX_GOALS = 20
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_SEED = 230

# Fixed before any result is loaded.  These bounds are a solver contract, not
# fitted calibration parameters.  The total domain follows the accepted #189
# O/U domain; the share domain follows its bounded home/away split.
SOLVER_VERSION = "full_market_surface_coarse_to_fine_v1"
SOLVER_SETTINGS = {
    "lambda_total_lower": 0.001,
    "lambda_total_upper": 20.0,
    "home_share_lower": 0.01,
    "home_share_upper": 0.99,
    "coarse_total_points": 13,
    "coarse_share_points": 11,
    "refinement_levels": 2,
    "refinement_points": 5,
    "tie_break": "(loss, lambda_total, home_share)",
    "matrix_max_goals": MAX_GOALS,
    "rho": 0.0,
    "objective": "mean(1X2 residual^2) + mean(O/U residual^2) + mean(AH residual^2)",
}

MODEL_CONTRACT = {
    "model_family": MODEL_FAMILY,
    "solver_version": SOLVER_VERSION,
    "solver_settings": SOLVER_SETTINGS,
    "market_surface": ["1X2", "O/U", "Asian Handicap"],
    "market_snapshot_contract": "accepted_issue_189_frozen_prematch_snapshot",
    "de_vig": "accepted_issue_189_proportional_inverse_odds_per_quote_row",
    "settlement": "accepted_issue_189_split_quarter_line_win_loss_probability",
    "score_distribution": "independent_poisson_rho_0_normalized_finite_0_to_20_grid",
    "objective_family_balance": "each family mean is one additive block; quote count cannot change family weight",
    "outcome_access": "all market projections frozen before verified result loader is called",
    "result_tuning": False,
    "automatic_promotion": False,
    "production_enabled": False,
}


class FullMarketSurfaceBlocked(RuntimeError):
    """Raised when the fixed market-surface authority is not available."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_sha256(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mean(values: Iterable[float]) -> float | None:
    clean = [float(value) for value in values if _number(value) is not None]
    return statistics.fmean(clean) if clean else None


def _quantile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if _number(value) is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    left, right = math.floor(position), math.ceil(position)
    if left == right:
        return ordered[left]
    weight = position - left
    return ordered[left] * (1.0 - weight) + ordered[right] * weight


def _grid(lower: float, upper: float, points: int) -> list[float]:
    if points < 2 or upper < lower:
        raise FullMarketSurfaceBlocked("SOLVER_GRID_CONTRACT_INVALID")
    return [lower + (upper - lower) * index / (points - 1) for index in range(points)]


def _matrix_rows(matrix: Mapping[tuple[int, int], float]) -> list[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "score": score_text(score),
            "home_goals": score[0],
            "away_goals": score[1],
            "probability": round(float(probability), 12),
        }
        for rank, (score, probability) in enumerate(
            sorted(matrix.items(), key=lambda item: (-float(item[1]), item[0][0], item[0][1])),
            start=1,
        )
    ]


def _distributions(matrix: Mapping[tuple[int, int], float]) -> dict[str, Any]:
    outcomes = {key: 0.0 for key in OUTCOMES}
    totals: dict[int, float] = defaultdict(float)
    differences: dict[int, float] = defaultdict(float)
    btts_yes = 0.0
    for (home, away), probability in matrix.items():
        value = float(probability)
        outcomes[actual_outcome((home, away))] += value
        totals[home + away] += value
        differences[home - away] += value
        if home > 0 and away > 0:
            btts_yes += value
    return {
        "1x2": outcomes,
        "totals": dict(totals),
        "differences": dict(differences),
        "btts_yes": btts_yes,
    }


def _fair_from_distribution(
    distribution: Mapping[int, float],
    line: float,
    selection: str,
    *,
    family: str = "total",
) -> float:
    win = 0.0
    loss = 0.0
    components = split_quarter_line(float(line))
    for component in components:
        for value, probability in distribution.items():
            if family == "asian_handicap":
                delta = float(value) + component
            elif family == "total":
                delta = float(value) - component
            else:
                raise AuditError("UNSUPPORTED_SETTLEMENT_FAMILY")
            if selection == "under" or selection == "away":
                delta = -delta
            if delta > 1e-9:
                win += float(probability) / len(components)
            elif delta < -1e-9:
                loss += float(probability) / len(components)
    denominator = win + loss
    if win <= EPSILON or loss <= EPSILON or denominator <= EPSILON:
        raise AuditError("SETTLEMENT_PRICE_NOT_IDENTIFIABLE")
    return win / denominator


def _family_targets(one_x2: Mapping[str, Any], ou: Mapping[str, Any], ah: Mapping[str, Any]) -> dict[str, Any]:
    if one_x2.get("reason"):
        raise FullMarketSurfaceBlocked(str(one_x2["reason"]))
    if ou.get("reason"):
        raise FullMarketSurfaceBlocked(str(ou["reason"]))
    if ah.get("reason"):
        raise FullMarketSurfaceBlocked(str(ah["reason"]))
    if not one_x2.get("valid") or not ou.get("valid") or not ah.get("valid"):
        raise FullMarketSurfaceBlocked("FULL_MARKET_SURFACE_FAMILY_EMPTY")
    return {
        "1x2": {key: float((one_x2.get("consensus") or {})[key]) for key in OUTCOMES},
        "ou": [
            {"line": float(row["line"]), "selection": "over", "target": float(row["fair_first_probability"]), "bookmaker": row["bookmaker"]}
            for row in ou["valid"]
        ],
        "ah": [
            {"line": float(row["line"]), "selection": "home", "target": float(row["fair_first_probability"]), "bookmaker": row["bookmaker"]}
            for row in ah["valid"]
        ],
    }


def _market_surface_digest(one_x2: Mapping[str, Any], ou: Mapping[str, Any], ah: Mapping[str, Any]) -> str:
    return _json_sha256({"1x2": one_x2.get("valid") or [], "ou": ou.get("valid") or [], "ah": ah.get("valid") or []})


def _candidate_projection(lambda_total: float, home_share: float) -> tuple[dict[str, Any], dict[str, Any]]:
    lambda_home = float(lambda_total) * float(home_share)
    lambda_away = float(lambda_total) * (1.0 - float(home_share))
    matrix, tail = independent_score_matrix(lambda_home, lambda_away, max_goals=MAX_GOALS)
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_total,
        "rho": 0.0,
        "matrix": matrix,
        "tail": tail,
    }, _distributions(matrix)


def _objective_for_projection(projection: Mapping[str, Any], distributions: Mapping[str, Any], targets: Mapping[str, Any]) -> dict[str, Any]:
    residuals: dict[str, list[float]] = {"1x2": [], "ou": [], "ah": []}
    modeled_1x2 = distributions["1x2"]
    for key in OUTCOMES:
        residuals["1x2"].append(float(modeled_1x2[key]) - float(targets["1x2"][key]))
    modeled_lines: dict[tuple[str, float, str], float] = {}
    for row in targets["ou"]:
        cache_key = ("ou", row["line"], row["selection"])
        if cache_key not in modeled_lines:
            modeled_lines[cache_key] = _fair_from_distribution(distributions["totals"], row["line"], row["selection"])
        modeled = modeled_lines[cache_key]
        residuals["ou"].append(modeled - float(row["target"]))
    for row in targets["ah"]:
        cache_key = ("ah", row["line"], row["selection"])
        if cache_key not in modeled_lines:
            modeled_lines[cache_key] = _fair_from_distribution(
                distributions["differences"], row["line"], row["selection"], family="asian_handicap"
            )
        modeled = modeled_lines[cache_key]
        residuals["ah"].append(modeled - float(row["target"]))
    family_losses = {family: statistics.fmean(value * value for value in values) for family, values in residuals.items()}
    return {
        "loss": sum(family_losses.values()),
        "family_losses": family_losses,
        "family_residuals": residuals,
        "family_quote_counts": {"1x2": len(residuals["1x2"]), "ou": len(residuals["ou"]), "ah": len(residuals["ah"])},
        "modeled_1x2": dict(modeled_1x2),
        "lambda_home": projection["lambda_home"],
        "lambda_away": projection["lambda_away"],
        "lambda_total": projection["lambda_total"],
    }


def solve_full_market_surface(one_x2: Mapping[str, Any], ou: Mapping[str, Any], ah: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic bounded market-only solver; inputs contain no outcomes."""
    targets = _family_targets(one_x2, ou, ah)
    lower_total = float(SOLVER_SETTINGS["lambda_total_lower"])
    upper_total = float(SOLVER_SETTINGS["lambda_total_upper"])
    lower_share = float(SOLVER_SETTINGS["home_share_lower"])
    upper_share = float(SOLVER_SETTINGS["home_share_upper"])
    candidates: list[tuple[float, float, float, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    def evaluate(total: float, share: float) -> None:
        projection, distributions = _candidate_projection(total, share)
        try:
            objective = _objective_for_projection(projection, distributions, targets)
        except AuditError as exc:
            # A bounded candidate can put effectively zero mass on one side
            # of an extreme integer line.  That candidate is not an
            # identifiable settlement projection; skip it and let the fixed
            # grid choose among identifiable candidates.  If every candidate
            # is skipped, ``best`` fails closed with SOLVER_NO_CANDIDATE.
            if str(exc) != "SETTLEMENT_PRICE_NOT_IDENTIFIABLE":
                raise
            return
        candidates.append((float(objective["loss"]), float(total), float(share), projection, distributions, objective))

    def best() -> tuple[float, float, float, dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not candidates:
            raise FullMarketSurfaceBlocked("SOLVER_NO_CANDIDATE")
        return min(candidates, key=lambda item: (item[0], item[1], item[2]))

    for total in _grid(lower_total, upper_total, int(SOLVER_SETTINGS["coarse_total_points"])):
        for share in _grid(lower_share, upper_share, int(SOLVER_SETTINGS["coarse_share_points"])):
            evaluate(total, share)

    current = best()
    total_span = (upper_total - lower_total) / (int(SOLVER_SETTINGS["coarse_total_points"]) - 1)
    share_span = (upper_share - lower_share) / (int(SOLVER_SETTINGS["coarse_share_points"]) - 1)
    for _ in range(int(SOLVER_SETTINGS["refinement_levels"])):
        total_span /= 3.0
        share_span /= 3.0
        total_low = max(lower_total, current[1] - total_span)
        total_high = min(upper_total, current[1] + total_span)
        share_low = max(lower_share, current[2] - share_span)
        share_high = min(upper_share, current[2] + share_span)
        for total in _grid(total_low, total_high, int(SOLVER_SETTINGS["refinement_points"])):
            for share in _grid(share_low, share_high, int(SOLVER_SETTINGS["refinement_points"])):
                evaluate(total, share)
        current = best()

    loss, total, share, projection, distributions, objective = current
    projection_output = _projection_output(projection, distributions)
    return {
        "status": "EVALUABLE",
        "solver_version": SOLVER_VERSION,
        "solver_settings": SOLVER_SETTINGS,
        "targets": {
            "1x2": targets["1x2"],
            "ou_quote_count": len(targets["ou"]),
            "ah_quote_count": len(targets["ah"]),
        },
        "lambda_home": round(float(projection["lambda_home"]), 12),
        "lambda_away": round(float(projection["lambda_away"]), 12),
        "lambda_total": round(float(projection["lambda_total"]), 12),
        "home_share": round(float(share), 12),
        "loss": round(float(loss), 12),
        "family_losses": {key: round(float(value), 12) for key, value in objective["family_losses"].items()},
        "family_residuals": objective["family_residuals"],
        "family_quote_counts": objective["family_quote_counts"],
        "evaluated_candidates": len(candidates),
        "projection": projection_output,
        "market_surface_digest": _market_surface_digest(one_x2, ou, ah),
    }


def _handicap_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for line in (-1.0, -0.5, 0.0, 0.5, 1.0):
        result = {"home": {"win": 0.0, "push": 0.0, "loss": 0.0}, "away": {"win": 0.0, "push": 0.0, "loss": 0.0}}
        for (home, away), probability in matrix.items():
            for selection in ("home", "away"):
                parts = split_quarter_line(line)
                units: list[float] = []
                for component in parts:
                    delta = home - away + component
                    if selection == "away":
                        delta = -delta
                    units.append(1.0 if delta > 1e-9 else 0.0 if abs(delta) <= 1e-9 else -1.0)
                average = sum(units) / len(units)
                label = "win" if average > 0 else "push" if average == 0 else "loss"
                result[selection][label] += float(probability)
        output[str(line)] = result
    return output


def _projection_output(projection: Mapping[str, Any], distributions: Mapping[str, Any]) -> dict[str, Any]:
    matrix = projection["matrix"]
    rows = _matrix_rows(matrix)
    btts_yes = float(distributions["btts_yes"])
    total_distribution = {str(key): round(float(value), 12) for key, value in sorted(distributions["totals"].items())}
    return {
        "lambda_home": round(float(projection["lambda_home"]), 12),
        "lambda_away": round(float(projection["lambda_away"]), 12),
        "lambda_total": round(float(projection["lambda_total"]), 12),
        "rho": 0.0,
        "score_matrix": rows,
        "score_matrix_tail_probability": round(float(projection["tail"]), 12),
        "score_matrix_normalization": {
            "max_goals": MAX_GOALS,
            "represented_probability_sum": round(sum(float(value) for value in matrix.values()), 12),
            "finite_grid_raw_mass": round(1.0 - float(projection["tail"]), 12),
            "tail_semantics": "omitted raw independent-Poisson mass outside explicit finite grid",
        },
        "exact_top1": rows[0]["score"] if rows else None,
        "exact_top3": [row["score"] for row in rows[:3]],
        "exact_top5": [row["score"] for row in rows[:5]],
        "derived_markets": {
            "1x2": {key: round(float(value), 12) for key, value in distributions["1x2"].items()},
            "totals": {
                "distribution": total_distribution,
                "over_2_5": round(sum(value for key, value in distributions["totals"].items() if key >= 3), 12),
                "under_2_5": round(sum(value for key, value in distributions["totals"].items() if key <= 2), 12),
            },
            "btts": {"yes": round(btts_yes, 12), "no": round(1.0 - btts_yes, 12)},
            "handicap": _handicap_probabilities(matrix),
        },
    }


def _quote_family_metadata(one_x2: Mapping[str, Any], ou: Mapping[str, Any], ah: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "1x2": {"raw_count": one_x2.get("raw_row_count", 0), "valid_count": one_x2.get("valid_bookmaker_count", 0), "digest": _json_sha256(one_x2.get("valid") or [])},
        "ou": {"raw_count": ou.get("raw_row_count", 0), "valid_count": ou.get("valid_bookmaker_count", 0), "digest": _json_sha256(ou.get("valid") or [])},
        "ah": {"raw_count": ah.get("raw_row_count", 0), "valid_count": ah.get("valid_bookmaker_count", 0), "digest": _json_sha256(ah.get("valid") or [])},
        "surface_digest": _market_surface_digest(one_x2, ou, ah),
    }


def _frozen_observation(record: Mapping[str, Any]) -> dict[str, Any]:
    snapshot, snapshot_error = _load_snapshot_for_record(record, DEFAULT_INPUT_SNAPSHOT_ROOT)
    legal = load_legal_market_snapshot(record, snapshot)
    if legal.get("snapshot") is None:
        return {
            "match_key": _identity_key(record),
            "record": dict(record),
            "snapshot": None,
            "snapshot_error": snapshot_error or legal.get("reason"),
            "source": legal.get("source"),
            "captured_at": legal.get("captured_at"),
            "one_x2": {"reason": "NO_LEGAL_SNAPSHOT"},
            "ou": {"reason": "NO_LEGAL_SNAPSHOT"},
            "ah": {"reason": "NO_LEGAL_SNAPSHOT"},
            "baseline": {"status": "NOT_EVALUABLE", "reason": legal.get("reason") or snapshot_error},
            "challenger": {"status": "NOT_EVALUABLE", "reason": legal.get("reason") or snapshot_error},
        }
    chosen = legal["snapshot"]
    one_x2 = extract_1x2_quotes(chosen)
    ou = extract_ou_quotes(chosen)
    ah = extract_ah_quotes(chosen)
    try:
        baseline = build_market_baseline(one_x2, ou)
    except (AuditError, ValueError) as error:
        baseline = {"status": "NOT_EVALUABLE", "reason": f"BASELINE:{type(error).__name__}:{error}"}
    try:
        challenger = solve_full_market_surface(one_x2, ou, ah)
    except (AuditError, FullMarketSurfaceBlocked, ValueError) as error:
        challenger = {"status": "NOT_EVALUABLE", "reason": f"FULL_SURFACE:{type(error).__name__}:{error}"}
    return {
        "match_key": _identity_key(record),
        "record": dict(record),
        "snapshot": chosen,
        "snapshot_error": snapshot_error,
        "source": legal.get("source"),
        "captured_at": legal.get("captured_at"),
        "one_x2": one_x2,
        "ou": ou,
        "ah": ah,
        "quote_families": _quote_family_metadata(one_x2, ou, ah),
        "baseline": baseline,
        "challenger": challenger,
    }


def _bootstrap(values: Sequence[float], seed: int) -> dict[str, Any]:
    clean = [float(value) for value in values if _number(value) is not None]
    if not clean:
        return {"n": 0, "point": None, "ci95": [None, None], "iterations": 0, "seed": seed}
    rng = random.Random(seed)
    samples = [statistics.fmean(clean[rng.randrange(len(clean))] for _ in clean) for _ in range(BOOTSTRAP_ITERATIONS)]
    return {"n": len(clean), "point": statistics.fmean(clean), "ci95": [_quantile(samples, 0.025), _quantile(samples, 0.975)], "iterations": BOOTSTRAP_ITERATIONS, "seed": seed}


def _paired_interval(new_values: Sequence[float], baseline_values: Sequence[float], *, lower_is_better: bool, seed: int) -> dict[str, Any]:
    pairs = [(float(new), float(base)) for new, base in zip(new_values, baseline_values) if _number(new) is not None and _number(base) is not None]
    new = [item[0] for item in pairs]
    base = [item[1] for item in pairs]
    delta = [left - right for left, right in pairs]
    delta_stat = _bootstrap(delta, seed)
    point = delta_stat["point"]
    ci = delta_stat["ci95"]
    if point is None or ci[0] is None or ci[1] is None or ci[0] <= 0.0 <= ci[1]:
        decision = "NEITHER_ESTABLISHED"
    elif lower_is_better:
        decision = "FULL_SURFACE_BETTER" if point < 0 else "MARKET_BASELINE_BETTER"
    else:
        decision = "FULL_SURFACE_BETTER" if point > 0 else "MARKET_BASELINE_BETTER"
    return {
        "new": _bootstrap(new, seed + 1),
        "baseline": _bootstrap(base, seed + 2),
        "paired_delta_new_minus_baseline": delta_stat,
        "lower_is_better": lower_is_better,
        "decision": decision,
    }


def _rps(probabilities: Mapping[str, float], actual: str) -> float:
    predicted = 0.0
    observed = 0.0
    value = 0.0
    for key in OUTCOMES[:-1]:
        predicted += float(probabilities[key])
        observed += float(key == actual)
        value += (predicted - observed) ** 2
    return value / 2.0


def _model_metric_row(observation: Mapping[str, Any], result: Mapping[str, Any], model_key: str) -> dict[str, Any] | None:
    model = observation.get(model_key) or {}
    if model.get("status") != "EVALUABLE":
        return None
    projection = model["projection"]
    actual = (int(result["home_score_90m"]), int(result["away_score_90m"]))
    actual_text = score_text(actual)
    if model_key == "baseline":
        matrix = {tuple(score): float(probability) for score, probability in (projection.get("matrix") or {}).items()}
        ordered = [score_text(tuple(score)) for score, _ in sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))]
        probabilities = projection["probabilities"]
        over_2_5 = projection["total_over_2_5"]
        btts_yes = projection["btts_yes"]
        lambda_home = projection["lambda_home"]
        lambda_away = projection["lambda_away"]
        lambda_total = projection["lambda_total"]
        family_residuals = {
            "1x2": [float(probabilities[key]) - float((observation["one_x2"].get("consensus") or {})[key]) for key in OUTCOMES],
            "ou": [],
            "ah": [],
        }
        for quote in observation["ou"].get("valid") or []:
            try:
                family_residuals["ou"].append(fair_probability_from_matrix(matrix, float(quote["line"]), "total", "over") - float(quote["fair_first_probability"]))
            except AuditError:
                continue
        for quote in observation["ah"].get("valid") or []:
            try:
                family_residuals["ah"].append(fair_probability_from_matrix(matrix, float(quote["line"]), "asian_handicap", "home") - float(quote["fair_first_probability"]))
            except AuditError:
                continue
    else:
        matrix = {(row["home_goals"], row["away_goals"]): float(row["probability"]) for row in projection["score_matrix"]}
        ordered = [row["score"] for row in projection["score_matrix"]]
        probabilities = projection["derived_markets"]["1x2"]
        over_2_5 = projection["derived_markets"]["totals"]["over_2_5"]
        btts_yes = projection["derived_markets"]["btts"]["yes"]
        lambda_home = model["lambda_home"]
        lambda_away = model["lambda_away"]
        lambda_total = model["lambda_total"]
        family_residuals = model.get("family_residuals") or {}
    outcome = actual_outcome(actual)
    actual_probability = matrix.get(actual, 0.0)
    total_actual = sum(actual)
    btts_actual = actual[0] > 0 and actual[1] > 0
    over_actual = total_actual >= 3
    return {
        "match_key": observation["match_key"],
        "actual_score": actual_text,
        "actual_outcome": outcome,
        "actual_score_in_support": actual in matrix,
        "actual_score_rank": ordered.index(actual_text) + 1 if actual_text in ordered else None,
        "exact_nll": -math.log(max(actual_probability, EPSILON)),
        "exact_top1": int(actual_text == ordered[0]) if ordered else 0,
        "exact_top3": int(actual_text in ordered[:3]),
        "exact_top5": int(actual_text in ordered[:5]),
        "actual_score_probability": actual_probability,
        "ft_1x2_log_loss": -math.log(max(float(probabilities[outcome]), EPSILON)),
        "ft_1x2_brier": sum((float(probabilities[key]) - float(key == outcome)) ** 2 for key in OUTCOMES),
        "ft_1x2_rps": _rps(probabilities, outcome),
        "ou_2_5_brier": (float(over_2_5) - float(over_actual)) ** 2,
        "btts_brier": (float(btts_yes) - float(btts_actual)) ** 2,
        "home_lambda": float(lambda_home),
        "away_lambda": float(lambda_away),
        "total_lambda": float(lambda_total),
        "actual_home_goals": actual[0],
        "actual_away_goals": actual[1],
        "actual_total_goals": total_actual,
        "actual_one_one": int(actual == (1, 1)),
        "top_score_one_one": int(ordered[0] == "1-1") if ordered else 0,
        "family_residuals": family_residuals,
        "loss": _number(model.get("loss")),
    }


def _metric_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}

    def mean(key: str) -> float | None:
        return _mean(float(row[key]) for row in rows if _number(row.get(key)) is not None)

    def calibration(actual_key: str, lambda_key: str) -> dict[str, Any]:
        actual = [float(row[actual_key]) for row in rows]
        predicted = [float(row[lambda_key]) for row in rows]
        return {
            "observed_mean": _mean(actual),
            "predicted_mean": _mean(predicted),
            "bias_observed_minus_predicted": _mean(a - p for a, p in zip(actual, predicted)),
            "mae": _mean(abs(a - p) for a, p in zip(actual, predicted)),
        }

    return {
        "n": len(rows),
        "exact_nll": mean("exact_nll"),
        "exact_top1": mean("exact_top1"),
        "exact_top3": mean("exact_top3"),
        "exact_top5": mean("exact_top5"),
        "full_actual_score_rank": mean("actual_score_rank"),
        "mean_actual_score_probability": mean("actual_score_probability"),
        "ft_1x2_log_loss": mean("ft_1x2_log_loss"),
        "ft_1x2_brier": mean("ft_1x2_brier"),
        "ft_1x2_rps": mean("ft_1x2_rps"),
        "ou_2_5_brier": mean("ou_2_5_brier"),
        "btts_brier": mean("btts_brier"),
        "lambda_calibration": {
            "home": calibration("actual_home_goals", "home_lambda"),
            "away": calibration("actual_away_goals", "away_lambda"),
            "total": calibration("actual_total_goals", "total_lambda"),
        },
        "one_one_actual_rate": mean("actual_one_one"),
        "one_one_top_score_share": mean("top_score_one_one"),
        "actual_score_out_of_support": sum(not row["actual_score_in_support"] for row in rows),
        "family_reconstruction_residuals": {
            family: _summary_numbers(value)
            for family in ("1x2", "ou", "ah")
            for value in []
        },
    }


def _add_family_residual_summary(summary: dict[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    for family in ("1x2", "ou", "ah"):
        values = [abs(float(residual)) for row in rows for residual in (row.get("family_residuals") or {}).get(family, [])]
        summary.setdefault("family_reconstruction_residuals", {})[family] = _summary_numbers(values)


def _paired_scorecard(metric_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    common = sorted({row["match_key"] for row in metric_rows.get("baseline", ())} & {row["match_key"] for row in metric_rows.get("challenger", ())})
    baseline_by_key = {row["match_key"]: row for row in metric_rows.get("baseline", ())}
    challenger_by_key = {row["match_key"]: row for row in metric_rows.get("challenger", ())}
    pairs = [(challenger_by_key[key], baseline_by_key[key]) for key in common]
    metrics = {
        "exact_nll": True,
        "actual_score_rank": True,
        "ft_1x2_log_loss": True,
        "ft_1x2_brier": True,
        "ft_1x2_rps": True,
        "ou_2_5_brier": True,
        "btts_brier": True,
        "exact_top1": False,
        "exact_top3": False,
        "exact_top5": False,
    }
    output: dict[str, Any] = {"paired_unique_match_n": len(pairs), "metrics": {}}
    for index, (key, lower_is_better) in enumerate(metrics.items()):
        new_values = [float(new[key]) for new, _ in pairs if _number(new.get(key)) is not None and _number(_[key]) is not None]
        base_values = [float(base[key]) for new, base in pairs if _number(new.get(key)) is not None and _number(base.get(key)) is not None]
        output["metrics"][key] = _paired_interval(new_values, base_values, lower_is_better=lower_is_better, seed=BOOTSTRAP_SEED + index * 10)
    return output


def _control_metric_rows(observations: Sequence[Mapping[str, Any]], results_by_key: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    controls: dict[str, list[dict[str, Any]]] = {"champion": [], "challenger_c": []}
    for observation in observations:
        result = results_by_key.get(observation["match_key"])
        if result is None:
            continue
        record = observation["record"]
        actual = (int(result["home_score_90m"]), int(result["away_score_90m"]))
        actual_outcome_value = actual_outcome(actual)
        probabilities = _champion_probabilities(record)
        if probabilities is not None:
            scores = _champion_score_list(record, "score_top1") + _champion_score_list(record, "score_top3") + _champion_score_list(record, "score_top5")
            controls["champion"].append({
                "match_key": observation["match_key"],
                "ft_1x2_log_loss": -math.log(max(float(probabilities[actual_outcome_value]), EPSILON)),
                "ft_1x2_brier": sum((float(probabilities[key]) - float(key == actual_outcome_value)) ** 2 for key in OUTCOMES),
                "exact_top1": int(score_text(actual) == _champion_score_list(record, "score_top1")[:1][0]) if _champion_score_list(record, "score_top1") else 0,
                "exact_top3": int(score_text(actual) in _champion_score_list(record, "score_top3")[:3]),
                "exact_top5": int(score_text(actual) in _champion_score_list(record, "score_top5")[:5]),
            })
        # Origin/main has no immutable Challenger C score surface.  Do not
        # reconstruct or re-run C merely to fill a comparison column.
    return controls


def _control_metric_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    return {
        "n": len(rows),
        "ft_1x2_log_loss": _mean(row["ft_1x2_log_loss"] for row in rows),
        "ft_1x2_brier": _mean(row["ft_1x2_brier"] for row in rows),
        "exact_top1": _mean(row["exact_top1"] for row in rows),
        "exact_top3": _mean(row["exact_top3"] for row in rows),
        "exact_top5": _mean(row["exact_top5"] for row in rows),
    }


def _build_shadow_record(observation: Mapping[str, Any], baseline: Mapping[str, Any], challenger: Mapping[str, Any], model_digest: str) -> dict[str, Any]:
    record = observation["record"]
    projection = challenger["projection"]
    source_identity = {
        "prediction_id": record.get("prediction_id"),
        "match_key": observation["match_key"],
        "input_snapshot_ref": record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref"),
        "input_sha256": record.get("input_sha256"),
        "canonical_model_input_sha256": record.get("canonical_model_input_sha256"),
        "source_cutoff_at": record.get("source_cutoff_at"),
        "kickoff_at": record.get("kickoff_at"),
        "snapshot_id": (observation.get("snapshot") or {}).get("snapshot_id"),
        "captured_at": observation.get("captured_at"),
    }
    market = {
        "source": observation.get("source"),
        "families": observation["quote_families"],
        "surface_digest": observation["quote_families"]["surface_digest"],
    }
    shadow = {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "namespace": "full_market_surface_score_challenger_1",
        "prediction_id": "FMS-" + _sha256_bytes((observation["match_key"] + "|" + model_digest).encode("utf-8"))[:24],
        "model_family": MODEL_FAMILY,
        "model_digest": model_digest,
        "source_identity": source_identity,
        "market_surface": market,
        "solver": {"version": SOLVER_VERSION, "settings": SOLVER_SETTINGS},
        "loss": {"by_family": challenger["family_losses"], "total": challenger["loss"], "quote_counts": challenger["family_quote_counts"]},
        "lambda_home": challenger["lambda_home"],
        "lambda_away": challenger["lambda_away"],
        "lambda_total": challenger["lambda_total"],
        "prediction": projection,
        "baseline_189": {
            "status": baseline.get("status"),
            "lambda_home": (baseline.get("projection") or {}).get("lambda_home"),
            "lambda_away": (baseline.get("projection") or {}).get("lambda_away"),
            "surface": "1X2+O/U; AH held out",
        },
        "production_enabled": False,
        "user_visible": False,
        "post_match_input_used_for_generation": False,
    }
    shadow["prediction_sha256"] = _json_sha256(shadow)
    return shadow


def _select_and_freeze_market_observations(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records, inventory = load_prediction_rows(root)
    selection = select_unique_legal_versions(records)
    observations = [_frozen_observation(record) for record in selection["selected_records"]]
    observations.sort(key=lambda item: item["match_key"])
    funnel = {
        "raw_prediction_rows": len(records),
        "selected_unique_matches": len(observations),
        "legal_snapshot_matches": sum(item.get("snapshot") is not None for item in observations),
        "valid_1x2_matches": sum(not item["one_x2"].get("reason") for item in observations),
        "valid_ou_matches": sum(not item["ou"].get("reason") for item in observations),
        "valid_ah_matches": sum(not item["ah"].get("reason") for item in observations),
        "baseline_189_evaluable": sum(item["baseline"].get("status") == "EVALUABLE" for item in observations),
        "full_surface_evaluable": sum(item["challenger"].get("status") == "EVALUABLE" for item in observations),
    }
    return observations, {"inventory": inventory, "selection": {key: value for key, value in selection.items() if key not in {"selected_records", "groups"}}, "funnel": funnel}


def _attach_historical_results(observations: list[dict[str, Any]], root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Mapping[str, Any]]]:
    """Load outcomes only after all frozen A/B market projections exist."""
    ledger_keys, ledger_info = _ledger_keys(root)
    results, duplicate_keys, result_info = load_verified_results(root)
    verified_by_key: dict[str, Mapping[str, Any]] = {}
    for observation in observations:
        result, reason = _verified_result_for_record(observation["record"], ledger_keys, results, duplicate_keys)
        observation["result"] = result
        observation["result_reason"] = reason
        if result is not None:
            verified_by_key[observation["match_key"]] = result
    return observations, {"ledger": ledger_info, "results": result_info, "duplicate_result_keys": sorted(duplicate_keys)}, verified_by_key


def _prospective_rows(observations: Sequence[Mapping[str, Any]], prospective_after: datetime) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for observation in observations:
        record = observation["record"]
        kickoff = _parse_datetime(record.get("kickoff_at"))
        if kickoff is None or kickoff <= prospective_after:
            skipped["not_future_prospective"] += 1
            continue
        if observation.get("snapshot") is None:
            skipped[str(observation.get("snapshot_error") or "NO_LEGAL_SNAPSHOT")] += 1
            continue
        if observation["challenger"].get("status") != "EVALUABLE":
            skipped[str(observation["challenger"].get("reason") or "FULL_SURFACE_NOT_EVALUABLE")] += 1
            continue
        rows.append(dict(observation))
    return rows, skipped


def _evaluation_summary(observations: Sequence[Mapping[str, Any]], results_by_key: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    baseline_rows: list[dict[str, Any]] = []
    challenger_rows: list[dict[str, Any]] = []
    for observation in observations:
        result = results_by_key.get(observation["match_key"])
        if result is None:
            continue
        baseline_row = _model_metric_row(observation, result, "baseline")
        challenger_row = _model_metric_row(observation, result, "challenger")
        if baseline_row is not None:
            baseline_rows.append(baseline_row)
        if challenger_row is not None:
            challenger_rows.append(challenger_row)
    baseline_summary = _metric_summary(baseline_rows)
    challenger_summary = _metric_summary(challenger_rows)
    _add_family_residual_summary(baseline_summary, baseline_rows)
    _add_family_residual_summary(challenger_summary, challenger_rows)
    paired = _paired_scorecard({"baseline": baseline_rows, "challenger": challenger_rows})
    controls = _control_metric_rows(observations, results_by_key)
    control_summary = {
        "champion": {"status": "EVALUABLE" if controls["champion"] else "NOT_AVAILABLE", "metrics": _control_metric_summary(controls["champion"])},
        "challenger_c": {"status": "NOT_AVAILABLE_ON_ORIGIN_MAIN", "metrics": {"n": 0}},
    }
    return {
        "baseline_189": {"label": "1X2+O/U accepted #189 baseline; AH held out", "metrics": baseline_summary},
        "full_market_surface": {"label": "1X2+O/U+AH fixed joint fit", "metrics": challenger_summary},
        "paired": paired,
        "controls": control_summary,
        "metric_rows": {"baseline": baseline_rows, "full_market_surface": challenger_rows},
    }


def _decision(observations: Sequence[Mapping[str, Any]], historical: Mapping[str, Any], shadow_rows: Sequence[Mapping[str, Any]], integrity_failures: Sequence[str]) -> str:
    if integrity_failures:
        return "FAIL_CLOSED"
    if shadow_rows:
        return "FULL_MARKET_SURFACE_SHADOW_WIRED"
    if historical.get("paired", {}).get("paired_unique_match_n", 0) > 0:
        return "FULL_MARKET_SURFACE_EVALUATED_ONLY"
    return "FAIL_CLOSED"


def _build_report(summary: Mapping[str, Any]) -> str:
    funnel = summary["coverage_funnel"]
    paired = summary["historical_evaluation"]["paired"]
    lines = [
        f"# {MILESTONE}",
        "",
        "Research-only; current Champion/C serving is unchanged; DO NOT MERGE.",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Source origin/main: `{summary['source_main_sha']}`",
        f"- Historical unique selected: `{funnel['selected_unique_matches']}`; full-surface evaluable: `{funnel['full_surface_evaluable']}`; paired verified A/B: `{paired['paired_unique_match_n']}`",
        f"- Prospective shadow rows: `{summary['prospective_shadow']['row_count']}`",
        "",
        "## Fixed contract",
        "",
        f"- Solver: `{SOLVER_VERSION}`; settings `{json.dumps(SOLVER_SETTINGS, sort_keys=True)}`",
        "- Objective: family-balanced mean squared reconstruction loss across 1X2, O/U and AH.",
        "- AH is included only in the challenger; the #189 baseline is 1X2+O/U with AH held out.",
        "- rho=0; finite normalized 0..20 independent-Poisson matrix; all derived markets use the same matrix.",
        "- Solver settings and market projections are frozen before result loading; no outcome is used for fitting.",
        "",
        "## Coverage",
        "",
    ]
    for key, value in funnel.items():
        lines.append(f"- `{key}`: `{value}`")
    lines += ["", "## Historical paired evaluation", ""]
    for model_key in ("baseline_189", "full_market_surface"):
        model = summary["historical_evaluation"][model_key]
        lines.append(f"### {model['label']}")
        lines.append(f"`{json.dumps(model['metrics'], ensure_ascii=False, sort_keys=True)}`")
        lines.append("")
    lines.append("### Paired bootstrap (full surface minus #189 baseline)")
    lines.append(f"`{json.dumps(paired, ensure_ascii=False, sort_keys=True)}`")
    lines += ["", "## Controls and integrity", "", f"- Controls: `{json.dumps(summary['historical_evaluation']['controls'], ensure_ascii=False, sort_keys=True)}`", f"- Integrity: `{json.dumps(summary['integrity'], ensure_ascii=False, sort_keys=True)}`", "", "STOP: READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE.", ""]
    return "\n".join(lines)


def run_challenger(*, prospective_after: datetime = DEFAULT_PROSPECTIVE_AFTER, root: Path = ROOT) -> dict[str, Any]:
    # The only pre-outcome phase: select legal versions, read frozen snapshots,
    # parse/de-vig all three families, and freeze both A and B projections.
    observations, inventory = _select_and_freeze_market_observations(root)
    observations, result_inventory, results_by_key = _attach_historical_results(observations, root)
    historical = _evaluation_summary(observations, results_by_key)
    shadow_observations, shadow_skips = _prospective_rows(observations, prospective_after)
    integrity_failures: list[str] = []
    if any(str(observation.get("snapshot_error") or "").startswith("LATER_OR_CLOSING") for observation in observations):
        integrity_failures.append("LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED")
    if len({observation["match_key"] for observation in observations}) != len(observations):
        integrity_failures.append("DUPLICATE_UNIQUE_MATCH_KEY")
    now = datetime.now(timezone.utc).isoformat()
    model_content = canonical_json(MODEL_CONTRACT).encode("utf-8")
    model_digest = _sha256_bytes(model_content)
    shadow_rows = [_build_shadow_record(observation, observation["baseline"], observation["challenger"], model_digest) for observation in shadow_observations]
    shadow_rows.sort(key=lambda row: str(row["source_identity"].get("match_key") or ""))
    decision = _decision(observations, historical, shadow_rows, integrity_failures)
    full_evaluable = [item for item in observations if item["challenger"].get("status") == "EVALUABLE"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "decision": decision,
        "reviewed_at": now,
        "source_main_sha": _source_main_sha(root),
        "model_family": MODEL_FAMILY,
        "model_digest": model_digest,
        "model_contract": MODEL_CONTRACT,
        "coverage_funnel": {**inventory["funnel"], "historical_verified_results": len(results_by_key), "historical_paired_ab": historical["paired"]["paired_unique_match_n"]},
        "selection_authority": inventory["selection"],
        "inventory": {**inventory["inventory"], "results": result_inventory},
        "historical_evaluation": {key: value for key, value in historical.items() if key != "metric_rows"},
        "historical_metric_rows": historical["metric_rows"],
        "prospective_shadow": {"prospective_after": prospective_after.isoformat(), "row_count": len(shadow_rows), "skipped": dict(sorted(shadow_skips.items())), "production_enabled": False, "user_visible": False},
        "integrity": {
            "status": "PASS" if not integrity_failures else "FAIL_CLOSED",
            "failures": sorted(integrity_failures),
            "network_calls": 0,
            "external_provider_calls": 0,
            "frozen_snapshots_mutated": False,
            "frozen_history_mutated": False,
            "champion_c_serving_ui_changed": False,
            "outcomes_loaded_after_market_freeze": True,
            "solver_result_tuned": False,
            "family_weights_tuned": False,
            "rho": 0.0,
            "automatic_promotion": False,
            "production_enabled": False,
            "user_visible": False,
        },
        "controls_retained": ["Market #189 baseline", "Champion immutable authority", "Challenger C where immutable authority exists"],
        "source": {"prediction_records": "data/model_governance/predictions", "input_snapshots": _repo_relative(DEFAULT_INPUT_SNAPSHOT_ROOT), "results": "data/postmatch_automation/results", "prospective_ledger": "data/prospective/ledger.jsonl"},
        "stop": "READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE",
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(DEFAULT_MODEL, {**MODEL_CONTRACT, "schema_version": SCHEMA_VERSION, "model_digest": model_digest, "generated_at": now})
    _write_json(DEFAULT_SHADOW, {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "model_family": MODEL_FAMILY, "model_digest": model_digest, "prospective_after": prospective_after.isoformat(), "row_count": len(shadow_rows), "rows": shadow_rows, "production_enabled": False, "user_visible": False})
    _write_json(DEFAULT_SUMMARY, summary)
    DEFAULT_REPORT.write_text(_build_report(summary), encoding="utf-8")
    return summary


def _source_main_sha(root: Path) -> str | None:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "origin/main"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prospective-after", default=None, help="ISO timestamp; default is the fixed Issue #230 review cutoff")
    args = parser.parse_args(argv)
    prospective_after = _parse_datetime(args.prospective_after) if args.prospective_after else DEFAULT_PROSPECTIVE_AFTER
    if prospective_after is None:
        print(json.dumps({"decision": "FAIL_CLOSED", "blocker": "INVALID_PROSPECTIVE_AFTER"}, sort_keys=True))
        return 2
    try:
        summary = run_challenger(prospective_after=prospective_after)
    except (OSError, ValueError, FullMarketSurfaceBlocked, AuditError) as error:
        summary = {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "decision": "FAIL_CLOSED", "blocker": f"{type(error).__name__}:{error}", "production_enabled": False, "user_visible": False}
        _write_json(DEFAULT_SUMMARY, summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"decision": summary["decision"], "historical_paired_ab": summary["coverage_funnel"]["historical_paired_ab"], "prospective_shadow_rows": summary["prospective_shadow"]["row_count"], "model_digest": summary["model_digest"], "current_serving_changed": False}, ensure_ascii=False, sort_keys=True))
    return 0 if summary["decision"] != "FAIL_CLOSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
