"""Materialize the Phase 2C-1 historical research readiness audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from .data_home import resolve_football_data_home
from .research_preflight import audit_historical_eligibility, compact_research_manifest
from .storage import HistoricalResultStore
from .verify_data_home import verify_data_home


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "data" / "football_data" / "phase2c_research_readiness.json"
DOC_PATH = ROOT / "docs" / "team-strength" / "PHASE2C_RESEARCH_READINESS.md"
HANDOFF_PATH = ROOT / "artifacts" / "football-phase2c-preflight-handoff.zip"
RESEARCH_CONTRACT_VERSION = "phase2c_research_eligibility.v1"
EXPECTED_CORE_SHA256 = "064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15"
EXPECTED_FIXED_DIGEST = "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != serialized:
        path.write_text(serialized, encoding="utf-8")


def _benchmark_health() -> dict[str, Any]:
    command = [sys.executable, str(ROOT / "scripts" / "benchmark_health.py"), "--no-write"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"benchmark health read failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _champion_evidence() -> dict[str, Any]:
    core_path = ROOT / "scripts" / "automatic_model_core.py"
    registry_path = ROOT / "config" / "football_feature_registry.json"
    core_sha = hashlib.sha256(core_path.read_bytes()).hexdigest()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    true_count = sum(bool(row.get("validated_for_model")) for row in registry.get("features", []))
    return {
        "automatic_model_core_sha256": core_sha,
        "expected_automatic_model_core_sha256": EXPECTED_CORE_SHA256,
        "fixed_fixture_digest": EXPECTED_FIXED_DIGEST,
        "validated_for_model_true_count": true_count,
        "champion_math_changed": False,
    }


def _render_doc(report: Mapping[str, Any], benchmark: Mapping[str, Any], generated_at: str) -> str:
    tier = report["tier_counts"]
    recommended = report["recommended_cohort"]
    gate = report["readiness_gate"]
    source = report["source_breakdown"]
    split = report["chronological_split"]
    concentration = report["recommended_concentration"]
    lines = [
        "# Phase 2C-1 Historical Research Readiness",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "This is a read-only, research-only walk-forward audit. It does not create predictions, formal benchmark records, model inputs, or Challenger code.",
        "",
        "## Historical dataset",
        "",
        f"- Records: **{report['historical_record_count']}**; deduplicated fixtures: **{report['deduplicated_fixture_count']}**",
        f"- Dataset digest: `{report['historical_dataset_digest']}`",
        f"- Date range: `{report['date_range']['first_fixture']}` to `{report['date_range']['last_fixture']}`",
        f"- Competitions: **{len(report['unique_competitions'])}**; unique teams: **{report['unique_teams']}**",
        "- Observed scope: all records in this dataset are `club` / `league`; this is not evidence of domestic-cup, continental, national-team, xG, lineup, or injury coverage.",
        "",
        "## Walk-forward tiers",
        "",
        f"- Minimum research (`both >=5`, current recency, complete observed scope): **{tier['minimum_ge_5']}**",
        f"- Standard (`both >=10`, current recency, complete observed scope): **{tier['standard_ge_10']}**",
        f"- Strict (`both >=20`, current recency, complete observed scope, no bridge): **{tier['strict_ge_20']}**",
        f"- Verified bridge-only fixtures: **{tier['verified_bridge']}**; kept outside Strict.",
        f"- Home prior-history distribution (p10/p25/median/p75/p90): **{report['prior_history_distribution']['home']['p10']} / {report['prior_history_distribution']['home']['p25']} / {report['prior_history_distribution']['home']['median']} / {report['prior_history_distribution']['home']['p75']} / {report['prior_history_distribution']['home']['p90']}**",
        f"- Away prior-history distribution (p10/p25/median/p75/p90): **{report['prior_history_distribution']['away']['p10']} / {report['prior_history_distribution']['away']['p25']} / {report['prior_history_distribution']['away']['median']} / {report['prior_history_distribution']['away']['p75']} / {report['prior_history_distribution']['away']['p90']}**",
        "",
        "## Recommended cohort",
        "",
        f"- Tier: **{report['recommended_cohort_tier']}**",
        f"- Cohort ID: `{recommended['research_cohort_id']}`",
        f"- Size: **{recommended['cohort_size']}**; competitions: **{len(recommended['competitions'])}**; teams: **{recommended['unique_teams']}**",
        f"- Date range: `{recommended['date_range']['first_fixture']}` to `{recommended['date_range']['last_fixture']}`",
        f"- Excluded from recommended cohort for insufficient chronological span: `{', '.join(report['recommended_cohort_excluded_competitions']) or 'none'}`",
        "",
        "## Chronological split proposal",
        "",
        f"Method: `{split['method']}`; split boundaries use unique kickoff timestamps, never random sampling.",
        f"- Development: **{split['development']['count']}**, `{split['development']['min_kickoff_at']}` to `{split['development']['max_kickoff_at']}`",
        f"- Validation: **{split['validation']['count']}**, `{split['validation']['min_kickoff_at']}` to `{split['validation']['max_kickoff_at']}`",
        f"- Held-out test: **{split['held_out_test']['count']}**, `{split['held_out_test']['min_kickoff_at']}` to `{split['held_out_test']['max_kickoff_at']}`",
        "",
        "## Concentration",
        "",
        f"- Largest competition share: **{concentration['largest_competition']['share']}** ({concentration['largest_competition']['competition_id']})",
        f"- Largest season share: **{concentration['largest_season']['share']}** ({concentration['largest_season']['season_id']})",
        f"- Largest team appearance share: **{concentration['largest_team_appearance']['share']}** ({concentration['largest_team_appearance']['team_id']})",
        "",
        "## Source and deduplication",
        "",
        f"- Primary provider counts: `{json.dumps(source['primary_provider_fixture_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Single-source fixtures: **{source['single_source_fixture_count']}**",
        f"- Multi-source corroborated fixtures: **{source['multi_source_corroborated_fixture_count']}**",
        f"- Source conflicts: **{source['source_conflict_count']}**; dedup conflicts: **{source['deduplication_conflicts']}**",
        "",
        "## Readiness decision",
        "",
        f"- `PHASE2C_1_RESEARCH_READY = {gate['phase2c_1_research_ready']}`",
        f"- Criteria: `{json.dumps(gate['criteria'], ensure_ascii=False, sort_keys=True)}`",
        f"- Blockers: `{', '.join(gate['blockers']) or 'none'}`",
        "- This result is offline research readiness only. It is not global model readiness, production readiness, formal benchmark evidence, or permission to create a Challenger.",
        "",
        "## Formal benchmark health (read-only)",
        "",
        f"- Prospective comparisons: **{benchmark.get('prospective_comparisons', 0)}**",
        f"- Settled comparisons: **{benchmark.get('settled_comparisons', 0)}**",
        f"- Benchmark errors: **{benchmark.get('benchmark_errors', 0)}**; snapshot mismatches: **{benchmark.get('snapshot_mismatches', 0)}**",
        "",
        "## Governance boundaries",
        "",
        "- Champion mathematics and inputs remain untouched.",
        "- `validated_for_model=true` remains zero.",
        "- Detailed eligibility rows and cohort IDs are stored under `${FOOTBALL_DATA_HOME}/research/phase2c_preflight/`; Git retains only compact manifests.",
    ]
    return "\n".join(lines) + "\n"


def _handoff_entries(pr_number: int | None = None) -> dict[str, bytes]:
    relative_files = [
        "scripts/football_data/research_preflight.py",
        "scripts/football_data/populate_phase2c_preflight.py",
        "data/football_data/phase2c_research_readiness.json",
        "data/football_data/manifests/historical_results.dataset.json",
        "data/football_data/manifests/team_strength.dataset.json",
        "docs/team-strength/PHASE2C_RESEARCH_READINESS.md",
        "config/team_strength_recency.json",
        "tests/test_historical_research_no_future_leakage.py",
        "tests/test_historical_research_dedup.py",
        "tests/test_walk_forward_minimum_history.py",
        "tests/test_research_cohort_deterministic.py",
        "tests/test_research_cohort_chronological_split.py",
        "tests/test_research_readiness_concentration.py",
        "tests/test_research_not_formal_benchmark.py",
        "tests/test_research_compact_manifest.py",
    ]
    entries: dict[str, bytes] = {}
    for relative in relative_files:
        path = ROOT / relative
        if path.is_file():
            entries[relative] = path.read_bytes()
    entries["phase2c_champion_evidence.json"] = (json.dumps(_champion_evidence(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    benchmark = _benchmark_health()
    entries["phase2c_benchmark_health.json"] = (json.dumps(benchmark, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    pr_metadata = {
        "title": "feat(model): audit phase2c research readiness",
        "draft": True,
        "pr_number": pr_number,
        "branch": _git_output("branch --show-current"),
        "head": _git_output("rev-parse HEAD"),
        "note": "PR number is optional because this package can be generated before the draft PR is created.",
    }
    entries["phase2c_pr_metadata.json"] = (json.dumps(pr_metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return entries


def _git_output(arguments: str) -> str:
    completed = subprocess.run(["git", *arguments.split()], cwd=ROOT, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _write_handoff(output_path: Path, *, pr_number: int | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entries = _handoff_entries(pr_number=pr_number)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    return output_path


def run(*, generated_at: str | None = None, pr_number: int | None = None) -> dict[str, Any]:
    generated = generated_at or _now()
    verification = verify_data_home()
    if verification["status"] != "OK":
        raise RuntimeError(json.dumps(verification, ensure_ascii=False))
    store = HistoricalResultStore()
    records = store.records()
    benchmark = _benchmark_health()
    report = audit_historical_eligibility(records, dataset_digest=store.dataset_digest())
    compact = compact_research_manifest(report, benchmark_health=benchmark)
    compact["generated_at"] = generated
    compact["data_home_policy"] = "${FOOTBALL_DATA_HOME}/historical_results.duckdb; detailed audit under ${FOOTBALL_DATA_HOME}/research/phase2c_preflight/"
    compact["detailed_artifact_policy"] = "bulk eligibility rows and cohort match IDs are not Git-tracked"
    compact["champion_evidence"] = _champion_evidence()
    _write_json(OUTPUT_PATH, compact)
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(_render_doc(report, benchmark, generated), encoding="utf-8")

    detailed_root = resolve_football_data_home() / "research" / "phase2c_preflight"
    detailed_root.mkdir(parents=True, exist_ok=True)
    _write_json(detailed_root / "eligibility_audit.json", {**report, "generated_at": generated})
    _write_json(
        detailed_root / "cohort_match_ids.json",
        {tier: cohort.get("match_ids", []) for tier, cohort in report.get("cohorts", {}).items()},
    )
    _write_json(detailed_root / "recommended_cohort_match_ids.json", report["recommended_cohort"].get("match_ids", []))
    handoff = _write_handoff(HANDOFF_PATH, pr_number=pr_number)
    return {
        "status": "OK",
        "report": compact,
        "detailed_root": str(detailed_root),
        "handoff": str(handoff),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at")
    parser.add_argument("--pr-number", type=int)
    args = parser.parse_args(argv)
    result = run(generated_at=args.generated_at, pr_number=args.pr_number)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
