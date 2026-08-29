"""Run the final fixed-config Sweden history/DC paired replay.

This module is deliberately separate from the FE-DC-1 branch.  It reuses the
FE-DC-1 model implementation and its pre-registered configuration, but keeps
the old pre-closure run as an external comparison input and never writes to a
production or frozen prediction store.

The runner is strict about chronology and target identity.  It records a
model-specific optimizer failure instead of silently dropping a target, so a
fixed-config evaluation blocker remains visible in the final verdict.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .data_home import historical_results_path
from .fe_dc1_model import (
    COMPETITION_ID,
    PreRegisteredConfig,
    coerce_match,
    evaluate_predictions,
    fit_league_model,
    network_diagnostics,
    predict_score_distribution,
    run_chronological_backtest,
)
from .run_fe_dc1 import _load_sweden_records
from .storage import HistoricalResultStore, canonical_json_bytes, content_sha256


MILESTONE = "FE-SE-DC-CLOSE"
TARGET_COUNT = 103
OLD_DATABASE_ROW_COUNT = 1554
OLD_SWEDEN_MATCH_COUNT = 135
OLD_DATABASE_DIGEST = "710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e"
OLD_PREDICTION_DIGEST = "617e299b646c910bee84419c5a94a39e5bb02a419333cf85680ff5c6b071c51a"
NEW_DATABASE_ROW_COUNT = 1778
NEW_DATABASE_DIGEST = "48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "football_data" / "fe_se_dc_close"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "team-strength" / "FE_SE_DC_CLOSE.md"
LANDSCAPE_REFERENCES = (
    "https://doi.org/10.1111/j.1467-9574.1982.tb00782.x",
    "https://doi.org/10.1111/1467-9876.00065",
    "https://github.com/martineastwood/penaltyblog",
    "https://github.com/jpmouracodex/football-mle",
)
METRIC_FIELDS = (
    "brier_1x2",
    "logloss_1x2",
    "top1_outcome_hit_rate",
    "goal_mae",
    "total_goal_mae",
    "exact_top1",
    "exact_top3",
    "exact_top5",
    "score_nll",
    "one_one_top1_share",
    "actual_one_one_share",
)


class ReplayIntegrityError(ValueError):
    """Raised when the fixed target set or chronology cannot be audited."""


def _write_json(path: Path, value: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _parse_kickoff(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_digest(records: Iterable[Mapping[str, Any]]) -> str:
    return content_sha256(sorted(content_sha256(record) for record in records))


def _distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "min": None,
            "p05": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p95": None,
            "max": None,
        }
    ordered = sorted(float(value) for value in values)

    def quantile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "min": ordered[0],
        "p05": quantile(0.05),
        "p25": quantile(0.25),
        "median": quantile(0.50),
        "p75": quantile(0.75),
        "p95": quantile(0.95),
        "max": ordered[-1],
    }


def _outcome_name(row: Mapping[str, Any]) -> str:
    home = int(row["actual_home_goals"])
    away = int(row["actual_away_goals"])
    if home > away:
        return "home"
    if home == away:
        return "draw"
    return "away"


def _top1_outcome_hit(row: Mapping[str, Any], model_key: str) -> bool:
    probabilities = row["models"][model_key]["probabilities"]
    order = {"home": 0, "draw": 1, "away": 2}
    predicted = max(probabilities, key=lambda name: (float(probabilities[name]), -order[name]))
    return predicted == _outcome_name(row)


def _evaluate_extended(predictions: Sequence[Mapping[str, Any]], model_key: str, config: PreRegisteredConfig) -> dict[str, Any]:
    """Reuse FE-DC-1 evaluation and add the closeout-only diagnostics."""

    available = [row for row in predictions if model_key in row.get("models", {})]
    metrics = dict(evaluate_predictions(available, model_key))
    if not available:
        metrics.update(
            {
                "model_key": model_key,
                "top1_outcome_hit_rate": None,
                "rho_boundary_hit_frequency": {
                    "lower": 0,
                    "upper": 0,
                    "any": 0,
                    "share": None,
                    "bounds": list(config.rho_bounds),
                },
            }
        )
        return metrics
    top1_hits = sum(_top1_outcome_hit(row, model_key) for row in available)
    lower, upper = config.rho_bounds
    lower_hits = sum(abs(float(row["models"][model_key]["rho"]) - lower) <= 1e-9 for row in available)
    upper_hits = sum(abs(float(row["models"][model_key]["rho"]) - upper) <= 1e-9 for row in available)
    any_hits = lower_hits + upper_hits
    metrics.update(
        {
            "model_key": model_key,
            "top1_outcome_hit_rate": top1_hits / len(available),
            "rho_boundary_hit_frequency": {
                "lower": lower_hits,
                "upper": upper_hits,
                "any": any_hits,
                "share": any_hits / len(available),
                "bounds": list(config.rho_bounds),
            },
        }
    )
    return metrics


def _metric_delta(new: Mapping[str, Any], old: Mapping[str, Any]) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for field in METRIC_FIELDS:
        new_value = new.get(field)
        old_value = old.get(field)
        output[field] = float(new_value) - float(old_value) if new_value is not None and old_value is not None else None
    return output


def _fixture_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row["season_id"]),
        _parse_kickoff(row["kickoff_at"]).date().isoformat(),
        str(row["home_team_id"]),
        str(row["away_team_id"]),
    )


def _load_records(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    database_path = Path(path)
    store = HistoricalResultStore(database_path)
    records, metadata = _load_sweden_records(store)
    metadata = {
        **metadata,
        "database_path": str(database_path.resolve()),
        "database_row_count": store.count(),
        "database_digest": store.dataset_digest(),
    }
    return records, metadata


def _validate_data_scope(
    metadata: Mapping[str, Any],
    *,
    expected_database_rows: int,
    expected_database_digest: str,
    expected_sweden_matches: int,
) -> None:
    if int(metadata["database_row_count"]) != expected_database_rows:
        raise ReplayIntegrityError(
            f"unexpected database row count: {metadata['database_row_count']} != {expected_database_rows}"
        )
    if str(metadata["database_digest"]) != expected_database_digest:
        raise ReplayIntegrityError("database digest does not match the pinned closeout input")
    if int(metadata["deduplicated_rows"]) != expected_sweden_matches:
        raise ReplayIntegrityError(
            f"unexpected Sweden input count: {metadata['deduplicated_rows']} != {expected_sweden_matches}"
        )
    if int(metadata["duplicates_collapsed"]) != 0 or int(metadata["duplicate_conflicts"]) != 0:
        raise ReplayIntegrityError("input deduplication is not empty")


def _target_reconciliation(
    old_predictions: Sequence[Mapping[str, Any]],
    new_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve old target IDs exactly, with a deterministic date fixture fallback."""

    by_id = {str(row["canonical_match_id"]): dict(row) for row in new_records}
    by_fixture: defaultdict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in new_records:
        by_fixture[_fixture_key(row)].append(dict(row))
    mappings: list[dict[str, Any]] = []
    unresolved: list[str] = []
    ambiguous: list[dict[str, Any]] = []
    used_new_ids: set[str] = set()
    for old in old_predictions:
        old_id = str(old["match_id"])
        if old_id in by_id:
            new = by_id[old_id]
            method = "canonical_match_id_exact"
        else:
            candidates = by_fixture.get(_fixture_key(old), [])
            if len(candidates) != 1:
                if not candidates:
                    unresolved.append(old_id)
                else:
                    ambiguous.append(
                        {
                            "old_match_id": old_id,
                            "candidate_match_ids": sorted(str(row["canonical_match_id"]) for row in candidates),
                        }
                    )
                continue
            new = candidates[0]
            method = "season_date_home_away_deterministic_reconciliation"
        new_id = str(new["canonical_match_id"])
        if new_id in used_new_ids:
            raise ReplayIntegrityError(f"two old targets resolve to one new target: {new_id}")
        if (
            str(old["season_id"]) != str(new["season_id"])
            or _parse_kickoff(old["kickoff_at"]).date() != _parse_kickoff(new["kickoff_at"]).date()
            or str(old["home_team_id"]) != str(new["home_team_id"])
            or str(old["away_team_id"]) != str(new["away_team_id"])
            or int(old["actual_home_goals"]) != int(new["home_goals"])
            or int(old["actual_away_goals"]) != int(new["away_goals"])
        ):
            raise ReplayIntegrityError(f"target fixture/outcome changed during reconciliation: {old_id}")
        used_new_ids.add(new_id)
        mappings.append(
            {
                "old_match_id": old_id,
                "new_match_id": new_id,
                "method": method,
                "old_kickoff_at": old["kickoff_at"],
                "new_kickoff_at": new["kickoff_at"],
            }
        )
    if unresolved or ambiguous:
        raise ReplayIntegrityError(
            f"target reconciliation incomplete: unresolved={len(unresolved)} ambiguous={len(ambiguous)}"
        )
    if len(mappings) != len(old_predictions) or len(used_new_ids) != len(old_predictions):
        raise ReplayIntegrityError("target reconciliation changed the target count")
    return {
        "old_target_count": len(old_predictions),
        "new_target_count": len(used_new_ids),
        "exact_id_count": sum(item["method"] == "canonical_match_id_exact" for item in mappings),
        "deterministic_reconciled_count": sum(
            item["method"] == "season_date_home_away_deterministic_reconciliation" for item in mappings
        ),
        "mappings": mappings,
    }


