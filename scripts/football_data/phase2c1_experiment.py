"""Orchestration for the offline Phase 2C-1 Team Strength experiment."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from .data_home import resolve_football_data_home
from .phase2c1_model import (
    CANDIDATE_SPECS,
    MODEL_CONTRACT_VERSION,
    CandidateSpec,
    InsufficientHistoryError,
    attach_actual,
    build_baseline_prediction,
    build_team_strength_prediction,
    candidate_specs_manifest,
    classification_from_deltas,
    evaluate_predictions,
    metric_loss_values,
    paired_bootstrap_deltas,
    select_spec,
    spec_from_dict,
)
from .storage import HistoricalResultStore, content_sha256
from .verify_data_home import verify_data_home


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COHORT_ID = "phase2c-1:standard_recommended:aeca9b371975d229e598507257f0c26961ccbdb24184f38b42c464e6f8198257"
EXPECTED_COHORT_MATCH_DIGEST = "6e7f22a3db6ba8b1ef32bb7f3601f6c59bfceb579f35c40698ab39261cccdf2a"
EXPECTED_DATASET_DIGEST = "710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e"
EXPECTED_COHORT_SIZE = 688
EXPECTED_SPLIT_COUNTS = {"development": 410, "validation": 134, "held_out_test": 144}
EXPECTED_CORE_SHA256 = "064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15"
EXPECTED_FIXED_DIGEST = "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"
COMPACT_PREFLIGHT_PATH = ROOT / "data" / "football_data" / "phase2c_research_readiness.json"
COMPACT_MANIFEST_PATH = ROOT / "data" / "football_data" / "phase2c1_experiment_manifest.json"
COMPACT_RESULTS_PATH = ROOT / "data" / "football_data" / "phase2c1_results_summary.json"
DOC_PATH = ROOT / "docs" / "team-strength" / "PHASE2C1_BASIC_TEAM_STRENGTH.md"
HANDOFF_PATH = ROOT / "artifacts" / "football-phase2c1-team-strength-handoff.zip"


class HeldoutAlreadyEvaluatedError(RuntimeError):
    """Raised if code attempts to evaluate the locked test set twice."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != serialized:
        path.write_text(serialized, encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _data_home(data_home: str | Path | None = None) -> Path:
    return Path(data_home).expanduser() if data_home is not None else resolve_football_data_home()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _record_sort_key(record: Mapping[str, Any]) -> tuple[datetime, str]:
    return (_parse_time(record.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(record.get("canonical_match_id") or ""))


def _git_output(root: Path, arguments: list[str]) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        return completed.stdout.strip()
    git_marker = root / ".git"
    if git_marker.is_file():
        text = git_marker.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            git_dir = text.split(":", 1)[1].strip()
            fallback = subprocess.run(
                ["git", f"--git-dir={git_dir}", f"--work-tree={root}", *arguments],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            if fallback.returncode == 0:
                return fallback.stdout.strip()
    return ""


def validate_cohort_lock(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the externally approved cohort identity, size, and digest."""

    if str(metadata.get("research_cohort_id")) != EXPECTED_COHORT_ID:
        raise ValueError(f"approved research cohort ID mismatch: {metadata.get('research_cohort_id')}")
    if str(metadata.get("cohort_match_id_digest")) != EXPECTED_COHORT_MATCH_DIGEST:
        raise ValueError("approved research cohort match digest mismatch")
    if int(metadata.get("cohort_size") or 0) != EXPECTED_COHORT_SIZE:
        raise ValueError("approved research cohort size mismatch")
    return {
        "research_cohort_id": EXPECTED_COHORT_ID,
        "cohort_match_id_digest": EXPECTED_COHORT_MATCH_DIGEST,
        "cohort_size": EXPECTED_COHORT_SIZE,
    }


def load_approved_cohort(*, data_home: str | Path | None = None, root: Path = ROOT) -> dict[str, Any]:
    """Load the approved cohort IDs from shared Data Home and verify its lock."""

    compact = _read_json(root / "data" / "football_data" / "phase2c_research_readiness.json")
    recommended = dict(compact.get("recommended_cohort") or {})
    validate_cohort_lock(recommended)
    detail_root = _data_home(data_home) / "research" / "phase2c_preflight"
    ids_path = detail_root / "recommended_cohort_match_ids.json"
    audit_path = detail_root / "eligibility_audit.json"
    if not ids_path.is_file() or not audit_path.is_file():
        raise FileNotFoundError("approved cohort detail is unavailable in shared Football Data Home")
    match_ids = sorted(str(value) for value in _read_json(ids_path))
    if len(match_ids) != EXPECTED_COHORT_SIZE or content_sha256(match_ids) != EXPECTED_COHORT_MATCH_DIGEST:
        raise ValueError("approved cohort IDs do not match the locked cohort digest")
    audit = _read_json(audit_path)
    detailed_recommended = dict(audit.get("recommended_cohort") or {})
    validate_cohort_lock(detailed_recommended)
    split = dict(audit.get("chronological_split") or {})
    split_ids: dict[str, list[str]] = {}
    for name, expected_count in EXPECTED_SPLIT_COUNTS.items():
        bucket = dict(split.get(name) or {})
        values = sorted(str(value) for value in bucket.get("match_ids") or [])
        if len(values) != expected_count:
            raise ValueError(f"approved {name} split count mismatch")
        split_ids[name] = values
    union = set().union(*(set(values) for values in split_ids.values()))
    if union != set(match_ids) or sum(len(values) for values in split_ids.values()) != len(union):
        raise ValueError("approved chronological split is not a disjoint partition of the cohort")
    for left_name, left_values in split_ids.items():
        for right_name, right_values in split_ids.items():
            if left_name < right_name and set(left_values) & set(right_values):
                raise ValueError("approved chronological split has overlapping buckets")
    return {
        "metadata": recommended,
        "match_ids": match_ids,
        "split_ids": split_ids,
        "split": split,
        "compact_preflight": compact,
    }


def experiment_id_for(*, cohort_id: str, dataset_digest: str, spec: Mapping[str, Any]) -> str:
    payload = {
        "contract_version": MODEL_CONTRACT_VERSION,
        "cohort_id": cohort_id,
        "historical_dataset_digest": dataset_digest,
        "selected_spec": dict(spec),
    }
    return f"phase2c1:{content_sha256(payload)}"


def research_boundary() -> dict[str, Any]:
    return {
        "research_only": True,
        "formal_benchmark_eligible": False,
        "champion_comparison_supported": False,
        "production_model_input": False,
        "validated_for_model": False,
        "prospective_shadow_registered": False,
    }


def champion_evidence(root: Path = ROOT) -> dict[str, Any]:
    core_path = root / "scripts" / "automatic_model_core.py"
    registry = _read_json(root / "config" / "football_feature_registry.json")
    core_sha = hashlib.sha256(core_path.read_bytes()).hexdigest()
    true_count = sum(bool(row.get("validated_for_model")) for row in registry.get("features", []))
    return {
        "automatic_model_core_sha256": core_sha,
        "expected_automatic_model_core_sha256": EXPECTED_CORE_SHA256,
        "fixed_fixture_digest": EXPECTED_FIXED_DIGEST,
        "validated_for_model_true_count": true_count,
        "champion_math_changed": False,
    }


def evaluate_heldout_once(predictions: Iterable[Mapping[str, Any]], *, heldout_evaluation_count: int) -> dict[str, Any]:
    if int(heldout_evaluation_count) != 0:
        raise HeldoutAlreadyEvaluatedError("held-out evaluation is locked after its first run")
    return {"heldout_evaluation_count": 1, "predictions": [dict(row) for row in predictions]}


def _benchmark_health(root: Path) -> dict[str, Any]:
    command = [sys.executable, str(root / "scripts" / "benchmark_health.py"), "--no-write"]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"benchmark health read failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _prediction_set(targets: list[Mapping[str, Any]], records: list[Mapping[str, Any]], spec: CandidateSpec, competitions: set[str]) -> dict[str, list[dict[str, Any]]]:
    team_strength: list[dict[str, Any]] = []
    baseline_a: list[dict[str, Any]] = []
    baseline_b: list[dict[str, Any]] = []
    for target in sorted(targets, key=_record_sort_key):
        try:
            team = build_team_strength_prediction(target, records, spec)
            base_a = build_baseline_prediction(target, records, baseline_kind="competition_poisson")
            base_b = build_baseline_prediction(target, records, baseline_kind="global_poisson", allowed_competitions=competitions)
        except InsufficientHistoryError as exc:
            raise RuntimeError(f"approved cohort target cannot be evaluated: {target.get('canonical_match_id')}: {exc}") from exc
        team_strength.append(attach_actual(team, target))
        baseline_a.append(attach_actual(base_a, target))
        baseline_b.append(attach_actual(base_b, target))
    return {"team_strength": team_strength, "baseline_a": baseline_a, "baseline_b": baseline_b}


def _metrics_for_set(predictions: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {name: evaluate_predictions(rows) for name, rows in predictions.items()}


def _metric_deltas(challenger: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, float]:
    metric_names = (
        "one_x_two_log_loss",
        "one_x_two_brier",
        "goal_distribution_nll",
        "home_goals_mae",
        "away_goals_mae",
        "expected_total_goals_mae",
        "over_2_5_log_loss",
        "over_2_5_brier",
        "btts_log_loss",
        "btts_brier",
    )
    return {name: float(challenger[name]) - float(baseline[name]) for name in metric_names}


def _per_competition(heldout: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = heldout["team_strength"]
    competitions = sorted({str(row.get("competition_id")) for row in rows})
    output: dict[str, Any] = {}
    for competition in competitions:
        selected = {
            name: [row for row in values if str(row.get("competition_id")) == competition]
            for name, values in heldout.items()
        }
        team_metrics = evaluate_predictions(selected["team_strength"])
        base_metrics = evaluate_predictions(selected["baseline_a"])
        deltas = _metric_deltas(team_metrics, base_metrics)
        output[competition] = {
            "sample": len(selected["team_strength"]),
            "team_strength": {
                "one_x_two_log_loss": team_metrics["one_x_two_log_loss"],
                "one_x_two_brier": team_metrics["one_x_two_brier"],
                "goal_distribution_nll": team_metrics["goal_distribution_nll"],
            },
            "baseline_a": {
                "one_x_two_log_loss": base_metrics["one_x_two_log_loss"],
                "one_x_two_brier": base_metrics["one_x_two_brier"],
                "goal_distribution_nll": base_metrics["goal_distribution_nll"],
            },
            "deltas": {key: deltas[key] for key in ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll")},
        }
    return output


def _bootstrap_summary(heldout: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    challenger = heldout["team_strength"]
    baseline = heldout["baseline_a"]
    metrics = ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss")
    return {
        metric: paired_bootstrap_deltas(
            metric_loss_values(challenger, metric),
            metric_loss_values(baseline, metric),
            n_bootstrap=1000,
            seed=20260811,
        )
        for metric in metrics
    }


def _render_doc(summary: Mapping[str, Any], benchmark: Mapping[str, Any], generated_at: str) -> str:
    heldout = summary["heldout_evaluation"]
    lines = [
        "# Phase 2C-1 Basic Team Strength",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "This is an offline research experiment. It does not register a production Challenger, alter Champion inputs, or create formal benchmark records.",
        "",
        "## Locked cohort",
        "",
        f"- Cohort: `{summary['cohort']['research_cohort_id']}`",
        f"- Match digest: `{summary['cohort']['cohort_match_id_digest']}`",
        f"- Size: **{summary['cohort']['cohort_size']}**; development **{summary['splits']['development']}**, validation **{summary['splits']['validation']}**, held-out **{summary['splits']['held_out_test']}**",
        f"- Experiment ID: `{summary['experiment_id']}`",
        "",
        "## Specifications",
        "",
        f"- Candidates were frozen before validation: **{len(summary['candidate_specs'])}**",
        f"- Selected specification: `{summary['selected_spec']['selected_spec_id']}`",
        f"- Selection: {summary['selected_spec']['selection_reason']}",
        "",
        "## Held-out result",
        "",
        f"- Evaluation count: **{heldout['heldout_evaluation_count']}**",
        f"- Team Strength 1X2 log loss: **{heldout['team_strength']['one_x_two_log_loss']}**; Baseline A: **{heldout['baseline_a']['one_x_two_log_loss']}**",
        f"- Team Strength goal NLL: **{heldout['team_strength']['goal_distribution_nll']}**; Baseline A: **{heldout['baseline_a']['goal_distribution_nll']}**",
        f"- Research classification: **{summary['research_classification']}**",
        "",
        "## Boundaries",
        "",
        "- Features use historical goals/results only and strictly exclude target and future kickoffs.",
        "- No xG, lineups, injuries, Elo, opponent strength, schedule strength, odds, or manual judgement is used.",
        "- Partial competition populations remain observed identity-mapped subsets; no entire-league validation claim is made.",
        f"- Formal prospective comparisons remain **{benchmark.get('prospective_comparisons', 0)}**.",
        "- Offline results are not a fair Champion comparison because historical Champion snapshots/market inputs are unavailable.",
        "",
    ]
    return "\n".join(lines)


def _handoff_entries(root: Path, summary: Mapping[str, Any], benchmark: Mapping[str, Any], pr_number: int | None) -> dict[str, bytes]:
    relative_files = [
        "scripts/football_data/phase2c1_model.py",
        "scripts/football_data/phase2c1_experiment.py",
        "scripts/football_data/run_phase2c1.py",
        "data/football_data/phase2c1_experiment_manifest.json",
        "data/football_data/phase2c1_results_summary.json",
        "docs/team-strength/PHASE2C1_BASIC_TEAM_STRENGTH.md",
        "tests/test_phase2c1_no_future_leakage.py",
        "tests/test_phase2c1_target_result_not_input.py",
        "tests/test_basic_team_strength_formula.py",
        "tests/test_team_strength_shrinkage.py",
        "tests/test_candidate_specs_frozen_before_validation.py",
        "tests/test_heldout_evaluated_once.py",
        "tests/test_phase2c1_probability_coherence.py",
        "tests/test_phase2c1_score_matrix_mass.py",
        "tests/test_phase2c1_metrics.py",
        "tests/test_phase2c1_paired_bootstrap.py",
        "tests/test_phase2c1_reproducible_experiment.py",
        "tests/test_phase2c1_not_formal_benchmark.py",
        "tests/test_phase2c1_champion_isolation.py",
        "tests/test_phase2c1_cohort_lock.py",
    ]
    entries: dict[str, bytes] = {}
    for relative in relative_files:
        path = root / relative
        if path.is_file():
            entries[relative] = path.read_bytes()
    entries["phase2c1_champion_evidence.json"] = (json.dumps(champion_evidence(root), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    entries["phase2c1_benchmark_health.json"] = (json.dumps(benchmark, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    entries["phase2c1_pr_metadata.json"] = (json.dumps({
        "title": "feat(model): evaluate phase2c1 team strength",
        "draft": True,
        "pr_number": pr_number,
        "branch": _git_output(root, ["branch", "--show-current"]),
        "head": _git_output(root, ["rev-parse", "HEAD"]),
        "research_only": True,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    entries["phase2c1_summary.json"] = (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return entries


def _write_handoff(root: Path, summary: Mapping[str, Any], benchmark: Mapping[str, Any], pr_number: int | None) -> Path:
    HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries = _handoff_entries(root, summary, benchmark, pr_number)
    with ZipFile(HANDOFF_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    return HANDOFF_PATH


def run_phase2c1(
    *,
    root: Path = ROOT,
    data_home: str | Path | None = None,
    generated_at: str | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    """Run the locked offline experiment and write compact repo artifacts."""

    generated = generated_at or _now()
    home = _data_home(data_home)
    verification = verify_data_home()
    if verification.get("status") != "OK":
        raise RuntimeError(json.dumps(verification, ensure_ascii=False))
    cohort = load_approved_cohort(data_home=home, root=root)
    store = HistoricalResultStore(home / "historical_results.duckdb")
    records = store.records()
    dataset_digest = store.dataset_digest()
    if dataset_digest != EXPECTED_DATASET_DIGEST:
        raise ValueError("historical dataset digest does not match approved preflight")
    records_by_id = {str(row.get("canonical_match_id")): row for row in records}
    targets = []
    for match_id in cohort["match_ids"]:
        if match_id not in records_by_id:
            raise ValueError(f"approved cohort match is missing from historical store: {match_id}")
        targets.append(records_by_id[match_id])
    targets.sort(key=_record_sort_key)
    split_sets = {name: set(values) for name, values in cohort["split_ids"].items()}
    split_targets = {
        name: [row for row in targets if str(row.get("canonical_match_id")) in values]
        for name, values in split_sets.items()
    }
    competitions = set(str(value) for value in cohort["metadata"].get("competitions") or [])
    artifact_root = home / "research" / "phase2c1"
    artifact_root.mkdir(parents=True, exist_ok=True)
    heldout_guard_path = artifact_root / "heldout_evaluation.json"
    if heldout_guard_path.is_file():
        raise HeldoutAlreadyEvaluatedError("Phase 2C-1 held-out artifact already exists; no second evaluation is allowed")

    registry = candidate_specs_manifest()
    registry_payload = {
        "contract_version": MODEL_CONTRACT_VERSION,
        "frozen_before_validation": True,
        "candidate_specs": registry,
        "registry_digest": content_sha256(registry),
        "registered_at": generated,
    }
    _write_json(artifact_root / "candidate_specs.json", registry_payload)

    baseline_sets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    candidate_development: list[dict[str, Any]] = []
    candidate_validation: list[dict[str, Any]] = []
    for spec in CANDIDATE_SPECS:
        dev = _prediction_set(split_targets["development"], records, spec, competitions)
        validation = _prediction_set(split_targets["validation"], records, spec, competitions)
        if not baseline_sets:
            baseline_sets["development"] = dev
            baseline_sets["validation"] = validation
        dev_metrics = evaluate_predictions(dev["team_strength"])
        validation_metrics = evaluate_predictions(validation["team_strength"])
        candidate_development.append({"spec_id": spec.spec_id, **dev_metrics})
        candidate_validation.append({"spec_id": spec.spec_id, **validation_metrics})
        _write_json(artifact_root / "candidates" / f"{spec.spec_id.replace(':', '_')}.development.json", dev["team_strength"])
        _write_json(artifact_root / "candidates" / f"{spec.spec_id.replace(':', '_')}.validation.json", validation["team_strength"])
    _write_json(artifact_root / "development_metrics.json", candidate_development)
    _write_json(artifact_root / "validation_metrics.json", candidate_validation)
    selection = select_spec(candidate_validation, registry)
    selected_spec = spec_from_dict(next(item for item in registry if item["spec_id"] == selection["selected_spec_id"]))

    heldout_sets = _prediction_set(split_targets["held_out_test"], records, selected_spec, competitions)
    heldout_evaluation = evaluate_heldout_once(heldout_sets["team_strength"], heldout_evaluation_count=0)
    heldout_sets = {name: values for name, values in heldout_sets.items()}
    heldout_prediction_digest = content_sha256(heldout_evaluation["predictions"])
    _write_json(heldout_guard_path, {
        "heldout_evaluation_count": heldout_evaluation["heldout_evaluation_count"],
        "selected_spec_id": selected_spec.spec_id,
        "cohort_id": cohort["metadata"]["research_cohort_id"],
        "prediction_digest": heldout_prediction_digest,
        "evaluated_at": generated,
    })
    for name, values in heldout_sets.items():
        _write_json(artifact_root / f"heldout_{name}.json", values)
    heldout_metrics = _metrics_for_set(heldout_sets)
    deltas = _metric_deltas(heldout_metrics["team_strength"], heldout_metrics["baseline_a"])
    bootstrap = _bootstrap_summary(heldout_sets)
    per_competition = _per_competition(heldout_sets)
    result_classification = classification_from_deltas(deltas)
    experiment_id = experiment_id_for(cohort_id=cohort["metadata"]["research_cohort_id"], dataset_digest=dataset_digest, spec=selected_spec.to_dict())
    benchmark = _benchmark_health(root)
    summary = {
        "experiment_id": experiment_id,
        "contract_version": MODEL_CONTRACT_VERSION,
        "research_only": True,
        "cohort": {
            "research_cohort_id": cohort["metadata"]["research_cohort_id"],
            "cohort_match_id_digest": cohort["metadata"]["cohort_match_id_digest"],
            "cohort_size": len(targets),
            "historical_dataset_digest": dataset_digest,
            "competitions": sorted(competitions),
            "unique_teams": len({team for row in targets for team in (row.get("home_team_id"), row.get("away_team_id"))}),
        },
        "splits": {name: len(rows) for name, rows in split_targets.items()},
        "split_boundaries": {
            name: {
                "min_kickoff_at": min((str(row.get("kickoff_at")) for row in rows), default=None),
                "max_kickoff_at": max((str(row.get("kickoff_at")) for row in rows), default=None),
            }
            for name, rows in split_targets.items()
        },
        "candidate_specs": registry,
        "candidate_registry_digest": registry_payload["registry_digest"],
        "artifact_digests": {
            "candidate_registry": registry_payload["registry_digest"],
            "heldout_prediction": heldout_prediction_digest,
        },
        "development_selection_metrics": candidate_development,
        "validation_selection_metrics": candidate_validation,
        "selected_spec": selection,
        "baseline_a": {"name": "Research Baseline A", "definition": "competition-specific historical independent Poisson", "metrics": heldout_metrics["baseline_a"]},
        "baseline_b": {"name": "Research Baseline B", "definition": "recommended-competition global historical independent Poisson", "metrics": heldout_metrics["baseline_b"]},
        "heldout_evaluation": {
            "heldout_evaluation_count": heldout_evaluation["heldout_evaluation_count"],
            "team_strength": heldout_metrics["team_strength"],
            "baseline_a": heldout_metrics["baseline_a"],
            "baseline_b": heldout_metrics["baseline_b"],
            "deltas_vs_baseline_a": deltas,
            "paired_bootstrap_vs_baseline_a": bootstrap,
        },
        "per_competition": per_competition,
        "research_classification": result_classification,
        "prospective_shadow_recommended": result_classification == "RESEARCH_PROMISING",
        "boundary": research_boundary(),
        "benchmark_health": benchmark,
        "validated_for_model_true_count": 0,
        "generated_at": generated,
    }
    _write_json(artifact_root / "experiment_manifest.json", {
        "experiment_id": experiment_id,
        "cohort": summary["cohort"],
        "selected_spec": selected_spec.to_dict(),
        "heldout_evaluation_count": 1,
        "artifact_policy": "bulk per-match predictions and diagnostics remain under FOOTBALL_DATA_HOME",
        "generated_at": generated,
    })
    _write_json(COMPACT_MANIFEST_PATH, {
        "experiment_id": experiment_id,
        "contract_version": MODEL_CONTRACT_VERSION,
        "research_cohort_id": EXPECTED_COHORT_ID,
        "cohort_match_id_digest": EXPECTED_COHORT_MATCH_DIGEST,
        "historical_dataset_digest": dataset_digest,
        "cohort_size": len(targets),
        "split_counts": summary["splits"],
        "selected_spec_id": selected_spec.spec_id,
        "artifact_digests": summary["artifact_digests"],
        "heldout_evaluation_count": 1,
        "artifact_root_policy": "${FOOTBALL_DATA_HOME}/research/phase2c1/",
        "formal_benchmark_eligible": False,
        "validated_for_model": False,
        "generated_at": generated,
    })
    _write_json(COMPACT_RESULTS_PATH, summary)
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(_render_doc(summary, benchmark, generated), encoding="utf-8")
    handoff = _write_handoff(root, summary, benchmark, pr_number)
    return {"status": "OK", "summary": summary, "artifact_root": str(artifact_root), "handoff": str(handoff)}


__all__ = [
    "EXPECTED_COHORT_ID",
    "EXPECTED_COHORT_MATCH_DIGEST",
    "EXPECTED_DATASET_DIGEST",
    "HeldoutAlreadyEvaluatedError",
    "champion_evidence",
    "evaluate_heldout_once",
    "experiment_id_for",
    "load_approved_cohort",
    "research_boundary",
    "run_phase2c1",
    "validate_cohort_lock",
]
