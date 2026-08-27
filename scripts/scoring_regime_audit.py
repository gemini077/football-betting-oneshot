#!/usr/bin/env python3
"""Read-only audit of recent verified 90-minute scoring regimes.

The audit deliberately keeps result truth separate from prematch prediction
selection.  It uses stored total-goal probabilities and stored settlement
metrics when available; it never reconstructs a Champion score matrix from
lambdas.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import random
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "scoring_regime_audit.v1"
BOOTSTRAP_SEED = 20260827
BOOTSTRAP_RESAMPLES = 10000
CLOSE_WIN_MAX_MARGIN = 2
RESULT_SCOPE = "regulation_90m_plus_stoppage"
_SCORE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def parse_aware(value: Any) -> dt.datetime | None:
    """Return an aware datetime, rejecting naive timestamps."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def classify_score(home_score: int, away_score: int) -> dict[str, Any]:
    """Apply the fixed scoring-regime definitions."""

    total = home_score + away_score
    margin = abs(home_score - away_score)
    draw = home_score == away_score
    return {
        "home_score": home_score,
        "away_score": away_score,
        "total_goals": total,
        "goal_margin": margin,
        "high_total": total >= 4,
        "big_margin_win": not draw and margin >= 3,
        "high_scoring_draw": draw and total >= 4,
        "high_scoring_close_win": not draw and total >= 4 and margin <= CLOSE_WIN_MAX_MARGIN,
    }