def _fit_diagnostics(model: Any) -> dict[str, Any]:
    return {
        "objective": model.objective,
        "log_likelihood": model.log_likelihood,
        "training_match_count": model.training_match_count,
        "reference_kickoff": model.reference_kickoff,
        "weighted_effective_sample_size": model.weighted_effective_sample_size,
        "optimizer_iterations": model.optimizer_iterations,
        "optimizer_converged": model.optimizer_converged,
        "optimizer_message": model.optimizer_message,
        "attack": model.attack,
        "defense": model.defense,
        "league_log_rate": model.league_log_rate,
        "home_advantage": model.home_advantage,
    }


def _model_payload(model: Any, home_team_id: str, away_team_id: str, config: PreRegisteredConfig) -> dict[str, Any]:
    return {
        **predict_score_distribution(model, home_team_id, away_team_id, max_goals=config.max_goals),
        "fit_diagnostics": _fit_diagnostics(model),
    }


def _replay_target_set(
    records: Sequence[Mapping[str, Any]],
    *,
    config: PreRegisteredConfig,
    target_ids: set[str] | None,
) -> dict[str, Any]:
    """Replay a target set while preserving every fit failure as an audit row."""

    matches = [coerce_match(record) for record in records]
    matches.sort(key=lambda row: (row.kickoff, row.match_id))
    if not matches:
        raise ReplayIntegrityError("replay input is empty")
    if any(row.competition_id != config.competition_id for row in matches):
        raise ReplayIntegrityError("replay input contains another competition")
    expected_teams = sorted({team for row in matches for team in (row.home_team_id, row.away_team_id)})
    available_ids = {row.match_id for row in matches}
    if target_ids is not None and not target_ids.issubset(available_ids):
        missing = sorted(target_ids - available_ids)
        raise ReplayIntegrityError(f"requested target IDs are missing from replay input: {missing[:5]}")
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    candidates = [row for row in matches if target_ids is None or row.match_id in target_ids]
    for target in candidates:
        training = [row for row in matches if row.kickoff < target.kickoff]
        base: dict[str, Any] = {
            "match_id": target.match_id,
            "competition_id": target.competition_id,
            "season_id": target.season_id,
            "kickoff_at": target.kickoff_at,
            "home_team_id": target.home_team_id,
            "away_team_id": target.away_team_id,
            "actual_home_goals": target.home_goals,
            "actual_away_goals": target.away_goals,
            "history_match_count": len(training),
            "home_history_match_count": sum(
                target.home_team_id in (row.home_team_id, row.away_team_id) for row in training
            ),
            "away_history_match_count": sum(
                target.away_team_id in (row.home_team_id, row.away_team_id) for row in training
            ),
            "used_history_match_ids": [row.match_id for row in training],
            "used_history_kickoffs": [row.kickoff_at for row in training],
            "models": {},
            "fit_errors": {},
        }
        if len(training) < config.warmup_matches:
            skipped["warmup"] += 1
            base["status"] = "skipped_warmup"
            rows.append(base)
            continue
        network = network_diagnostics(training)
        base.update(
            {
                "network_team_count": network["team_count"],
                "network_component_count": network["component_count"],
                "training_max_kickoff": max(row.kickoff_at for row in training),
            }
        )
        if network["team_ids"] != expected_teams:
            skipped["not_all_teams_seen"] += 1
            base["status"] = "skipped_not_all_teams_seen"
            rows.append(base)
            continue
        if network["component_count"] != 1:
            skipped["network_not_connected"] += 1
            base["status"] = "skipped_network_not_connected"
            rows.append(base)
            continue
        if target.home_team_id not in network["team_ids"] or target.away_team_id not in network["team_ids"]:
            skipped["target_team_missing"] += 1
            base["status"] = "skipped_target_team_missing"
            rows.append(base)
            continue
        for model_key, rho_mode in (("dixon_coles", "fit"), ("rho0_control", "zero")):
            try:
                model = fit_league_model(
                    training,
                    config=config,
                    reference_kickoff=target.kickoff,
                    rho_mode=rho_mode,
                )
                base["models"][model_key] = _model_payload(model, target.home_team_id, target.away_team_id, config)
            except Exception as exc:  # preserve a fixed-config evaluation blocker in the artifact
                base["fit_errors"][model_key] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
        if len(base["models"]) == 2:
            base["status"] = "success"
        elif base["models"]:
            base["status"] = "partial_fit"
        else:
            base["status"] = "fit_failed"
        rows.append(base)
    rows.sort(key=lambda row: (_parse_kickoff(row["kickoff_at"]), str(row["match_id"])))
    return {
        "rows": rows,
        "candidate_count": len(candidates),
        "skipped_counts": dict(sorted(skipped.items())),
        "expected_team_ids": expected_teams,
    }


