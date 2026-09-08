#!/usr/bin/env python3
"""Canonical frozen-market normalization and pricing helpers.

The Champion and ``market_reference.v1`` deliberately keep their existing
policies.  This module owns their shared quote parsing, de-vig and line
extraction mechanics without changing either policy's aggregation semantics.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import re
from statistics import fmean, median
from typing import Any, Mapping, Sequence
import unicodedata

from market_contracts import settle_asian_contract
from score_engine import (
    SCORE_ENGINE_VERSION,
    asian_handicap_settlement,
    btts_probabilities,
    independent_poisson_score_matrix_with_tail,
    matrix_settlement_probability,
    outcome_probabilities,
    ranked_exact_score_rows,
    score_matrix_rows,
    total_goal_distribution,
)


MARKET_REFERENCE_VERSION = "market_reference.v1"
MARKET_REFERENCE_POLICY = MARKET_REFERENCE_VERSION
CHAMPION_MARKET_POLICY = "champion.multibook_proportional_devig_mean.v1"
PURE_MARKET_EXACT_VERSION = "pure_market_exact_prospective_1"
PURE_MARKET_EXACT_MARKET_POLICY = "market_189.same_time_proportional_devig.v1"
PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM = 20
PURE_MARKET_EXACT_LAMBDA_LOWER = 0.001
PURE_MARKET_EXACT_LAMBDA_UPPER = 20.0
PURE_MARKET_EXACT_LAMBDA_ITERATIONS = 90
PURE_MARKET_EXACT_SHARE_LOWER = 0.01
PURE_MARKET_EXACT_SHARE_UPPER = 0.99
PURE_MARKET_EXACT_SHARE_ITERATIONS = 70
PURE_MARKET_EXACT_TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
PURE_MARKET_EXACT_HANDICAP_LINES = (
    -1.5, -1.0, -0.75, -0.5, -0.25, 0.0,
    0.25, 0.5, 0.75, 1.0, 1.5,
)
OUTCOMES = ("home", "draw", "away")
MARKET_PROVIDER_PRIORITY = {"nowscore": 0, "500_deep": 1}
SNAPSHOT_FIELDS = (
    "match_key",
    "snapshot_id",
    "canonical_model_input_sha256",
    "source_cutoff_at",
    "market_snapshot_at",
    "checkpoint_stage",
)


def valid_three_way_decimal_odds(value: Any) -> dict[str, float] | None:
    """Return validated decimal 1X2 quotes, or ``None`` for an invalid quote."""
    if not isinstance(value, Mapping):
        return None
    try:
        values = {key: float(value[key]) for key in OUTCOMES}
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(number) or number <= 1.0 for number in values.values()):
        return None
    return values


def proportional_devig_three_way(value: Mapping[str, Any] | Sequence[Any]) -> dict[str, float] | None:
    """Apply the existing proportional implied-probability normalization."""
    if isinstance(value, Mapping):
        odds = valid_three_way_decimal_odds(value)
    else:
        try:
            odds = valid_three_way_decimal_odds(dict(zip(OUTCOMES, value, strict=True)))
        except (TypeError, ValueError):
            odds = None
    if odds is None:
        return None
    inverse = {key: 1.0 / odds[key] for key in OUTCOMES}
    total = sum(inverse.values())
    return {key: inverse[key] / total for key in OUTCOMES}


def champion_bookmaker_rows(deep: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = (deep.get("ouzhi") or {}).get("bookmakers") or []
    return [row for row in rows if isinstance(row, dict)]


def valid_champion_bookmakers(deep: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in champion_bookmaker_rows(deep)
        if valid_three_way_decimal_odds(row.get("spf_current")) is not None
    ]


def champion_consensus_probabilities(deep: Mapping[str, Any]) -> dict[str, float] | None:
    """Keep Champion's mean-of-bookmaker proportional de-vig policy intact."""
    rows = []
    for bookmaker in champion_bookmaker_rows(deep):
        fair = proportional_devig_three_way(bookmaker.get("spf_current") or {})
        if fair is not None:
            rows.append([fair[key] for key in OUTCOMES])
    if not rows:
        return None
    return {key: fmean(row[index] for row in rows) for index, key in enumerate(OUTCOMES)}


