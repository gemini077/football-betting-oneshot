#!/usr/bin/env python3
"""Run the bounded final review for the frozen Challenger C cohort.

The review is deliberately read-only with respect to production, frozen
predictions, and prospective shadow history.  It consumes the existing shadow
closure artifacts and writes a separate review artifact only when requested.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import (  # noqa: E402
    CANDIDATE_ID,
    evaluate_paired_cohort,
    _is_promotion_eligible_pair,
)
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)


REVIEW_ID = "CHALLENGER-C-PROMOTION-REVIEW-1"
REVIEW_SCHEMA_VERSION = "challenger_c_promotion_review_1.v1"
DEFAULT_LATEST = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
DEFAULT_RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
DEFAULT_CONFIG = ROOT / "config" / "model_governance.json"
DEFAULT_OUTPUT = ROOT / "data" / "prediction_quality" / "challenger_c_promotion_review_1" / "review.json"
DEFAULT_REPORT = ROOT / "docs" / "prediction-quality" / "CHALLENGER-C-PROMOTION-REVIEW-1_FINAL_REPORT.md"

MIN_MEANINGFUL_SLICE = 10
SAFETY_FLOORS = {
    "one_x_two_brier": 0.10,
    "one_x_two_log_loss": 0.20,
    "btts_brier": 0.08,
    "ou_2_5_brier": 0.08,
}

METRIC_PATHS = {
    "exact_top1": ("exact_score", "top1_hit_rate"),
    "exact_top3": ("exact_score", "top3_hit_rate"),
    "exact_nll": ("exact_score", "nll"),
    "one_x_two_accuracy": ("one_x_two", "accuracy"),
    "one_x_two_brier": ("one_x_two", "brier"),
    "one_x_two_log_loss": ("one_x_two", "log_loss"),
    "one_x_two_ece": ("one_x_two", "ece"),
    "btts_accuracy": ("btts", "accuracy"),
    "btts_brier": ("btts", "brier"),
    "btts_log_loss": ("btts", "log_loss"),
    "btts_ece": ("btts", "ece"),
    "ou_2_5_accuracy": ("ou_2_5", "accuracy"),
    "ou_2_5_brier": ("ou_2_5", "brier"),
    "ou_2_5_log_loss": ("ou_2_5", "log_loss"),
    "one_one_top1_share": ("distribution", "one_one_top1_share"),
    "lambda_median_abs_gap": ("lambda", "median_abs_gap"),
    "lambda_gap_lt_0_5_share": ("lambda", "gap_lt_0_5_share"),
}

# These are the accepted 112-row values supplied for this review.  They are
# a reproduction target, not a new fit or a replacement for the source data.
EXPECTED_ACCEPTED_METRICS = {
    "champion": {
        "exact_top1": 0.107142857,
        "exact_top3": 0.285714286,
        "exact_nll": 3.028904590,
        "one_x_two_accuracy": 0.821428571,
        "one_x_two_brier": 0.435564753,
        "one_x_two_log_loss": 0.771894548,
        "one_x_two_ece": 0.161987113,
        "btts_accuracy": 0.428571429,
        "btts_brier": 0.276515756,
        "btts_log_loss": 0.748053264,
        "btts_ece": 0.156400330,
        "ou_2_5_accuracy": 0.660714286,
        "ou_2_5_brier": 0.226804847,
        "ou_2_5_log_loss": 0.645220633,
        "one_one_top1_share": 0.660714286,
        "lambda_median_abs_gap": 0.486788,
        "lambda_gap_lt_0_5_share": 0.526785714,
    },
    "challenger": {
        "exact_top1": 0.125000000,
        "exact_top3": 0.303571429,
        "exact_nll": 2.974156721,
        "one_x_two_accuracy": 0.803571429,
        "one_x_two_brier": 0.378420080,
        "one_x_two_log_loss": 0.687059633,
        "one_x_two_ece": 0.126259979,
        "btts_accuracy": 0.455357143,
        "btts_brier": 0.281726415,
        "btts_log_loss": 0.759251846,
        "btts_ece": 0.163669907,
        "ou_2_5_accuracy": 0.660714286,
        "ou_2_5_brier": 0.226805045,
        "ou_2_5_log_loss": 0.645221067,
        "one_one_top1_share": 0.383928571,
        "lambda_median_abs_gap": 0.773430,
        "lambda_gap_lt_0_5_share": 0.285714286,
    },
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_value(candidate: dict[str, Any], name: str) -> float | None:
    current: Any = candidate
    for key in METRIC_PATHS[name]:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _number(current)


def compact_candidate_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"sample_count": candidate.get("sample_count")}
    for name in METRIC_PATHS:
        result[name] = _metric_value(candidate, name)
    return result


def compact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        candidate_id: compact_candidate_metrics(candidate)
        for candidate_id, candidate in (evaluation.get("candidates") or {}).items()
        if isinstance(candidate, dict)
    }


def _metric_projection_matches(
    observed: dict[str, Any], expected: dict[str, dict[str, float]], *, tolerance: float = 1e-9
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for candidate_id, expected_metrics in expected.items():
        actual = observed.get(candidate_id) or {}
        for name, expected_value in expected_metrics.items():
            actual_value = _number(actual.get(name))
            if actual_value is None or not math.isclose(actual_value, expected_value, rel_tol=0.0, abs_tol=tolerance):
                mismatches.append({
                    "candidate": candidate_id,
                    "metric": name,
                    "expected": expected_value,
                    "observed": actual_value,
                })
    return {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load_universe_map(universe_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(universe_root.glob("*.json")):
        try:
            document = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        for row in document.get("fixtures") or []:
            if isinstance(row, dict) and row.get("matchId") is not None:
                result[str(row["matchId"])] = row
    return result


def _pair_metadata(pair: dict[str, Any], universe_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    snapshot_path = ROOT / str(pair.get("input_snapshot_ref") or "")
    document = _load_json(snapshot_path)
    input_projection = document.get("input") or {}
    baseline = input_projection.get("official_market_baseline") or {}
    fair_probabilities = baseline.get("fair_probabilities") or {}
    fair_values = sorted(
        [value for value in (_number(item) for item in fair_probabilities.values()) if value is not None],
        reverse=True,
    )
    challenger_inputs = (pair.get("challenger") or {}).get("inputs") or {}
    market_share = _number(challenger_inputs.get("market_share"))
    return {
        "league": (universe_map.get(str(pair.get("match_id"))) or {}).get("league"),
        "market_share": market_share,
        "favorite_probability": fair_values[0] if fair_values else None,
        "favorite_gap": fair_values[0] - fair_values[1] if len(fair_values) >= 2 else None,
        "input_snapshot_ref": pair.get("input_snapshot_ref"),
    }


def _select_latest_unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("match_id") or "")].append(row)
    selected: list[dict[str, Any]] = []
    for match_id, candidates in grouped.items():
        if not match_id:
            continue
        selected.append(
            max(
                candidates,
                key=lambda row: (
                    _parse_time(row.get("source_cutoff")) or datetime.min.replace(tzinfo=timezone.utc),
                    _parse_time(row.get("freeze_created_at")) or datetime.min.replace(tzinfo=timezone.utc),
                    str(row.get("pair_id") or ""),
                ),
            )
        )
    return sorted(
        selected,
        key=lambda row: (
            _parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("match_id") or ""),
        ),
    )


def _slice_metrics(rows: list[dict[str, Any]], result_map: dict[str, Any]) -> dict[str, Any]:
    evaluation = evaluate_paired_cohort(rows, result_map)
    return {
        "pair_row_count": len(rows),
        "unique_match_count": len({str(row.get("match_id") or "") for row in rows}),
        "metrics": compact_evaluation(evaluation),
    }


def _meaningful_slices(
    unique_rows: list[dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
    result_map: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    slices: dict[str, list[dict[str, Any]]] = {}
    if len(unique_rows) >= 2:
        middle = len(unique_rows) // 2
        slices["chronological_earlier"] = unique_rows[:middle]
        slices["chronological_later"] = unique_rows[middle:]

    league_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unique_rows:
        league = metadata[row["pair_id"]].get("league") or "<missing>"
        league_groups[str(league)].append(row)
    for league, rows in league_groups.items():
        if len(rows) >= MIN_MEANINGFUL_SLICE:
            slices[f"league::{league}"] = rows

    market_share_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unique_rows:
        value = metadata[row["pair_id"]].get("market_share")
        if value is None:
            continue
        label = "away_leaning" if value <= 0.45 else "home_leaning" if value >= 0.55 else "balanced"
        market_share_groups[label].append(row)
    for label, rows in market_share_groups.items():
        if len(rows) >= MIN_MEANINGFUL_SLICE:
            slices[f"market_side::{label}"] = rows

    favorite_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unique_rows:
        value = metadata[row["pair_id"]].get("favorite_probability")
        if value is None:
            continue
        label = "balanced" if value < 0.45 else "moderate" if value < 0.60 else "strong"
        favorite_groups[label].append(row)
    for label, rows in favorite_groups.items():
        if len(rows) >= MIN_MEANINGFUL_SLICE:
            slices[f"favorite_strength::{label}"] = rows

    observed = {name: _slice_metrics(rows, result_map) for name, rows in slices.items()}
    counts = {
        "league": {str(name): len(rows) for name, rows in league_groups.items()},
        "market_side": {name: len(rows) for name, rows in market_share_groups.items()},
        "favorite_strength": {name: len(rows) for name, rows in favorite_groups.items()},
        "minimum_meaningful_slice": MIN_MEANINGFUL_SLICE,
        "excluded_league_groups_below_minimum": sorted(
            name for name, rows in league_groups.items() if len(rows) < MIN_MEANINGFUL_SLICE
        ),
    }
    return observed, counts


def _safety_triggers(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    champion = metrics.get("champion") or {}
    challenger = metrics.get("challenger") or {}
    checks = (
        ("one_x_two_brier", "1X2 Brier", SAFETY_FLOORS["one_x_two_brier"]),
        ("one_x_two_log_loss", "1X2 LogLoss", SAFETY_FLOORS["one_x_two_log_loss"]),
        ("btts_brier", "BTTS Brier", SAFETY_FLOORS["btts_brier"]),
        ("ou_2_5_brier", "O/U 2.5 Brier", SAFETY_FLOORS["ou_2_5_brier"]),
    )
    triggers: list[dict[str, Any]] = []
    for metric, label, floor in checks:
        champion_value = _number(champion.get(metric))
        challenger_value = _number(challenger.get(metric))
        if champion_value is None or challenger_value is None:
            triggers.append({"metric": metric, "label": label, "status": "MISSING"})
            continue
        worsening = challenger_value - champion_value
        if worsening > floor:
            triggers.append({
                "metric": metric,
                "label": label,
                "status": "TRIGGERED",
                "worsening": round(worsening, 9),
                "floor": floor,
            })
    return triggers


def _subgroup_gate(slices: dict[str, Any]) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    triggers: list[dict[str, Any]] = []
    for name, value in slices.items():
        metrics = value.get("metrics") or {}
        slice_triggers = _safety_triggers(metrics)
        checked.append({"slice": name, "pair_row_count": value.get("pair_row_count"), "unique_match_count": value.get("unique_match_count")})
        triggers.extend({"slice": name, **trigger} for trigger in slice_triggers)
    return {
        "status": "PASS" if not triggers else "FAIL",
        "checked_slices": checked,
        "triggers": triggers,
    }


def _integrity_summary(
    pairs: list[dict[str, Any]],
    eligible: list[dict[str, Any]],
    result_map: dict[str, Any],
    matching: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "same_match_id": sum((pair.get("integrity") or {}).get("same_match_id") is True for pair in pairs),
        "same_source_cutoff": sum((pair.get("integrity") or {}).get("same_source_cutoff") is True for pair in pairs),
        "same_freeze_eligibility": sum((pair.get("integrity") or {}).get("same_freeze_eligibility") is True for pair in pairs),
        "same_frozen_input_digest": sum((pair.get("integrity") or {}).get("same_frozen_input_digest") is True for pair in pairs),
        "same_fixture": sum(pair.get("same_fixture") is True for pair in pairs),
        "champion_preserved": sum(pair.get("champion_preserved") is True for pair in pairs),
        "post_match_input_used_for_generation_false": sum(
            pair.get("post_match_input_used_for_generation") is False for pair in pairs
        ),
        "eligible_post_match_input_used_for_generation_false": sum(
            pair.get("post_match_input_used_for_generation") is False for pair in eligible
        ),
        "eligible_source_cutoff_before_kickoff": sum(
            (_parse_time(pair.get("source_cutoff")) is not None)
            and (_parse_time(pair.get("kickoff_at")) is not None)
            and _parse_time(pair.get("source_cutoff")) < _parse_time(pair.get("kickoff_at"))
            for pair in eligible
        ),
    }
    expected_pairs = len(pairs)
    pair_checks_pass = all(
        value == expected_pairs
        for key, value in checks.items()
        if key in {
            "same_match_id", "same_source_cutoff", "same_freeze_eligibility", "same_frozen_input_digest",
            "same_fixture", "champion_preserved", "post_match_input_used_for_generation_false",
        }
    )
    integrity_status = "PASS" if (
        pair_checks_pass
        and checks["eligible_post_match_input_used_for_generation_false"] == len(eligible)
        and checks["eligible_source_cutoff_before_kickoff"] == len(eligible)
        and int(matching.get("result_identity_mismatches") or 0) == 0
    ) else "FAIL"
    return {
        "status": integrity_status,
        "pair_count": expected_pairs,
        "eligible_pair_count": len(eligible),
        "verified_eligible_pair_count": sum(str(pair.get("pair_id")) in result_map for pair in eligible),
        "checks": checks,
        "matching": matching,
    }


def _gate_statuses(
    *,
    integrity: dict[str, Any],
    reproduction: dict[str, Any],
    unique_count: int,
    verified_pair_count: int,
    minimum_unique_matches: int,
    subgroup_gate: dict[str, Any],
    overall_metrics: dict[str, dict[str, Any]],
    slices: dict[str, Any],
) -> dict[str, Any]:
    overall_triggers = _safety_triggers(overall_metrics)
    exact_support: list[str] = []
    one_one_support: list[str] = []
    for name, value in slices.items():
        metrics = value.get("metrics") or {}
        champion = metrics.get("champion") or {}
        challenger = metrics.get("challenger") or {}
        if (
            _number(challenger.get("exact_nll")) is not None
            and _number(champion.get("exact_nll")) is not None
            and challenger["exact_nll"] <= champion["exact_nll"]
        ):
            exact_support.append(name)
        if (
            _number(challenger.get("one_one_top1_share")) is not None
            and _number(champion.get("one_one_top1_share")) is not None
            and challenger["one_one_top1_share"] < champion["one_one_top1_share"]
        ):
            one_one_support.append(name)
    statuses = {
        "pair_freeze_integrity": integrity["status"] == "PASS",
        "accepted_overall_112_reproduce": reproduction["status"] == "PASS",
        "unique_match_promotion_gate": unique_count >= minimum_unique_matches
        and unique_count == verified_pair_count,
        "meaningful_subgroup_safety": subgroup_gate["status"] == "PASS" and not overall_triggers,
        "exact_score_improvement_not_confined": len(exact_support) >= 2,
        "one_one_reduction_broad": len(one_one_support) >= 2,
        "btts_regression_bounded": not any(trigger.get("metric") == "btts_brier" for trigger in overall_triggers),
        "no_post_match_information_in_generation": integrity["status"] == "PASS",
    }
    return {
        "status": "PASS" if all(statuses.values()) else "FAIL",
        "checks": statuses,
        "overall_safety_triggers": overall_triggers,
        "exact_supporting_slices": exact_support,
        "one_one_supporting_slices": one_one_support,
        "minimum_unique_matches": minimum_unique_matches,
    }


def _metric_table_row(label: str, candidate_id: str, metrics: dict[str, Any]) -> str:
    values = [
        label,
        candidate_id,
        str(metrics.get("sample_count")),
        f"{metrics.get('exact_top1'):.6f}",
        f"{metrics.get('exact_top3'):.6f}",
        f"{metrics.get('exact_nll'):.6f}",
        f"{metrics.get('one_x_two_accuracy'):.6f}",
        f"{metrics.get('one_x_two_brier'):.6f}",
        f"{metrics.get('one_x_two_log_loss'):.6f}",
        f"{metrics.get('btts_accuracy'):.6f}",
        f"{metrics.get('btts_brier'):.6f}",
        f"{metrics.get('btts_log_loss'):.6f}",
        f"{metrics.get('btts_ece'):.6f}",
        f"{metrics.get('ou_2_5_accuracy'):.6f}",
        f"{metrics.get('ou_2_5_brier'):.6f}",
        f"{metrics.get('ou_2_5_log_loss'):.6f}",
        f"{metrics.get('one_one_top1_share'):.6f}",
        f"{metrics.get('lambda_median_abs_gap'):.6f}",
        f"{metrics.get('lambda_gap_lt_0_5_share'):.6f}",
    ]
    return "| " + " | ".join(values) + " |"


def render_report(evidence: dict[str, Any]) -> str:
    overall = evidence["overall"]["metrics"]
    lines = [
        f"# {REVIEW_ID}",
        "",
        f"Decision: **`{evidence['decision']}`**",
        f"Safety Gate: **`{evidence['safety_gate']['status']}`**",
        "",
        "## Stop state",
        "",
        "The final review stops before Champion promotion, merge, and production verification.",
        "No new Challenger was created and no frozen/prospective history was rewritten.",
        "",
        "## Source and cohort",
        "",
        f"- Latest shadow artifact: `{evidence['source']['latest']}`",
        f"- Existing result artifacts only; no new matches fetched: `{evidence['source']['result_root']}`",
        f"- Pair rows: `{evidence['counts']['pair_rows']}`; promotion-eligible rows: `{evidence['counts']['promotion_eligible_rows']}`",
        f"- Verified promotion-eligible rows: `{evidence['counts']['verified_pair_rows']}`",
        f"- Verified unique matches: `{evidence['counts']['verified_unique_matches']}`",
        f"- Duplicate verified-match groups: `{evidence['counts']['duplicate_verified_match_groups']}`; duplicate rows beyond one per match: `{evidence['counts']['duplicate_verified_rows']}`",
        "",
        "The accepted `112` value is therefore a pair-row count, not 112 independent matches. "
        "The repository promotion gate requires unique-match evaluation, and the current cohort has "
        f"`{evidence['counts']['verified_unique_matches']}` unique matches against a minimum of "
        f"`{evidence['safety_gate']['minimum_unique_matches']}`.",
        "",
        "## Accepted 112-row reproduction",
        "",
        "| Scope | Candidate | n | Exact Top1 | Exact Top3 | Exact NLL | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | BTTS Acc | BTTS Brier | BTTS LogLoss | BTTS ECE | O/U Acc | O/U Brier | O/U LogLoss | 1-1 Top1 | Median Lambda Gap | Lambda Gap < 0.5 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for candidate_id in ("champion", "challenger"):
        lines.append(_metric_table_row("112 pair rows", candidate_id, overall[candidate_id]))
    lines.extend([
        "",
        f"Reproduction check: **`{evidence['overall_reproduction']['status']}`**; mismatches: `{len(evidence['overall_reproduction']['mismatches'])}`.",
        "",
        "## Bounded robustness slices",
        "",
        "Slices below use one deterministic latest pre-match row per unique match. "
        f"Only groups with at least `{MIN_MEANINGFUL_SLICE}` unique matches are shown; smaller league/regime groups are count-only and are not decision signals.",
        "",
        "| Slice | Candidate | n | Exact Top1 | Exact Top3 | Exact NLL | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | BTTS Acc | BTTS Brier | BTTS LogLoss | BTTS ECE | O/U Acc | O/U Brier | O/U LogLoss | 1-1 Top1 | Median Lambda Gap | Lambda Gap < 0.5 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for slice_name, slice_value in evidence["slices"].items():
        for candidate_id in ("champion", "challenger"):
            lines.append(_metric_table_row(slice_name, candidate_id, slice_value["metrics"][candidate_id]))
    lines.extend([
        "",
        "Slice counts not reported as decision signals:",
        f"`{json.dumps(evidence['slice_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Gate evidence",
        "",
        "| Gate | Result |",
        "|---|---|",
    ])
    for name, value in evidence["safety_gate"]["checks"].items():
        lines.append(f"| {name} | `{ 'PASS' if value else 'FAIL' }` |")
    lines.extend([
        "",
        "Safety floors used:",
        f"`{json.dumps(SAFETY_FLOORS, sort_keys=True)}`",
        "",
        f"Overall safety-floor triggers: `{json.dumps(evidence['safety_gate']['overall_safety_triggers'], ensure_ascii=False, sort_keys=True)}`.",
        f"Subgroup safety: **`{evidence['subgroup_safety']['status']}`**; checked slices: `{len(evidence['subgroup_safety']['checked_slices'])}`; triggers: `{len(evidence['subgroup_safety']['triggers'])}`.",
        "",
        "## Integrity and production boundary",
        "",
        f"- Pair/freeze integrity: **`{evidence['integrity']['status']}`**",
        f"- Post-match generation flag: `{evidence['integrity']['checks']['eligible_post_match_input_used_for_generation_false']}/{evidence['counts']['promotion_eligible_rows']}` false",
        f"- Result identity mismatches: `{evidence['integrity']['matching'].get('result_identity_mismatches')}`",
        "- No promotion implementation, merge, production run, or production mutation was attempted after the failed gate.",
        "- Current Champion remains `recent_form_market_calibrated_poisson_v2`; C remains shadow-only.",
        "",
        "## Exact stop decision",
        "",
        "`KEEP CHAMPION / KEEP C SHADOW`",
        "",
        "Required next action is to repair/replace the prospective cohort capture so that the formal review has the required unique-match population. Do not refit C and do not create another Challenger in this stopped milestone.",
        "",
    ])
    return "\n".join(lines)


def run_review(
    *,
    latest_path: Path = DEFAULT_LATEST,
    result_root: Path = DEFAULT_RESULT_ROOT,
    universe_root: Path = DEFAULT_UNIVERSE_ROOT,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    latest = _load_json(latest_path)
    if not isinstance(latest, dict):
        raise ValueError("latest shadow artifact must be an object")
    pairs = [pair for pair in latest.get("pairs") or [] if isinstance(pair, dict)]
    if str(latest.get("candidate_id") or "") != CANDIDATE_ID:
        raise ValueError("latest artifact is not Challenger C")

    catalog, discovery = discover_verified_results(result_root)
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    eligible = [pair for pair in pairs if _is_promotion_eligible_pair(pair)]
    verified = [pair for pair in eligible if str(pair.get("pair_id")) in result_map]
    by_match: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in verified:
        by_match[str(pair.get("match_id") or "")].append(pair)
    duplicate_groups = {match_id: rows for match_id, rows in by_match.items() if len(rows) > 1}
    duplicate_rows = sum(len(rows) - 1 for rows in duplicate_groups.values())

    overall_evaluation = evaluate_paired_cohort(pairs, result_map)
    overall_metrics = compact_evaluation(overall_evaluation)
    overall_reproduction = _metric_projection_matches(overall_metrics, EXPECTED_ACCEPTED_METRICS)
    universe_map = _load_universe_map(universe_root)
    metadata = {pair["pair_id"]: _pair_metadata(pair, universe_map) for pair in verified}
    unique_verified = _select_latest_unique(verified)
    slices, slice_counts = _meaningful_slices(unique_verified, metadata, result_map)
    integrity = _integrity_summary(pairs, eligible, result_map, matching)
    config = _load_json(config_path)
    minimum_unique_matches = int((config.get("promotion_gates") or {}).get("minimum_holdout_unique_matches") or 0)
    subgroup_safety = _subgroup_gate(slices)
    safety_gate = _gate_statuses(
        integrity=integrity,
        reproduction=overall_reproduction,
        unique_count=len(unique_verified),
        verified_pair_count=len(verified),
        minimum_unique_matches=minimum_unique_matches,
        subgroup_gate=subgroup_safety,
        overall_metrics=overall_metrics,
        slices=slices,
    )
    evidence = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_id": REVIEW_ID,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "decision": "KEEP CHAMPION / KEEP C SHADOW" if safety_gate["status"] == "FAIL" else "PROMOTE",
        "source": {
            "latest": latest_path.relative_to(ROOT).as_posix() if latest_path.is_relative_to(ROOT) else str(latest_path),
            "result_root": result_root.relative_to(ROOT).as_posix() if result_root.is_relative_to(ROOT) else str(result_root),
            "universe_root": universe_root.relative_to(ROOT).as_posix() if universe_root.is_relative_to(ROOT) else str(universe_root),
            "source_pins": latest.get("source_pins"),
            "new_matches_fetched": False,
        },
        "counts": {
            "pair_rows": len(pairs),
            "eligible_rows": len(eligible),
            "promotion_eligible_rows": len(eligible),
            "verified_pair_rows": len(verified),
            "verified_unique_matches": len(unique_verified),
            "duplicate_verified_match_groups": len(duplicate_groups),
            "duplicate_verified_rows": duplicate_rows,
            "eligible_unique_matches": len({str(pair.get("match_id") or "") for pair in eligible}),
            "unmatched_eligible_rows": len(eligible) - len(verified),
        },
        "discovery": discovery,
        "matching": matching,
        "integrity": integrity,
        "overall": {
            "metrics": overall_metrics,
            "stored_evaluation": compact_evaluation(latest.get("evaluation") or {}),
        },
        "overall_reproduction": overall_reproduction,
        "slices": slices,
        "slice_counts": slice_counts,
        "subgroup_safety": subgroup_safety,
        "safety_floors": SAFETY_FLOORS,
        "safety_gate": safety_gate,
        "production_action": "STOPPED_BEFORE_PROMOTION",
        "no_new_challenger": True,
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--universe-root", type=Path, default=DEFAULT_UNIVERSE_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--write", action="store_true", help="write review JSON and Markdown evidence")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    evidence = run_review(
        latest_path=args.latest,
        result_root=args.result_root,
        universe_root=args.universe_root,
        config_path=args.config,
    )
    if args.write:
        _write_json(args.output, evidence)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(evidence), encoding="utf-8")
    print(json.dumps({
        "review_id": evidence["review_id"],
        "decision": evidence["decision"],
        "safety_gate": evidence["safety_gate"]["status"],
        "pair_rows": evidence["counts"]["pair_rows"],
        "verified_pair_rows": evidence["counts"]["verified_pair_rows"],
        "verified_unique_matches": evidence["counts"]["verified_unique_matches"],
        "overall_reproduction": evidence["overall_reproduction"]["status"],
        "written": bool(args.write),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["safety_gate"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