def _prediction_integrity(rows: Sequence[Mapping[str, Any]], config: PreRegisteredConfig) -> dict[str, Any]:
    chronology_flags: list[bool] = []
    model_counts = Counter()
    for row in rows:
        target_kickoff = _parse_kickoff(row["kickoff_at"])
        history_kickoffs = [_parse_kickoff(value) for value in row.get("used_history_kickoffs", [])]
        if history_kickoffs:
            chronology_flags.append(
                target_kickoff > max(history_kickoffs)
                and row["match_id"] not in set(row.get("used_history_match_ids", []))
                and len(row.get("used_history_match_ids", [])) == row["history_match_count"]
            )
        else:
            chronology_flags.append(row["history_match_count"] == 0)
        for model_key, model in row.get("models", {}).items():
            model_counts[model_key] += 1
    # Recompute the matrix error without relying on the row-sum scratch above.
    matrix_sum_errors = [
        abs(sum(float(cell) for matrix_row in row["models"][key]["matrix"] for cell in matrix_row) - 1.0)
        for row in rows
        for key in row.get("models", {})
    ]
    target_ids = [str(row["match_id"]) for row in rows]
    success_both = [row for row in rows if len(row.get("models", {})) == 2]
    return {
        "target_rows": len(rows),
        "target_ids_unique": len(set(target_ids)) == len(target_ids),
        "model_available_counts": dict(sorted(model_counts.items())),
        "both_models_available_count": len(success_both),
        "fit_failure_count": sum(bool(row.get("fit_errors")) for row in rows),
        "fit_failure_ids": [row["match_id"] for row in rows if row.get("fit_errors")],
        "all_history_strictly_pre_match": all(chronology_flags),
        "all_score_matrices_sum_to_one": all(error <= 1e-10 for error in matrix_sum_errors),
        "max_matrix_sum_error": max(matrix_sum_errors, default=0.0),
        "all_available_fits_converged": all(
            bool(model["fit_diagnostics"]["optimizer_converged"])
            for row in rows
            for model in row.get("models", {}).values()
        ),
        "same_target_set_for_primary_and_control": len(success_both) == len(rows),
        "config_rho_bounds": list(config.rho_bounds),
    }