def _parse_score(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _SCORE_RE.match(value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _result_row(raw: dict[str, Any], source_file: str) -> tuple[dict[str, Any] | None, str | None]:
    match_key = raw.get("match_key")
    if not isinstance(match_key, str) or not match_key.strip():
        return None, "missing_match_key"
    kickoff = parse_aware(raw.get("kickoff_local"))
    if kickoff is None:
        return None, "invalid_or_naive_kickoff"
    if raw.get("scope") != RESULT_SCOPE:
        return None, "not_verified_90m_scope"
    home_score = raw.get("home_score")
    away_score = raw.get("away_score")
    if (
        isinstance(home_score, bool)
        or not isinstance(home_score, int)
        or isinstance(away_score, bool)
        or not isinstance(away_score, int)
        or home_score < 0
        or away_score < 0
    ):
        return None, "invalid_score_fields"
    parsed_score = _parse_score(raw.get("result_90m"))
    if parsed_score != (home_score, away_score):
        return None, "result_90m_mismatch"
    verified = parse_aware(raw.get("verified_at"))
    row = {
        "match_key": match_key.strip(),
        "kickoff": kickoff,
        "date": kickoff.date(),
        "home": raw.get("home"),
        "away": raw.get("away"),
        "home_score": home_score,
        "away_score": away_score,
        "result_90m": raw.get("result_90m"),
        "scope": raw.get("scope"),
        "verification_quality": raw.get("verification_quality"),
        "source_file": source_file,
        "verified_at": verified,
    }
    row.update(classify_score(home_score, away_score))
    return row, None


def load_verified_results(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    rows: list[dict[str, Any]] = []
    reason_counts: collections.Counter[str] = collections.Counter()
    paths = sorted(root.glob("*.json")) if root.is_dir() else []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reason_counts["invalid_json"] += 1
            continue
        if not isinstance(raw, dict):
            reason_counts["non_object"] += 1
            continue
        row, reason = _result_row(raw, path.name)
        if row is None:
            reason_counts[reason or "invalid"] += 1
        else:
            rows.append(row)
    return {
        "rows": rows,
        "raw_file_count": len(paths),
        "valid_row_count": len(rows),
        "invalid_row_count": sum(reason_counts.values()),
        "invalid_reason_counts": dict(sorted(reason_counts.items())),
    }


def dedupe_results(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    missing_identity = 0
    for row in rows:
        key = row.get("match_key")
        if not isinstance(key, str) or not key:
            missing_identity += 1
            continue
        groups[key].append(row)
    selected: list[dict[str, Any]] = []
    duplicate_rows = 0
    duplicate_groups = 0
    conflict_match_count = 0
    for key, group in groups.items():
        signatures = {(x.get("home_score"), x.get("away_score"), x.get("kickoff")) for x in group}
        if len(signatures) > 1:
            conflict_match_count += 1
            continue
        if len(group) > 1:
            duplicate_groups += 1
            duplicate_rows += len(group) - 1
        selected.append(
            max(
                group,
                key=lambda x: (
                    x.get("verified_at") or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                    str(x.get("source_file", "")),
                ),
            )
        )
    return {
        "rows": sorted(selected, key=lambda x: (x["date"], x["match_key"])),
        "unique_match_count": len(selected),
        "duplicate_groups": duplicate_groups,
        "duplicate_rows": duplicate_rows,
        "conflict_match_count": conflict_match_count,
        "missing_identity_count": missing_identity,
    }


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(x) for x in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def summarize_window(rows: Iterable[dict[str, Any]], label: str, start: str, end: str) -> dict[str, Any]:
    rows = list(rows)
    totals = [int(row["home_score"]) + int(row["away_score"]) for row in rows]
    scores = collections.Counter(f"{row['home_score']}-{row['away_score']}" for row in rows)
    counts = {
        "high_total": sum(bool(row.get("high_total", int(row["home_score"]) + int(row["away_score"]) >= 4)) for row in rows),
        "big_margin_win": sum(bool(row.get("big_margin_win", abs(int(row["home_score"]) - int(row["away_score"])) >= 3 and row["home_score"] != row["away_score"])) for row in rows),
        "high_scoring_draw": sum(bool(row.get("high_scoring_draw", row["home_score"] == row["away_score"] and int(row["home_score"]) + int(row["away_score"]) >= 4)) for row in rows),
        "high_scoring_close_win": sum(bool(row.get("high_scoring_close_win", row["home_score"] != row["away_score"] and int(row["home_score"]) + int(row["away_score"]) >= 4 and abs(int(row["home_score"]) - int(row["away_score"])) <= CLOSE_WIN_MAX_MARGIN)) for row in rows),
    }
    total_bins = {
        "0-2": sum(total <= 2 for total in totals),
        "3": sum(total == 3 for total in totals),
        "4": sum(total == 4 for total in totals),
        "5+": sum(total >= 5 for total in totals),
    }
    n = len(rows)
    shares = lambda mapping: {key: (value / n if n else None) for key, value in mapping.items()}
    date_values = [row["date"] if isinstance(row["date"], dt.date) else dt.date.fromisoformat(str(row["date"])) for row in rows]
    return {
        "label": label,
        "start": start,
        "end": end,
        "n": n,
        "date_min": str(min(date_values)) if date_values else None,
        "date_max": str(max(date_values)) if date_values else None,
        "observed_days": len(set(date_values)),
        "mean_total_goals": _mean(totals),
        "median_total_goals": _quantile(totals, 0.5),
        "total_goal_quantiles": {"p25": _quantile(totals, 0.25), "p75": _quantile(totals, 0.75), "p90": _quantile(totals, 0.90)},
        "total_bins": {key: {"count": value, "share": value / n if n else None} for key, value in total_bins.items()},
        "counts": counts,
        "shares": shares(counts),
        "event_rates": {
            "total_ge_4": sum(total >= 4 for total in totals) / n if n else None,
            "total_ge_5": sum(total >= 5 for total in totals) / n if n else None,
            "total_ge_6": sum(total >= 6 for total in totals) / n if n else None,
        },
        "score_counts": dict(sorted(scores.items(), key=lambda item: (int(item[0].split("-")[0]), int(item[0].split("-")[1])))),
    }


def bootstrap_proportion_difference(
    recent_values: Iterable[Any],
    prior_values: Iterable[Any],
    *,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
    comparison_label: str = "recent_minus_prior",
) -> dict[str, Any] | None:
    recent = [float(bool(value)) if isinstance(value, bool) else float(value) for value in recent_values]
    prior = [float(bool(value)) if isinstance(value, bool) else float(value) for value in prior_values]
    if not recent or not prior:
        return None
    point = sum(recent) / len(recent) - sum(prior) / len(prior)
    rng = random.Random(seed)
    differences: list[float] = []
    for _ in range(resamples):
        recent_mean = sum(recent[rng.randrange(len(recent))] for _ in recent) / len(recent)
        prior_mean = sum(prior[rng.randrange(len(prior))] for _ in prior) / len(prior)
        differences.append(recent_mean - prior_mean)
    return {
        "comparison_label": comparison_label,
        "point_difference": point,
        "ci95": [_quantile(differences, 0.025), _quantile(differences, 0.975)],
        "seed": seed,
        "resamples": resamples,
    }


def _formal_flag(record: dict[str, Any]) -> bool:
    return bool(record.get("formal_eligible") or record.get("model_formal_eligible"))


def _freeze_time(record: dict[str, Any]) -> dt.datetime | None:
    for field in ("freeze_created_at", "prediction_created_at", "created_at"):
        if record.get(field) not in (None, ""):
            return parse_aware(record.get(field))
    return None


def select_latest_legal_formal(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    raw_formal_count = sum(_formal_flag(record) for record in records)
    invalid_reasons: collections.Counter[str] = collections.Counter()
    legal: list[dict[str, Any]] = []
    for record in records:
        if not _formal_flag(record):
            continue
        if record.get("model_role") != "champion":
            invalid_reasons["non_champion"] += 1
            continue
        match_key = record.get("match_key")
        if not isinstance(match_key, str) or not match_key.strip():
            invalid_reasons["missing_match_key"] += 1
            continue
        kickoff = parse_aware(record.get("kickoff_at"))
        frozen = _freeze_time(record)
        if kickoff is None:
            invalid_reasons["invalid_or_naive_kickoff"] += 1
            continue
        if frozen is None:
            invalid_reasons["invalid_or_naive_freeze_time"] += 1
            continue
        if frozen >= kickoff:
            invalid_reasons["after_kickoff_freeze"] += 1
            continue
        selected = dict(record)
        selected["_kickoff_dt"] = kickoff
        selected["_freeze_dt"] = frozen
        legal.append(selected)
    by_match: dict[str, dict[str, Any]] = {}
    for record in legal:
        key = record["match_key"]
        current = by_match.get(key)
        rank = (record["_freeze_dt"], str(record.get("prediction_id", "")))
        current_rank = (current["_freeze_dt"], str(current.get("prediction_id", ""))) if current else None
        if current is None or rank > current_rank:
            by_match[key] = record
    return {
        "records": by_match,
        "raw_formal_eligible_count": raw_formal_count,
        "legal_record_count": len(legal),
        "unique_match_count": len(by_match),
        "superseded_record_count": len(legal) - len(by_match),
        "invalid_record_count": sum(invalid_reasons.values()),
        "invalid_reason_counts": dict(sorted(invalid_reasons.items())),
    }


def load_json_records(root: str | Path) -> list[dict[str, Any]]:
    root = Path(root)
    result = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    result = []
    path = Path(path)
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _total_probabilities(record: dict[str, Any]) -> dict[str, float] | None:
    values: dict[str, float] = {}
    for item in record.get("totals", []) if isinstance(record.get("totals"), list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("goals"))
        number = _number(item.get("probability"))
        if key in {"0", "1", "2", "3", "4", "5", "6+"} and number is not None:
            values[key] = number
    required = {"0", "1", "2", "3", "4", "5", "6+"}
    return values if required.issubset(values) else None


def _metric(record: dict[str, Any] | None, name: str) -> float | None:
    if not record:
        return None
    return _number((record.get("metrics") or {}).get(name))


def _model_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    actual_totals = [row["actual_total"] for row in rows]
    predicted_lambdas = [row["lambda_sum"] for row in rows]
    def mean_field(name: str) -> float | None:
        values = [row[name] for row in rows if row.get(name) is not None]
        return _mean(values)
    def rate(predicate) -> float | None:
        return sum(predicate(row) for row in rows) / n if n else None
    return {
        "n": n,
        "actual_total_mean": _mean(actual_totals),
        "predicted_lambda_sum_mean": _mean(predicted_lambdas),
        "actual_minus_predicted_mean": (_mean(actual_totals) - _mean(predicted_lambdas)) if rows else None,
        "total_mae": _mean(abs(row["actual_total"] - row["lambda_sum"]) for row in rows),
        "actual_event_rates": {
            "total_ge_4": rate(lambda row: row["actual_total"] >= 4),
            "total_ge_5": rate(lambda row: row["actual_total"] >= 5),
            "total_ge_6": rate(lambda row: row["actual_total"] >= 6),
        },
        "predicted_tail_probability_mean": {
            "total_ge_4": mean_field("p_ge_4"),
            "total_ge_5": mean_field("p_ge_5"),
            "total_ge_6": mean_field("p_ge_6"),
        },
        "tail_calibration_gap_predicted_minus_actual": {
            "total_ge_4": (mean_field("p_ge_4") - rate(lambda row: row["actual_total"] >= 4)) if rows and mean_field("p_ge_4") is not None else None,
            "total_ge_5": (mean_field("p_ge_5") - rate(lambda row: row["actual_total"] >= 5)) if rows and mean_field("p_ge_5") is not None else None,
            "total_ge_6": (mean_field("p_ge_6") - rate(lambda row: row["actual_total"] >= 6)) if rows and mean_field("p_ge_6") is not None else None,
        },
        "brier_mean": mean_field("brier"),
        "log_loss_mean": mean_field("log_loss"),
        "1x2_top1_rate": mean_field("outcome_top1"),
        "exact_top1_rate": rate(lambda row: row["exact_top1"]),
        "exact_top3_rate": rate(lambda row: row["exact_top3"]),
        "top1_1_1_share": rate(lambda row: row["predicted_top1"] == "1-1"),
        "actual_score_nll_mean": mean_field("actual_score_nll"),
        "actual_score_nll_supported_count": sum(row.get("actual_score_nll") is not None for row in rows),
        "total_goals_nll_mean": mean_field("total_goals_nll"),
        "total_goals_nll_supported_count": sum(row.get("total_goals_nll") is not None for row in rows),
    }


def _build_model_rows(
    selection: dict[str, Any],
    results_by_match: dict[str, dict[str, Any]],
    ledger_by_prediction: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for match_key, prediction in selection["records"].items():
        result = results_by_match.get(match_key)
        if not result:
            continue
        home = int(result["home_score"])
        away = int(result["away_score"])
        totals = _total_probabilities(prediction)
        if totals is None:
            continue
        prediction_id = prediction.get("prediction_id")
        ledger = ledger_by_prediction.get(prediction_id)
        metrics = (ledger or {}).get("metrics") or {}
        actual_score = f"{home}-{away}"
        top3 = prediction.get("score_top3") if isinstance(prediction.get("score_top3"), list) else []
        rows.append(
            {
                "match_key": match_key,
                "date": result["date"],
                "home": result.get("home"),
                "away": result.get("away"),
                "actual_score": actual_score,
                "actual_total": home + away,
                "predicted_top1": prediction.get("score_top1"),
                "predicted_top3": top3,
                "exact_top1": prediction.get("score_top1") == actual_score,
                "exact_top3": actual_score in top3,
                "lambda_sum": float(prediction.get("lambda_home", 0)) + float(prediction.get("lambda_away", 0)),
                "p_ge_4": totals["4"] + totals["5"] + totals["6+"],
                "p_ge_5": totals["5"] + totals["6+"],
                "p_ge_6": totals["6+"],
                "brier": _number(metrics.get("brier_score_1x2")),
                "log_loss": _number(metrics.get("log_loss_1x2")),
                "outcome_top1": _number(metrics.get("top1_accuracy_1x2")),
                "actual_score_nll": _number(metrics.get("actual_score_nll")),
                "total_goals_nll": _number(metrics.get("total_goals_nll")),
                "high_total": result["high_total"],
                "big_margin_win": result["big_margin_win"],
                "high_scoring_draw": result["high_scoring_draw"],
                "high_scoring_close_win": result["high_scoring_close_win"],
            }
        )
    return sorted(rows, key=lambda row: (row["date"], row["match_key"]))


def diagnose_champion(
    prediction_root: str | Path,
    ledger_path: str | Path | None,
    results_by_match: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    predictions = load_json_records(prediction_root)
    selection = select_latest_legal_formal(predictions)
    ledger_rows = load_jsonl(ledger_path) if ledger_path else []
    ledger_by_id = {row.get("prediction_id"): row for row in ledger_rows if row.get("prediction_id")}
    model_rows = _build_model_rows(selection, results_by_match, ledger_by_id)
    subgroup_names = ["high_total", "big_margin_win", "high_scoring_draw", "high_scoring_close_win"]
    subgroups = {
        name: _model_summary([row for row in model_rows if row[name]]) for name in subgroup_names
    }
    ordered = sorted(model_rows, key=lambda row: (row["date"], row["match_key"]))
    half = len(ordered) // 2
    blocks = {
        "early_half": _model_summary(ordered[:half]),
        "late_half": _model_summary(ordered[half:]),
        "last_7_days": _model_summary([row for row in ordered if row["date"] >= max((x["date"] for x in ordered), default=dt.date.min) - dt.timedelta(days=6)]),
    }
    examples = []
    for row in sorted(model_rows, key=lambda x: (not x["high_total"], x["match_key"])):
        if len(examples) >= 6:
            break
        examples.append({key: (str(value) if isinstance(value, dt.date) else value) for key, value in row.items() if key in {"match_key", "home", "away", "date", "actual_score", "predicted_top1", "lambda_sum", "p_ge_4", "high_total", "big_margin_win", "high_scoring_draw", "high_scoring_close_win"}})
    return {
        "selection_policy": "formal Champion records; latest legal freeze_created_at, fallback prediction_created_at/created_at; strict aware freeze < kickoff; prediction_id tie-break",
        "formal_prediction_file_count": len(predictions),
        "raw_formal_eligible_count": selection["raw_formal_eligible_count"],
        "legal_formal_record_count": selection["legal_record_count"],
        "unique_formal_match_count": selection["unique_match_count"],
        "superseded_formal_record_count": selection["superseded_record_count"],
        "invalid_formal_record_count": selection["invalid_record_count"],
        "invalid_formal_reason_counts": selection["invalid_reason_counts"],
        "matched_result_count": len(model_rows),
        "unmatched_selected_formal_count": selection["unique_match_count"] - len(model_rows),
        "stored_total_probability_supported_count": len(model_rows),
        "stored_score_distribution_shape": {"top10_rows": sum(len(selection["records"][row["match_key"]].get("score_distribution", [])) == 10 for row in model_rows), "full_matrix_rows": sum(len(selection["records"][row["match_key"]].get("score_distribution", [])) > 10 for row in model_rows)},
        "full_score_matrix_used": False,
        "summary": _model_summary(model_rows),
        "subgroups": subgroups,
        "time_blocks": blocks,
        "examples": examples,
    }


def _shadow_source_id(record: dict[str, Any]) -> str | None:
    value = record.get("source_champion_prediction_id")
    if isinstance(value, str) and value:
        return value
    ref = record.get("source_champion_prediction_ref")
    if isinstance(ref, str) and ref:
        return Path(ref).stem
    return None


def shadow_state(
    shadow_prediction_root: str | Path | None,
    shadow_settlement_root: str | Path | None,
    champion_records: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    if not shadow_prediction_root:
        return None
    champions = {record.get("prediction_id"): record for record in champion_records if record.get("prediction_id")}
    shadows = load_json_records(shadow_prediction_root)
    invalid_reasons: collections.Counter[str] = collections.Counter()
    valid = 0
    isolation_failures = collections.Counter()
    for shadow in shadows:
        source = champions.get(_shadow_source_id(shadow))
        shadow_time = parse_aware(shadow.get("shadow_created_at"))
        kickoff = parse_aware(shadow.get("kickoff_at"))
        champion_time = _freeze_time(source or {})
        if source is None:
            invalid_reasons["missing_source_champion"] += 1
        elif shadow_time is None or kickoff is None:
            invalid_reasons["invalid_shadow_or_kickoff_time"] += 1
        elif champion_time is None or not (champion_time <= shadow_time < kickoff):
            invalid_reasons["not_strictly_prematch_after_champion"] += 1
        else:
            valid += 1
        if shadow.get("prospective_shadow") is not True:
            isolation_failures["prospective_shadow"] += 1
        if shadow.get("user_visible") is not False:
            isolation_failures["user_visible"] += 1
        if shadow.get("formal_eligible") is not False:
            isolation_failures["formal_eligible"] += 1
        if shadow.get("primary_benchmark_eligible") is not False:
            isolation_failures["primary_benchmark_eligible"] += 1
        if shadow.get("changed_variables") != ["market_direction_fusion"]:
            isolation_failures["changed_variables"] += 1
    settlements = load_json_records(shadow_settlement_root) if shadow_settlement_root else []
    by_comparison = {record.get("comparison_id"): record for record in shadows if record.get("comparison_id")}
    settlement_valid = 0
    settlement_informal = 0
    settlement_matches: set[str] = set()
    for settlement in settlements:
        shadow = by_comparison.get(settlement.get("comparison_id"))
        timing_ok = False
        if shadow:
            source = champions.get(_shadow_source_id(shadow))
            st = parse_aware(shadow.get("shadow_created_at"))
            kt = parse_aware(shadow.get("kickoff_at"))
            ct = _freeze_time(source or {})
            timing_ok = bool(source and st and kt and ct and ct <= st < kt)
        if timing_ok and settlement.get("comparison_status") == "complete":
            settlement_valid += 1
        if settlement.get("excluded_from_formal_metrics") is True and settlement.get("formal_eligible") is False:
            settlement_informal += 1
        if settlement.get("match_key"):
            settlement_matches.add(settlement["match_key"])
    return {
        "shadow_prediction_files": len(shadows),
        "shadow_unique_matches": len({x.get("match_key") for x in shadows if x.get("match_key")}),
        "shadow_unique_source_champion_ids": len({_shadow_source_id(x) for x in shadows if _shadow_source_id(x)}),
        "shadow_strict_prematch_valid": valid,
        "shadow_invalid_timing_count": sum(invalid_reasons.values()),
        "shadow_invalid_timing_reasons": dict(sorted(invalid_reasons.items())),
        "shadow_isolation_failure_counts": dict(sorted(isolation_failures.items())),
        "settlement_files": len(settlements),
        "settlement_unique_matches": len(settlement_matches),
        "settlement_complete_with_valid_shadow_timing": settlement_valid,
        "settlement_excluded_from_formal_metrics": settlement_informal,
        "settlement_is_research_only": settlement_informal == len(settlements),
    }


def _date_window(rows: list[dict[str, Any]], start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    return [row for row in rows if start <= row["date"] <= end]


def build_report(
    result_root: str | Path,
    prediction_root: str | Path | None = None,
    ledger_path: str | Path | None = None,
    shadow_prediction_root: str | Path | None = None,
    shadow_settlement_root: str | Path | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    loaded = load_verified_results(result_root)
    deduped = dedupe_results(loaded["rows"])
    rows = deduped["rows"]
    dates = [row["date"] for row in rows]
    as_of = max(dates) if dates else None
    recent_start = as_of - dt.timedelta(days=29) if as_of else None
    prior_end = recent_start - dt.timedelta(days=1) if recent_start else None
    prior_start = prior_end - dt.timedelta(days=29) if prior_end else None
    recent = _date_window(rows, recent_start, as_of) if as_of else []
    prior = _date_window(rows, prior_start, prior_end) if prior_start else []
    early_end = recent_start + dt.timedelta(days=14) if recent_start else None
    recent_early = _date_window(rows, recent_start, early_end) if recent_start else []
    recent_late = _date_window(rows, early_end + dt.timedelta(days=1), as_of) if early_end else []
    windows = {
        "all_available": summarize_window(rows, "all_available", str(min(dates)) if dates else "", str(max(dates)) if dates else ""),
        "recent_30": summarize_window(recent, "recent_30", str(recent_start) if recent_start else "", str(as_of) if as_of else ""),
        "prior_30": summarize_window(prior, "prior_30", str(prior_start) if prior_start else "", str(prior_end) if prior_end else ""),
        "recent_early_15": summarize_window(recent_early, "recent_early_15", str(recent_start) if recent_start else "", str(early_end) if early_end else ""),
        "recent_late_15": summarize_window(recent_late, "recent_late_15", str(early_end + dt.timedelta(days=1)) if early_end else "", str(as_of) if as_of else ""),
    }
    category_keys = ["high_total", "big_margin_win", "high_scoring_draw", "high_scoring_close_win"]
    differences = {
        key: bootstrap_proportion_difference(
            [row[key] for row in recent],
            [row[key] for row in prior],
            comparison_label="recent_30_minus_incomplete_prior_30",
        )
        for key in category_keys
    }
    complete_temporal_differences = {
        key: bootstrap_proportion_difference(
            [row[key] for row in recent_late],
            [row[key] for row in recent_early],
            comparison_label="recent_late_15_minus_recent_early_15",
        )
        for key in category_keys
    }
    competition_candidates = ["competition", "competition_id", "league", "league_name", "tournament"]
    competition_presence = {key: sum(key in row for row in loaded["rows"]) for key in competition_candidates}
    champion = None
    champion_records: list[dict[str, Any]] = []
    if prediction_root:
        champion_records = load_json_records(prediction_root)
        result_by_match = {row["match_key"]: row for row in rows}
        champion = diagnose_champion(prediction_root, ledger_path, result_by_match)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_commit": source_commit,
        "policy": {
            "result_source": "data/postmatch_automation/results",
            "result_scope": RESULT_SCOPE,
            "result_truth": "verified 90-minute home_score/away_score with result_90m agreement",
            "dedupe_key": "match_key; conflicting result identities are excluded",
            "recent_window": "latest valid result date minus 29 calendar days through latest valid result date",
            "prior_window": "the immediately preceding 30 calendar days",
            "big_margin_win": "non-draw and absolute goal difference >= 3",
            "high_scoring_draw": "draw and total goals >= 4",
            "high_scoring_close_win": f"non-draw, total goals >= 4, absolute goal difference <= {CLOSE_WIN_MAX_MARGIN}",
            "prediction_selection": "latest formal Champion frozen record strictly before kickoff using aware timestamps; no result fields used",
            "prediction_total_probabilities": "use stored totals bins 0,1,2,3,4,5,6+; no lambda-to-matrix reconstruction",
            "competition_standardization": "not performed when the verified result store has no persisted competition field",
            "model_change": "NO_MODEL_CHANGE",
        },
        "coverage": {
            "raw_result_file_count": loaded["raw_file_count"],
            "valid_result_row_count": loaded["valid_row_count"],
            "invalid_result_row_count": loaded["invalid_row_count"],
            "invalid_result_reason_counts": loaded["invalid_reason_counts"],
            "unique_match_count": deduped["unique_match_count"],
            "duplicate_result_groups": deduped["duplicate_groups"],
            "duplicate_result_rows": deduped["duplicate_rows"],
            "conflicting_result_match_count": deduped["conflict_match_count"],
            "missing_identity_count": deduped["missing_identity_count"],
            "date_min": str(min(dates)) if dates else None,
            "date_max": str(max(dates)) if dates else None,
            "competition_field_presence": competition_presence,
            "scope_counts": dict(collections.Counter(str(row.get("scope", "unknown")) for row in loaded["rows"])),
            "verification_quality_counts": dict(collections.Counter(str(row.get("verification_quality", "unknown")) for row in loaded["rows"])),
        },
        "window_coverage": {
            "as_of_date": str(as_of) if as_of else None,
            "recent_30": {"calendar_days": 30, "source_covers_full_date_span": bool(dates and min(dates) <= recent_start and max(dates) >= as_of)},
            "prior_30": {"calendar_days": 30, "source_covers_full_date_span": bool(dates and min(dates) <= prior_start and max(dates) >= prior_end), "available_days": len({row["date"] for row in prior}), "comparison_status": "INCOMPLETE_NON_DECISIVE" if not (dates and min(dates) <= prior_start and max(dates) >= prior_end) else "COMPLETE"},
            "twelve_month_baseline_available": bool(dates and min(dates) <= as_of - dt.timedelta(days=364)),
            "same_coverage_long_baseline": {
                "candidate": "data/football_data/historical_result_ledger",
                "candidate_rows_observed_at_source_commit": 206,
                "used_for_scoring_comparison": False,
                "reason_not_used": "canonical team-strength records use a different competition subset and canonical_match_id/home_goals fields; no verified match_key join to the 90-minute result store was established",
            },
        },
        "windows": windows,
        "recent_minus_prior_bootstrap": differences,
        "complete_recent_late_minus_early_bootstrap": complete_temporal_differences,
        "champion_diagnostic": champion,
        "shadow_state": shadow_state(shadow_prediction_root, shadow_settlement_root, champion_records) if shadow_prediction_root else None,
        "model_decision": "NO_MODEL_CHANGE",
        "decision_reason": "Same-system late-15 scoring uptick and Champion right-tail underprediction exist, but no full previous-30-day or 12-month same-coverage baseline and no competition field or verified join to standardize schedule composition.",
        "future_hypothesis": {
            "id": "dynamic_total_goals_regime_v1",
            "status": "NOT_QUALIFIED",
            "type": "hypothesis_only",
            "parameter_grid": False,
            "production_hook": False,
        },
        "conclusion": {
            "status": "DIAGNOSTIC_ONLY",
            "model_change": "NO_MODEL_CHANGE",
            "interpretation_limits": [
                "The prior 30-day window is incomplete when the result store starts after its beginning.",
                "The verified result store does not persist competition or league, so composition cannot be standardized here.",
                "Champion exact-score storage is top-10; no full score matrix was reconstructed.",
                "A short recent window is evidence for monitoring, not a reason to tune parameters.",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-root", required=True)
    parser.add_argument("--prediction-root")
    parser.add_argument("--ledger")
    parser.add_argument("--shadow-prediction-root")
    parser.add_argument("--shadow-settlement-root")
    parser.add_argument("--source-commit")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(
        args.result_root,
        args.prediction_root,
        args.ledger,
        args.shadow_prediction_root,
        args.shadow_settlement_root,
        args.source_commit,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "schema_version": SCHEMA_VERSION, "unique_matches": report["coverage"]["unique_match_count"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
