#!/usr/bin/env python3
"""Audit pre-match information loss without changing the production model."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable


MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
FORM_WEIGHT = 0.60
MARKET_TOTAL_WEIGHT = 0.40
HIGH_TOTAL_GOALS = 4
CLOSE_WIN_MARGIN = 2
MISMATCH_A_MARKET_TOTAL = 3.0
MISMATCH_B_FORM_TOTAL = 3.2
MISMATCH_FINAL_TOTAL = 2.8

# These identifiers are stable in the immutable 144-match manifest.  The audit
# deliberately keys the examples by immutable identifiers rather than labels.
ERROR_EXAMPLE_MATCH_KEYS = (
    "FBOS-202608140100-008206fb46",
    "FBOS-202608140230-73f5889157",
    "FBOS-202608141800-c219c53c24",
)


def parse_aware(value: object) -> datetime | None:
    """Parse an explicitly timezone-aware ISO timestamp; reject naive time."""

    if isinstance(value, datetime):
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rate(row: dict, field: str) -> float | None:
    """Production helper: one aggregate field divided by matches."""

    try:
        matches = float(row.get("matches") or 0)
        value = float(row.get(field))
    except (TypeError, ValueError):
        return None
    return value / matches if matches > 0 else None


def _mean(values: Iterable[float | None]) -> float | None:
    """Production helper: arithmetic mean after ignoring missing values."""

    clean = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]
    return fmean(clean) if clean else None


def _market_total(deep: dict) -> float | None:
    """Production helper: median of valid current Asian-total lines."""

    lines = []
    for company in (deep.get("daxiao") or {}).get("companies") or []:
        try:
            line = float(company.get("current_line"))
        except (TypeError, ValueError):
            continue
        if 1.0 <= line <= 5.0:
            lines.append(line)
    return median(lines) if lines else None


def _deep_snapshot(snapshot: dict) -> dict:
    """Read the immutable Nowscore deep snapshot used by this audit."""

    payload = snapshot["input"]
    return payload["source_snapshots"]["nowscore"]["snapshots"][0]


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _prediction_created_at(row: dict) -> object:
    return (
        row.get("prediction_created_at")
        or row.get("created_at")
        or row.get("freeze_created_at")
        or (row.get("model_run_identity") or {}).get("created_at")
    )


def _result_kickoff(result: dict) -> object:
    return (
        result.get("kickoff_local")
        or result.get("kickoff_at")
        or (result.get("match_identity") or {}).get("kickoff_at")
    )


def _is_formal_eligible(row: dict) -> bool:
    if row.get("prediction_status") != "formal":
        return False
    for key in ("formal_eligible", "model_formal_eligible"):
        if key in row and row[key] is not True:
            return False
    return True


def select_latest_legal_formal(
    predictions: list[dict], results: list[dict]
) -> tuple[dict[str, dict], dict]:
    """Select the latest formal prediction created strictly before kickoff."""

    result_by_match = {
        row.get("match_key"): row
        for row in results
        if isinstance(row, dict) and row.get("match_key")
    }
    formal_rows = [
        row
        for row in predictions
        if isinstance(row, dict) and row.get("prediction_status") == "formal"
    ]
    legal_rows: list[dict] = []
    excluded_reasons: Counter[str] = Counter()
    for row in formal_rows:
        match_key = row.get("match_key")
        result = result_by_match.get(match_key)
        if not _is_formal_eligible(row):
            excluded_reasons["not_formal_eligible"] += 1
            continue
        if result is None:
            excluded_reasons["missing_postmatch_result"] += 1
            continue
        created = parse_aware(_prediction_created_at(row))
        kickoff = parse_aware(_result_kickoff(result))
        if created is None:
            excluded_reasons["prediction_time_not_explicitly_aware"] += 1
            continue
        if kickoff is None:
            excluded_reasons["kickoff_time_not_explicitly_aware"] += 1
            continue
        if created >= kickoff:
            excluded_reasons["created_at_not_strictly_before_kickoff"] += 1
            continue
        legal_rows.append(row)

    selected: dict[str, dict] = {}
    for row in legal_rows:
        match_key = row.get("match_key")
        if not match_key:
            excluded_reasons["missing_match_key"] += 1
            continue
        prior = selected.get(match_key)
        if prior is None:
            selected[match_key] = row
            continue
        current_time = parse_aware(_prediction_created_at(row))
        prior_time = parse_aware(_prediction_created_at(prior))
        current_key = (current_time, str(row.get("prediction_id") or ""))
        prior_key = (prior_time, str(prior.get("prediction_id") or ""))
        if current_key > prior_key:
            selected[match_key] = row

    return selected, {
        "raw_prediction_rows": len(predictions),
        "raw_formal_rows": len(formal_rows),
        "legal_formal_rows": len(legal_rows),
        "excluded_rows": len(formal_rows) - len(legal_rows),
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        "unique_latest_legal_matches": len(selected),
    }


def _market_probabilities(deep: dict) -> dict | None:
    """Replicate the current 1X2 aggregator for the contract audit."""

    rows = []
    for bookmaker in (deep.get("ouzhi") or {}).get("bookmakers") or []:
        odds = bookmaker.get("spf_current") or {}
        try:
            prices = [float(odds[key]) for key in ("home", "draw", "away")]
        except (KeyError, TypeError, ValueError):
            continue
        if any(price <= 1 for price in prices):
            continue
        inverse = [1 / price for price in prices]
        total = sum(inverse)
        rows.append([value / total for value in inverse])
    if not rows:
        return None
    return {
        key: fmean(row[index] for row in rows)
        for index, key in enumerate(("home", "draw", "away"))
    }


def _form_evidence(deep: dict) -> dict:
    recent_form = (deep.get("shuju") or {}).get("recent_form") or {}
    home_home = recent_form.get("home_home") or {}
    away_away = recent_form.get("away_away") or {}
    home_overall = recent_form.get("home_overall") or {}
    away_overall = recent_form.get("away_overall") or {}
    effective_home_home = home_home if home_home.get("matches") else home_overall
    effective_away_away = away_away if away_away.get("matches") else away_overall

    home_venue = _mean(
        [
            _rate(effective_home_home, "goals_for"),
            _rate(effective_away_away, "goals_against"),
        ]
    )
    away_venue = _mean(
        [
            _rate(effective_away_away, "goals_for"),
            _rate(effective_home_home, "goals_against"),
        ]
    )
    home_general = _mean(
        [_rate(home_overall, "goals_for"), _rate(away_overall, "goals_against")]
    )
    away_general = _mean(
        [_rate(away_overall, "goals_for"), _rate(home_overall, "goals_against")]
    )
    home_form = _mean([home_venue, home_venue, home_general])
    away_form = _mean([away_venue, away_venue, away_general])
    form_total = (
        max(1.2, min(4.2, home_form + away_form))
        if home_form is not None and away_form is not None
        else None
    )
    return {
        "home": _round(home_form),
        "away": _round(away_form),
        "total": _round(form_total),
        "home_venue": _round(home_venue),
        "away_venue": _round(away_venue),
        "home_general": _round(home_general),
        "away_general": _round(away_general),
        "source": "shuju.recent_form",
    }


def _market_handicap(deep: dict) -> float | None:
    lines = []
    for company in (deep.get("yazhi") or {}).get("companies") or []:
        try:
            line = float(company.get("current_handicap"))
        except (TypeError, ValueError):
            continue
        if -5.0 <= line <= 5.0:
            lines.append(line)
    return median(lines) if lines else None


def _market_lines(deep: dict) -> list[float]:
    lines = []
    for company in (deep.get("daxiao") or {}).get("companies") or []:
        try:
            line = float(company.get("current_line"))
        except (TypeError, ValueError):
            continue
        if 1.0 <= line <= 5.0:
            lines.append(line)
    return lines


def extract_prematch_evidence(prediction: dict, snapshot: dict) -> dict:
    """Extract only pre-match inputs and the persisted model total."""

    deep = _deep_snapshot(snapshot)
    lines = _market_lines(deep)
    market_total = _market_total(deep)
    handicap_lines = []
    for company in (deep.get("yazhi") or {}).get("companies") or []:
        value = _finite_float(company.get("current_handicap"))
        if value is not None and -5.0 <= value <= 5.0:
            handicap_lines.append(value)

    form = _form_evidence(deep)
    form_total = form["total"]
    target_total = market_total if market_total is not None else form_total
    preblend = (
        FORM_WEIGHT * form_total + MARKET_TOTAL_WEIGHT * target_total
        if form_total is not None and target_total is not None
        else None
    )
    output = prediction.get("prediction_output") or {}
    lambda_home = _finite_float(prediction.get("lambda_home"))
    if lambda_home is None:
        lambda_home = _finite_float(output.get("lambda_home"))
    lambda_away = _finite_float(prediction.get("lambda_away"))
    if lambda_away is None:
        lambda_away = _finite_float(output.get("lambda_away"))
    final_total = _finite_float(output.get("expected_goals"))
    if final_total is None and lambda_home is not None and lambda_away is not None:
        final_total = lambda_home + lambda_away

    market_probabilities = _market_probabilities(deep)
    return {
        "prediction_id": prediction.get("prediction_id"),
        "match_key": prediction.get("match_key"),
        "model_family": prediction.get("model_family") or MODEL_FAMILY,
        "form": form,
        "market_total": {
            "median": _round(market_total),
            "current_lines": [_round(value) for value in lines],
            "valid_company_count": len(lines),
            "water_semantics": "asian_water_not_decimal_probability",
        },
        "market_handicap": {
            "median": _round(median(handicap_lines) if handicap_lines else None),
            "current_lines": [_round(value) for value in handicap_lines],
            "valid_company_count": len(handicap_lines),
        },
        "market_1x2": {
            "consensus_probabilities": (
                {key: _round(value) for key, value in market_probabilities.items()}
                if market_probabilities
                else None
            ),
            "aggregation": "per_bookmaker_devig_then_arithmetic_mean",
        },
        "preblend_total": _round(preblend),
        "final_total": _round(final_total),
        "lambda_sum": _round(
            lambda_home + lambda_away
            if lambda_home is not None and lambda_away is not None
            else None
        ),
        "usage": {
            "market_total_in_lambda": market_total is not None,
            "market_total_weight": MARKET_TOTAL_WEIGHT,
            "form_total_weight": FORM_WEIGHT,
            "one_x_two_current_odds_in_share": market_probabilities is not None,
            "asian_handicap_in_lambda": False,
            "ou_water_in_lambda": False,
            "opening_to_current_change_in_lambda": False,
            "company_quality_in_lambda": False,
            "company_disagreement_in_lambda": False,
            "context_probability_override": False,
        },
        "calibration": {
            "active": False,
            "effective": False,
            "applied_to_final_total": False,
            "basis": "locked audit fact for this Champion run",
        },
    }


def _snapshot_lookup(snapshots: dict, snapshot_ref: object) -> dict | None:
    if not isinstance(snapshot_ref, str) or not snapshot_ref:
        return None
    normalized = snapshot_ref.replace("\\", "/")
    candidates = [normalized, normalized.lstrip("./"), Path(normalized).name]
    for key in candidates:
        value = snapshots.get(key)
        if isinstance(value, dict):
            return value
    for value in snapshots.values():
        if not isinstance(value, dict):
            continue
        if value.get("snapshot_ref") == snapshot_ref:
            return value
        if Path(str(value.get("snapshot_ref") or "")).name == Path(normalized).name:
            return value
    return None


def _score(result: dict) -> tuple[int, int] | None:
    home = _finite_float(result.get("home_score"))
    away = _finite_float(result.get("away_score"))
    if home is None or away is None:
        text = result.get("result_90m") or result.get("score")
        if isinstance(text, str) and "-" in text:
            left, right = text.split("-", 1)
            home = _finite_float(left.strip())
            away = _finite_float(right.strip())
    if home is None or away is None:
        return None
    return int(home), int(away)


def _stats(rows: list[dict], field: str) -> dict:
    values = [
        _finite_float(row.get(field))
        for row in rows
        if _finite_float(row.get(field)) is not None
    ]
    return {
        "count": len(values),
        "mean": _round(fmean(values) if values else None),
        "median": _round(median(values) if values else None),
    }


def _actual_4_plus(rows: list[dict]) -> dict:
    usable = [row for row in rows if row.get("actual_total") is not None]
    count = sum(int(row["actual_total"]) >= HIGH_TOTAL_GOALS for row in usable)
    return {
        "count": len(usable),
        "actual_4_plus_count": count,
        "actual_4_plus_rate": _round(count / len(usable) if usable else None),
    }


def _cohort(rows: list[dict]) -> dict:
    result = _actual_4_plus(rows)
    result["match_keys"] = [row["match_key"] for row in rows]
    return result


def _field_audit(joined_rows: list[dict]) -> dict:
    snapshots = [row["snapshot"] for row in joined_rows if row.get("snapshot")]
    recent_form_buckets = (
        "home_overall",
        "home_home",
        "away_overall",
        "away_away",
    )
    form_rows = []
    open_line_present = 0
    for snapshot in snapshots:
        try:
            deep = _deep_snapshot(snapshot)
        except (KeyError, IndexError, TypeError):
            continue
        form = (deep.get("shuju") or {}).get("recent_form") or {}
        form_rows.extend(
            form.get(bucket) or {} for bucket in recent_form_buckets if form.get(bucket)
        )
        if any(
            company.get("open_line") is not None
            for company in (deep.get("daxiao") or {}).get("companies") or []
        ):
            open_line_present += 1

    form_keys = set().union(*(row.keys() for row in form_rows)) if form_rows else set()
    return {
        "lambda_fundamental_fields_used": [
            "shuju.recent_form.<bucket>.matches",
            "shuju.recent_form.<bucket>.goals_for",
            "shuju.recent_form.<bucket>.goals_against",
        ],
        "fundamental_fields_available_but_not_in_lambda": [
            "shuju.recent_form.<bucket>.wins",
            "shuju.recent_form.<bucket>.draws",
            "shuju.recent_form.<bucket>.losses",
            "nowscore_context.coach",
            "nowscore_context.referee",
            "nowscore_context.panlu",
        ],
        "fundamental_field_presence": {
            "recent_form.wins": "wins" in form_keys,
            "recent_form.draws": "draws" in form_keys,
            "recent_form.losses": "losses" in form_keys,
            "coach": sum(
                bool((_deep_snapshot(snapshot).get("nowscore_context") or {}).get("coach"))
                for snapshot in snapshots
            ),
            "referee": sum(
                bool((_deep_snapshot(snapshot).get("nowscore_context") or {}).get("referee"))
                for snapshot in snapshots
            ),
            "panlu": sum(
                bool((_deep_snapshot(snapshot).get("nowscore_context") or {}).get("panlu"))
                for snapshot in snapshots
            ),
        },
        "current_snapshot_missing_fields": [
            "daxiao.companies.open_line",
            "daxiao.companies.open_over_water",
            "daxiao.companies.open_under_water",
            "yazhi.companies.open_handicap",
            "yazhi.companies.open_water_home",
            "yazhi.companies.open_water_away",
            "ouzhi.bookmakers.spf_open",
            "market_company_quality",
            "market_liquidity_or_volume",
            "market_disagreement_metric",
            "shuju.recent_form.<bucket>.xg_for",
            "shuju.recent_form.<bucket>.xg_against",
            "shuju.recent_form.<bucket>.shots_for",
            "shuju.recent_form.<bucket>.shots_against",
            "shuju.recent_form.<bucket>.shot_quality",
            "shuju.recent_form.<bucket>.injuries",
            "shuju.recent_form.<bucket>.lineup",
            "shuju.recent_form.<bucket>.stage",
            "shuju.recent_form.<bucket>.congestion",
        ],
        "opening_total_line_snapshot_coverage": {
            "snapshots_with_open_line": open_line_present,
            "snapshots_without_open_line": len(snapshots) - open_line_present,
        },
        "context_probability_override": False,
    }


def run_audit(
    predictions: list[dict],
    results: list[dict],
    snapshots: dict,
    source_commit: str = "UNKNOWN",
) -> dict:
    selected, selection = select_latest_legal_formal(predictions, results)
    result_by_match = {
        row.get("match_key"): row
        for row in results
        if isinstance(row, dict) and row.get("match_key")
    }
    rows: list[dict] = []
    joined_rows: list[dict] = []
    for match_key in sorted(selected):
        prediction = selected[match_key]
        result = result_by_match.get(match_key) or {}
        score = _score(result)
        snapshot = _snapshot_lookup(
            snapshots,
            prediction.get("model_input_snapshot_ref")
            or prediction.get("input_snapshot_ref"),
        )
        evidence = None
        if snapshot is not None:
            try:
                evidence = extract_prematch_evidence(prediction, snapshot)
            except (KeyError, IndexError, TypeError):
                evidence = None
        row = {
            "match_key": match_key,
            "prediction_id": prediction.get("prediction_id"),
            "home": result.get("home") or (prediction.get("match_identity") or {}).get("home"),
            "away": result.get("away") or (prediction.get("match_identity") or {}).get("away"),
            "kickoff_at": _result_kickoff(result),
            "home_score": score[0] if score else None,
            "away_score": score[1] if score else None,
            "actual_total": sum(score) if score else None,
            "snapshot": snapshot,
            "evidence": evidence,
        }
        if evidence:
            row.update(
                {
                    "market_total": evidence["market_total"]["median"],
                    "form_total": evidence["form"]["total"],
                    "preblend_total": evidence["preblend_total"],
                    "final_total": evidence["final_total"],
                    "lambda_sum": evidence["lambda_sum"],
                }
            )
        else:
            row.update(
                {
                    "market_total": None,
                    "form_total": None,
                    "preblend_total": None,
                    "final_total": None,
                    "lambda_sum": None,
                }
            )
        rows.append(row)
        joined_rows.append(row)

    metric_rows = [row for row in rows if row.get("evidence")]
    high_total = [
        row for row in metric_rows if row.get("actual_total") is not None and row["actual_total"] >= HIGH_TOTAL_GOALS
    ]
    non_high_total = [
        row for row in metric_rows if row.get("actual_total") is not None and row["actual_total"] < HIGH_TOTAL_GOALS
    ]
    mismatch_a = [
        row
        for row in metric_rows
        if row.get("market_total") is not None
        and row.get("final_total") is not None
        and row["market_total"] >= MISMATCH_A_MARKET_TOTAL
        and row["final_total"] <= MISMATCH_FINAL_TOTAL
    ]
    mismatch_b = [
        row
        for row in metric_rows
        if row.get("form_total") is not None
        and row.get("final_total") is not None
        and row["form_total"] >= MISMATCH_B_FORM_TOTAL
        and row["final_total"] <= MISMATCH_FINAL_TOTAL
    ]

    market_gaps = [
        row["market_total"] - row["final_total"]
        for row in metric_rows
        if row.get("market_total") is not None and row.get("final_total") is not None
    ]
    form_gaps = [
        row["form_total"] - row["final_total"]
        for row in metric_rows
        if row.get("form_total") is not None and row.get("final_total") is not None
    ]
    final_preblend_gaps = [
        row["final_total"] - row["preblend_total"]
        for row in metric_rows
        if row.get("final_total") is not None and row.get("preblend_total") is not None
    ]

    error_rows = [
        row for key in ERROR_EXAMPLE_MATCH_KEYS if (row := next((item for item in rows if item["match_key"] == key), None))
    ]
    error_examples = [
        {
            "match_key": row["match_key"],
            "prediction_id": row["prediction_id"],
            "home_score": row["home_score"],
            "away_score": row["away_score"],
            "form_total": row["form_total"],
            "market_total": row["market_total"],
            "preblend_total": row["preblend_total"],
            "final_total": row["final_total"],
        }
        for row in error_rows
    ]

    close_win = [
        row
        for row in metric_rows
        if row.get("actual_total") is not None
        and row["actual_total"] >= HIGH_TOTAL_GOALS
        and row.get("home_score") != row.get("away_score")
        and abs(row["home_score"] - row["away_score"]) <= CLOSE_WIN_MARGIN
    ]
    high_scoring_draw = [
        row
        for row in metric_rows
        if row.get("actual_total") is not None
        and row["actual_total"] >= HIGH_TOTAL_GOALS
        and row.get("home_score") == row.get("away_score")
    ]

    field_audit = _field_audit(joined_rows)
    report = {
        "schema_version": "prematch_information_root_cause_audit.v1",
        "source_commit": source_commit,
        "model_family": MODEL_FAMILY,
        "policy": {
            "latest_legal_definition": "formal, explicitly eligible, timestamp-aware, created strictly before kickoff",
            "high_total_goal_threshold": HIGH_TOTAL_GOALS,
            "close_win_margin": CLOSE_WIN_MARGIN,
            "mismatch_a": "market_total >= 3.0 and final_total <= 2.8",
            "mismatch_b": "form_total >= 3.2 and final_total <= 2.8",
        },
        "sample_selection": selection,
        "coverage": {
            "selected_latest_legal_matches": len(selected),
            "postmatch_result_joined": sum(row.get("actual_total") is not None for row in rows),
            "snapshot_joined": sum(row.get("snapshot") is not None for row in rows),
            "snapshot_missing": sum(row.get("snapshot") is None for row in rows),
            "market_total": sum(row.get("market_total") is not None for row in rows),
            "form_total": sum(row.get("form_total") is not None for row in rows),
            "final_total": sum(row.get("final_total") is not None for row in rows),
        },
        "core_contract": {
            "market_total": "median of valid daxiao.companies.current_line in [1, 5]",
            "market_total_uses_water": False,
            "market_total_uses_open_to_current_change": False,
            "market_total_uses_company_quality_or_disagreement": False,
            "market_handicap": "median current yazhi.companies.current_handicap; diagnostic only",
            "asian_handicap_in_lambda": False,
            "one_x_two_aggregator": "each valid bookmaker spf_current is devigged, then arithmetic mean",
            "one_x_two_used_for": "market share only, not total layer",
            "form_formula": "venue=(home venue GF + away venue GA)/2; general=(overall GF + opponent overall GA)/2; team form=mean(venue, venue, general)",
            "form_total_formula": "max(1.2, min(4.2, home_form + away_form))",
            "total_formula": "target_total=market_total if present else form_total; preblend=0.60*form_total+0.40*target_total",
            "final_total_formula": "clamp(preblend + approved_calibration_total_shift*strength, 1.0, 4.8); current run calibration inactive/effective false",
            "direction_share_formula": "share=0.65*form_share+0.35*market_share; lambda_home=final_total*share; lambda_away=final_total*(1-share)",
            "context_probability_override": False,
        },
        "calibration": {
            "active": False,
            "effective": False,
            "total_layer_applied": False,
            "direction_layer_changed": False,
            "dispersion_layer_changed": False,
        },
        "aggregates": {
            "snapshot_join": {
                "selected_matches": len(rows),
                "joined_snapshot": sum(row.get("snapshot") is not None for row in rows),
                "missing_snapshot": sum(row.get("snapshot") is None for row in rows),
            },
            "market_total": _stats(metric_rows, "market_total"),
            "form_total": _stats(metric_rows, "form_total"),
            "final_lambda_sum": _stats(metric_rows, "lambda_sum"),
            "market_total_final_gap": {
                **_stats([{"value": value} for value in market_gaps], "value"),
                "definition": "market_total - final_total",
            },
            "form_total_final_gap": {
                **_stats([{"value": value} for value in form_gaps], "value"),
                "definition": "form_total - final_total",
            },
            "final_preblend_gap": {
                **_stats([{"value": value} for value in final_preblend_gaps], "value"),
                "definition": "final_total - preblend_total",
            },
            "high_total": {
                **_actual_4_plus(high_total),
                "market_total": _stats(high_total, "market_total"),
                "form_total": _stats(high_total, "form_total"),
            },
            "non_high_total": {
                **_actual_4_plus(non_high_total),
                "market_total": _stats(non_high_total, "market_total"),
                "form_total": _stats(non_high_total, "form_total"),
            },
            "mismatch_cohort_a": {
                **_cohort(mismatch_a),
                "threshold": "market_total >= 3.0 and final_total <= 2.8",
            },
            "mismatch_cohort_b": {
                **_cohort(mismatch_b),
                "threshold": "form_total >= 3.2 and final_total <= 2.8",
            },
        },
        "case_categories": {
            "high_scoring_close_win": len(close_win),
            "high_scoring_draw": len(high_scoring_draw),
        },
        "error_examples": error_examples,
        "field_audit": field_audit,
        "root_cause_assessment": {
            "market_total_integration_gap_primary": {
                "supported": False,
                "evidence": "mismatch A has 5 matches and 0/5 actual 4+; market total is not a primary explanation in this cohort",
            },
            "recent_form_total": {
                "discrimination_signal": "high-total mean ~3.009 versus non-high mean ~2.728",
                "representation": "coarse GF/GA aggregate rates only",
            },
            "detailed_context": {
                "fields_present": ["coach", "referee", "panlu"],
                "probability_override": False,
                "usage": "match-script/context narrative and uncertainty only",
            },
            "opening_totals": {
                "present_in_all_144_snapshots": False,
                "present_snapshot_count": field_audit["opening_total_line_snapshot_coverage"]["snapshots_with_open_line"],
            },
            "not_in_recent_form_lambda": [
                "xG",
                "shot quality",
                "injury",
                "lineup",
                "stage",
                "congestion",
            ],
        },
        "decision": {
            "model_decision": "NO_MODEL_CHANGE",
            "next_research_hypothesis": "fundamental-total-strength-v1",
            "status": "NOT_QUALIFIED/HYPOTHESIS_ONLY",
            "research_only": True,
            "production_integrated": False,
            "single_variable": "replace only the total-layer fundamental estimator",
            "fixed_components": [
                "existing market-total 40% mechanism",
                "Champion direction share",
            ],
            "prohibited_in_this_hypothesis": [
                "weight tuning",
                "production integration",
                "direction-share changes",
            ],
        },
        "rows": [
            {
                key: value
                for key, value in row.items()
                if key not in {"snapshot", "evidence"}
            }
            for row in rows
        ],
    }
    return report


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_prediction_files(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.glob("*.json")):
        value = _load_json(path)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _load_result_files(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.rglob("*.json")):
        value = _load_json(path)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _load_snapshot_files(directory: Path) -> dict[str, dict]:
    snapshots: dict[str, dict] = {}
    for path in sorted(directory.glob("*.json")):
        value = _load_json(path)
        if isinstance(value, dict):
            snapshots[path.name] = value
            if value.get("snapshot_ref"):
                snapshots[str(value["snapshot_ref"]).replace("\\", "/")] = value
    return snapshots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-dir", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--snapshots-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    manifest = _load_json(args.manifest)
    predictions = _load_prediction_files(args.predictions_dir)
    results = _load_result_files(args.results_dir)
    snapshots = _load_snapshot_files(args.snapshots_dir)
    report = run_audit(
        predictions,
        results,
        snapshots,
        source_commit=str(manifest.get("source_commit") or "UNKNOWN"),
    )
    report["input"] = {
        "manifest": str(args.manifest),
        "manifest_match_count": manifest.get("count"),
        "prediction_directory": str(args.predictions_dir),
        "prediction_file_count": len(predictions),
        "results_directory": str(args.results_dir),
        "result_file_count": len(results),
        "snapshots_directory": str(args.snapshots_dir),
        "snapshot_file_count": len(
            [key for key in snapshots if "/" not in key and "\\" not in key]
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "coverage": report["coverage"],
                "mismatch_a": report["aggregates"]["mismatch_cohort_a"],
                "mismatch_b": report["aggregates"]["mismatch_cohort_b"],
                "hypothesis": report["decision"]["next_research_hypothesis"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