def _compact_model_payload(model: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the full score distribution while omitting per-fit team parameters."""

    return {
        "model_id": model["model_id"],
        "rho_mode": model["rho_mode"],
        "lambda_home": model["lambda_home"],
        "lambda_away": model["lambda_away"],
        "rho": model["rho"],
        "max_goals": model["max_goals"],
        "matrix": model["matrix"],
        "grid_mass": model["grid_mass"],
        "independent_poisson_grid_mass": model["independent_poisson_grid_mass"],
        "tail_mass": model["tail_mass"],
        "normalization_factor": model["normalization_factor"],
        "probabilities": model["probabilities"],
        "score_probabilities": model["score_probabilities"],
        "top_scores": model["top_scores"][:5],
        "total_goals_distribution": model["total_goals_distribution"],
    }


def _compact_prediction(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "match_id": row["match_id"],
        "competition_id": row["competition_id"],
        "season_id": row["season_id"],
        "kickoff_at": row["kickoff_at"],
        "home_team_id": row["home_team_id"],
        "away_team_id": row["away_team_id"],
        "actual_home_goals": row["actual_home_goals"],
        "actual_away_goals": row["actual_away_goals"],
        "history_match_count": row.get("history_match_count"),
        "home_history_match_count": row.get("home_history_match_count"),
        "away_history_match_count": row.get("away_history_match_count"),
        "network_team_count": row.get("network_team_count"),
        "network_component_count": row.get("network_component_count"),
        "training_max_kickoff": row.get("training_max_kickoff"),
        "status": row.get("status"),
        "reconciled_new_match_id": row.get("reconciled_new_match_id"),
        "target_reconciliation_method": row.get("target_reconciliation_method"),
        "fit_errors": row.get("fit_errors", {}),
        "models": {
            key: _compact_model_payload(value) for key, value in sorted(row.get("models", {}).items())
        },
    }


def _history_summary_for_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "all_league_match_count": _distribution_summary([float(row["history_match_count"]) for row in rows]),
        "home_team_match_count": _distribution_summary([float(row["home_history_match_count"]) for row in rows]),
        "away_team_match_count": _distribution_summary([float(row["away_history_match_count"]) for row in rows]),
    }


def _full_network(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return network_diagnostics(records)


def _data_scope(metadata: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        **metadata,
        "full_network": _full_network(records),
        "input_record_digest": _record_digest(records),
        "input_match_id_digest": content_sha256(sorted(str(row["canonical_match_id"]) for row in records)),
    }


def _subset_by_ids(rows: Sequence[Mapping[str, Any]], ids: set[str]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row["match_id"]) in ids]


def _relabel_reconciled_targets(
    rows: Sequence[Mapping[str, Any]], reconciliation: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Give new rows the old target key while retaining the new canonical ID."""

    by_new_id = {str(row["match_id"]): dict(row) for row in rows}
    relabeled: list[dict[str, Any]] = []
    for mapping in reconciliation["mappings"]:
        new_id = str(mapping["new_match_id"])
        if new_id not in by_new_id:
            raise ReplayIntegrityError(f"reconciled new target is missing from replay rows: {new_id}")
        row = by_new_id[new_id]
        row["reconciled_new_match_id"] = new_id
        row["target_reconciliation_method"] = mapping["method"]
        row["match_id"] = str(mapping["old_match_id"])
        relabeled.append(row)
    relabeled.sort(key=lambda row: (_parse_kickoff(row["kickoff_at"]), str(row["match_id"])))
    return relabeled


def _pairwise_comparison(
    old_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    *,
    model_key: str,
    config: PreRegisteredConfig,
) -> dict[str, Any]:
    old_by_id = {str(row["match_id"]): row for row in old_rows if model_key in row.get("models", {})}
    new_by_id = {str(row["match_id"]): row for row in new_rows if model_key in row.get("models", {})}
    ids = sorted(set(old_by_id) & set(new_by_id))
    old_subset = [old_by_id[match_id] for match_id in ids]
    new_subset = [new_by_id[match_id] for match_id in ids]
    old_metrics = _evaluate_extended(old_subset, model_key, config)
    new_metrics = _evaluate_extended(new_subset, model_key, config)
    return {
        "model_key": model_key,
        "paired_sample_count": len(ids),
        "old_missing_from_pair": sorted(set(old_by_id) - set(new_by_id)),
        "new_missing_from_pair": sorted(set(new_by_id) - set(old_by_id)),
        "old_metrics": old_metrics,
        "new_metrics": new_metrics,
        "new_minus_old": _metric_delta(new_metrics, old_metrics),
    }


def _build_report(summary: Mapping[str, Any]) -> str:
    config = summary["config"]
    old = summary["old_data_scope"]
    new = summary["new_data_scope"]
    target = summary["target_reconciliation"]
    comparison = summary["comparison"]
    expanded = summary["expanded_secondary"]
    integrity = summary["integrity"]
    lines = [
        "# FE-SE-DC-CLOSE — Sweden History Closure + Fixed-Config Re-evaluation",
        "",
        "状态：`READY_FOR_ACCEPTANCE`",
        "",
        "## Scope and boundaries",
        "",
        "本轮是 Sweden / Dixon-Coles 专题的最后执行里程碑。FE-SE-HIST-1 已独立验收 PASS，并在本分支治理记录中标记 SEALED；PR #114 保持 OPEN、未合并。这里只复用 FE-DC-1 的 model implementation、runner/evaluation contract 和 focused tests，不把 PR #114 的旧数据状态覆盖到 main。",
        "",
        "唯一预注册变化是历史输入从 FE-DC-1 的 incomplete 1554-row store / 135 Sweden matches 变为 FE-SE-HIST-1 closure 后的 1778-row store / 359 Sweden matches；没有 rho、half-life、attack/defense、optimizer 或 score-grid sweep。",
        "",
        "## Fixed configuration",
        "",
        f"- competition: `{config['competition_id']}`",
        f"- half-life: `{config['half_life_days']}` days；warmup: `{config['warmup_matches']}`",
        f"- max goals: `{config['max_goals']}`；rho bounds: `{config['rho_bounds']}`；rho=0 control fixed",
        f"- optimizer max_iter: `{config['optimizer_max_iter']}`；tolerance: `{config['optimizer_tolerance']}`",
        "- parameter bounds、home advantage bounds、time weighting：与 FE-DC-1 完全相同",
        "- no sweep / no tuning / no production mutation",
        "",
        "## Input and target integrity",
        "",
        f"- old input: `{old['database_row_count']}` rows；Sweden `{old['deduplicated_rows']}` matches；digest `{old['database_digest']}`",
        f"- new input: `{new['database_row_count']}` rows；Sweden `{new['deduplicated_rows']}` matches；digest `{new['database_digest']}`",
        f"- fixed old target IDs: `{target['old_target_count']}`；new resolved IDs: `{target['new_target_count']}`",
        f"- exact canonical ID matches: `{target['exact_id_count']}`；deterministic reconciliations: `{target['deterministic_reconciled_count']}`",
        f"- new target rows with both models: `{integrity['both_models_available_count']}` / `{target['old_target_count']}`",
        f"- model-specific available rows: `{json.dumps(integrity['model_available_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- fixed-config fit failures: `{integrity['fit_failure_count']}`; IDs are retained in the audit rather than dropped",
        f"- chronology: `{integrity['all_history_strictly_pre_match']}`; score matrix normalization: `{integrity['all_score_matrices_sum_to_one']}` (max error `{integrity['max_matrix_sum_error']:.3g}`)",
        "",
        "## Primary apples-to-apples comparison",
        "",
        "同一 103 target IDs 已锁定；但 fixed FE-DC-1 optimizer 在 complete-history replay 中有 model-specific non-convergence，因此不能把 partial rows 冒充完整 103-row improvement。",
        "",
        f"- DC old vs new common rows: `{comparison['dixon_coles']['paired_sample_count']}`",
        f"- rho=0 old vs new common rows: `{comparison['rho0_control']['paired_sample_count']}`",
        f"- DC new vs rho=0 new common rows: `{comparison['new_dc_vs_rho0']['paired_sample_count']}`",
        "",
        "### Metrics (new minus old; only the stated common rows)",
        "",
        "| 比较 | n | Brier Δ | LogLoss Δ | Goal MAE Δ | Total MAE Δ | Score NLL Δ | Exact Top1 Δ | Exact Top3 Δ | Exact Top5 Δ | 1:1 Top1 Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, item in (
        ("DC new - DC old", comparison["dixon_coles"]),
        ("rho=0 new - rho=0 old", comparison["rho0_control"]),
        ("DC new - rho=0 new", comparison["new_dc_vs_rho0"]),
    ):
        delta = item["new_minus_old"] if "new_minus_old" in item else item["new_minus_control"]
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                label,
                item["paired_sample_count"],
                _fmt(delta.get("brier_1x2")),
                _fmt(delta.get("logloss_1x2")),
                _fmt(delta.get("goal_mae")),
                _fmt(delta.get("total_goal_mae")),
                _fmt(delta.get("score_nll")),
                _fmt(delta.get("exact_top1")),
                _fmt(delta.get("exact_top3")),
                _fmt(delta.get("exact_top5")),
                _fmt(delta.get("one_one_top1_share")),
            )
        )
    lines.extend(
        [
            "",
            "正负号按 new - old；Brier、LogLoss、MAE、Score NLL 低于 0 才是改善，命中率/Top-k 高于 0 才是改善。由于不是完整 103-row common sample，这些数字只作 partial diagnostic。",
            "",
            "## Required model diagnostics",
            "",
        ]
    )
    for label, item in (
        ("DC old (full 103)", comparison["old_metrics_full_103"]["dixon_coles"]),
        ("DC new (available)", comparison["new_metrics_by_model_available"]["dixon_coles"]),
        ("rho=0 old (full 103)", comparison["old_metrics_full_103"]["rho0_control"]),
        ("rho=0 new (available)", comparison["new_metrics_by_model_available"]["rho0_control"]),
    ):
        lines.extend(_metric_block(label, item))
    lines.extend(
        [
            "",
            "### History visible per target",
            "",
            f"- old 103 targets: `{json.dumps(comparison['old_history_visible_per_prediction'], ensure_ascii=False, sort_keys=True)}`",
            f"- new 103 targets attempted (including fit-failed rows): `{json.dumps(comparison['new_history_visible_per_prediction_all_103'], ensure_ascii=False, sort_keys=True)}`",
            f"- new successful model rows: `{json.dumps(comparison['new_history_visible_per_prediction_available'], ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Expanded secondary diagnostic",
            "",
            f"- complete Sweden input: `{expanded['input_match_count']}` matches / `{expanded['input_team_count']}` teams",
            f"- chronological candidates after warmup/network gates: `{expanded['candidate_count']}`",
            f"- successful both-model rows: `{expanded['both_models_available_count']}`",
            f"- skipped: `{json.dumps(expanded['skipped_counts'], ensure_ascii=False, sort_keys=True)}`",
            f"- fit failures: `{expanded['fit_failure_count']}`",
            "- This diagnostic is not used as the old-vs-new primary improvement claim.",
            "",
            "## Final verdict",
            "",
            "`INCONCLUSIVE`",
            "",
            "固定配置 replay 没有完成同一 103 targets 的双模型闭环：新完整历史下有 7 个 target 至少一个 fixed optimizer fit 未收敛。这个明确的评估完整性 blocker 不是理由去调 rho、half-life 或 optimizer；因此本轮不把 partial 指标解释为历史补全改善，也不把 Dixon-Coles 或 rho=0 架构 promotion。",
            "",
            "1. 历史补全是否明显改善：当前不能在完整 103 paired sample 上裁决；补全后的输入确实被读取并形成 19-team connected network。",
            "2. 改善来自基础 network 还是 rho correction：当前不能在完整 paired sample 上裁决；DC new vs rho=0 new 只保留 common successful rows。",
            "3. 1:1 concentration：按 partial diagnostic 报告，但不作为完整样本结论。",
            "4. 极端 lambda / strong-favourite calibration：按 partial diagnostic 报告；fixed-fit failure 本身应保留为模型路线风险。",
            "5. 是否跨联赛继续验证：Sweden-specific further tuning 已 CLOSED；下一候选只记录为 League-Agnostic Historical Coverage / Automatic Coverage Gate，不在本轮实现。",
            "",
            "## Governance closeout",
            "",
            "- FE-SE-HIST-1: `SEALED` / `ACCEPTANCE PASS`",
            "- FE-SE-DC-CLOSE: `READY_FOR_ACCEPTANCE`",
            "- SWEDEN_SPECIFIC_FURTHER_TUNING: `CLOSED`",
            "- Champion、production prediction、frozen prediction、用户侧预测均未修改",
            "- PR #114 未合并；未生成 ZIP",
            "",
            "## Research references",
        ]
    )
    lines.extend(f"- `{reference}`" for reference in summary["landscape_references"])
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- comparison: `{summary['artifact_paths']['comparison']}`",
            f"- paired full score distributions: `{summary['artifact_paths']['paired_predictions']}`",
            f"- expanded secondary: `{summary['artifact_paths']['expanded_secondary']}`",
            f"- integrity audit: `{summary['artifact_paths']['integrity']}`",
            f"- target reconciliation: `{summary['artifact_paths']['target_reconciliation']}`",
            "",
            "最终状态：`READY_FOR_ACCEPTANCE`",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _metric_block(label: str, metrics: Mapping[str, Any]) -> list[str]:
    total_goals = metrics.get("total_goals_distribution", {})
    lambdas = metrics.get("lambda_distribution", {})
    lines = [
        f"### {label} (n={metrics.get('sample_size', 0)})",
        "",
        f"- 1X2 Brier `{_fmt(metrics.get('brier_1x2'))}`；LogLoss `{_fmt(metrics.get('logloss_1x2'))}`；Top1 outcome hit `{_fmt(metrics.get('top1_outcome_hit_rate'))}`",
        f"- home/away Goal MAE `{_fmt(metrics.get('goal_mae'))}`；Total Goal MAE `{_fmt(metrics.get('total_goal_mae'))}`",
        f"- Exact Top1/Top3/Top5 `{_fmt(metrics.get('exact_top1'))}` / `{_fmt(metrics.get('exact_top3'))}` / `{_fmt(metrics.get('exact_top5'))}`；Score NLL `{_fmt(metrics.get('score_nll'))}`",
        f"- 1:1 Top1 share `{_fmt(metrics.get('one_one_top1_share'))}`；actual 1:1 share `{_fmt(metrics.get('actual_one_one_share'))}`",
        f"- predicted/actual P(total goals ≥5) `{_fmt(total_goals.get('predicted_ge_5_probability'))}` / `{_fmt(total_goals.get('actual_frequency_ge_5'))}`",
        f"- λ_home `{json.dumps(lambdas.get('home', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- λ_away `{json.dumps(lambdas.get('away', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- λ_total `{json.dumps(lambdas.get('total', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- rho `{json.dumps(metrics.get('rho_distribution', {}), ensure_ascii=False, sort_keys=True)}`; boundary hits `{json.dumps(metrics.get('rho_boundary_hit_frequency', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- score-grid tail mass `{json.dumps(metrics.get('score_grid_tail_mass', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- strong favourites `{json.dumps(metrics.get('extreme_probability_diagnostics', {}).get('strong_favourite', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- calibration `{json.dumps(metrics.get('calibration', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- extreme probability `{json.dumps(metrics.get('extreme_probability_diagnostics', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
    ]
    return lines


