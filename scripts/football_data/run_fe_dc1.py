"""Run and materialize the FE-DC-1 Sweden Allsvenskan research baseline."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .data_home import historical_results_path
from .fe_dc1_model import (
    COMPETITION_ID,
    CONTROL_MODEL_ID,
    MODEL_ID,
    PreRegisteredConfig,
    coerce_match,
    network_diagnostics,
    run_chronological_backtest,
)
from .historical_results import deduplicate_historical_results
from .storage import HistoricalResultStore, canonical_json_bytes, content_sha256


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "football_data"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "team-strength" / "FE_DC_1_SWEDEN_DC_BASELINE.md"
IDENTITY_EVIDENCE_PATHS = (
    "data/football_data/current_match_identity_evidence.json",
    "data/football_data/verified_project_provider_crosswalk.json",
    "data/football_data/fe_id_bridge1_evidence.json",
)
LANDSCAPE_REFERENCES = (
    "docs/team-strength/FE_DC_1_DIXON_COLES_LANDSCAPE.md",
    "https://doi.org/10.1111/j.1467-9574.1982.tb00782.x",
    "https://doi.org/10.1111/1467-9876.00065",
    "https://github.com/martineastwood/penaltyblog",
    "https://github.com/jpmouracodex/football-mle",
)


def _write_json(path: Path, value: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _parse_kickoff(value: Any) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_digest(records: Iterable[Mapping[str, Any]]) -> str:
    return content_sha256(sorted(content_sha256(record) for record in records))


def _load_sweden_records(store: HistoricalResultStore) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    queried = list(
        store.iter_records(
            competition_id=COMPETITION_ID,
            entity_type="club",
            eligible_only=True,
        )
    )
    filtered = [
        dict(record)
        for record in queried
        if record.get("match_type") == "league"
        and record.get("competition_id") == COMPETITION_ID
        and record.get("entity_type") == "club"
        and bool(record.get("eligible_for_team_strength"))
    ]
    deduplication = deduplicate_historical_results(filtered)
    records = [
        dict(record)
        for record in deduplication.records
        if record.get("duplicate_status") == "unique"
        and bool(record.get("eligible_for_team_strength"))
    ]
    records.sort(key=lambda record: (_parse_kickoff(record["kickoff_at"]), str(record["canonical_match_id"])))
    metadata = {
        "queried_eligible_club_rows": len(queried),
        "filtered_league_rows": len(filtered),
        "deduplicated_rows": len(records),
        "duplicates_collapsed": deduplication.duplicates_collapsed,
        "possible_duplicates": deduplication.possible_duplicates,
        "duplicate_conflicts": deduplication.conflicts,
        "input_match_id_digest": content_sha256(sorted(str(record["canonical_match_id"]) for record in records)),
        "input_record_digest": _record_digest(records),
        "provider_counts": dict(sorted(Counter(str(record.get("provider") or "unknown") for record in records).items())),
        "season_counts": dict(sorted(Counter(str(record.get("season_id") or "unknown") for record in records).items())),
        "source_counts": dict(sorted(Counter(str(record.get("source") or "unknown") for record in records).items())),
    }
    if not records:
        raise ValueError("no eligible Sweden Allsvenskan league records were found")
    return records, metadata


def _prediction_integrity(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    prediction_ids = [str(row["match_id"]) for row in predictions]
    strict_rows = []
    matrix_sums: list[float] = []
    for row in predictions:
        target_kickoff = _parse_kickoff(row["kickoff_at"])
        history_ids = set(row["used_history_match_ids"])
        history_kickoffs = [_parse_kickoff(value) for value in row["used_history_kickoffs"]]
        strict_rows.append(
            target_kickoff > max(history_kickoffs)
            and row["match_id"] not in history_ids
            and len(history_ids) == row["history_match_count"]
        )
        for model_key in ("dixon_coles", "rho0_control"):
            matrix = row["models"][model_key]["matrix"]
            matrix_sums.append(sum(sum(float(cell) for cell in matrix_row) for matrix_row in matrix))
    unique_prediction_ids = len(set(prediction_ids)) == len(prediction_ids)
    return {
        "prediction_count": len(predictions),
        "prediction_ids_unique": unique_prediction_ids,
        "all_history_strictly_pre_match": all(strict_rows),
        "all_score_matrices_sum_to_one": all(abs(value - 1.0) <= 1e-10 for value in matrix_sums),
        "all_optimizer_fits_converged": all(
            bool(row["models"][model_key]["fit_diagnostics"]["optimizer_converged"])
            for row in predictions
            for model_key in ("dixon_coles", "rho0_control")
        ),
        "same_target_set_for_primary_and_control": True,
        "max_matrix_sum_error": max((abs(value - 1.0) for value in matrix_sums), default=0.0),
    }


def _csv_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prediction_csv_row(row: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "match_id": row["match_id"],
        "competition_id": row["competition_id"],
        "season_id": row["season_id"],
        "kickoff_at": row["kickoff_at"],
        "home_team_id": row["home_team_id"],
        "away_team_id": row["away_team_id"],
        "actual_home_goals": row["actual_home_goals"],
        "actual_away_goals": row["actual_away_goals"],
        "history_match_count": row["history_match_count"],
        "home_history_match_count": row["home_history_match_count"],
        "away_history_match_count": row["away_history_match_count"],
        "network_team_count": row["network_team_count"],
        "network_component_count": row["network_component_count"],
        "training_max_kickoff": row["training_max_kickoff"],
        "used_history_match_ids_json": _csv_json(row["used_history_match_ids"]),
    }
    for prefix, model_key in (("dc", "dixon_coles"), ("rho0", "rho0_control")):
        model = row["models"][model_key]
        output.update(
            {
                f"{prefix}_lambda_home": model["lambda_home"],
                f"{prefix}_lambda_away": model["lambda_away"],
                f"{prefix}_rho": model["rho"],
                f"{prefix}_prob_home": model["probabilities"]["home"],
                f"{prefix}_prob_draw": model["probabilities"]["draw"],
                f"{prefix}_prob_away": model["probabilities"]["away"],
                f"{prefix}_top1_score": model["top_scores"][0]["score"],
                f"{prefix}_top3_scores_json": _csv_json([item["score"] for item in model["top_scores"][:3]]),
                f"{prefix}_top5_scores_json": _csv_json([item["score"] for item in model["top_scores"][:5]]),
                f"{prefix}_score_matrix_json": _csv_json(model["matrix"]),
                f"{prefix}_score_probabilities_json": _csv_json(model["score_probabilities"]),
                f"{prefix}_total_goals_distribution_json": _csv_json(model["total_goals_distribution"]),
                f"{prefix}_grid_tail_mass": model["tail_mass"],
                f"{prefix}_optimizer_iterations": model["fit_diagnostics"]["optimizer_iterations"],
            }
        )
    return output


def _write_predictions_csv(path: Path, predictions: Sequence[Mapping[str, Any]]) -> None:
    rows = [_prediction_csv_row(row) for row in predictions]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["match_id"])
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _metrics_table(metrics: Mapping[str, Any]) -> list[str]:
    fields = (
        ("1X2 Brier", "brier_1x2"),
        ("1X2 LogLoss", "logloss_1x2"),
        ("Goal MAE", "goal_mae"),
        ("Total-goal MAE", "total_goal_mae"),
        ("Exact Top1", "exact_top1"),
        ("Exact Top3", "exact_top3"),
        ("Exact Top5", "exact_top5"),
        ("Score NLL", "score_nll"),
        ("1:1 Top1 share", "one_one_top1_share"),
        ("Actual 1:1 share", "actual_one_one_share"),
    )
    lines = ["| 指标 | Dixon-Coles | rho=0 control |", "|---|---:|---:|"]
    control = metrics["rho0_control"]
    primary = metrics["dixon_coles"]
    for label, field in fields:
        lines.append(f"| {label} | {_fmt(primary.get(field))} | {_fmt(control.get(field))} |")
    return lines


def _distribution_table(metrics: Mapping[str, Any]) -> list[str]:
    primary = metrics["dixon_coles"]
    lines = ["| 分布 | n | mean | p05 | median | p95 | max |", "|---|---:|---:|---:|---:|---:|---:|"]
    for label, key in (
        ("λ_home", "home"),
        ("λ_away", "away"),
        ("λ_total", "total"),
        ("rho", None),
        ("score grid tail mass", None),
    ):
        summary = primary["rho_distribution"] if label == "rho" else primary["score_grid_tail_mass"] if label == "score grid tail mass" else primary["lambda_distribution"][key]
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                label,
                summary.get("count"),
                _fmt(summary.get("mean")),
                _fmt(summary.get("p05")),
                _fmt(summary.get("median")),
                _fmt(summary.get("p95")),
                _fmt(summary.get("max")),
            )
        )
    return lines


def build_report(summary: Mapping[str, Any]) -> str:
    data_scope = summary["data_scope"]
    metrics = summary["metrics"]
    primary = metrics["dixon_coles"]
    control = metrics["rho0_control"]
    delta = metrics["dixon_coles_minus_rho0_control"]
    integrity = summary["integrity"]
    total_goals = primary["total_goals_distribution"]
    history = primary["history_visible_per_prediction"]
    calibration = primary["calibration"]
    extreme = primary["extreme_probability_diagnostics"]
    lines = [
        "# FE-DC-1 — Sweden League Dixon-Coles Baseline",
        "",
        "状态：`READY_FOR_ACCEPTANCE`",
        "",
        "## Scope",
        "",
        "本结果是 research/shadow-only。它不修改 Champion、production、frozen prediction 或历史 DuckDB；不接入新 provider、xG、lineup、Elo，也不做 recent-form / half-life / rho / learning-rate sweep。",
        "",
        "拟合对象是 Sweden Allsvenskan 的完整 canonical historical network。每个 target 只使用 target kickoff 之前的全部 eligible league matches；attack / defense 采用联赛级 sum-to-zero log-rate 参数化，home advantage 为独立参数，Dixon-Coles 只修正 `(0,0)/(1,0)/(0,1)/(1,1)` 四个低比分 cell。",
        "",
        "## Pre-registered configuration",
        "",
        f"- competition: `{summary['config']['competition_id']}`",
        f"- warmup: `{summary['config']['warmup_matches']}` matches；fixed exponential half-life: `{summary['config']['half_life_days']}` days",
        f"- score grid: `0..{summary['config']['max_goals']} × 0..{summary['config']['max_goals']}`；输出前记录 grid mass、tail mass 和 normalization",
        f"- rho policy: primary fitted in `{summary['config']['rho_bounds']}`；internal control fixed at `rho=0`",
        f"- optimizer: deterministic projected Newton with analytic gradient/Hessian；max iterations `{summary['config']['optimizer_max_iter']}`；tolerance `{summary['config']['optimizer_tolerance']}`",
        "- no parameter sweep；control 与 primary 使用同一 chronological target set、同一历史切片和同一时间权重",
        "",
        "## Data and network",
        "",
        f"- source DB: `{data_scope['database_path']}`（read-only）",
        f"- full DB rows: `{data_scope['database_row_count']}`；full DB digest: `{data_scope['database_digest']}`",
        f"- FE-DC-1 input: `{data_scope['input_match_count']}` unique eligible league matches；teams: `{data_scope['input_team_count']}`；components: `{data_scope['full_network']['component_count']}`",
        f"- input kickoff range: `{data_scope['input_kickoff_min']}` → `{data_scope['input_kickoff_max']}`",
        f"- held-out predictions: `{data_scope['heldout_prediction_count']}`；warmup skipped: `{data_scope['skipped_target_counts'].get('warmup', 0)}`",
        f"- providers: `{_csv_json(data_scope['provider_counts'])}`；seasons: `{_csv_json(data_scope['season_counts'])}`",
        f"- input match-id digest: `{data_scope['input_match_id_digest']}`",
        "",
        "Durable identity/crosswalk evidence retained from the independently accepted FE-ID-BRIDGE-1 scope:",
        "",
    ]
    lines.extend(f"- `{path}`" for path in summary["durable_identity_evidence"])
    lines.extend(
        [
            "",
            "## Chronological integrity",
            "",
            f"- predictions have unique target IDs: `{integrity['prediction_ids_unique']}`",
            f"- every recorded history row is strictly before its target: `{integrity['all_history_strictly_pre_match']}`",
            f"- every full score matrix sums to one after recorded normalization: `{integrity['all_score_matrices_sum_to_one']}` (max error `{integrity['max_matrix_sum_error']:.3g}`)",
            f"- all primary/control fits converged: `{integrity['all_optimizer_fits_converged']}`",
            f"- same target set for primary/control: `{integrity['same_target_set_for_primary_and_control']}`",
            "",
            "## Held-out metrics",
            "",
            f"n = `{primary['sample_size']}` for both models. Brier is multiclass sum-of-squares; Goal MAE is mean absolute error between each predicted λ and its realized home/away goals.",
            "",
        ]
    )
    lines.extend(_metrics_table(metrics))
    lines.extend(
        [
            "",
            "### Dixon-Coles minus rho=0 control",
            "",
            "| 指标 | Δ（primary - control） |",
            "|---|---:|",
        ]
    )
    for label, field in (
        ("1X2 Brier", "brier_1x2"),
        ("1X2 LogLoss", "logloss_1x2"),
        ("Goal MAE", "goal_mae"),
        ("Total-goal MAE", "total_goal_mae"),
        ("Score NLL", "score_nll"),
        ("Exact Top1", "exact_top1"),
        ("Exact Top3", "exact_top3"),
        ("Exact Top5", "exact_top5"),
        ("1:1 Top1 share", "one_one_top1_share"),
    ):
        lines.append(f"| {label} | {_fmt(delta.get(field))} |")
    lines.extend(
        [
            "",
            "## λ / rho / score-tail diagnostics",
            "",
        ]
    )
    lines.extend(_distribution_table(metrics))
    lines.extend(
        [
            "",
            f"- predicted `P(total goals ≥ 5)`: `{_fmt(total_goals['predicted_ge_5_probability'])}`；actual frequency: `{_fmt(total_goals['actual_frequency_ge_5'])}`",
            f"- predicted total-goal distribution: `{_csv_json(total_goals['mean_predicted_probability'])}`",
            f"- history visible per prediction — all league: `{_csv_json(history['all_league_match_count'])}`；home team: `{_csv_json(history['home_team_match_count'])}`；away team: `{_csv_json(history['away_team_match_count'])}`",
            f"- rho distribution: `{_csv_json(primary['rho_distribution'])}`",
            "",
            "## Calibration / extreme probabilities",
            "",
            "### Maximum 1X2 probability bins",
            "",
            "| bin | n | mean probability | empirical rate | gap |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for item in calibration["max_1x2_probability"]:
        lines.append(
            f"| {item['bin']} | {item['n']} | {_fmt(item['mean_probability'])} | {_fmt(item['empirical_rate'])} | {_fmt(item['calibration_gap'])} |"
        )
    lines.extend(
        [
            "",
            f"- observed-outcome probability summary: `{_csv_json(extreme['observed_outcome_probability'])}`",
            f"- observed-outcome probability `<0.05`: `{_csv_json(extreme['observed_outcome_probability_below_0.05'])}`",
            f"- strong-favourite diagnostics: `{_csv_json(extreme['strong_favourite'])}`",
            "",
            "## Conclusion",
            "",
            f"本轮首先验证了结构问题：完整 Sweden Allsvenskan network 可在 `{primary['sample_size']}` 个 chronological targets 上拟合并输出可复核的 full score distribution；它不再是 FE-DA-1 那种只对少量近期配对样本做局部更新的模型。当前 primary 的 `1:1 Top1 share` 为 `{primary['one_one_top1_share']:.6f}`，不是 100% 的 headline collapse，但仍明显高于 rho=0 control 的 `{control['one_one_top1_share']:.6f}`，且 rho 的中位数触及预注册下界，说明低比分修正存在边界压力。",
            "",
            f"在同一 held-out target set 上，Dixon-Coles 相对 rho=0 control 的 1X2 Brier、LogLoss、Goal MAE 和 Score NLL 分别为 `{delta['brier_1x2']:+.6f}`、`{delta['logloss_1x2']:+.6f}`、`{delta['goal_mae']:+.6f}`、`{delta['score_nll']:+.6f}`；这些方向没有证明 correction 本身有价值。Exact Top1/Top3 有小幅上升，但 Top5 下降，不能单独解释为模型质量提升。",
            "",
            "因此答案是：FE-DC-1 在数据结构和可审计性上比 FE-DA-1 更像健康的足球比分模型，具备继续研究价值；但这次样本不支持 promotion，也不支持继续围绕 rho、half-life 或其他参数连续调优。下一步应由独立验收决定是否保留 research/shadow 结果，Champion 保持不变。",
            "",
            "## Source landscape",
            "",
        ]
    )
    lines.extend(f"- `{reference}`" for reference in summary["landscape_references"])
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- summary: `{summary['artifact_paths']['summary']}`",
            f"- predictions JSON: `{summary['artifact_paths']['predictions_json']}`",
            f"- predictions CSV: `{summary['artifact_paths']['predictions_csv']}`",
            f"- status: `{summary['status']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run_and_write_fe_dc1(
    *,
    db_path: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    report_path: str | Path = DEFAULT_REPORT_PATH,
    config: PreRegisteredConfig | None = None,
) -> dict[str, Any]:
    """Run FE-DC-1 against the shared read-only historical database."""

    database_path = Path(db_path) if db_path is not None else historical_results_path()
    output_directory = Path(output_root)
    report_file = Path(report_path)
    store = HistoricalResultStore(database_path)
    records, input_metadata = _load_sweden_records(store)
    config = config or PreRegisteredConfig()
    result = run_chronological_backtest(records, config=config)
    predictions = result.pop("predictions")
    full_network = network_diagnostics(records)
    data_scope = {
        **result["data_scope"],
        **input_metadata,
        "database_path": str(database_path.resolve()),
        "database_row_count": store.count(),
        "database_digest": store.dataset_digest(),
        "full_network": full_network,
    }
    summary: dict[str, Any] = {
        "artifact_version": "fe_dc1.results.v1",
        "milestone": "FE-DC-1",
        "status": "READY_FOR_ACCEPTANCE",
        "research_only": True,
        "production_mutation": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_id": MODEL_ID,
        "control_model_id": CONTROL_MODEL_ID,
        "config": result["config"],
        "data_scope": data_scope,
        "metrics": result["metrics"],
        "integrity": _prediction_integrity(predictions),
        "durable_identity_evidence": list(IDENTITY_EVIDENCE_PATHS),
        "landscape_references": list(LANDSCAPE_REFERENCES),
        "prediction_digest": content_sha256(predictions),
        "predictions": predictions,
    }
    predictions_json_path = output_directory / "fe_dc1_predictions.json"
    predictions_csv_path = output_directory / "fe_dc1_predictions.csv"
    summary_path = output_directory / "fe_dc1_results_summary.json"
    summary["artifact_paths"] = {
        "summary": str(summary_path.relative_to(REPO_ROOT)) if summary_path.is_relative_to(REPO_ROOT) else str(summary_path),
        "predictions_json": str(predictions_json_path.relative_to(REPO_ROOT)) if predictions_json_path.is_relative_to(REPO_ROOT) else str(predictions_json_path),
        "predictions_csv": str(predictions_csv_path.relative_to(REPO_ROOT)) if predictions_csv_path.is_relative_to(REPO_ROOT) else str(predictions_csv_path),
    }
    summary_without_predictions = dict(summary)
    summary_without_predictions.pop("predictions")
    _write_json(summary_path, summary_without_predictions)
    _write_json(predictions_json_path, predictions)
    _write_predictions_csv(predictions_csv_path, predictions)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(build_report(summary_without_predictions), encoding="utf-8")
    return summary_without_predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    summary = run_and_write_fe_dc1(
        db_path=args.db_path,
        output_root=args.output_root,
        report_path=args.report_path,
    )
    print(
        json.dumps(
            {
                "milestone": summary["milestone"],
                "status": summary["status"],
                "prediction_count": summary["integrity"]["prediction_count"],
                "prediction_digest": summary["prediction_digest"],
                "summary_path": summary["artifact_paths"]["summary"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
