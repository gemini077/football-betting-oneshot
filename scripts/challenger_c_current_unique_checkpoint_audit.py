#!/usr/bin/env python3
"""Run a read-only current unique-match checkpoint for Challenger C.

Issue #169 uses the existing Challenger C pair artifacts, representative
selector, checkpoint semantics, and promotion review.  This wrapper never
refits or writes the production shadow artifact; it builds a temporary
current pair-set document only so the existing review code can evaluate all
tracked pair/version rows when ``latest.json`` lags the pair directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import challenger_c_promotion_review as promotion_review  # noqa: E402
import market_side_shadow as shadow  # noqa: E402
import market_side_shadow_refresh as shadow_refresh  # noqa: E402


MILESTONE = "CHALLENGER-C-CURRENT-UNIQUE-CHECKPOINT-2"
SCHEMA_VERSION = "challenger_c_current_unique_checkpoint_2.v1"
DEFAULT_LATEST = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
DEFAULT_PAIR_ROOT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
DEFAULT_RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
DEFAULT_CONFIG = ROOT / "config" / "model_governance.json"
DEFAULT_OUTPUT_DIR = Path("audit-artifact")

METRIC_COLUMNS = (
    "exact_top1",
    "exact_top3",
    "exact_nll",
    "one_x_two_accuracy",
    "one_x_two_brier",
    "one_x_two_log_loss",
    "one_x_two_ece",
    "btts_accuracy",
    "btts_brier",
    "btts_log_loss",
    "btts_ece",
    "ou_2_5_accuracy",
    "ou_2_5_brier",
    "ou_2_5_log_loss",
    "one_one_top1_share",
    "lambda_median_abs_gap",
    "lambda_gap_lt_0_5_share",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _git_sha(ref: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", ref],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _pair_inventory(pair_root: Path) -> dict[str, Any]:
    paths = sorted(pair_root.glob("MS-SHADOW-PAIR-*.json"))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return {
        "file_count": len(paths),
        "inventory_sha256": digest.hexdigest(),
        "filenames": [path.name for path in paths],
    }


def _compact_reproduction(value: Mapping[str, Any]) -> dict[str, Any]:
    mismatches = value.get("mismatches")
    return {
        "status": value.get("status"),
        "mismatch_count": len(mismatches) if isinstance(mismatches, list) else None,
    }


def _compact_slices(slices: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, value in slices.items():
        if not isinstance(value, Mapping):
            continue
        output[str(name)] = {
            "representative_count": value.get("representative_count"),
            "pair_row_count": value.get("pair_row_count"),
            "unique_match_count": value.get("unique_match_count"),
            "metrics": value.get("metrics"),
        }
    return output


def _metric_table(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in ("champion", "challenger"):
        candidate_metrics = metrics.get(candidate) or {}
        rows.append(
            {
                "candidate": candidate,
                **{column: candidate_metrics.get(column) for column in METRIC_COLUMNS},
            }
        )
    return rows


def _final_decision(
    checkpoint: Mapping[str, Any],
    review: Mapping[str, Any],
    *,
    pair_artifact_integrity: Mapping[str, Any],
    ambiguous_final_chronology_match_groups: int,
) -> tuple[str, list[str]]:
    fail_closed_reasons: list[str] = []
    if pair_artifact_integrity.get("status") != "PASS":
        fail_closed_reasons.append("PAIR_ARTIFACT_INTEGRITY_FAILED")
    if (review.get("integrity") or {}).get("status") != "PASS":
        fail_closed_reasons.append("PAIR_FREEZE_INTEGRITY_FAILED")
    if (review.get("overall_reproduction") or {}).get("status") != "PASS":
        fail_closed_reasons.append("CURRENT_OVERALL_REPRODUCTION_FAILED")
    if int(ambiguous_final_chronology_match_groups or 0) > 0:
        fail_closed_reasons.append("AMBIGUOUS_FINAL_CHRONOLOGY")
    if (review.get("matching") or {}).get("result_identity_mismatches", 0):
        fail_closed_reasons.append("RESULT_IDENTITY_MISMATCH")
    if (review.get("discovery") or {}).get("result_identity_conflicts", 0):
        fail_closed_reasons.append("RESULT_IDENTITY_CONFLICT")
    if fail_closed_reasons:
        return "FAIL_CLOSED", sorted(set(fail_closed_reasons))

    status = checkpoint.get("status")
    if status == "NOT_REACHED":
        return "NOT_REACHED_KEEP_SHADOW", []
    if status == "CHECKPOINT":
        return "CHECKPOINT_REACHED_KEEP_SHADOW", []
    if status == "PROMOTION_REVIEW_READY":
        return "PROMOTION_REVIEW_READY_PENDING_INDEPENDENT_ACCEPTANCE", []
    return "FAIL_CLOSED", ["UNKNOWN_CHECKPOINT_STATUS"]


def _build_report(summary: Mapping[str, Any]) -> str:
    source = summary["source"]
    state = summary["current_input_state"]
    counts = summary["counts"]
    checkpoint = summary["checkpoint"]
    metrics = summary["metrics"]["unique_match"]
    reproduction = summary["reproduction"]
    safety = summary["safety"]
    controls = summary["controls"]
    lines = [
        f"# {summary['milestone']}",
        "",
        f"- final decision: **`{summary['final_decision']}`**",
        "- research/read-only checkpoint; no refit, new Challenger, Champion, production, provider, frozen-history, serving, or UI change.",
        "",
        "## Current source and pair-set truth",
        "",
        f"- source `origin/main` SHA: `{source['source_main_sha']}`",
        f"- audit HEAD SHA: `{source.get('head_sha')}`",
        f"- latest shadow artifact: `{source['latest_shadow_artifact']}`",
        f"- tracked pair artifact root: `{source['tracked_pair_artifact_root']}`",
        f"- latest.json pair/version rows: `{state['latest_json_pair_rows']}`",
        f"- tracked pair artifact files: `{state['tracked_pair_artifact_files']}`",
        f"- loaded current pair/version rows: `{state['loaded_current_pair_rows']}`",
        f"- tracked rows absent from latest.json: `{state['tracked_rows_absent_from_latest_json']}`",
        f"- current pair inventory SHA-256: `{state['pair_inventory_sha256']}`",
        "- The review input is the current tracked pair-artifact set; latest.json is retained as a read-only comparison and is not rewritten.",
        "",
        "## Current unique-match checkpoint",
        "",
        f"- total pair/version rows: `{counts['total_pair_version_rows']}`",
        f"- promotion-eligible pair/version rows: `{counts['promotion_eligible_pair_version_rows']}`",
        f"- verified pair/version rows: `{counts['verified_pair_version_rows']}`",
        f"- verified paired rows (raw audit alias): `{counts['verified_pair_rows']}`",
        f"- promotion-eligible unique matches: `{counts['promotion_eligible_unique_matches']}`",
        f"- verified unique matches: `{counts['verified_unique_matches']}`",
        f"- version-history match groups: `{counts['version_history_match_groups']}`",
        f"- extra version rows: `{counts['extra_version_rows']}`",
        f"- unmatched eligible unique matches: `{counts['unmatched_eligible_unique_matches']}`",
        f"- duplicate verified match groups / rows: `{counts['duplicate_verified_match_groups']}` / `{counts['duplicate_verified_rows']}`",
        f"- equal-final chronology ambiguity groups: `{summary['ambiguity']['ambiguous_final_chronology_match_groups']}`",
        f"- checkpoint: **`{checkpoint['status']}`** at `{checkpoint['verified_unique_matches']}` unique matches; next threshold `{checkpoint['next_threshold']}`; auto-promote `{checkpoint['auto_promote']}`.",
        "",
        "## Champion-vs-C metrics (unique-match unit)",
        "",
        "The complete existing metric projection, including ECE, BTTS, O/U 2.5, 1-1 Top1 share, and lambda diagnostics, is preserved in summary.json.",
        "",
        "| candidate | n | Exact Top1 | Exact Top3 | Exact NLL | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | 1X2 ECE | BTTS Brier | O/U Brier | 1-1 Top1 | Median Lambda Gap | Lambda Gap < 0.5 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in _metric_table(metrics):
        values = [
            row["candidate"],
            str(metrics[row["candidate"]].get("sample_count")),
            *("-" if row[column] is None else f"{row[column]:.6f}" for column in (
                "exact_top1",
                "exact_top3",
                "exact_nll",
                "one_x_two_accuracy",
                "one_x_two_brier",
                "one_x_two_log_loss",
                "one_x_two_ece",
                "btts_brier",
                "ou_2_5_brier",
                "one_one_top1_share",
                "lambda_median_abs_gap",
                "lambda_gap_lt_0_5_share",
            )),
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## Integrity, reproduction, and safety",
            "",
            f"- pair/freeze integrity: `{summary['integrity']['status']}`",
            f"- current pair-set overall reproduction: `{reproduction['current_pair_set_overall']['status']}` ({reproduction['current_pair_set_overall']['mismatch_count']} mismatches)",
            f"- latest.json versus current pair-set projection: `{reproduction['latest_json_vs_current_pair_set']['status']}` ({reproduction['latest_json_vs_current_pair_set']['mismatch_count']} mismatches)",
            f"- accepted historical version-row projection: `{reproduction['accepted_version_row_baseline']['status']}` ({reproduction['accepted_version_row_baseline']['mismatch_count']} mismatches); diagnostic only, not a current checkpoint gate.",
            f"- existing safety gate: `{safety['safety_gate']['status']}`",
            f"- meaningful subgroup safety: `{safety['subgroup_safety']['status']}`",
            f"- result files discovered/accepted/rejected: `{summary['discovery']['result_files_scanned']}` / `{summary['discovery']['result_files_accepted']}` / `{summary['discovery']['result_files_rejected']}`",
            "",
            "## Stop state",
            "",
            f"- controls: `{json.dumps(controls, ensure_ascii=False, sort_keys=True)}`",
            f"- production action: `{summary['production_action']}`",
            f"- final decision: **`{summary['final_decision']}`**",
            "- DO NOT MERGE. Independent acceptance decides any later action.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    latest_path: Path = DEFAULT_LATEST,
    pair_root: Path = DEFAULT_PAIR_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    universe_root: Path = DEFAULT_UNIVERSE_ROOT,
    config_path: Path = DEFAULT_CONFIG,
    source_main_sha: str | None = None,
    head_sha: str | None = None,
) -> dict[str, Any]:
    latest_path = Path(latest_path)
    pair_root = Path(pair_root)
    result_root = Path(result_root)
    universe_root = Path(universe_root)
    config_path = Path(config_path)
    latest = _load_json(latest_path)
    if not isinstance(latest, dict):
        raise ValueError("latest shadow artifact must be an object")
    if latest.get("candidate_id") != shadow.CANDIDATE_ID:
        raise ValueError("latest shadow artifact is not Challenger C")

    inventory = _pair_inventory(pair_root)
    pairs = shadow.load_persisted_pairs(pair_root)
    pair_ids = [str(pair.get("pair_id") or "") for pair in pairs]
    latest_pairs = [pair for pair in latest.get("pairs") or [] if isinstance(pair, dict)]
    latest_ids = {str(pair.get("pair_id") or "") for pair in latest_pairs}
    current_ids = set(pair_ids)
    pair_artifact_integrity = {
        "status": "PASS"
        if inventory["file_count"] == len(pairs) == len(current_ids) and "" not in current_ids
        else "FAIL",
        "tracked_file_count": inventory["file_count"],
        "loaded_pair_count": len(pairs),
        "duplicate_pair_id_count": len(pair_ids) - len(current_ids),
    }

    discovery_catalog, discovery = shadow_refresh.discover_verified_results(result_root)
    result_map, matching = shadow_refresh.build_identity_safe_result_map(
        pairs, discovery_catalog
    )
    source_manifest = {
        "source_latest_json": _relative_path(latest_path),
        "source_pair_artifacts": _relative_path(pair_root),
        "current_pair_artifact_file_count": inventory["file_count"],
        "result_files_scanned": discovery["result_files_scanned"],
        "result_files_accepted": discovery["result_files_accepted"],
        "matched_pair_count": matching["matched_pair_count"],
    }
    current_document = shadow.build_shadow_document(
        pairs,
        result_map,
        source_manifest=source_manifest,
    )
    if isinstance(latest.get("source_pins"), dict):
        current_document["source_pins"] = latest["source_pins"]

    with tempfile.TemporaryDirectory(prefix="fbos-challenger-c-checkpoint-") as temporary:
        temporary_latest = Path(temporary) / "latest.json"
        temporary_latest.write_text(
            json.dumps(current_document, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        review = promotion_review.run_review(
            latest_path=temporary_latest,
            result_root=result_root,
            universe_root=universe_root,
            config_path=config_path,
        )

    counts = dict(review["counts"])
    selector_counts = dict((review.get("representative_selector") or {}).get("counts") or {})
    verified_unique_matches = int(counts["verified_unique_matches"])
    checkpoint = shadow.checkpoint_status(
        verified_unique_matches,
        verified_pair_version_rows=int(counts["verified_pair_version_rows"]),
    )
    latest_projection = promotion_review.compact_evaluation(latest.get("evaluation") or {})
    current_projection = promotion_review.compact_evaluation(current_document["evaluation"])
    latest_vs_current = promotion_review._metric_projection_matches(
        current_projection,
        latest_projection,
    )
    ambiguous_final = int(selector_counts.get("ambiguous_final_chronology_match_groups") or 0)
    final_decision, fail_closed_reasons = _final_decision(
        checkpoint,
        review,
        pair_artifact_integrity=pair_artifact_integrity,
        ambiguous_final_chronology_match_groups=ambiguous_final,
    )

    resolved_source_main_sha = source_main_sha or _git_sha("origin/main")
    if not resolved_source_main_sha:
        raise ValueError("SOURCE_MAIN_SHA_UNAVAILABLE")
    resolved_head_sha = head_sha or _git_sha("HEAD")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "source": {
            "source_main_ref": "origin/main",
            "source_main_sha": resolved_source_main_sha,
            "head_sha": resolved_head_sha,
            "latest_shadow_artifact": _relative_path(latest_path),
            "tracked_pair_artifact_root": _relative_path(pair_root),
            "authoritative_result_root": _relative_path(result_root),
            "prediction_universe_root": _relative_path(universe_root),
            "model_governance_config": _relative_path(config_path),
            "new_matches_fetched": False,
            "network_access": "NO_NETWORK",
            "read_only": True,
        },
        "current_input_state": {
            "latest_json_sha256": _sha256_file(latest_path),
            "latest_json_pair_rows": len(latest_pairs),
            "tracked_pair_artifact_files": inventory["file_count"],
            "loaded_current_pair_rows": len(pairs),
            "tracked_rows_absent_from_latest_json": len(current_ids - latest_ids),
            "latest_rows_absent_from_tracked_artifacts": len(latest_ids - current_ids),
            "pair_inventory_sha256": inventory["inventory_sha256"],
            "pair_artifact_integrity": pair_artifact_integrity,
            "current_pair_set_used_for_review": True,
        },
        "counts": {
            **counts,
            "tracked_pair_artifact_files": inventory["file_count"],
            "latest_json_pair_rows": len(latest_pairs),
            "duplicate_or_equal_final_ambiguity_failures": ambiguous_final,
        },
        "checkpoint": checkpoint,
        "metrics": {
            "metric_unit": review["overall"]["metric_unit"],
            "unique_match": review["overall"]["metrics"],
            "version_row_audit": review["overall"]["version_row_audit_metrics"],
            "meaningful_slices": _compact_slices(review.get("slices") or {}),
            "slice_counts": review.get("slice_counts") or {},
        },
        "integrity": review["integrity"],
        "discovery": discovery,
        "matching": matching,
        "reproduction": {
            "current_pair_set_overall": _compact_reproduction(review["overall_reproduction"]),
            "latest_json_vs_current_pair_set": _compact_reproduction(latest_vs_current),
            "accepted_version_row_baseline": _compact_reproduction(
                review["version_row_reproduction"]
            ),
        },
        "representative_selection": {
            "selector": (review.get("representative_selector") or {}).get("selector"),
            "selector_version": (review.get("representative_selector") or {}).get(
                "selector_version"
            ),
            "counts": selector_counts,
        },
        "ambiguity": {
            "duplicate_verified_match_groups": counts.get("duplicate_verified_match_groups"),
            "duplicate_verified_rows": counts.get("duplicate_verified_rows"),
            "ambiguous_final_chronology_match_groups": ambiguous_final,
            "result_identity_conflicts": discovery.get("result_identity_conflicts"),
            "result_identity_mismatches": matching.get("result_identity_mismatches"),
        },
        "safety": {
            "safety_gate": review["safety_gate"],
            "subgroup_safety": review["subgroup_safety"],
            "safety_floors": review["safety_floors"],
        },
        "controls": {
            "research_only": True,
            "challenger_id": shadow.CANDIDATE_ID,
            "challenger_refit": False,
            "new_challenger_created": False,
            "champion_modified": False,
            "production_modified": False,
            "provider_modified": False,
            "frozen_history_rewritten": False,
            "serving_modified": False,
            "ui_modified": False,
            "auto_promote": False,
            "promotion_attempted": False,
            "current_pair_set_built_in_memory_only": True,
            "target_results_fetched": False,
        },
        "production_action": "STOPPED_BEFORE_PROMOTION",
        "final_decision": final_decision,
        "fail_closed_reasons": fail_closed_reasons,
        "stop_state": "STOP_AFTER_CURRENT_UNIQUE_CHECKPOINT_EVIDENCE",
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--universe-root", type=Path, default=DEFAULT_UNIVERSE_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-main-sha")
    parser.add_argument("--head-sha")
    args = parser.parse_args(argv)
    summary = run_audit(
        latest_path=args.latest,
        pair_root=args.pair_root,
        result_root=args.result_root,
        universe_root=args.universe_root,
        config_path=args.config,
        source_main_sha=args.source_main_sha,
        head_sha=args.head_sha,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(
        _build_report(summary),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "milestone": summary["milestone"],
                "source_main_sha": summary["source"]["source_main_sha"],
                "tracked_pair_artifact_files": summary["current_input_state"][
                    "tracked_pair_artifact_files"
                ],
                "verified_unique_matches": summary["counts"]["verified_unique_matches"],
                "checkpoint_status": summary["checkpoint"]["status"],
                "final_decision": summary["final_decision"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