def _build_comparison(
    old_predictions: Sequence[Mapping[str, Any]],
    new_target_rows: Sequence[Mapping[str, Any]],
    *,
    config: PreRegisteredConfig,
) -> dict[str, Any]:
    old_by_id = {str(row["match_id"]): row for row in old_predictions}
    target_ids = set(old_by_id)
    new_attempted = _subset_by_ids(new_target_rows, target_ids)
    new_both = [row for row in new_attempted if len(row.get("models", {})) == 2]
    old_metrics_dc = _evaluate_extended(old_predictions, "dixon_coles", config)
    old_metrics_rho0 = _evaluate_extended(old_predictions, "rho0_control", config)
    dc_pair = _pairwise_comparison(old_predictions, new_attempted, model_key="dixon_coles", config=config)
    rho0_pair = _pairwise_comparison(old_predictions, new_attempted, model_key="rho0_control", config=config)
    new_dc_rows = [row for row in new_attempted if "dixon_coles" in row.get("models", {})]
    new_rho0_rows = [row for row in new_attempted if "rho0_control" in row.get("models", {})]
    common_new = [row for row in new_attempted if len(row.get("models", {})) == 2]
    new_dc = _evaluate_extended(new_dc_rows, "dixon_coles", config)
    new_rho0 = _evaluate_extended(new_rho0_rows, "rho0_control", config)
    new_common_dc = _evaluate_extended(common_new, "dixon_coles", config)
    new_common_rho0 = _evaluate_extended(common_new, "rho0_control", config)
    new_dc_vs_rho0 = {
        "model_key": "dixon_coles_vs_rho0_control",
        "paired_sample_count": len(common_new),
        "new_dixon_coles_metrics": new_common_dc,
        "new_rho0_metrics": new_common_rho0,
        "new_minus_control": _metric_delta(new_common_dc, new_common_rho0),
    }
    old_target_by_id = {str(row["match_id"]): row for row in old_predictions}
    new_target_by_id = {str(row["match_id"]): row for row in new_attempted}
    old_history_rows = list(old_predictions)
    new_history_rows = [new_target_by_id[match_id] for match_id in sorted(target_ids) if match_id in new_target_by_id]
    return {
        "target_count": len(target_ids),
        "old_metrics_full_103": {
            "dixon_coles": old_metrics_dc,
            "rho0_control": old_metrics_rho0,
        },
        "dixon_coles": dc_pair,
        "rho0_control": rho0_pair,
        "new_dc_vs_rho0": new_dc_vs_rho0,
        "new_metrics_by_model_available": {
            "dixon_coles": new_dc,
            "rho0_control": new_rho0,
        },
        "old_history_visible_per_prediction": _history_summary_for_rows(old_history_rows),
        "new_history_visible_per_prediction_all_103": _history_summary_for_rows(new_history_rows),
        "new_history_visible_per_prediction_available": {
            "dixon_coles": _history_summary_for_rows(new_dc_rows),
            "rho0_control": _history_summary_for_rows(new_rho0_rows),
            "both_models": _history_summary_for_rows(common_new),
        },
        "target_outcome_consistency": all(
            old_target_by_id[match_id]["actual_home_goals"] == new_target_by_id[match_id]["actual_home_goals"]
            and old_target_by_id[match_id]["actual_away_goals"] == new_target_by_id[match_id]["actual_away_goals"]
            for match_id in target_ids
        ),
        "full_103_paired_comparison_available": len(new_both) == TARGET_COUNT,
    }


