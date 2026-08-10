#!/usr/bin/env python3
"""Frozen-snapshot market and simple-Poisson benchmark baselines.

This module deliberately has no dependency on the Champion implementation.  A
caller passes one already-frozen pre-match snapshot and receives an auditable
baseline result carrying the snapshot identity fields unchanged.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from statistics import median
from typing import Any
import unicodedata


MARKET_REFERENCE_VERSION = "market_reference.v1"
SIMPLE_POISSON_VERSION = "simple_poisson.v1"
MIN_LAMBDA = 0.15
MAX_LAMBDA = 4.0
MAX_GOALS_PER_TEAM = 12
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
            for source in _as_rows(provider_rows):
                for name in names:
                    section = source.get(name)
                    if name in {"handicap", "asian_handicap"}:
                        section = source.get("yazhi") if name == "handicap" else section
                    if name in {"total", "over_under"}:
                        section = source.get("daxiao") if name == "total" else section
                    rows.extend(_as_rows(section))
    return [deepcopy(row) for row in rows]


def _line_from_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> float | None:
    for row in rows:
        for key in keys:
            value = _number(row.get(key))
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
        raw_home, raw_draw, raw_away = (1.0 / value for value in odds)
        total = raw_home + raw_draw + raw_away
        if not math.isfinite(total) or total <= 0:
            continue
        fair = {
            "home": raw_home / total,
            "draw": raw_draw / total,
            "away": raw_away / total,
        }
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
    return _with_metadata(result, snapshot)


def _number_from_snapshot(snapshot: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    source = _model_input(snapshot)
    for key in keys:
        value = _number(source.get(key))
        if value is not None:
            return value
    return None


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


def _poisson_matrix(lambda_home: float, lambda_away: float) -> list[dict[str, Any]]:
    raw: list[tuple[tuple[int, int], float]] = []
    for home_goals in range(MAX_GOALS_PER_TEAM + 1):
        home_p = math.exp(-lambda_home) * lambda_home ** home_goals / math.factorial(home_goals)
        for away_goals in range(MAX_GOALS_PER_TEAM + 1):
            away_p = math.exp(-lambda_away) * lambda_away ** away_goals / math.factorial(away_goals)
            raw.append(((home_goals, away_goals), home_p * away_p))
    total = sum(probability for _, probability in raw)
    rows = [
        {"score": f"{home_goals}-{away_goals}", "home_goals": home_goals, "away_goals": away_goals,
         "probability": probability / total}
        for (home_goals, away_goals), probability in raw
    ]
    return sorted(rows, key=lambda row: (-row["probability"], row["home_goals"], row["away_goals"]))


def _total_distribution(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, float] = {}
    for row in matrix:
        total = int(row["home_goals"]) + int(row["away_goals"])
        buckets[total] = buckets.get(total, 0.0) + float(row["probability"])
    return [
        {"goals": goals, "probability": probability}
        for goals, probability in sorted(buckets.items())
    ]


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

    matrix = _poisson_matrix(lambda_home, lambda_away)
    probabilities = {
        "home": sum(row["probability"] for row in matrix if row["home_goals"] > row["away_goals"]),
        "draw": sum(row["probability"] for row in matrix if row["home_goals"] == row["away_goals"]),
        "away": sum(row["probability"] for row in matrix if row["home_goals"] < row["away_goals"]),
    }
    total_distribution = _total_distribution(matrix)
    btts_yes = sum(row["probability"] for row in matrix if row["home_goals"] > 0 and row["away_goals"] > 0)
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
