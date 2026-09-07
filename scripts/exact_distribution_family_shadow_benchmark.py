#!/usr/bin/env python3
"""Run the Issue #223 distribution-family benchmark with fail-closed authority.

The benchmark is deliberately read-only.  It verifies the accepted fixed 107
match manifest and searches only existing frozen pair/snapshot/result records
for a strictly earlier, disjoint training authority.  Family scoring is gated
behind that authority check so the evaluation cohort can never be used to fit
rho or kappa.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import (  # noqa: E402
    _actual_for_pair,
    load_persisted_pairs,
)
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)


MILESTONE = "EXACT-DISTRIBUTION-FAMILY-SHADOW-BENCHMARK-1"
SCHEMA_VERSION = "exact_distribution_family_shadow_benchmark_1.v1"
FIXED_COHORT_COUNT = 107
MIN_TRAINING_UNIQUE_MATCHES = 2
DEFAULT_MANIFEST = ROOT / "artifacts" / "exact-distribution-family-shadow-benchmark-1" / "fixed_107_manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "exact-distribution-family-shadow-benchmark-1" / "summary.json"
DEFAULT_REPORT = ROOT / "artifacts" / "exact-distribution-family-shadow-benchmark-1" / "report.md"
AUTHORITY = {
    "repository": "gemini077/Memory-Hub",
    "path": "PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-POST-221-DISTRIBUTION-FAMILY-ROUTE-R2.md",
    "sha": "589dc62fbeedaf0cff8468495ec9bf8dff967a6b",
    "url": "https://github.com/gemini077/Memory-Hub/blob/main/PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-POST-221-DISTRIBUTION-FAMILY-ROUTE-R2.md",
}
FAMILIES = ("INDEPENDENT_POISSON", "DIXON_COLES", "SHARED_GAMMA_BIVARIATE_NB")
FINAL_RESULT_SCOPES = {"regulation_90m_plus_stoppage", "regulation_90m", "90m"}


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _canonical_manifest_rows(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return json.dumps(list(rows), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _manifest_row(pair: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: pair.get(key)
        for key in (
            "pair_id",
            "match_id",
            "match_key",
            "kickoff_at",
            "source_cutoff",
            "freeze_created_at",
            "frozen_input_digest",
            "input_snapshot_ref",
        )
    }


def _resolve_snapshot(pair: Mapping[str, Any]) -> Path | None:
    reference = str(pair.get("input_snapshot_ref") or "").strip()
    if not reference:
        return None
    path = Path(reference)
    return path if path.is_absolute() else ROOT / path


def _prematch_market_snapshot_status(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the existence of a legal pre-kickoff source snapshot.

    This does not reconstruct lambda or read a provider.  It only establishes
    whether the immutable local record could supply the accepted #189 input.
    """

    path = _resolve_snapshot(pair)
    if path is None:
        return {"status": "FAIL", "reason": "MISSING_INPUT_SNAPSHOT_REF"}
    if not path.is_file():
        return {"status": "FAIL", "reason": "MISSING_INPUT_SNAPSHOT_FILE", "path": _repo_relative(path)}
    try:
        document = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {"status": "FAIL", "reason": "INVALID_INPUT_SNAPSHOT", "path": _repo_relative(path)}
    input_document = document.get("input") if isinstance(document, Mapping) else None
    source_snapshots = input_document.get("source_snapshots") if isinstance(input_document, Mapping) else None
    if not isinstance(source_snapshots, Mapping) or not source_snapshots:
        return {"status": "FAIL", "reason": "NO_FROZEN_SOURCE_SNAPSHOT", "path": _repo_relative(path)}
    cutoff = _parse_datetime(pair.get("source_cutoff"))
    kickoff = _parse_datetime(pair.get("kickoff_at"))
    if cutoff is None or kickoff is None or cutoff >= kickoff:
        return {"status": "FAIL", "reason": "UNSAFE_PAIR_CHRONOLOGY", "path": _repo_relative(path)}
    legal_capture_count = 0
    missing_capture_timestamp = 0
    for source in source_snapshots.values():
        snapshots = source.get("snapshots") if isinstance(source, Mapping) else None
        for snapshot in snapshots or []:
            captured = _parse_datetime(snapshot.get("fetched_at") or snapshot.get("captured_at")) if isinstance(snapshot, Mapping) else None
            if captured is None:
                missing_capture_timestamp += 1
                continue
            if captured <= cutoff and captured < kickoff:
                legal_capture_count += 1
    if legal_capture_count == 0:
        return {
            "status": "FAIL",
            "reason": "NO_LEGAL_PREMATCH_SOURCE_CAPTURE",
            "path": _repo_relative(path),
            "missing_capture_timestamp": missing_capture_timestamp,
        }
    return {
        "status": "PASS",
        "path": _repo_relative(path),
        "legal_capture_count": legal_capture_count,
        "missing_capture_timestamp": missing_capture_timestamp,
    }