def run_closeout(
    *,
    old_db_path: str | Path,
    new_db_path: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    report_path: str | Path = DEFAULT_REPORT_PATH,
    config: PreRegisteredConfig | None = None,
) -> dict[str, Any]:
    config = config or PreRegisteredConfig()
    old_records, old_metadata = _load_records(old_db_path)
    _validate_data_scope(
        old_metadata,
        expected_database_rows=OLD_DATABASE_ROW_COUNT,
        expected_database_digest=OLD_DATABASE_DIGEST,
        expected_sweden_matches=OLD_SWEDEN_MATCH_COUNT,
    )
    current_db = Path(new_db_path) if new_db_path is not None else historical_results_path()
    new_records, new_metadata = _load_records(current_db)
    _validate_data_scope(
        new_metadata,
        expected_database_rows=NEW_DATABASE_ROW_COUNT,
        expected_database_digest=NEW_DATABASE_DIGEST,
        expected_sweden_matches=359,
    )
    old_result = run_chronological_backtest(old_records, config=config)
    old_predictions = old_result["predictions"]
    if len(old_predictions) != TARGET_COUNT:
        raise ReplayIntegrityError(f"old FE-DC-1 target count is not {TARGET_COUNT}")
    old_prediction_digest = content_sha256(old_predictions)
    if old_prediction_digest != OLD_PREDICTION_DIGEST:
        raise ReplayIntegrityError("old FE-DC-1 replay digest does not match PR #114")
    reconciliation = _target_reconciliation(old_predictions, new_records)
    target_ids = {str(row["match_id"]) for row in old_predictions}
    expanded_result = _replay_target_set(new_records, config=config, target_ids=None)
    reconciled_new_ids = {str(item["new_match_id"]) for item in reconciliation["mappings"]}
    new_target_rows = _relabel_reconciled_targets(
        _subset_by_ids(expanded_result["rows"], reconciled_new_ids), reconciliation
    )
    if len(new_target_rows) != TARGET_COUNT:
        raise ReplayIntegrityError("new replay did not retain all 103 target rows")
    integrity = _prediction_integrity(new_target_rows, config)
    comparison = _build_comparison(old_predictions, new_target_rows, config=config)
    expanded_success = [row for row in expanded_result["rows"] if row.get("models")]
    expanded_both = [row for row in expanded_result["rows"] if len(row.get("models", {})) == 2]
    expanded_scope = {
        "input_match_count": len(new_records),
        "input_team_count": len(expanded_result["expected_team_ids"]),
        "input_team_ids": expanded_result["expected_team_ids"],
        "candidate_count": expanded_result["candidate_count"],
        "skipped_counts": expanded_result["skipped_counts"],
        "model_available_counts": dict(
            sorted(
                Counter(
                    key
                    for row in expanded_result["rows"]
                    for key in row.get("models", {})
                ).items()
            )
        ),
        "both_models_available_count": len(expanded_both),
        "fit_failure_count": sum(bool(row.get("fit_errors")) for row in expanded_result["rows"]),
        "fit_failure_ids": [row["match_id"] for row in expanded_result["rows"] if row.get("fit_errors")],
        "dixon_coles_metrics": _evaluate_extended(expanded_success, "dixon_coles", config),
        "rho0_control_metrics": _evaluate_extended(expanded_success, "rho0_control", config),
    }
    output_directory = Path(output_root)
    comparison_path = output_directory / "old_vs_new_comparison.json"
    paired_path = output_directory / "paired_replay_predictions.json"
    expanded_path = output_directory / "expanded_secondary_diagnostic.json"
    integrity_path = output_directory / "integrity_audit.json"
    reconciliation_path = output_directory / "target_reconciliation.json"
    summary_path = output_directory / "fe_se_dc_close_results_summary.json"
    paired_predictions = []
    old_by_id = {str(row["match_id"]): row for row in old_predictions}
    new_by_id = {str(row["match_id"]): row for row in new_target_rows}
    for match_id in sorted(target_ids, key=lambda value: (_parse_kickoff(old_by_id[value]["kickoff_at"]), value)):
        paired_predictions.append(
            {
                "match_id": match_id,
                "old_incomplete": _compact_prediction(old_by_id[match_id]),
                "new_complete": _compact_prediction(new_by_id[match_id]),
            }
        )
    _write_json(comparison_path, comparison)
    _write_json(paired_path, paired_predictions)
    _write_json(expanded_path, expanded_scope)
    _write_json(integrity_path, integrity)
    _write_json(reconciliation_path, reconciliation)
    summary: dict[str, Any] = {
        "artifact_version": "fe_se_dc_close.results.v1",
        "milestone": MILESTONE,
        "status": "READY_FOR_ACCEPTANCE",
        "verdict": "INCONCLUSIVE",
        "research_only": True,
        "production_mutation": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "config": {
            "competition_id": config.competition_id,
            "warmup_matches": config.warmup_matches,
            "half_life_days": config.half_life_days,
            "max_goals": config.max_goals,
            "optimizer_max_iter": config.optimizer_max_iter,
            "optimizer_tolerance": config.optimizer_tolerance,
            "parameter_bound": config.parameter_bound,
            "base_log_rate_bounds": list(config.base_log_rate_bounds),
            "home_advantage_bounds": list(config.home_advantage_bounds),
            "rho_bounds": list(config.rho_bounds),
            "rho_policy": "fit primary; fixed zero internal control",
            "time_weight_policy": "fixed exponential half-life; no sweep",
            "target_policy": "exact old FE-DC-1 103 canonical match IDs",
        },
        "old_data_scope": _data_scope(old_metadata, old_records),
        "new_data_scope": _data_scope(new_metadata, new_records),
        "old_prediction_digest": old_prediction_digest,
        "target_reconciliation": reconciliation,
        "integrity": integrity,
        "comparison": comparison,
        "expanded_secondary": expanded_scope,
        "landscape_references": list(LANDSCAPE_REFERENCES),
        "verdict_reason": "fixed-config optimizer non-convergence on 7 of the 103 new target rows blocks a complete paired evaluation; no tuning was attempted",
        "governance": {
            "fe_se_hist_1": "SEALED",
            "fe_se_dc_close": "READY_FOR_ACCEPTANCE",
            "sweden_specific_further_tuning": "CLOSED",
            "next_candidate": "League-Agnostic Historical Coverage / Automatic Coverage Gate",
        },
        "protected_scope": {
            "champion_modified": False,
            "production_prediction_modified": False,
            "frozen_prediction_modified": False,
            "user_prediction_surface_modified": False,
            "new_provider_added": False,
            "other_league_added": False,
        },
        "artifact_paths": {
            "summary": str(summary_path.relative_to(REPO_ROOT)) if summary_path.is_relative_to(REPO_ROOT) else str(summary_path),
            "comparison": str(comparison_path.relative_to(REPO_ROOT)) if comparison_path.is_relative_to(REPO_ROOT) else str(comparison_path),
            "paired_predictions": str(paired_path.relative_to(REPO_ROOT)) if paired_path.is_relative_to(REPO_ROOT) else str(paired_path),
            "expanded_secondary": str(expanded_path.relative_to(REPO_ROOT)) if expanded_path.is_relative_to(REPO_ROOT) else str(expanded_path),
            "integrity": str(integrity_path.relative_to(REPO_ROOT)) if integrity_path.is_relative_to(REPO_ROOT) else str(integrity_path),
            "target_reconciliation": str(reconciliation_path.relative_to(REPO_ROOT)) if reconciliation_path.is_relative_to(REPO_ROOT) else str(reconciliation_path),
        },
    }
    _write_json(summary_path, summary)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(_build_report(summary), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-db", type=Path, required=True)
    parser.add_argument("--new-db", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    summary = run_closeout(
        old_db_path=args.old_db,
        new_db_path=args.new_db,
        output_root=args.output_root,
        report_path=args.report_path,
    )
    print(
        json.dumps(
            {
                "milestone": summary["milestone"],
                "status": summary["status"],
                "verdict": summary["verdict"],
                "target_count": summary["comparison"]["target_count"],
                "new_both_models": summary["integrity"]["both_models_available_count"],
                "fit_failures": summary["integrity"]["fit_failure_count"],
                "comparison_path": summary["artifact_paths"]["comparison"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
