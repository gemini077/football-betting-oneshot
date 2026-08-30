"""Run the one-shot PRED-TRUST-3 market-side-only hybrid replay.

This module reads the accepted PRED-TRUST-2 replay and its pinned cohort,
then evaluates exactly Champion, the already-rejected Challenger B, and one
new deterministic candidate C.  Candidate C keeps the Champion total and
replaces only the side-share with the frozen market side-share.  No fitting,
new data, selector rerun, or post-match parameter enters the replay.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prediction_trust_2_replay import (  # noqa: E402
    ACCEPTED_PRODUCTION_RUN,
    ACCEPTED_WRITEBACK_COMMIT,
    OUTCOMES,
    PINNED_PRED_TRUST_1_HEAD,
    _actual_tail_reference,
    _evaluate_candidate,
    _form_and_market_inputs,
    _load_pinned_records,
    _metric_value,
    _prepare_row,
    _round,
    _sha256_file,
    _tradeoff_status,
    build_automatic_model,
    build_score_matrix,
    derive_candidate_lambdas,
)


DEFAULT_AUDIT = ROOT / "data" / "prediction_quality" / "pred_trust_1" / "audit_2026-08-30.json"
DEFAULT_PRED_TRUST_2_REPLAY = ROOT / "data" / "prediction_quality" / "pred_trust_2" / "replay_2026-08-30.json"
DEFAULT_MANIFEST = ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
DEFAULT_OUTPUT = ROOT / "data" / "prediction_quality" / "pred_trust_3" / "replay_2026-08-30.json"
DEFAULT_REPORT = ROOT / "docs" / "prediction-quality" / "PRED-TRUST-3_FINAL_REPORT.md"
SAME_TOLERANCE = 0.005


# The registry is intentionally limited to the requested three-way comparison.
CANDIDATE_SPECS = (
    {
        "candidate_id": "champion",
        "label": "Champion",
        "hypothesis": "current_recent_form_market_calibrated_poisson_v2",
        "formula_version": "pred_trust_2_champion_replay.v1",
        "boundary_changed": "none; stored Champion lambda state",
    },
    {
        "candidate_id": "existing_challenger_b_market_to_goal_separation",
        "label": "Existing Challenger B",
        "hypothesis": "market_to_goal_separation",
        "formula_version": "pred_trust_2_market_to_goal_separation.v1",
        "boundary_changed": "total and side share use frozen market state",
    },
    {
        "candidate_id": "market_side_only_hybrid",
        "label": "New Challenger C",
        "hypothesis": "market_side_only_hybrid",
        "formula_version": "market_side_only_hybrid.v1",
        "boundary_changed": "side share only; Champion total retained",
    },
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


def derive_market_side_only_lambdas(
    *,
    form_home: float,
    form_away: float,
    market_total: float | None,
    market_share: float | None,
    form_total: float,
) -> dict[str, float | str]:
    """Keep Champion total and use only the frozen market side-share."""

    champion = derive_candidate_lambdas(
        "champion",
        form_home=form_home,
        form_away=form_away,
        market_total=market_total,
        market_share=market_share,
        form_total=form_total,
    )
    share = float(market_share) if market_share is not None else float(champion["form_share"])
    share = _clamp(share, 0.15, 0.85)
    total = float(champion["total"])
    return {
        "candidate_id": "market_side_only_hybrid",
        "form_share": float(champion["form_share"]),
        "market_share": share,
        "target_total": float(champion["target_total"]),
        "total": total,
        "share": share,
        "lambda_home": total * share,
        "lambda_away": total * (1.0 - share),
    }


def _load_pred_trust_2_replay(path: Path) -> dict[str, Any]:
    replay = json.loads(path.read_text(encoding="utf-8"))
    if replay.get("milestone") != "PRED-TRUST-2":
        raise ValueError("PRED-TRUST-3 requires the PRED-TRUST-2 replay artifact")
    source = replay.get("source") or {}
    cohort = replay.get("cohort") or {}
    stop_state = replay.get("stop_state") or {}
    if source.get("accepted_production_run") != ACCEPTED_PRODUCTION_RUN:
        raise ValueError("PRED-TRUST-2 production-run pin mismatch")
    if source.get("accepted_writeback_commit") != ACCEPTED_WRITEBACK_COMMIT:
        raise ValueError("PRED-TRUST-2 write-back pin mismatch")
    if source.get("pred_trust_1_head") != PINNED_PRED_TRUST_1_HEAD:
        raise ValueError("PRED-TRUST-1 head pin mismatch")
    if cohort.get("pinned_unique_final_legal_prematch_matches") != 217:
        raise ValueError("PRED-TRUST-2 cohort is not the pinned 217-match cohort")
    if cohort.get("verified_90m_matches") != 181:
        raise ValueError("PRED-TRUST-2 verified cohort is not the pinned 181-match cohort")
    if replay.get("reproduction", {}).get("candidate_count") != 3:
        raise ValueError("PRED-TRUST-2 did not contain the required three-candidate replay")
    if stop_state.get("offline_batches") != 1:
        raise ValueError("PRED-TRUST-2 must have exactly one offline batch")
    for key in (
        "champion_modified",
        "production_enabled",
        "shadow_enabled",
        "frozen_predictions_rewritten",
        "prospective_ledger_rewritten",
        "health_monitor_modified",
        "health_gate_modified",
        "new_provider_added",
        "parameter_sweep",
    ):
        if stop_state.get(key):
            raise ValueError(f"PRED-TRUST-2 stop-state violation: {key}")
    return replay


def _derive(candidate_id: str, inputs: Mapping[str, Any]) -> dict[str, float | str]:
    arguments = {
        "form_home": inputs["form_home"],
        "form_away": inputs["form_away"],
        "market_total": inputs["market_total"],
        "market_share": inputs["market_share"],
        "form_total": inputs["form_total"],
    }
    if candidate_id == "market_side_only_hybrid":
        return derive_market_side_only_lambdas(**arguments)
    if candidate_id == "existing_challenger_b_market_to_goal_separation":
        return derive_candidate_lambdas("challenger_b_market_to_goal_separation", **arguments)
    return derive_candidate_lambdas("champion", **arguments)


TRADEOFF_METRICS = (
    ("1X2 accuracy", "one_x_two.accuracy", "higher"),
    ("1X2 Brier", "one_x_two.brier", "lower"),
    ("1X2 LogLoss", "one_x_two.log_loss", "lower"),
    ("Exact Score Top1 hit", "exact_score.top1_hit_rate", "higher"),
    ("Exact Score Top3 hit", "exact_score.top3_hit_rate", "higher"),
    ("Actual-score probability", "exact_score.mean_probability_assigned_to_actual_score", "higher"),
    ("Exact Score NLL", "exact_score.nll", "lower"),
    ("BTTS accuracy", "btts.accuracy", "higher"),
    ("BTTS Brier", "btts.brier", "lower"),
    ("O/U 2.5 accuracy", "ou_2_5.accuracy", "higher"),
    ("O/U 2.5 Brier", "ou_2_5.brier", "lower"),
    ("1X2 macro ECE", "one_x_two.ece", "lower"),
    ("BTTS ECE", "btts.ece", "lower"),
    ("O/U 2.5 ECE", "ou_2_5.ece", "lower"),
    ("1-1 Top1 share", "distribution.one_one_top1_share", "lower"),
    ("Top1 support size", "distribution.top1_support_size", "higher"),
    ("High-score Top1 share", "distribution.high_score_top1_share", "higher"),
    ("Gap <0.25 share", "distribution.gap_lt_0_25_share", "lower"),
    ("Gap <0.5 share", "distribution.gap_lt_0_5_share", "lower"),
    ("Median absolute lambda gap", "distribution.absolute_gap.P50", "higher"),
    ("Mean P(total >=4)", "distribution.mean_probability_total_ge_4", "higher"),
    ("Mean P(total >=5)", "distribution.mean_probability_total_ge_5", "higher"),
    ("Mean P(total >=6)", "distribution.mean_probability_total_ge_6", "higher"),
)


def _tradeoff_table(metrics_by_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    champion = metrics_by_id["champion"]
    table = []
    for label, path, direction in TRADEOFF_METRICS:
        champion_value = _metric_value(champion, path)
        row: dict[str, Any] = {
            "metric": label,
            "path": path,
            "direction": f"{direction}_is_better",
            "champion": _round(champion_value, 9),
        }
        for candidate_id in (
            "existing_challenger_b_market_to_goal_separation",
            "market_side_only_hybrid",
        ):
            value = _metric_value(metrics_by_id[candidate_id], path)
            row[candidate_id] = {
                "value": _round(value, 9),
                "status": _tradeoff_status(value, champion_value, direction),
                "delta_vs_champion": _round(value - champion_value, 9),
            }
        table.append(row)
    return table


def _qualification(
    metrics: Mapping[str, Any],
    champion: Mapping[str, Any],
    actual_tail: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_distribution = metrics["distribution"]
    champion_distribution = champion["distribution"]
    one = metrics["one_x_two"]
    one_base = champion["one_x_two"]
    exact = metrics["exact_score"]
    exact_base = champion["exact_score"]
    btts = metrics["btts"]
    btts_base = champion["btts"]
    ou = metrics["ou_2_5"]
    ou_base = champion["ou_2_5"]

    tail_checks: dict[str, bool] = {}
    tail_errors: dict[str, float] = {}
    champion_tail_errors: dict[str, float] = {}
    for suffix in ("4", "5", "6"):
        candidate_value = candidate_distribution[f"mean_probability_total_ge_{suffix}"]
        actual_value = actual_tail[f"actual_total_ge_{suffix}_share"]
        champion_value = champion_distribution[f"mean_probability_total_ge_{suffix}"]
        error = abs(candidate_value - actual_value)
        champion_error = abs(champion_value - actual_value)
        tail_errors[f"total_ge_{suffix}"] = error
        champion_tail_errors[f"total_ge_{suffix}"] = champion_error
        tail_checks[f"right_tail_total_ge_{suffix}_not_worse"] = error <= champion_error + 0.02

    checks = {
        "one_x_two_accuracy_gain_retained": one["accuracy"] >= one_base["accuracy"] + 0.02,
        "one_x_two_brier_improves": one["brier"] <= one_base["brier"] - 0.01,
        "one_x_two_log_loss_improves": one["log_loss"] <= one_base["log_loss"] - 0.02,
        "concentration_materially_improves": candidate_distribution["one_one_top1_share"] <= champion_distribution["one_one_top1_share"] - 0.10,
        "lambda_gap_distribution_separates": (
            candidate_distribution["gap_lt_0_5_share"] <= champion_distribution["gap_lt_0_5_share"] - 0.05
            and candidate_distribution["absolute_gap"]["P50"] >= champion_distribution["absolute_gap"]["P50"] + 0.05
        ),
        "exact_top1_not_unacceptable": exact["top1_hit_rate"] >= exact_base["top1_hit_rate"] - 0.03,
        "exact_top3_not_unacceptable": exact["top3_hit_rate"] >= exact_base["top3_hit_rate"] - 0.03,
        "exact_nll_not_unacceptable": exact["nll"] <= exact_base["nll"] + 0.15,
        "actual_score_probability_not_unacceptable": exact["mean_probability_assigned_to_actual_score"] >= exact_base["mean_probability_assigned_to_actual_score"] - 0.01,
        "btts_accuracy_basically_maintained": btts["accuracy"] >= btts_base["accuracy"] - 0.02,
        "btts_brier_basically_maintained": btts["brier"] <= btts_base["brier"] + 0.005,
        "btts_ece_not_materially_worse": btts["ece"] <= btts_base["ece"] + 0.02,
        "ou_accuracy_basically_maintained": ou["accuracy"] >= ou_base["accuracy"] - 0.02,
        "ou_brier_basically_maintained": ou["brier"] <= ou_base["brier"] + 0.005,
        "ou_ece_not_materially_worse": ou["ece"] <= ou_base["ece"] + 0.02,
    }
    checks.update(tail_checks)
    return {
        "candidate_id": "market_side_only_hybrid",
        "checks": checks,
        "qualified_for_shadow": all(checks.values()),
        "right_tail": {
            "candidate_absolute_errors": tail_errors,
            "champion_absolute_errors": champion_tail_errors,
            "actual_total_shares": {
                "total_ge_4": actual_tail["actual_total_ge_4_share"],
                "total_ge_5": actual_tail["actual_total_ge_5_share"],
                "total_ge_6": actual_tail["actual_total_ge_6_share"],
            },
        },
        "thresholds": {
            "one_x_two_accuracy_gain": 0.02,
            "one_x_two_brier_improvement": 0.01,
            "one_x_two_log_loss_improvement": 0.02,
            "one_one_share_reduction": 0.10,
            "lambda_gap_lt_0_5_reduction": 0.05,
            "median_gap_increase": 0.05,
            "exact_hit_rate_tolerance": 0.03,
            "exact_nll_tolerance": 0.15,
            "exact_actual_probability_tolerance": 0.01,
            "binary_accuracy_tolerance": 0.02,
            "binary_brier_tolerance": 0.005,
            "binary_ece_tolerance": 0.02,
            "right_tail_error_tolerance": 0.02,
        },
    }


def _metrics_without_rows(metrics_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        candidate_id: {key: value for key, value in metrics.items() if key != "evaluated_rows"}
        for candidate_id, metrics in metrics_by_id.items()
    }


def run_replay(
    *,
    root: Path = ROOT,
    pred_trust_2_replay_path: Path = DEFAULT_PRED_TRUST_2_REPLAY,
    manifest_path: Path = DEFAULT_MANIFEST,
    audit_path: Path = DEFAULT_AUDIT,
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    pred_trust_2_replay = _load_pred_trust_2_replay(pred_trust_2_replay_path)
    if pred_trust_2_replay["source"]["audit_artifact_sha256"] != _sha256_file(audit_path):
        raise ValueError("PRED-TRUST-1 audit artifact changed after PRED-TRUST-2")
    if pred_trust_2_replay["source"]["cohort_manifest_sha256"] != _sha256_file(manifest_path):
        raise ValueError("PRED-TRUST-2 cohort manifest changed after acceptance")
    records, manifest = _load_pinned_records(root, manifest_path)
    if len(records) != 217 or manifest.get("selected_match_count") != 217:
        raise ValueError("PRED-TRUST-3 requires the pinned 217-match cohort")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    verified_rows = audit.get("prospective_evaluation", {}).get("evaluated_rows") or []
    verified_by_id = {str(row["prediction_id"]): row for row in verified_rows if row.get("prediction_id")}
    if len(verified_by_id) != 181 or not set(verified_by_id).issubset({record["prediction_id"] for record in records}):
        raise ValueError("PRED-TRUST-1 verified prospective pin must contain 181 selected matches")

    candidate_rows: dict[str, list[dict[str, Any]]] = {spec["candidate_id"]: [] for spec in CANDIDATE_SPECS}
    champion_lambda_deltas: list[float] = []
    input_status: dict[str, int] = {"venue_split": 0, "venue_proxy_used": 0}
    calibration_states: dict[str, int] = {"active": 0, "inactive": 0}
    for record in records:
        snapshot_ref = str(record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or "")
        snapshot = json.loads((root / snapshot_ref).read_text(encoding="utf-8"))
        context = snapshot.get("input") or {}
        model_result = build_automatic_model(context)
        champion_model = model_result.get("model") if isinstance(model_result, dict) else None
        if not isinstance(champion_model, dict):
            raise ValueError(f"Champion replay returned no model for {record['prediction_id']}")
        inputs = _form_and_market_inputs(context)
        input_status["venue_proxy_used" if inputs["venue_proxy_used"] else "venue_split"] += 1
        closed_loop = ((champion_model.get("calibration") or {}).get("closed_loop") or {})
        calibration_states["active" if closed_loop.get("active") else "inactive"] += 1
        derived_champion = _derive("champion", inputs)
        champion_lambda_deltas.extend(
            [
                abs(float(champion_model["lambda_home"]) - float(derived_champion["lambda_home"])),
                abs(float(champion_model["lambda_away"]) - float(derived_champion["lambda_away"])),
            ]
        )
        for spec in CANDIDATE_SPECS:
            candidate_id = spec["candidate_id"]
            if candidate_id == "champion":
                candidate = {
                    **derived_champion,
                    "lambda_home": float(champion_model["lambda_home"]),
                    "lambda_away": float(champion_model["lambda_away"]),
                }
            else:
                candidate = _derive(candidate_id, inputs)
            matrix = build_score_matrix(float(candidate["lambda_home"]), float(candidate["lambda_away"]))
            candidate_rows[candidate_id].append(_prepare_row(record, champion_model, candidate, matrix))

    max_absolute_lambda_delta = max(champion_lambda_deltas) if champion_lambda_deltas else None
    if max_absolute_lambda_delta is None or max_absolute_lambda_delta > 1e-6:
        raise ValueError(f"Champion replay did not reproduce within 1e-6: {max_absolute_lambda_delta}")

    metrics_by_id = {
        candidate_id: _evaluate_candidate(rows, verified_by_id)
        for candidate_id, rows in candidate_rows.items()
    }
    actual_tail = _actual_tail_reference(verified_by_id)
    champion = metrics_by_id["champion"]
    qualification = _qualification(metrics_by_id["market_side_only_hybrid"], champion, actual_tail)
    if qualification["qualified_for_shadow"]:
        decision = "MARKET_SIDE_FUSION_PROMISING"
        next_milestone = "bounded prospective shadow"
    else:
        decision = "MARKET_SIDE_ONLY_NOT_SUFFICIENT"
        next_milestone = "football evidence / team strength representation; stop market/lambda patch series"

    result = {
        "schema_version": "pred_trust_3.replay.v1",
        "milestone": "PRED-TRUST-3",
        "status": "READY_FOR_ACCEPTANCE",
        "decision": decision,
        "generated_at": "2026-08-30T00:00:00+08:00",
        "source": {
            "pred_trust_2_replay_sha256": _sha256_file(pred_trust_2_replay_path),
            "pred_trust_2_replay_decision": pred_trust_2_replay["decision"],
            "accepted_production_run": ACCEPTED_PRODUCTION_RUN,
            "accepted_writeback_commit": ACCEPTED_WRITEBACK_COMMIT,
            "pred_trust_1_head": PINNED_PRED_TRUST_1_HEAD,
            "audit_artifact_sha256": _sha256_file(audit_path),
            "cohort_manifest_sha256": _sha256_file(manifest_path),
            "no_new_data": True,
            "post_match_fields_used_only_for_evaluation": True,
        },
        "cohort": {
            "pinned_unique_final_legal_prematch_matches": len(records),
            "verified_90m_matches": len(verified_by_id),
            "unverified_pinned_matches": len(records) - len(verified_by_id),
            "selected_prediction_digest": manifest["selected_prediction_digest"],
            "verified_prediction_digest": manifest["verified_prediction_digest"],
            "integrity": "record and input snapshot hashes matched the accepted PRED-TRUST-2 manifest",
        },
        "dependency_map": {
            "football_evidence": "frozen source_snapshots.shuju.recent_form",
            "recent_form": "venue-specific and overall goals for/against -> form_home/form_away",
            "market_baseline": "frozen multi-book 1X2 consensus + total line",
            "strength_representation": "form_share = clipped form_home / (form_home + form_away)",
            "calibration": "embedded Champion calibration is inactive/shadow_only in the pinned inputs",
            "lambda_home_away": "Champion total=0.60 form + 0.40 market; Champion share=0.65 form + 0.35 market",
            "candidate_c_boundary": "retain Champion total; replace only side share with market_share",
            "probability_state": "independent Poisson score matrix with rho=0 -> 1X2 / BTTS / totals / exact score",
        },
        "candidate_specs": list(CANDIDATE_SPECS),
        "excluded_candidates": {
            "challenger_a_strength_separation": "REJECT from PRED-TRUST-2; not replayed",
        },
        "reproduction": {
            "candidate_count": len(CANDIDATE_SPECS),
            "replay_rows_per_candidate": {candidate_id: len(rows) for candidate_id, rows in candidate_rows.items()},
            "max_absolute_lambda_delta": max_absolute_lambda_delta,
            "selector_recomputed": False,
            "post_match_parameter_input": False,
            "input_status": input_status,
            "calibration_state": calibration_states,
        },
        "actual_tail_reference": actual_tail,
        "metrics_by_candidate": _metrics_without_rows(metrics_by_id),
        "tradeoff_table": _tradeoff_table(metrics_by_id),
        "qualification": qualification,
        "product_interpretation": {
            "recommended_choice": "single exact-score Top1 with insufficient-confidence warning",
            "reason": "Keep the current exact-score contract and communicate uncertainty; do not change UI in this milestone.",
        },
        "next_single_milestone": next_milestone,
        "stop_state": {
            "champion_modified": False,
            "production_enabled": False,
            "shadow_enabled": False,
            "frozen_predictions_rewritten": False,
            "prospective_ledger_rewritten": False,
            "health_monitor_modified": False,
            "health_gate_modified": False,
            "new_provider_added": False,
            "parameter_sweep": False,
            "offline_batches": 1,
        },
    }
    _write_json(output_path, result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(result), encoding="utf-8")
    return result


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "n/a"
        return f"{value:.4f}"
    return str(value)


def render_markdown(result: Mapping[str, Any]) -> str:
    metrics = result["metrics_by_candidate"]
    labels = {
        "champion": "Champion",
        "existing_challenger_b_market_to_goal_separation": "Existing B",
        "market_side_only_hybrid": "New C",
    }
    lines = [
        "# PRED-TRUST-3 - Market-Side-Only Hybrid Knockout",
        "",
        f"Status: `{result['status']}`",
        f"Decision: `{result['decision']}`",
        "",
        "## Pinned scope",
        "",
        f"- PRED-TRUST-2 replay SHA-256: `{result['source']['pred_trust_2_replay_sha256']}`",
        f"- Accepted production run: `{result['source']['accepted_production_run']}`",
        f"- Accepted write-back commit: `{result['source']['accepted_writeback_commit']}`",
        f"- Cohort: `{result['cohort']['pinned_unique_final_legal_prematch_matches']}` unique final legal prematch; `{result['cohort']['verified_90m_matches']}` verified 90m",
        "- Exactly one new candidate C; no new data, fitting, selector rerun, or post-match parameter input.",
        "",
        "## Candidate formulas",
        "",
        "```text",
        "Champion: total=0.60*form_total+0.40*market_total; share=0.65*form_share+0.35*market_share",
        "Existing B: total=market_total; share=market_share",
        "New C: total=Champion total; share=market_share",
        "All candidates: clamp + independent Poisson + rho=0 + same score matrix",
        "```",
        "",
        "Challenger A remains excluded because PRED-TRUST-2 already marked it REJECT.",
        "",
        "## Verified 90m metrics",
        "",
        "| Metric | Champion | Existing B | New C |",
        "|---|---:|---:|---:|",
    ]
    verified_paths = (
        ("1X2 accuracy", "one_x_two.accuracy"),
        ("1X2 Brier", "one_x_two.brier"),
        ("1X2 LogLoss", "one_x_two.log_loss"),
        ("1X2 macro ECE", "one_x_two.ece"),
        ("Exact Top1 hit", "exact_score.top1_hit_rate"),
        ("Exact Top3 hit", "exact_score.top3_hit_rate"),
        ("Exact NLL", "exact_score.nll"),
        ("Actual-score probability", "exact_score.mean_probability_assigned_to_actual_score"),
        ("BTTS accuracy", "btts.accuracy"),
        ("BTTS Brier", "btts.brier"),
        ("BTTS ECE", "btts.ece"),
        ("O/U 2.5 accuracy", "ou_2_5.accuracy"),
        ("O/U 2.5 Brier", "ou_2_5.brier"),
        ("O/U 2.5 ECE", "ou_2_5.ece"),
    )
    for label, path in verified_paths:
        lines.append(f"| {label} | " + " | ".join(_fmt(_metric_value(metrics[candidate_id], path)) for candidate_id in labels) + " |")
    lines.extend([
        "",
        "## Lambda and score distribution (n=217)",
        "",
        "| Metric | Champion | Existing B | New C |",
        "|---|---:|---:|---:|",
    ])
    distribution_paths = (
        ("Median lambda total", "distribution.lambda_total.P50"),
        ("Median absolute lambda gap", "distribution.absolute_gap.P50"),
        ("Gap <0.25 share", "distribution.gap_lt_0_25_share"),
        ("Gap <0.5 share", "distribution.gap_lt_0_5_share"),
        ("1-1 Top1 share", "distribution.one_one_top1_share"),
        ("Top1 support size", "distribution.top1_support_size"),
        ("Home-margin Top1 share", "distribution.home_margin_top1_share"),
        ("Draw Top1 share", "distribution.draw_top1_share"),
        ("Away-margin Top1 share", "distribution.away_margin_top1_share"),
        ("High-score Top1 share", "distribution.high_score_top1_share"),
        ("Mean P(total>=4)", "distribution.mean_probability_total_ge_4"),
        ("Mean P(total>=5)", "distribution.mean_probability_total_ge_5"),
        ("Mean P(total>=6)", "distribution.mean_probability_total_ge_6"),
    )
    for label, path in distribution_paths:
        lines.append(f"| {label} | " + " | ".join(_fmt(_metric_value(metrics[candidate_id], path)) for candidate_id in labels) + " |")
    actual = result["actual_tail_reference"]
    lines.extend([
        "",
        f"Actual verified tail: total>=4 `{actual['actual_total_ge_4_share']:.4f}`, total>=5 `{actual['actual_total_ge_5_share']:.4f}`, total>=6 `{actual['actual_total_ge_6_share']:.4f}`.",
        "",
        "## Machine trade-off table",
        "",
        "Every Existing B/New C cell is `BETTER`, `SAME`, or `WORSE` against Champion using the fixed SAME tolerance.",
        "",
        "| Metric | Champion | Existing B value/status | New C value/status |",
        "|---|---:|---:|---:|",
    ])
    for row in result["tradeoff_table"]:
        existing_b = row["existing_challenger_b_market_to_goal_separation"]
        new_c = row["market_side_only_hybrid"]
        lines.append(f"| {row['metric']} | {_fmt(row['champion'])} | {_fmt(existing_b['value'])} / **{existing_b['status']}** | {_fmt(new_c['value'])} / **{new_c['status']}** |")
    qualification = result["qualification"]
    failed = [key for key, value in qualification["checks"].items() if not value]
    lines.extend([
        "",
        "## Decision",
        "",
        f"New C qualification: `{'PASS' if qualification['qualified_for_shadow'] else 'FAIL'}`.",
        f"Failed checks: `{', '.join(failed) if failed else 'none'}`.",
        f"Final bounded decision: **{result['decision']}**.",
        f"Next sole milestone: **{result['next_single_milestone']}**.",
        "",
        "## Product interpretation",
        "",
        "Keep a single exact-score Top1 with an insufficient-confidence warning. No UI change is part of this milestone.",
        "",
        "## STOP state",
        "",
        "Champion, production, shadow, frozen predictions, prospective ledger, health monitor/gate, providers, and frontend were not changed.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--pred-trust-2-replay", type=Path, default=DEFAULT_PRED_TRUST_2_REPLAY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_replay(
        root=args.root,
        pred_trust_2_replay_path=args.pred_trust_2_replay,
        manifest_path=args.manifest,
        audit_path=args.audit,
        output_path=args.output,
        report_path=args.report,
    )
    print(json.dumps({"status": result["status"], "decision": result["decision"], "output": str(args.output), "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