def _load_fixed_cohort(
    manifest_path: Path,
    pairs: Sequence[Mapping[str, Any]],
    result_map: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    manifest = _load_json(manifest_path)
    rows = manifest.get("rows") if isinstance(manifest, Mapping) else None
    failures: list[str] = []
    if not isinstance(rows, list) or len(rows) != FIXED_COHORT_COUNT:
        failures.append("fixed_manifest_count_not_107")
        rows = rows if isinstance(rows, list) else []
    pair_by_id = {str(pair.get("pair_id")): pair for pair in pairs if pair.get("pair_id")}
    current_rows: list[dict[str, Any]] = []
    match_ids: set[str] = set()
    for index, expected in enumerate(rows):
        if not isinstance(expected, Mapping):
            failures.append(f"fixed_manifest_row_{index}_invalid")
            continue
        pair_id = str(expected.get("pair_id") or "")
        pair = pair_by_id.get(pair_id)
        if pair is None:
            failures.append(f"fixed_pair_missing:{pair_id}")
            continue
        for key in ("match_id", "match_key", "kickoff_at", "source_cutoff", "freeze_created_at", "frozen_input_digest", "input_snapshot_ref"):
            if pair.get(key) != expected.get(key):
                failures.append(f"fixed_pair_manifest_mismatch:{pair_id}:{key}")
        if pair.get("pair_status") != "PAIRED":
            failures.append(f"fixed_pair_not_paired:{pair_id}")
        if pair.get("post_match_input_used_for_generation") is not False:
            failures.append(f"fixed_pair_post_match_input:{pair_id}")
        match_id = str(pair.get("match_id") or pair.get("match_key") or "")
        if not match_id or match_id in match_ids:
            failures.append(f"fixed_match_identity_not_unique:{pair_id}")
        match_ids.add(match_id)
        snapshot_status = _prematch_market_snapshot_status(pair)
        if snapshot_status.get("status") != "PASS":
            failures.append(f"fixed_market_snapshot:{pair_id}:{snapshot_status.get('reason')}")
        actual = _actual_for_pair(pair, result_map)
        if actual is None:
            failures.append(f"fixed_verified_result_missing:{pair_id}")
        current_rows.append({
            "pair_id": pair_id,
            "match_id": match_id,
            "kickoff_at": pair.get("kickoff_at"),
            "source_cutoff": pair.get("source_cutoff"),
            "actual_score": f"{actual[0]}-{actual[1]}" if actual is not None else None,
        })
    current_rows.sort(key=lambda row: (str(row.get("kickoff_at") or ""), str(row.get("pair_id") or "")))
    if len(current_rows) != FIXED_COHORT_COUNT:
        failures.append("fixed_cohort_not_107")
    if len({row["match_id"] for row in current_rows}) != len(current_rows):
        failures.append("fixed_cohort_duplicate_match_identity")
    actual_manifest_rows = [_manifest_row(pair_by_id[row["pair_id"]]) for row in rows if isinstance(row, Mapping) and row.get("pair_id") in pair_by_id]
    actual_digest = hashlib.sha256(_canonical_manifest_rows(actual_manifest_rows)).hexdigest()
    if actual_digest != manifest.get("cohort_digest_sha256"):
        failures.append("fixed_cohort_digest_mismatch")
    kickoffs = [_parse_datetime(row.get("kickoff_at")) for row in current_rows]
    kickoffs = [value for value in kickoffs if value is not None]
    return {
        "status": "PASS" if not failures else "FAIL",
        "requested_match_count": FIXED_COHORT_COUNT,
        "verified_match_count": len(current_rows),
        "unique_match_count": len({row["match_id"] for row in current_rows}),
        "earliest_kickoff": min(kickoffs).isoformat() if kickoffs else None,
        "latest_kickoff": max(kickoffs).isoformat() if kickoffs else None,
        "manifest": _repo_relative(manifest_path),
        "manifest_cohort_digest_sha256": manifest.get("cohort_digest_sha256"),
        "current_cohort_digest_sha256": actual_digest,
        "rows": current_rows,
        "failures": failures,
    }, failures


def _training_candidates(
    pairs: Sequence[Mapping[str, Any]],
    result_map: Mapping[str, Any],
    result_catalog: Mapping[str, Mapping[str, Any]],
    *,
    evaluation_earliest: datetime,
    evaluation_match_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    for pair in pairs:
        pair_id = str(pair.get("pair_id") or "")
        match_id = str(pair.get("match_id") or pair.get("match_key") or "")
        kickoff = _parse_datetime(pair.get("kickoff_at"))
        if kickoff is None or kickoff >= evaluation_earliest:
            continue
        if match_id in evaluation_match_ids:
            exclusions["EVALUATION_MATCH_OVERLAP"] += 1
            continue
        if pair.get("pair_status") != "PAIRED":
            exclusions["NOT_PAIRED"] += 1
            continue
        if pair.get("post_match_input_used_for_generation") is not False:
            exclusions["POST_MATCH_INPUT"] += 1
            continue
        eligibility = pair.get("freeze_eligibility") if isinstance(pair.get("freeze_eligibility"), Mapping) else {}
        if eligibility.get("formal_eligible") is not True or eligibility.get("model_formal_eligible") is not True:
            exclusions["NOT_FORMAL_PREMATCH_ROW"] += 1
            continue
        result = result_catalog.get(str(pair.get("match_key") or ""))
        if result is None or pair_id not in result_map:
            exclusions["NO_VERIFIED_RESULT"] += 1
            continue
        if result.get("scope") not in FINAL_RESULT_SCOPES:
            exclusions["NON_REGULATION_RESULT"] += 1
            continue
        verified_at = _parse_datetime(result.get("verified_at") or result.get("result_verified_at"))
        freeze_created = _parse_datetime(pair.get("freeze_created_at"))
        if verified_at is None or freeze_created is None or verified_at <= freeze_created:
            exclusions["RESULT_NOT_VERIFIED_AFTER_PREMATCH_ROW"] += 1
            continue
        snapshot_status = _prematch_market_snapshot_status(pair)
        if snapshot_status.get("status") != "PASS":
            exclusions[f"MARKET_SNAPSHOT:{snapshot_status.get('reason')}"] += 1
            continue
        candidates.append({
            "pair_id": pair_id,
            "match_id": match_id,
            "match_key": pair.get("match_key"),
            "kickoff_at": pair.get("kickoff_at"),
            "source_cutoff": pair.get("source_cutoff"),
            "promotion_eligible": pair.get("promotion_eligible"),
            "actual_score": _actual_for_pair(pair, result_map),
        })
    unique: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda row: (str(row.get("kickoff_at") or ""), str(row.get("source_cutoff") or ""), row["pair_id"])):
        unique.setdefault(candidate["match_id"], candidate)
    return list(unique.values()), dict(sorted(exclusions.items()))


def _empty_family_result(reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_EVALUATED",
        "reason": reason,
        "exact_nll": None,
        "exact_top1": None,
        "exact_top3": None,
        "mean_actual_probability": None,
        "actual_score_rank": None,
        "one_one_top1_share": None,
        "tail_support": None,
    }


def run_benchmark(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    pair_root: Path | None = None,
    result_root: Path | None = None,
) -> dict[str, Any]:
    pairs = load_persisted_pairs(pair_root or (ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"))
    catalog, discovery = discover_verified_results(result_root or (ROOT / "data" / "postmatch_automation" / "results"))
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    manifest = _load_json(manifest_path)
    manifest_ids = [str(row.get("pair_id") or "") for row in (manifest.get("rows") or []) if isinstance(row, Mapping)]
    fixed_pairs = [pair for pair in pairs if str(pair.get("pair_id") or "") in set(manifest_ids)]
    fixed_cohort, integrity_failures = _load_fixed_cohort(manifest_path, fixed_pairs, result_map)
    eval_match_ids = {row["match_id"] for row in fixed_cohort["rows"]}
    evaluation_earliest = _parse_datetime(fixed_cohort.get("earliest_kickoff"))
    evaluation_latest = _parse_datetime(fixed_cohort.get("latest_kickoff"))
    training_rows: list[dict[str, Any]] = []
    training_exclusions: dict[str, int] = {}
    if evaluation_earliest is not None:
        training_rows, training_exclusions = _training_candidates(
            pairs,
            result_map,
            catalog,
            evaluation_earliest=evaluation_earliest,
            evaluation_match_ids=eval_match_ids,
        )
    training_kickoffs = [_parse_datetime(row.get("kickoff_at")) for row in training_rows]
    training_kickoffs = [value for value in training_kickoffs if value is not None]
    training_sufficient = (
        not integrity_failures
        and len(training_rows) >= MIN_TRAINING_UNIQUE_MATCHES
        and bool(training_kickoffs)
        and all(value < evaluation_earliest for value in training_kickoffs)
        and not (eval_match_ids & {row["match_id"] for row in training_rows})
    ) if evaluation_earliest is not None else False
    training_status = "PASS" if training_sufficient else "FAIL_CLOSED_TRAINING_AUTHORITY"
    if integrity_failures:
        decision = "FAIL_CLOSED"
    elif not training_sufficient:
        decision = "FAIL_CLOSED_TRAINING_AUTHORITY"
    else:
        # This branch is intentionally not reachable for the current authority.
        # A future implementation must add the family math only after this gate.
        decision = "FAIL_CLOSED_TRAINING_AUTHORITY"
    not_evaluated_reason = "training_authority_not_proven_before_evaluation_cohort"
    family_results = {family: _empty_family_result(not_evaluated_reason) for family in FAMILIES}
    training_chronology = {
        "status": training_status,
        "evaluation_earliest_kickoff": fixed_cohort.get("earliest_kickoff"),
        "evaluation_latest_kickoff": fixed_cohort.get("latest_kickoff"),
        "training_earliest_kickoff": min(training_kickoffs).isoformat() if training_kickoffs else None,
        "training_latest_kickoff": max(training_kickoffs).isoformat() if training_kickoffs else None,
        "strictly_earlier_than_evaluation": bool(training_kickoffs) and evaluation_earliest is not None and all(value < evaluation_earliest for value in training_kickoffs),
        "evaluation_identity_overlap_unique_matches": len(eval_match_ids & {row["match_id"] for row in training_rows}),
        "candidate_pair_version_rows": sum(1 for pair in pairs if _parse_datetime(pair.get("kickoff_at")) is not None and evaluation_earliest is not None and _parse_datetime(pair.get("kickoff_at")) < evaluation_earliest),
        "training_unique_matches": len(training_rows),
        "minimum_required_unique_matches": MIN_TRAINING_UNIQUE_MATCHES,
        "training_exclusions": training_exclusions,
        "reason": None if training_sufficient else "no_sufficient_disjoint_pre_evaluation_training_authority_for_global_rho_kappa",
    }
    integrity_status = "PASS" if not integrity_failures else "FAIL_CLOSED"
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "integrity_status": integrity_status,
        "authority": AUTHORITY,
        "fixed_cohort": fixed_cohort,
        "training_unique_matches": len(training_rows),
        "training_chronology": training_chronology,
        "training_authority": {
            "status": training_status,
            "parameter_scope": "one global rho; one global kappa",
            "fit_on_evaluation_cohort": False,
            "scoring_attempted": False,
        },
        "families": family_results,
        "POISSON_EXACT_NLL": None,
        "DC_EXACT_NLL": None,
        "NB_EXACT_NLL": None,
        "DC_DELTA_CI": None,
        "NB_DELTA_CI": None,
        "BEST_SUPPORTED_FAMILY": None,
        "1X2_SAFETY": "NOT_EVALUATED_TRAINING_AUTHORITY",
        "source": {
            "pair_root": _repo_relative(pair_root or (ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs")),
            "result_root": _repo_relative(result_root or (ROOT / "data" / "postmatch_automation" / "results")),
            "network_calls": False,
            "new_data_source": False,
            "replay_or_backfill": False,
            "result_discovery": discovery,
            "result_matching": matching,
        },
        "integrity": {
            "status": integrity_status,
            "failures": integrity_failures,
            "fixed_cohort_only": True,
            "training_evaluation_identity_disjoint_checked": True,
        },
        "forbidden_actions_not_taken": [
            "C weight/rho/selector/calibration changes",
            "rho/kappa fitting on the 107 evaluation outcomes",
            "per-league or per-horizon tuning",
            "anti-1-1 or diversity heuristic",
            "new provider/source",
            "replay/backfill",
            "Champion/C/Market serving change",
            "UI or frozen history change",
            "automatic promotion",
        ],
    }


def _format(value: Any) -> str:
    return "NA" if value is None else str(value)


def render_report(evidence: Mapping[str, Any]) -> str:
    training = evidence["training_chronology"]
    fixed = evidence["fixed_cohort"]
    lines = [
        f"# {MILESTONE}",
        "",
        f"Decision: **`{evidence['decision']}`**",
        f"Integrity: **`{evidence['integrity_status']}`**",
        "",
        "## Fixed evaluation authority",
        "",
        f"- Accepted fixed cohort: `{fixed['verified_match_count']}/{fixed['requested_match_count']}` unique matches; manifest digest `{fixed['manifest_cohort_digest_sha256']}`.",
        f"- Evaluation chronology: `{fixed['earliest_kickoff']}` through `{fixed['latest_kickoff']}`.",
        f"- Fixed cohort validation: `{fixed['status']}`; failures: `{json.dumps(fixed['failures'], ensure_ascii=False)}`.",
        f"- Memory-Hub authority: [{AUTHORITY['path']}]({AUTHORITY['url']}) (blob SHA `{AUTHORITY['sha']}`).",
        "- Accepted #189 Market lambda was not recomputed or changed; no family scoring was attempted before training authority passed.",
        "",
        "## Training authority",
        "",
        f"- Candidate historical pair-version rows strictly earlier than the earliest evaluation kickoff: `{training['candidate_pair_version_rows']}`.",
        f"- Legal, verified, disjoint training unique matches: `{training['training_unique_matches']}`; minimum necessary global-parameter count: `{training['minimum_required_unique_matches']}`.",
        f"- Training chronology: `{training['training_earliest_kickoff']}` to `{training['training_latest_kickoff']}`; strictly earlier: `{training['strictly_earlier_than_evaluation']}`; identity overlap: `{training['evaluation_identity_overlap_unique_matches']}`.",
        f"- Training status: **`{training['status']}`** — `{training['reason']}`.",
        "- No rho/kappa was fit on the 107 evaluation outcomes. The family benchmark stops before scoring.",
        "",
        "## Family results",
        "",
        "All Exact, bootstrap, stability, distribution-shape, and 1X2 safety metrics are `NOT_EVALUATED_TRAINING_AUTHORITY`.",
        "",
        "- `POISSON_EXACT_NLL`: `NA`.",
        "- `DC_EXACT_NLL`: `NA`.",
        "- `NB_EXACT_NLL`: `NA`.",
        "- `DC_DELTA_CI`: `NA`.",
        "- `NB_DELTA_CI`: `NA`.",
        "- `BEST_SUPPORTED_FAMILY`: `NA`.",
        "- `1X2_SAFETY`: `NOT_EVALUATED_TRAINING_AUTHORITY`.",
        "",
        "## Stop state",
        "",
        "- Research-only artifact; no model, parameter, selector, serving, UI, or historical-data change.",
        "- No merge and no automatic promotion.",
        "- STOP: obtain a separate, strictly earlier, legally frozen and sufficiently sized training authority before rerunning.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--write", action="store_true", help="write research-only summary and report")
    args = parser.parse_args(argv)
    evidence = run_benchmark(manifest_path=args.manifest)
    if args.write:
        _write_json(args.output, evidence)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(evidence), encoding="utf-8")
    print(json.dumps({
        "milestone": evidence["milestone"],
        "decision": evidence["decision"],
        "training_unique_matches": evidence["training_unique_matches"],
        "integrity_status": evidence["integrity_status"],
        "written": bool(args.write),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["decision"] == "FAIL_CLOSED_TRAINING_AUTHORITY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