def champion_market_total(deep: Mapping[str, Any]) -> float | None:
    lines = []
    for company in (deep.get("daxiao") or {}).get("companies") or []:
        try:
            line = float(company.get("current_line"))
        except (TypeError, ValueError):
            continue
        if 1.0 <= line <= 5.0:
            lines.append(line)
    return median(lines) if lines else None


def champion_market_handicap(deep: Mapping[str, Any]) -> float | None:
    """Return the Champion median home-team Asian handicap from current quotes."""
    lines = []
    for company in (deep.get("yazhi") or {}).get("companies") or []:
        try:
            line = float(company.get("current_handicap"))
        except (TypeError, ValueError):
            continue
        if -5.0 <= line <= 5.0:
            lines.append(line)
    return median(lines) if lines else None


def champion_market_state(deep: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the Champion policy identity with its normalized market state."""
    return {
        "policy": CHAMPION_MARKET_POLICY,
        "probabilities": champion_consensus_probabilities(deep),
        "total_line": champion_market_total(deep),
        "handicap_line": champion_market_handicap(deep),
    }


def price_total_line(expected_goals: float, line: float) -> dict:
    """Price a Champion total line using the existing Poisson policy."""
    distribution = []
    covered = 0.0
    for goals in range(16):
        probability = math.exp(-expected_goals) * expected_goals ** goals / math.factorial(goals)
        distribution.append((goals, probability))
        covered += probability
    distribution.append((16, max(0.0, 1.0 - covered)))

    priced = {"line": round(float(line) * 4) / 4}
    for side in ("over", "under"):
        win_equivalent = loss_equivalent = 0.0
        for goals, probability in distribution:
            units = settle_asian_contract(
                {"family": "total", "selection": side, "line": line},
                (goals, 0),
            )["units"]
            win_equivalent += probability * max(0.0, units)
            loss_equivalent += probability * max(0.0, -units)
        fair_odds = 1.0 + loss_equivalent / win_equivalent if win_equivalent > 0 else None
        priced[side] = {
            "win_equivalent_probability": round(win_equivalent, 6),
            "loss_equivalent_probability": round(loss_equivalent, 6),
            "push_equivalent_probability": round(max(0.0, 1.0 - win_equivalent - loss_equivalent), 6),
            "fair_odds": round(fair_odds, 4) if fair_odds is not None else None,
        }
    return priced


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


def _model_input(snapshot: dict[str, Any]) -> dict[str, Any]:
    nested = snapshot.get("model_input")
    return nested if isinstance(nested, dict) else snapshot


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        if isinstance(value.get("rows"), list):
            return [row for row in value["rows"] if isinstance(row, dict)]
        if isinstance(value.get("bookmakers"), list):
            return [row for row in value["bookmakers"] if isinstance(row, dict)]
        if isinstance(value.get("companies"), list):
            return [row for row in value["companies"] if isinstance(row, dict)]
    return []


def _market_containers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    source = _model_input(snapshot)
    for key in ("market", "markets", "market_snapshot", "market_data"):
        value = source.get(key)
        if isinstance(value, dict):
            containers.append(value)
    return containers


def _one_x_two_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = _model_input(snapshot)
    containers = _market_containers(snapshot)
    for key in ("market_1x2", "market_1X2", "one_x_two", "1x2"):
        rows.extend(_as_rows(source.get(key)))
    for container in containers:
        for key in ("1x2", "1X2", "one_x_two", "spf"):
            rows.extend(_as_rows(container.get(key)))
        rows.extend(_as_rows(container.get("bookmakers")))

    source_snapshots = source.get("source_snapshots")
    if isinstance(source_snapshots, dict):
        provider_names = sorted(
            source_snapshots,
            key=lambda name: (
                MARKET_PROVIDER_PRIORITY.get(_canonical_provider(name), 2),
                _canonical_provider(name),
            ),
        )
        for provider_name in provider_names:
            provider = source_snapshots.get(provider_name)
            provider_rows = provider.get("snapshots") if isinstance(provider, dict) else None
            for snapshot_index, source_snapshot in enumerate(_as_rows(provider_rows)):
                bookmaker_rows = _as_rows((source_snapshot.get("ouzhi") or {}).get("bookmakers"))
                for row_index, row in enumerate(bookmaker_rows):
                    annotated = deepcopy(row)
                    annotated["_source_provider"] = _canonical_provider(
                        row.get("source_provider")
                        or row.get("source")
                        or provider_name
                    )
                    annotated["_source_order"] = (snapshot_index, row_index)
                    rows.append(annotated)
    return rows


def _canonical_provider(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if "now" in text:
        return "nowscore"
    if "500" in text:
        return "500_deep"
    return text or "snapshot"


def _quote_values(row: dict[str, Any]) -> tuple[float, float, float] | None:
    candidates = [row]
    for key in ("spf_current", "current", "odds", "1x2", "spf"):
        if isinstance(row.get(key), dict):
            candidates.append(row[key])
    aliases = {
        "home": ("home", "home_odds", "home_price", "win"),
        "draw": ("draw", "draw_odds", "draw_price"),
        "away": ("away", "away_odds", "away_price", "loss"),
    }
    for candidate in candidates:
        values: dict[str, float] = {}
        for outcome, keys in aliases.items():
            for key in keys:
                number = _number(candidate.get(key))
                if number is not None:
                    values[outcome] = number
                    break
        if len(values) == 3 and all(value > 1.0 for value in values.values()):
            return values["home"], values["draw"], values["away"]
    return None


def _bookmaker_name(row: dict[str, Any], index: int) -> str:
    for key in ("bookmaker", "company", "name", "title", "cid", "source_company_id", "id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return f"bookmaker-{index + 1}"


def _canonical_bookmaker_id(value: Any, index: int) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^\w]+", "", text, flags=re.UNICODE)
    return normalized or f"bookmaker{index + 1}"


def _provider_priority(value: Any) -> int:
    return MARKET_PROVIDER_PRIORITY.get(_canonical_provider(value), 2)


def _auxiliary_market_rows(snapshot: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = _model_input(snapshot)
    for name in names:
        rows.extend(_as_rows(source.get(name)))
    for container in _market_containers(snapshot):
        for name in names:
            rows.extend(_as_rows(container.get(name)))
    source_snapshots = source.get("source_snapshots")
    if isinstance(source_snapshots, dict):
        for provider in source_snapshots.values():
            provider_rows = provider.get("snapshots") if isinstance(provider, dict) else None
            for source_snapshot in _as_rows(provider_rows):
                for name in names:
                    section = source_snapshot.get(name)
                    if name in {"handicap", "asian_handicap"}:
                        section = source_snapshot.get("yazhi") if name == "handicap" else section
                    if name in {"total", "over_under"}:
                        section = source_snapshot.get("daxiao") if name == "total" else section
                    rows.extend(_as_rows(section))
    return [deepcopy(row) for row in rows]


def _line_from_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> float | None:
    for row in rows:
        for key in keys:
            value = _number(row.get(key))
            if value is not None:
                return value
    return None


def _number_from_snapshot(snapshot: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    source = _model_input(snapshot)
    for key in keys:
        value = _number(source.get(key))
        if value is not None:
            return value
    return None


def build_market_reference(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build Market Reference v1 from real 1X2 quotes in ``snapshot`` only."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")

    rows = _one_x_two_rows(snapshot)
    raw_devig: dict[str, dict[str, float]] = {}
    valid_rows: list[dict[str, Any]] = []
    selected: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    duplicate_bookmakers_excluded = 0
    for index, row in enumerate(rows):
        odds = _quote_values(row)
        if odds is None:
            continue
        fair = proportional_devig_three_way(odds)
        if fair is None:
            continue
        display_name = _bookmaker_name(row, index)
        canonical_id = _canonical_bookmaker_id(display_name, index)
        source_provider = _canonical_provider(
            row.get("_source_provider") or row.get("source_provider") or row.get("source")
        )
        source_order = row.get("_source_order")
        if not isinstance(source_order, (tuple, list)):
            source_order = (index, index)
        selection_key = (_provider_priority(source_provider), *tuple(source_order), index)
        candidate = {
            "bookmaker": display_name,
            "canonical_bookmaker_id": canonical_id,
            "source_provider": source_provider,
            "odds": {"home": odds[0], "draw": odds[1], "away": odds[2]},
            "raw_devig_probabilities": fair,
            "fair_probabilities": fair,
        }
        previous = selected.get(canonical_id)
        if previous is not None:
            duplicate_bookmakers_excluded += 1
            if selection_key >= previous[0]:
                continue
        selected[canonical_id] = (selection_key, candidate)

    for canonical_id, (_, row) in sorted(selected.items(), key=lambda item: item[0]):
        # Keep the historical display-name map while exposing the stable
        # canonical id on each auditable bookmaker row.
        raw_devig[row["bookmaker"]] = row["raw_devig_probabilities"]
        valid_rows.append(row)

    handicap_rows = _auxiliary_market_rows(snapshot, ("handicap", "asian_handicap", "yazhi"))
    total_rows = _auxiliary_market_rows(snapshot, ("total", "over_under", "daxiao"))
    handicap_line = _number_from_snapshot(snapshot, ("market_handicap_line", "handicap_line"))
    total_line = _number_from_snapshot(snapshot, ("market_total_line", "total_line"))
    handicap_line = handicap_line if handicap_line is not None else _line_from_rows(
        handicap_rows, ("line", "current_handicap", "handicap")
    )
    total_line = total_line if total_line is not None else _line_from_rows(
        total_rows, ("line", "current_line", "total_line")
    )

    result: dict[str, Any] = {
        "model": "market_reference",
        "version": MARKET_REFERENCE_VERSION,
        "status": "not_evaluable",
        "reason": "insufficient_valid_bookmakers",
        "probabilities": None,
        "fair_probabilities": None,
        "outcome_probabilities": None,
        "raw_devig_probabilities": raw_devig,
        "bookmaker_fair_probabilities": raw_devig,
        "bookmakers": valid_rows,
        "market_bookmaker_count": len(valid_rows),
        "market_probability_min": None,
        "market_probability_max": None,
        "market_min": None,
        "market_max": None,
        "market_dispersion_by_outcome": None,
        "market_dispersion": None,
        "market_handicap_line": handicap_line,
        "market_total_line": total_line,
        "market_handicap_quotes": handicap_rows,
        "market_total_quotes": total_rows,
        "market_read": True,
        "champion_read": False,
        "market_evaluable": False,
        "market_missing_reason": "insufficient_valid_bookmakers",
        "duplicate_bookmakers_excluded": duplicate_bookmakers_excluded,
    }
    if len(valid_rows) >= 2:
        by_outcome = {
            outcome: [row["raw_devig_probabilities"][outcome] for row in valid_rows]
            for outcome in OUTCOMES
        }
        medians = {outcome: median(values) for outcome, values in by_outcome.items()}
        median_total = sum(medians.values())
        probabilities = {outcome: medians[outcome] / median_total for outcome in OUTCOMES}
        dispersion_by_outcome = {
            outcome: max(values) - min(values) for outcome, values in by_outcome.items()
        }
        result.update({
            "status": "evaluable",
            "reason": None,
            "market_evaluable": True,
            "market_missing_reason": None,
            "probabilities": probabilities,
            "fair_probabilities": probabilities,
            "outcome_probabilities": probabilities,
            "market_probability_min": {outcome: min(values) for outcome, values in by_outcome.items()},
            "market_probability_max": {outcome: max(values) for outcome, values in by_outcome.items()},
            "market_min": {outcome: min(values) for outcome, values in by_outcome.items()},
            "market_max": {outcome: max(values) for outcome, values in by_outcome.items()},
            "market_dispersion_by_outcome": dispersion_by_outcome,
            "market_dispersion": max(dispersion_by_outcome.values()),
        })
    return {**_metadata(snapshot), **result}


def _pure_market_source(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = snapshot.get("input")
    return nested if isinstance(nested, Mapping) else snapshot


def _pure_market_rows(snapshot: Mapping[str, Any] | None, family: str) -> list[dict[str, Any]]:
    if not isinstance(snapshot, Mapping):
        return []
    source = _pure_market_source(snapshot)
    section = source.get(family)
    if not isinstance(section, Mapping):
        return []
    key = "bookmakers" if family == "ouzhi" else "companies"
    rows = section.get(key)
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _pure_quote_key(row: Mapping[str, Any]) -> str:
    for key in ("cid", "source_company_id", "company_id", "name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.casefold()
    return ""


def _pure_valid_quarter_line(value: Any, *, allow_negative: bool = False) -> float | None:
    number = _number(value)
    if number is None or (not allow_negative and number < 0.0):
        return None
    rounded = round(number * 4.0) / 4.0
    return rounded if abs(number - rounded) <= 1e-8 else None


def hk_water_to_decimal(water: Any) -> float:
    """Convert a positive Hong Kong water quote to decimal odds."""
    value = _number(water)
    if value is None or value <= 0.0:
        raise ValueError("INVALID_HK_WATER_DOMAIN")
    decimal = 1.0 + value
    if not math.isfinite(decimal) or decimal <= 1.0:
        raise ValueError("INVALID_DECIMAL_ODDS_DOMAIN")
    return decimal


def proportional_devig_two_way(first: Any, second: Any) -> tuple[float, float]:
    decimals = (hk_water_to_decimal(first), hk_water_to_decimal(second))
    inverse = tuple(1.0 / value for value in decimals)
    total = sum(inverse)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("INVALID_INVERSE_ODDS_SUM")
    return inverse[0] / total, inverse[1] / total


def extract_pure_market_1x2_quotes(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract the accepted #189 same-time 1X2 quote authority."""
    rows = _pure_market_rows(snapshot, "ouzhi")
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        key = _pure_quote_key(row)
        if not key:
            rejected["MISSING_BOOKMAKER_IDENTITY"] += 1
            continue
        if key in seen:
            rejected["DUPLICATE_BOOKMAKER_ROW"] += 1
            continue
        seen.add(key)
        odds = valid_three_way_decimal_odds(row.get("spf_current"))
        if odds is None:
            rejected["INVALID_1X2_DECIMAL_ODDS_DOMAIN"] += 1
            continue
        fair = proportional_devig_three_way(odds)
        if fair is None:
            rejected["INVALID_1X2_DEVIG"] += 1
            continue
        valid.append({"bookmaker": key, "odds": odds, "fair_probabilities": fair})
    consensus = None
    if valid:
        consensus = {
            outcome: fmean(row["fair_probabilities"][outcome] for row in valid)
            for outcome in OUTCOMES
        }
        total = sum(consensus.values())
        consensus = {outcome: consensus[outcome] / total for outcome in OUTCOMES}
    return {
        "valid": valid,
        "consensus": consensus,
        "raw_row_count": len(rows),
        "valid_bookmaker_count": len(valid),
        "rejected_reasons": dict(sorted(rejected.items())),
        "reason": None if valid else ("NO_FROZEN_1X2_QUOTE_ROWS" if not rows else "NO_VALID_1X2_QUOTE_ROWS"),
    }


def extract_pure_market_ou_quotes(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract and de-vig the accepted #189 Asian O/U quote rows."""
    rows = _pure_market_rows(snapshot, "daxiao")
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        key = _pure_quote_key(row)
        if not key:
            rejected["MISSING_BOOKMAKER_IDENTITY"] += 1
            continue
        if key in seen:
            rejected["DUPLICATE_BOOKMAKER_ROW"] += 1
            continue
        seen.add(key)
        line = _pure_valid_quarter_line(row.get("current_line"))
        if line is None:
            rejected["INVALID_QUARTER_LINE"] += 1
            continue
        try:
            fair_over, fair_under = proportional_devig_two_way(
                row.get("current_over_water"), row.get("current_under_water")
            )
        except ValueError as error:
            rejected[str(error)] += 1
            continue
        valid.append({
            "bookmaker": key,
            "line": line,
            "over_decimal": hk_water_to_decimal(row.get("current_over_water")),
            "under_decimal": hk_water_to_decimal(row.get("current_under_water")),
            "fair_over_probability": fair_over,
            "fair_under_probability": fair_under,
        })
    return {
        "valid": valid,
        "raw_row_count": len(rows),
        "valid_bookmaker_count": len(valid),
        "rejected_reasons": dict(sorted(rejected.items())),
        "reason": None if valid else ("NO_FROZEN_DAXIAO_QUOTE_ROWS" if not rows else "NO_VALID_DAXIAO_QUOTE_ROWS"),
    }


def pure_market_fair_probability(
    matrix: Mapping[tuple[int, int], float], line: float, selection: str = "over"
) -> float:
    """Return a two-sided fair probability using canonical Asian settlement."""
    if selection not in {"over", "under"}:
        raise ValueError("UNSUPPORTED_TOTAL_SELECTION")
    valid_line = _pure_valid_quarter_line(line)
    if valid_line is None:
        raise ValueError("INVALID_QUARTER_LINE")
    priced = matrix_settlement_probability(
        matrix,
        family="total",
        side=selection,
        line=valid_line,
    )
    win = float(priced["win"] or 0.0)
    loss = float(priced["loss"] or 0.0)
    denominator = win + loss
    if win <= 1e-12 or loss <= 1e-12 or denominator <= 1e-12:
        raise ValueError("SETTLEMENT_PRICE_NOT_IDENTIFIABLE")
    return win / denominator


def solve_pure_market_total_lambda(line: float, target_over_probability: float) -> dict[str, float]:
    """Solve total intensity against the exact #189 Asian O/U price."""
    valid_line = _pure_valid_quarter_line(line)
    target = _number(target_over_probability)
    if valid_line is None or target is None or not (1e-12 < target < 1.0 - 1e-12):
        raise ValueError("OU_SOLVE_DOMAIN_INVALID")

    def model_probability(lam: float) -> float:
        matrix, _ = independent_poisson_score_matrix_with_tail(
            lam,
            0.0,
            max_goals_per_team=PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
        )
        return pure_market_fair_probability(matrix, valid_line, "over")

    lower, upper = PURE_MARKET_EXACT_LAMBDA_LOWER, PURE_MARKET_EXACT_LAMBDA_UPPER
    try:
        low_probability = model_probability(lower)
        high_probability = model_probability(upper)
    except ValueError as error:
        raise ValueError("OU_SOLVE_DOMAIN_INVALID") from error
    if target < low_probability - 1e-10 or target > high_probability + 1e-10:
        raise ValueError("OU_SOLVE_NOT_IDENTIFIABLE")
    for _ in range(PURE_MARKET_EXACT_LAMBDA_ITERATIONS):
        middle = (lower + upper) / 2.0
        if model_probability(middle) < target:
            lower = middle
        else:
            upper = middle
    lam = (lower + upper) / 2.0
    residual = model_probability(lam) - target
    if not math.isfinite(residual) or abs(residual) > 1e-7:
        raise ValueError("OU_SOLVE_NO_CONVERGENCE")
    return {
        "lambda_total": lam,
        "target_probability": target,
        "model_probability": target + residual,
        "residual": residual,
    }


def solve_pure_market_home_share(
    lambda_total: float, target_probabilities: Mapping[str, Any]
) -> dict[str, float]:
    """Fit only the 1X2 home share; no handicap or calibration input is used."""
    target = {key: _number(target_probabilities.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0.0 for value in target.values()):
        raise ValueError("HOME_SHARE_TARGET_INVALID")
    total = sum(float(value) for value in target.values())
    if total <= 0.0 or not math.isfinite(total):
        raise ValueError("HOME_SHARE_TARGET_INVALID")
    target = {key: float(value) / total for key, value in target.items()}

    def evaluate(share: float) -> float:
        matrix, _ = independent_poisson_score_matrix_with_tail(
            lambda_total * share,
            lambda_total * (1.0 - share),
            max_goals_per_team=PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
        )
        probabilities = outcome_probabilities(matrix)
        return sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES)

    left, right = PURE_MARKET_EXACT_SHARE_LOWER, PURE_MARKET_EXACT_SHARE_UPPER
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - golden * (right - left)
    x2 = left + golden * (right - left)
    f1, f2 = evaluate(x1), evaluate(x2)
    for _ in range(PURE_MARKET_EXACT_SHARE_ITERATIONS):
        if f1 > f2:
            left, x1, f1 = x1, x2, f2
            x2 = left + golden * (right - left)
            f2 = evaluate(x2)
        else:
            right, x2, f2 = x2, x1, f1
            x1 = right - golden * (right - left)
            f1 = evaluate(x1)
    share = (left + right) / 2.0
    matrix, _ = independent_poisson_score_matrix_with_tail(
        lambda_total * share,
        lambda_total * (1.0 - share),
        max_goals_per_team=PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
    )
    probabilities = outcome_probabilities(matrix)
    return {
        "share": share,
        "lambda_home": lambda_total * share,
        "lambda_away": lambda_total * (1.0 - share),
        "loss": sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES),
        "iterations": PURE_MARKET_EXACT_SHARE_ITERATIONS,
    }


def _pure_market_line_key(line: float) -> str:
    text = f"{float(line):.2f}".rstrip("0")
    return text if not text.endswith(".") else f"{text}0"


def _pure_market_settlement_projection(
    matrix: Mapping[tuple[int, int], float], *, side: str, line: float
) -> dict[str, Any]:
    priced = matrix_settlement_probability(matrix, family="total", side=side, line=line)
    return {
        **priced,
        "win_probability": priced["win"],
        "push_probability": priced["push"],
        "loss_probability": priced["loss"],
    }


def build_pure_market_exact_projection(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Build the pure #189 Market full-score projection from one frozen snapshot."""
    one_x2 = extract_pure_market_1x2_quotes(snapshot)
    ou = extract_pure_market_ou_quotes(snapshot)
    base = {
        "model": "pure_market_exact",
        "version": PURE_MARKET_EXACT_VERSION,
        "market_policy": PURE_MARKET_EXACT_MARKET_POLICY,
        "score_engine_version": SCORE_ENGINE_VERSION,
        "rho": 0.0,
        "one_x2_quotes": one_x2,
        "ou_quotes": ou,
    }
    if one_x2["reason"]:
        return {**base, "status": "NOT_EVALUABLE", "reason": one_x2["reason"]}
    if ou["reason"]:
        return {**base, "status": "NOT_EVALUABLE", "reason": ou["reason"]}

    estimates: list[dict[str, Any]] = []
    solve_reasons: Counter[str] = Counter()
    for quote in ou["valid"]:
        try:
            solved = solve_pure_market_total_lambda(
                quote["line"], quote["fair_over_probability"]
            )
        except ValueError as error:
            solve_reasons[str(error)] += 1
            continue
        estimates.append({**quote, **solved})
    if not estimates:
        return {
            **base,
            "status": "NOT_EVALUABLE",
            "reason": "OU_SOLVE_FAILED_FOR_ALL_VALID_BOOKMAKERS",
            "solve_reasons": dict(sorted(solve_reasons.items())),
        }

    lambda_total = float(median(item["lambda_total"] for item in estimates))
    try:
        share = solve_pure_market_home_share(lambda_total, one_x2["consensus"])
    except ValueError as error:
        return {
            **base,
            "status": "NOT_EVALUABLE",
            "reason": str(error),
            "solve_reasons": dict(sorted(solve_reasons.items())),
        }

    matrix, tail = independent_poisson_score_matrix_with_tail(
        share["lambda_home"],
        share["lambda_away"],
        max_goals_per_team=PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
    )
    rows = score_matrix_rows(matrix)
    top_scores = ranked_exact_score_rows(matrix, limit=5)
    probabilities = outcome_probabilities(matrix)
    btts = btts_probabilities(matrix)
    totals = {
        _pure_market_line_key(line): {
            side: _pure_market_settlement_projection(matrix, side=side, line=line)
            for side in ("over", "under")
        }
        for line in PURE_MARKET_EXACT_TOTAL_LINES
    }
    handicaps = {
        _pure_market_line_key(line): asian_handicap_settlement(matrix, line)
        for line in PURE_MARKET_EXACT_HANDICAP_LINES
    }
    return {
        **base,
        "status": "EVALUABLE",
        "reason": None,
        "lambda_total": lambda_total,
        "lambda_home": share["lambda_home"],
        "lambda_away": share["lambda_away"],
        "one_x2_consensus": one_x2["consensus"],
        "lambda_total_bookmaker_count": len(estimates),
        "lambda_total_bookmaker_estimates": [
            {
                "bookmaker": item["bookmaker"],
                "line": item["line"],
                "lambda_total": item["lambda_total"],
                "residual": item["residual"],
            }
            for item in estimates
        ],
        "lambda_total_residuals": [item["residual"] for item in estimates],
        "solve_reasons": dict(sorted(solve_reasons.items())),
        "share_solver": share,
        "score_matrix": rows,
        "score_matrix_complete": True,
        "score_matrix_support": {
            "representation": "FINITE_NORMALIZED_GRID",
            "max_goals_per_team": PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
            "cell_count": len(rows),
            "full_support": False,
            "tail_bucket": False,
            "out_of_support_policy": "OUT_OF_EXPLICIT_SUPPORT",
            "omitted_probability_mass": tail,
        },
        "score_matrix_tail_probability": tail,
        "score_top1": top_scores[0]["score"],
        "score_top3": [row["score"] for row in top_scores[:3]],
        "score_top5": [row["score"] for row in top_scores[:5]],
        "probabilities": probabilities,
        "expected_goals": {
            "home": share["lambda_home"],
            "away": share["lambda_away"],
            "total": lambda_total,
        },
        "btts": btts,
        "derived_markets": {
            "ft_1x2": probabilities,
            "totals": totals,
            "btts": btts,
            "asian_handicap": handicaps,
            "total_goal_distribution": total_goal_distribution(rows),
        },
    }


market_reference = build_market_reference
