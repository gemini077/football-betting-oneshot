"""Bounded orchestration for the offline Phase 2C-2 experiment.

The orchestration layer keeps all detailed predictions under the shared
Football Data Home.  Only compact, reviewable summaries are written to Git.
It never loads the Phase 2C-1 spent held-out results; their IDs are used only
as an exclusion lock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

from .data_home import resolve_football_data_home
from .phase2c1_experiment import champion_evidence
from .phase2c1_model import (
    InsufficientHistoryError,
    attach_actual,
    build_baseline_prediction,
    evaluate_predictions,
    metric_loss_values,
    paired_bootstrap_deltas,
)
from .phase2c2_opponent_strength import (
    EXPECTED_DEVELOPMENT_SIZE,
    EXPECTED_POOL_SIZE,
    EXPECTED_SPENT_HELDOUT_DIGEST,
    EXPECTED_SPENT_HELDOUT_SIZE,
    EXPECTED_VALIDATION_SIZE,
    FROZEN_BASIC_SPEC_ID,
    FORMULA_VERSION,
    MatchedRawSpec,
    MATCHED_RAW_FORMULA_VERSION,
    OpponentSpec,
    _deltas,
    build_frozen_2c1_prediction,
    build_matched_raw_prediction,
    build_opponent_adjusted_prediction,
    build_rolling_folds,
    candidate_specs_manifest,
    classification_from_exploratory_evidence,
    evaluate_validation_once,
    experiment_id_for,
    load_phase2c2_research_pool,
    paired_comparison_bootstrap,
    phase2c2_research_boundary,
    select_opponent_spec,
)
from .storage import content_sha256
from .verify_data_home import verify_data_home


ROOT = Path(__file__).resolve().parents[2]
COMPACT_MANIFEST_PATH = ROOT / "data" / "football_data" / "phase2c2_experiment_manifest.json"
COMPACT_RESULTS_PATH = ROOT / "data" / "football_data" / "phase2c2_results_summary.json"
DOC_PATH = ROOT / "docs" / "team-strength" / "PHASE2C2_OPPONENT_STRENGTH.md"
HANDOFF_PATH = ROOT / "artifacts" / "football-phase2c2-opponent-strength-handoff.zip"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _data_home(data_home: str | Path | None = None) -> Path:
    return Path(data_home).expanduser() if data_home is not None else resolve_football_data_home()


def _sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("kickoff_at") or ""), str(row.get("canonical_match_id") or ""))


def _target_id(row: Mapping[str, Any]) -> str:
    return str(row.get("canonical_match_id") or row.get("target_match_id") or "")


def _benchmark_health(root: Path) -> dict[str, Any]:
    command = [sys.executable, str(root / "scripts" / "benchmark_health.py"), "--no-write"]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"benchmark health read failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _registered_spec(row: Mapping[str, Any]) -> OpponentSpec:
    spec = OpponentSpec(
        regularization=int(row["regularization"]),
        formula=str(row.get("formula") or FORMULA_VERSION),
        history_policy=str(row.get("history_policy") or "target_competition_all_prior"),
        home_away_formulation=str(row.get("home_away_formulation") or "venue_specific_multiplicative"),
        solver=str(row.get("solver") or "multiplicative_fixed_point"),
        convergence_tolerance=float(row.get("convergence_tolerance", 1e-8)),
        max_iterations=int(row.get("max_iterations", 1000)),
        minimum_history=int(row.get("minimum_history", 5)),
    )
    if spec.spec_id != str(row.get("spec_id")):
        raise ValueError("candidate registry row does not match its specification identity")
    return spec


def _candidate_registry(generated_at: str) -> dict[str, Any]:
    registry = candidate_specs_manifest()
    return {
        "contract_version": "phase2c2_opponent_strength.v1",
        "frozen_before_rolling": True,
        "candidate_specs": registry,
        "registry_digest": content_sha256(registry),
        "registered_at": generated_at,
    }


def _prediction_bundle(
    targets: Sequence[Mapping[str, Any]],
    fit_records: Sequence[Mapping[str, Any]],
    spec: OpponentSpec,
    *,
    spent_heldout_ids: Iterable[str],
    include_frozen: bool = False,
    include_baseline: bool = False,
) -> dict[str, Any]:
    output: dict[str, list[dict[str, Any]]] = {
        "opponent": [],
        "matched_raw": [],
    }
    if include_frozen:
        output["frozen_2c1"] = []
    if include_baseline:
        output["baseline_a"] = []
    skipped: list[dict[str, Any]] = []
    for target in sorted(targets, key=_sort_key):
        try:
            opponent = build_opponent_adjusted_prediction(
                target,
                fit_records,
                spec,
                spent_heldout_ids=spent_heldout_ids,
            )
            matched_raw = build_matched_raw_prediction(
                target,
                fit_records,
                MatchedRawSpec(spec.regularization),
                spent_heldout_ids=spent_heldout_ids,
            )
            frozen = None
            baseline = None
            if include_frozen:
                frozen = build_frozen_2c1_prediction(
                    target,
                    fit_records,
                    spent_heldout_ids=spent_heldout_ids,
                )
            if include_baseline:
                baseline = build_baseline_prediction(
                    target,
                    fit_records,
                    baseline_kind="competition_poisson",
                )
        except InsufficientHistoryError as exc:
            skipped.append({"target_match_id": _target_id(target), "reason": str(exc)})
            continue
        output["opponent"].append(attach_actual(opponent, target))
        output["matched_raw"].append(attach_actual(matched_raw, target))
        if frozen is not None:
            output["frozen_2c1"].append(attach_actual(frozen, target))
        if baseline is not None:
            output["baseline_a"].append(attach_actual(baseline, target))
    return {"predictions": output, "skipped": skipped}


def _metric_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    return evaluate_predictions(rows) if rows else None


def _per_competition_comparison(
    opponent: Sequence[Mapping[str, Any]],
    matched_raw: Sequence[Mapping[str, Any]],
    frozen: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    competitions = sorted({str(row.get("competition_id")) for row in opponent})
    output: dict[str, Any] = {}
    for competition in competitions:
        selected_opponent = [row for row in opponent if str(row.get("competition_id")) == competition]
        selected_raw = [row for row in matched_raw if str(row.get("competition_id")) == competition]
        selected_frozen = [row for row in (frozen or []) if str(row.get("competition_id")) == competition]
        opponent_metrics = evaluate_predictions(selected_opponent)
        raw_metrics = evaluate_predictions(selected_raw)
        item: dict[str, Any] = {
            "sample": len(selected_opponent),
            "opponent_vs_matched_raw": {
                "one_x_two_log_loss_delta": _deltas(opponent_metrics, raw_metrics)["one_x_two_log_loss"],
                "one_x_two_brier_delta": _deltas(opponent_metrics, raw_metrics)["one_x_two_brier"],
                "goal_nll_delta": _deltas(opponent_metrics, raw_metrics)["goal_distribution_nll"],
            },
        }
        if selected_frozen:
            frozen_metrics = evaluate_predictions(selected_frozen)
            item["opponent_vs_frozen_2c1"] = {
                "one_x_two_log_loss_delta": _deltas(opponent_metrics, frozen_metrics)["one_x_two_log_loss"],
                "one_x_two_brier_delta": _deltas(opponent_metrics, frozen_metrics)["one_x_two_brier"],
                "goal_nll_delta": _deltas(opponent_metrics, frozen_metrics)["goal_distribution_nll"],
            }
        output[competition] = item
    return output


def _bootstrap_against(opponent: Sequence[Mapping[str, Any]], reference: Sequence[Mapping[str, Any]], *, seed: int = 20260811, n_bootstrap: int = 1000) -> dict[str, Any]:
    metrics = ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss")
    result = {
        metric: paired_bootstrap_deltas(
            metric_loss_values(opponent, metric),
            metric_loss_values(reference, metric),
            seed=seed,
            n_bootstrap=n_bootstrap,
        )
        for metric in metrics
    }
    result["sample"] = len(opponent)
    return result


def _compare(opponent: Sequence[Mapping[str, Any]], reference: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    opponent_metrics = evaluate_predictions(opponent)
    reference_metrics = evaluate_predictions(reference)
    return {
        "opponent_metrics": opponent_metrics,
        "reference_metrics": reference_metrics,
        "deltas": _deltas(opponent_metrics, reference_metrics),
        "bootstrap": _bootstrap_against(opponent, reference),
    }


_COMPACT_METRICS = (
    "one_x_two_log_loss",
    "one_x_two_brier",
    "goal_distribution_nll",
    "over_2_5_log_loss",
    "over_2_5_brier",
    "btts_log_loss",
    "btts_brier",
    "home_goals_mae",
    "away_goals_mae",
    "expected_total_goals_mae",
    "sample",
)


def _compact_metric_map(value: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value[name] for name in _COMPACT_METRICS if name in value}


def _compact_fold(value: Mapping[str, Any]) -> dict[str, Any]:
    compact = {
        name: value[name]
        for name in (
            "fold_id",
            "train_count",
            "evaluation_count",
            "train_max_kickoff",
            "evaluation_min_kickoff",
            "evaluation_max_kickoff",
            "sample",
            "skipped",
            "eligible",
            "reason",
            "improved_core_metric_count",
            "improved_majority",
        )
        if name in value
    }
    metrics = value.get("metrics")
    if isinstance(metrics, Mapping):
        compact["metrics"] = {
            "opponent": _compact_metric_map(metrics.get("opponent_metrics") or {}),
            "matched_raw": _compact_metric_map(metrics.get("reference_metrics") or {}),
            "deltas": {
                name: metrics.get("deltas", {}).get(name)
                for name in ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss")
                if name in metrics.get("deltas", {})
            },
        }
    return compact


def _compact_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "spec_id": value.get("spec_id"),
        "spec": dict(value.get("spec") or {}),
        "aggregate_metrics": _compact_metric_map(value.get("aggregate_metrics") or {}),
        "matched_raw_metrics": _compact_metric_map(value.get("matched_raw_metrics") or {}),
        "aggregate_deltas": {
            name: value.get("aggregate_deltas", {}).get(name)
            for name in ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss")
            if name in value.get("aggregate_deltas", {})
        },
        "eligible_fold_count": value.get("eligible_fold_count"),
        "prediction_count": value.get("prediction_count"),
        "folds": [_compact_fold(fold) for fold in value.get("folds", [])],
    }


def _compact_summary(summary: Mapping[str, Any], candidate_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    compact = dict(summary)
    compact["rolling_folds"] = [_compact_fold(fold) for fold in summary.get("rolling_folds", [])]
    selected = dict(summary.get("selected_spec") or {})
    selected_metrics = selected.get("rolling_metrics")
    compact["selected_spec"] = {
        "selected_spec_id": selected.get("selected_spec_id"),
        "selection_reason": selected.get("selection_reason"),
        "rolling_metrics": _compact_candidate(selected_metrics) if isinstance(selected_metrics, Mapping) else {},
    }
    compact["rolling_candidate_results"] = [_compact_candidate(row) for row in candidate_results]
    consistency = dict(compact.get("rolling_fold_consistency") or {})
    selected_folds = selected_metrics.get("folds", []) if isinstance(selected_metrics, Mapping) else []
    consistency["folds"] = [_compact_fold(fold) for fold in selected_folds]
    compact["rolling_fold_consistency"] = consistency
    return compact


def _fold_result(
    fold: Mapping[str, Any],
    development_by_id: Mapping[str, Mapping[str, Any]],
    targets_by_id: Mapping[str, Mapping[str, Any]],
    external_history: Sequence[Mapping[str, Any]],
    spec: OpponentSpec,
    spent_heldout_ids: Iterable[str],
) -> dict[str, Any]:
    train_rows = [development_by_id[value] for value in fold["train_match_ids"]]
    evaluation_rows = [targets_by_id[value] for value in fold["evaluation_match_ids"]]
    fit_records = list(external_history) + train_rows
    bundle = _prediction_bundle(
        evaluation_rows,
        fit_records,
        spec,
        spent_heldout_ids=spent_heldout_ids,
    )["predictions"]
    if not bundle["opponent"]:
        return {
            **dict(fold),
            "sample": 0,
            "skipped": len(evaluation_rows),
            "eligible": False,
            "reason": "no target met minimum history",
        }
    comparison = _compare(bundle["opponent"], bundle["matched_raw"])
    core_deltas = {name: comparison["deltas"][name] for name in (
        "one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss"
    )}
    improved = sum(value < 0 for value in core_deltas.values())
    return {
        **dict(fold),
        "sample": len(bundle["opponent"]),
        "skipped": len(evaluation_rows) - len(bundle["opponent"]),
        "eligible": True,
        "metrics": comparison,
        "improved_core_metric_count": improved,
        "improved_majority": improved > len(core_deltas) / 2,
        "per_competition": _per_competition_comparison(bundle["opponent"], bundle["matched_raw"]),
    }


def _evaluate_candidate(
    spec: OpponentSpec,
    folds: Sequence[Mapping[str, Any]],
    development: Sequence[Mapping[str, Any]],
    history_records: Sequence[Mapping[str, Any]],
    spent_heldout_ids: Iterable[str],
) -> dict[str, Any]:
    development_by_id = {_target_id(row): row for row in development}
    targets_by_id = development_by_id
    pool_ids = set(development_by_id)
    external_history = [row for row in history_records if _target_id(row) not in pool_ids]
    fold_results = [
        _fold_result(fold, development_by_id, targets_by_id, external_history, spec, spent_heldout_ids)
        for fold in folds
    ]
    eligible = [row for row in fold_results if row.get("eligible")]
    opponent_rows = []
    raw_rows = []
    for fold in folds:
        train_rows = [development_by_id[value] for value in fold["train_match_ids"]]
        evaluation_rows = [targets_by_id[value] for value in fold["evaluation_match_ids"]]
        bundle = _prediction_bundle(
            evaluation_rows,
            list(external_history) + train_rows,
            spec,
            spent_heldout_ids=spent_heldout_ids,
        )["predictions"]
        opponent_rows.extend(bundle["opponent"])
        raw_rows.extend(bundle["matched_raw"])
    if not opponent_rows:
        raise RuntimeError(f"candidate {spec.spec_id} has no eligible rolling evaluation rows")
    aggregate = _compare(opponent_rows, raw_rows)
    return {
        "spec_id": spec.spec_id,
        "spec": spec.to_dict(),
        "aggregate_metrics": aggregate["opponent_metrics"],
        "matched_raw_metrics": aggregate["reference_metrics"],
        "aggregate_deltas": aggregate["deltas"],
        "folds": fold_results,
        "eligible_fold_count": len(eligible),
        "prediction_count": len(opponent_rows),
    }


def _render_doc(summary: Mapping[str, Any]) -> str:
    validation = summary["validation"]
    primary = validation["opponent_vs_matched_raw"]
    lines = [
        "# Phase 2C-2 Opponent / Schedule Strength Research",
        "",
        "This is bounded offline exploratory research. It does not register a production Challenger, alter Champion, or write formal benchmark records.",
        "",
        "## Locked data boundary",
        "",
        f"- Research pool: **{summary['research_pool']['count']}** fixtures; development **{summary['research_pool']['development']}**, reused validation **{summary['research_pool']['reused_validation']}**.",
        f"- Phase 2C-1 spent held-out set: **{summary['spent_heldout']['count']}** IDs, digest `{summary['spent_heldout']['digest']}`. Result payloads accessed for training/evaluation: **0 / 0**.",
        "- Fresh held-out data is unavailable. The 134-fixture validation result is exploratory evidence only.",
        "",
        "## Specifications",
        "",
        f"- Candidate registry: **{len(summary['candidate_specs'])}** regularization values, frozen before rolling evaluation.",
        f"- Selected specification: `{summary['selected_spec']['selected_spec_id']}`.",
        f"- Experiment ID: `{summary['experiment_id']}`.",
        "",
        "## Validation evidence",
        "",
        f"- Validation evaluation count: **{summary['validation_evaluation_count']}**.",
        f"- Opponent vs matched raw 1X2 log-loss delta: **{primary['deltas']['one_x_two_log_loss']}**; bootstrap CI `{primary['bootstrap']['one_x_two_log_loss']['ci_95']}`.",
        f"- Opponent vs matched raw goal-NLL delta: **{primary['deltas']['goal_distribution_nll']}**; bootstrap CI `{primary['bootstrap']['goal_distribution_nll']['ci_95']}`.",
        f"- Exploratory classification: **{summary['classification']}**.",
        "",
        "## Boundaries",
        "",
        "- Only historical results, goals, venue, competition, and target-time prior records were used.",
        "- No Elo, Bradley-Terry, schedule-strength coefficient, market, xG, lineup, injury, or manual judgement was used.",
        "- This is not a fair offline Champion comparison because historical Champion snapshots and market inputs are unavailable.",
        f"- Formal prospective benchmark comparisons remain **{summary['benchmark_health'].get('prospective_comparisons', 0)}**.",
        "",
    ]
    return "\n".join(lines)


def _handoff_entries(root: Path, summary: Mapping[str, Any], benchmark: Mapping[str, Any], pr_number: int | None) -> dict[str, bytes]:
    relative_files = [
        "scripts/football_data/phase2c2_opponent_strength.py",
        "scripts/football_data/phase2c2_experiment.py",
        "scripts/football_data/run_phase2c2.py",
        "data/football_data/phase2c2_experiment_manifest.json",
        "data/football_data/phase2c2_results_summary.json",
        "docs/team-strength/PHASE2C2_OPPONENT_STRENGTH.md",
        "tests/phase2c2_test_support.py",
    ]
    relative_files.extend(sorted(path.relative_to(root).as_posix() for path in (root / "tests").glob("test_phase2c2_*.py")))
    entries: dict[str, bytes] = {}
    for relative in relative_files:
        path = root / relative
        if path.is_file():
            entries[relative] = path.read_bytes()
    entries["phase2c2_champion_evidence.json"] = (json.dumps(champion_evidence(root), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    entries["phase2c2_benchmark_health.json"] = (json.dumps(benchmark, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, check=False).stdout.strip()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False).stdout.strip()
    entries["phase2c2_pr_metadata.json"] = (json.dumps({
        "title": "feat(model): evaluate phase2c2 opponent strength",
        "draft": True,
        "pr_number": pr_number,
        "branch": branch,
        "head": head,
        "research_only": True,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    entries["phase2c2_summary.json"] = (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return entries


def write_phase2c2_handoff(*, root: Path = ROOT, pr_number: int | None = None) -> Path:
    summary = _read_json(root / "data" / "football_data" / "phase2c2_results_summary.json")
    benchmark = _benchmark_health(root)
    HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries = _handoff_entries(root, summary, benchmark, pr_number)
    with ZipFile(HANDOFF_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    return HANDOFF_PATH


def refresh_phase2c2_compact_outputs(
    *,
    root: Path = ROOT,
    data_home: str | Path | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    """Rebuild only Git-tracked compact outputs from frozen Data Home results."""

    artifact_root = _data_home(data_home) / "research" / "phase2c2"
    summary = _read_json(artifact_root / "results_summary.json")
    candidate_results = _read_json(artifact_root / "rolling_results.json")
    compact = _compact_summary(summary, candidate_results)
    _write_json(root / "data" / "football_data" / "phase2c2_results_summary.json", compact)
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(_render_doc(compact), encoding="utf-8")
    handoff = write_phase2c2_handoff(root=root, pr_number=pr_number)
    return {"status": "OK", "handoff": str(handoff), "compact_summary": str(COMPACT_RESULTS_PATH)}


def run_phase2c2(
    *,
    root: Path = ROOT,
    data_home: str | Path | None = None,
    generated_at: str | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    """Run Phase 2C-2 once, freezing validation before writing its guard."""

    generated = generated_at or _now()
    home = _data_home(data_home)
    verification = verify_data_home(data_home=home, manifest_root=root / "data" / "football_data" / "manifests")
    if verification.get("status") != "OK":
        raise RuntimeError(json.dumps(verification, ensure_ascii=False))
    pool = load_phase2c2_research_pool(root=root, data_home=home)
    development = list(pool["development"])
    validation = list(pool["validation"])
    spent_ids = list(pool["spent_heldout_ids"])
    if len(development) != EXPECTED_DEVELOPMENT_SIZE or len(validation) != EXPECTED_VALIDATION_SIZE:
        raise ValueError("Phase 2C-2 research pool count mismatch")
    if len(spent_ids) != EXPECTED_SPENT_HELDOUT_SIZE or pool["spent_heldout_digest"] != EXPECTED_SPENT_HELDOUT_DIGEST:
        raise ValueError("Phase 2C-2 spent-heldout lock mismatch")
    artifact_root = home / "research" / "phase2c2"
    guard_path = artifact_root / "validation_evaluation.json"
    if guard_path.exists():
        raise RuntimeError("Phase 2C-2 reused validation has already been evaluated")

    registry_payload = _candidate_registry(generated)
    _write_json(artifact_root / "candidate_specs.json", registry_payload)
    registry = list(registry_payload["candidate_specs"])
    folds = build_rolling_folds(development)
    targets_by_id = {_target_id(row): row for row in development + validation}
    development_by_id = {_target_id(row): row for row in development}
    pool_ids = set(targets_by_id)
    external_history = [row for row in pool["history_records"] if _target_id(row) not in pool_ids]
    candidate_results = [
        _evaluate_candidate(
            _registered_spec(row),
            folds,
            development,
            pool["history_records"],
            spent_ids,
        )
        for row in registry
    ]
    selection = select_opponent_spec(candidate_results, registry)
    selected_row = next(row for row in registry if row["spec_id"] == selection["selected_spec_id"])
    selected_spec = _registered_spec(selected_row)

    validation_bundle = _prediction_bundle(
        validation,
        list(external_history) + development,
        selected_spec,
        spent_heldout_ids=spent_ids,
        include_frozen=True,
        include_baseline=True,
    )["predictions"]
    expected_validation_count = len(validation_bundle["opponent"])
    if expected_validation_count != EXPECTED_VALIDATION_SIZE:
        raise RuntimeError(f"reused validation did not produce all {EXPECTED_VALIDATION_SIZE} fixtures: {expected_validation_count}")
    validation_comparison = _compare(validation_bundle["opponent"], validation_bundle["matched_raw"])
    validation_vs_frozen = _compare(validation_bundle["opponent"], validation_bundle["frozen_2c1"])
    validation_vs_baseline_a = _compare(validation_bundle["opponent"], validation_bundle["baseline_a"])
    validation_bootstrap = paired_comparison_bootstrap(
        validation_bundle["opponent"],
        validation_bundle["matched_raw"],
        validation_bundle["frozen_2c1"],
    )
    evaluate_validation_once(
        validation_bundle["opponent"],
        validation_bundle["matched_raw"],
        guard_path,
        metadata={
            "cohort_id": pool["cohort_id"],
            "cohort_match_digest": pool["cohort_match_digest"],
            "selected_spec_id": selected_spec.spec_id,
            "spent_heldout_digest": pool["spent_heldout_digest"],
            "fresh_heldout_available": False,
            "historical_validation_reused": True,
        },
    )
    validation_per_competition = _per_competition_comparison(
        validation_bundle["opponent"],
        validation_bundle["matched_raw"],
        validation_bundle["frozen_2c1"],
    )

    selected_rolling = selection["rolling_metrics"]
    eligible_folds = [fold for fold in selected_rolling["folds"] if fold.get("eligible")]
    fold_improvements = sum(bool(fold.get("improved_majority")) for fold in eligible_folds)
    classification = classification_from_exploratory_evidence(
        validation_comparison["deltas"],
        validation_comparison["bootstrap"],
        rolling_fold_improvements=fold_improvements,
        rolling_fold_count=len(eligible_folds),
    )
    research_pool_ids = sorted(_target_id(row) for row in development + validation)
    research_pool_digest = content_sha256(research_pool_ids)
    experiment_id = experiment_id_for(
        pool_digest=research_pool_digest,
        spent_heldout_digest=pool["spent_heldout_digest"],
        selected_spec=selected_spec.to_dict(),
        candidate_registry_digest=registry_payload["registry_digest"],
        historical_dataset_digest=pool["historical_dataset_digest"],
    )
    champion = champion_evidence(root)
    if champion["automatic_model_core_sha256"] != champion["expected_automatic_model_core_sha256"] or champion["validated_for_model_true_count"] != 0:
        raise RuntimeError("Champion isolation evidence failed")
    benchmark = _benchmark_health(root)
    validation_predictions_digest = content_sha256(validation_bundle)
    rolling_digest = content_sha256(candidate_results)
    summary = {
        "experiment_id": experiment_id,
        "contract_version": "phase2c2_opponent_strength.v1",
        "research_only": True,
        "spent_heldout": {
            "count": len(spent_ids),
            "digest": pool["spent_heldout_digest"],
            "accessed_for_training": 0,
            "accessed_for_evaluation": 0,
            "ids_used_only_for_exclusion": True,
        },
        "research_pool": {
            "count": len(research_pool_ids),
            "digest": research_pool_digest,
            "development": len(development),
            "reused_validation": len(validation),
            "fresh_heldout_available": False,
        },
        "rolling_folds": folds,
        "candidate_specs": registry,
        "candidate_registry_digest": registry_payload["registry_digest"],
        "selected_spec": selection,
        "matched_raw_reference": {
            "spec_id": f"matched-raw:prior{selected_spec.regularization}",
            "formula": MATCHED_RAW_FORMULA_VERSION,
            "same_history_and_regularization": True,
            "opponent_identity_adjustment": False,
        },
        "opponent_adjusted": {
            "spec_id": selected_spec.spec_id,
            "formula": selected_spec.formula,
            "solver": selected_spec.solver,
            "history_policy": selected_spec.history_policy,
        },
        "validation_evaluation_count": 1,
        "validation": {
            "sample": len(validation_bundle["opponent"]),
            "opponent_vs_matched_raw": validation_comparison,
            "opponent_vs_frozen_2c1": validation_vs_frozen,
            "opponent_vs_baseline_a": validation_vs_baseline_a,
            "paired_bootstrap": validation_bootstrap,
            "per_competition": validation_per_competition,
        },
        "rolling_fold_consistency": {
            "eligible_fold_count": len(eligible_folds),
            "improving_fold_count": fold_improvements,
            "majority_improvement": fold_improvements > len(eligible_folds) / 2 if eligible_folds else False,
            "folds": selected_rolling["folds"],
        },
        "classification": classification,
        "prospective_shadow_recommended": classification == "EXPLORATORY_PROMISING",
        "boundary": phase2c2_research_boundary(),
        "benchmark_health": benchmark,
        "champion_evidence": champion,
        "validated_for_model_true_count": 0,
        "artifact_digests": {
            "candidate_registry": registry_payload["registry_digest"],
            "rolling_results": rolling_digest,
            "validation_predictions": validation_predictions_digest,
        },
        "generated_at": generated,
    }
    _write_json(artifact_root / "rolling_results.json", candidate_results)
    _write_json(artifact_root / "validation_predictions.json", validation_bundle)
    _write_json(artifact_root / "bootstrap.json", validation_bootstrap)
    _write_json(artifact_root / "experiment_manifest.json", {
        "experiment_id": experiment_id,
        "contract_version": summary["contract_version"],
        "research_pool": summary["research_pool"],
        "spent_heldout": summary["spent_heldout"],
        "selected_spec": selected_spec.to_dict(),
        "candidate_registry_digest": registry_payload["registry_digest"],
        "validation_evaluation_count": 1,
        "artifact_policy": "bulk rolling predictions, validation predictions, fitted strengths, and bootstrap diagnostics remain under FOOTBALL_DATA_HOME",
        "generated_at": generated,
    })
    _write_json(artifact_root / "results_summary.json", summary)
    compact_summary = _compact_summary(summary, candidate_results)
    _write_json(COMPACT_MANIFEST_PATH, {
        "experiment_id": experiment_id,
        "contract_version": summary["contract_version"],
        "research_cohort_id": pool["cohort_id"],
        "research_pool_digest": research_pool_digest,
        "historical_dataset_digest": pool["historical_dataset_digest"],
        "spent_heldout_digest": pool["spent_heldout_digest"],
        "split_counts": {"development": len(development), "reused_validation": len(validation), "fresh_heldout": 0},
        "selected_spec_id": selected_spec.spec_id,
        "candidate_registry_digest": registry_payload["registry_digest"],
        "validation_evaluation_count": 1,
        "artifact_digests": summary["artifact_digests"],
        "artifact_root_policy": "${FOOTBALL_DATA_HOME}/research/phase2c2/",
        "fresh_heldout_available": False,
        "historical_validation_reused": True,
        "formal_benchmark_eligible": False,
        "production_challenger_registered": False,
        "validated_for_model": False,
        "generated_at": generated,
    })
    _write_json(COMPACT_RESULTS_PATH, compact_summary)
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(_render_doc(compact_summary), encoding="utf-8")
    handoff = write_phase2c2_handoff(root=root, pr_number=pr_number)
    return {
        "status": "OK",
        "summary": summary,
        "artifact_root": str(artifact_root),
        "handoff": str(handoff),
    }


__all__ = ["refresh_phase2c2_compact_outputs", "run_phase2c2", "write_phase2c2_handoff"]
