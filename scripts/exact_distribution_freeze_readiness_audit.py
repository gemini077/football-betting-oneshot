#!/usr/bin/env python3
"""Bounded, offline audit for the prediction-time Exact distribution freeze."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from exact_distribution import JC_HANDICAP_SELECTION_ORDER, JC_TOTAL_GOALS_BUCKET_ORDER
from official_jc_handicap import build_official_jc_handicap_state


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "exact_distribution" / "current_model_input.json"
JC_HANDICAP_SOURCE_FIXTURE = ROOT / "tests" / "fixtures" / "jc_handicap" / "official_source_audit.json"
PREDICTION_ROOT = ROOT / "data" / "model_governance" / "predictions"
AUDIT_CONTRACT_VERSION = "exact_distribution_freeze_readiness.v1"
DECISION_READY = "EXACT_DISTRIBUTION_FREEZE_READY"
DECISION_PARTIAL = "EXACT_DISTRIBUTION_FREEZE_PARTIAL"
DECISION_FAIL_CLOSED = "FAIL_CLOSED"
HISTORICAL_PREFIXES = (
    "data/model_governance/predictions/",
    "data/model_governance/input_snapshots/",
    "data/prospective/",
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _audit_official_source_fixture() -> dict[str, Any]:
    document = _load_json(JC_HANDICAP_SOURCE_FIXTURE) or {}
    audit = document.get("audit") if isinstance(document.get("audit"), dict) else {}
    calculator = audit.get("official_calculator_probe") if isinstance(audit.get("official_calculator_probe"), dict) else {}
    request = audit.get("request_contract") if isinstance(audit.get("request_contract"), dict) else {}
    response_hash = str(calculator.get("response_sha256") or "").casefold()
    return {
        "fixture_present": bool(document),
        "current_source_status": audit.get("current_source_status"),
        "request_url": request.get("url"),
        "request_params": request.get("params"),
        "http_status": calculator.get("http_status"),
        "response_sha256_present": len(response_hash) == 64
        and all(character in "0123456789abcdef" for character in response_hash),
        "official_rows_returned": audit.get("official_rows_returned", 0),
        "hhad_line_available": audit.get("hhad_line_available", 0),
        "hhad_three_prices_available": audit.get("hhad_three_prices_available", 0),
        "binding_funnel": audit.get("binding_funnel") or {},
        "delivery_decision": audit.get("delivery_decision"),
        "parser_source_field": (audit.get("parser_contract") or {}).get("source_field"),
    }


def _git(root: Path, *args: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def _historical_rewrite_count() -> tuple[int, list[str]]:
    changed = set(_git(ROOT, "diff", "--name-only"))
    changed.update(_git(ROOT, "diff", "--cached", "--name-only"))
    base = _git(ROOT, "rev-parse", "origin/main")
    if base:
        changed.update(_git(ROOT, "diff", "--name-only", f"{base[0]}...HEAD"))
    historical = sorted(
        path for path in changed if any(path.startswith(prefix) for prefix in HISTORICAL_PREFIXES)
    )
    return len(historical), historical


def _audit_legacy_records(limit: int) -> dict[str, Any]:
    files = sorted(
        PREDICTION_ROOT.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    selected = files if limit <= 0 else files[:limit]
    authoritative = 0
    formal_champion = 0
    unreadable = 0
    for path in selected:
        record = _load_json(path)
        if record is None:
            unreadable += 1
            continue
        is_formal_champion = (
            record.get("model_role") == "champion"
            and record.get("model_formal_eligible") is True
            and record.get("formal_eligible") is True
        )
        formal_champion += int(is_formal_champion)
        if isinstance(record.get("exact_score_distribution"), dict):
            authoritative += 1
    return {
        "records_available": len(files),
        "records_scanned": len(selected),
        "formal_champion_records_scanned": formal_champion,
        "authoritative_exact_distribution_records_scanned": authoritative,
        "missing_formal_exact_authority_records_scanned": max(0, formal_champion - authoritative),
        "unreadable_records_scanned": unreadable,
        "formal_historical_full_support_truth": False,
        "historical_exact_metrics_scope": "RESEARCH_RECONSTRUCTED",
        "historical_rewrite_count": 0,
    }


def _probe_current_capture() -> dict[str, Any]:
    from automatic_model_core import build_automatic_model
    from exact_distribution import (
        EXACT_DISTRIBUTION_CELL_COUNT,
        EXACT_DISTRIBUTION_CONTRACT_VERSION,
        JC_TOTAL_GOALS_BUCKET_ORDER,
        JC_HANDICAP_SELECTION_ORDER,
        build_exact_distribution_contract,
        classify_frozen_exact_score,
        classify_frozen_jc_handicap,
        classify_frozen_jc_total_goals,
        validate_exact_distribution_contract,
    )

    context = _load_json(FIXTURE) or {}
    result = build_automatic_model(context, include_exact_distribution=True)
    model = result.get("model") if isinstance(result, dict) else None
    state = result.get("exact_distribution_state") if isinstance(result, dict) else None
    if not isinstance(model, dict) or not isinstance(state, dict):
        return {
            "capture_contract_valid": False,
            "failure": "current fixture did not produce an exact distribution state",
        }
    identity = {
        "prediction_id": "AUDIT-PROBE",
        "model_role": "champion",
        "model_family": model.get("method"),
        "model_core_version": model.get("method"),
        "release_version": "audit-probe",
        "model_source_fingerprint": "audit-probe",
        "model_run_fingerprint": "audit-probe",
        "input_sha256": "audit-probe",
    }
    selected = context.get("selected_workspace_match") or {}
    official_source = {
        "source": "sporttery.cn",
        "url": "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu",
        "business_date": "2026-09-05",
        "fetch_time": "2026-09-05T12:30:00+08:00",
        "success": True,
        "payload_success": True,
        "http_status": 200,
        "response_bytes": 1024,
        "raw_response_sha256": "b" * 64,
        "request_contract": {
            "method": "GET",
            "url": "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu",
            "params": {"channel": "c", "poolCode": "had,hhad,crs,ttg,hafu"},
            "required_headers": [
                "Accept",
                "Accept-Encoding",
                "Accept-Language",
                "Origin",
                "Referer",
                "User-Agent",
                "X-Requested-With",
            ],
            "source_surface": "https://m.sporttery.cn/mjc/jsq/zqspf/",
        },
        "matches": [{
            "matchId": str(context.get("request", {}).get("match_id") or "AUDIT-JC-001"),
            "matchNum": "AUDIT-JC-001",
            "businessDate": "2026-09-05",
            "homeTeam": selected.get("home"),
            "awayTeam": selected.get("away"),
            "matchDate": "2026-09-05",
            "matchTime": "16:00:00",
            "rqspf": {"handicap": -1, "home": 2.8, "draw": 3.4, "away": 2.2},
        }],
    }
    official_state = build_official_jc_handicap_state(
        official_source,
        {
            "match_id": str(context.get("request", {}).get("match_id") or "AUDIT-JC-001"),
            "match_num": "AUDIT-JC-001",
            "home": selected.get("home"),
            "away": selected.get("away"),
            "kickoff_local": "2026-09-05T16:00:00+08:00",
        },
        source_ref="audit://sporttery.cn/rqspf",
    )
    try:
        contract = build_exact_distribution_contract(
            state,
            model_identity=identity,
            official_jc_handicap_state=official_state,
        )
        validate_exact_distribution_contract(contract, expected_model_identity=identity)
    except ValueError as error:
        return {"capture_contract_valid": False, "failure": str(error)}
    cells = contract["cells"]
    tail_status = (contract.get("tail_diagnostic") or {}).get("status")
    probe_record = {**identity, "exact_score_distribution": contract}
    in_grid = classify_frozen_exact_score(probe_record, 0, 0)
    out_of_grid = classify_frozen_exact_score(probe_record, 13, 0)
    jc_six = classify_frozen_jc_total_goals(probe_record, 3, 3)
    jc_seven = classify_frozen_jc_total_goals(probe_record, 4, 3)
    jc_high_score = classify_frozen_jc_total_goals(probe_record, 13, 0)
    jc_handicap_home = classify_frozen_jc_handicap(probe_record, 2, 0)
    jc_handicap_draw = classify_frozen_jc_handicap(probe_record, 1, 0)
    jc_handicap_away = classify_frozen_jc_handicap(probe_record, 0, 0)
    jc_contract = contract.get("jc_total_goals") or {}
    jc_handicap_contract = contract.get("jc_handicap") or {}
    cell_by_score = {
        (cell["home_goals"], cell["away_goals"]): cell["probability"]
        for cell in cells
    }
    top_rows = model.get("score_probabilities") or []
    top_parity = all(
        isinstance(row, dict)
        and "-" in str(row.get("score") or "")
        and _rounded_probability(
            cell_by_score.get(tuple(int(part) for part in str(row["score"]).split("-", 1)))
        )
        == _rounded_probability(row.get("probability"))
        for row in top_rows[:5]
    )
    return {
        "capture_contract_valid": True,
        "contract_version": EXACT_DISTRIBUTION_CONTRACT_VERSION,
        "model_family": model.get("method"),
        "effective_matrix_cell_count": len(cells),
        "expected_frozen_cell_count": EXACT_DISTRIBUTION_CELL_COUNT,
        "max_home_goals": (contract.get("score_space") or {}).get("max_home_goals"),
        "max_away_goals": (contract.get("score_space") or {}).get("max_away_goals"),
        "finite_normalized_grid": (contract.get("score_space") or {}).get("representation") == "FINITE_NORMALIZED_GRID",
        "full_support": (contract.get("score_space") or {}).get("full_support"),
        "tail_diagnostic_status": tail_status,
        "formal_exact_log_score_on_frozen_cell": in_grid["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"],
        "out_of_support_fail_closed": (
            out_of_grid["OUT_OF_EXPLICIT_SUPPORT"]
            and not out_of_grid["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"]
            and out_of_grid["probability"] is None
        ),
        "top1_to_top5_parity": top_parity,
        "out_of_explicit_support_policy": (contract.get("score_space") or {}).get("out_of_support_policy"),
        "production_path": state.get("production_path"),
        "content_sha256": contract.get("content_sha256"),
        "jc_total_goals_formal_truth": jc_six["FORMAL_JC_TOTAL_GOALS_FROZEN"] and jc_high_score[
            "FORMAL_JC_TOTAL_GOALS_FROZEN"
        ],
        "jc_total_goals_order": jc_contract.get("selection_order"),
        "jc_total_goals_normalization": (jc_contract.get("normalization") or {}).get("status"),
        "same_time_official_market_baseline_status": (
            jc_contract.get("same_time_official_market_baseline") or {}
        ).get("status"),
        "jc_total_goals_boundary_6": jc_six["actual_jc_total_goals_bucket"],
        "jc_total_goals_boundary_7": jc_seven["actual_jc_total_goals_bucket"],
        "jc_total_goals_high_score": jc_high_score["actual_jc_total_goals_bucket"],
        "jc_handicap_formal_truth": (
            jc_handicap_home["FORMAL_JC_HANDICAP_FROZEN"]
            and jc_handicap_draw["FORMAL_JC_HANDICAP_FROZEN"]
            and jc_handicap_away["FORMAL_JC_HANDICAP_FROZEN"]
        ),
        "jc_handicap_order": jc_handicap_contract.get("selection_order"),
        "jc_handicap_line": jc_handicap_contract.get("handicap_line"),
        "jc_handicap_normalization": (jc_handicap_contract.get("normalization") or {}).get("status"),
        "same_time_official_handicap_market_baseline_status": (
            jc_handicap_contract.get("same_time_official_market_baseline") or {}
        ).get("status"),
        "jc_handicap_source_provider": (
            jc_handicap_contract.get("source_authority") or {}
        ).get("provider"),
        "jc_handicap_not_asian_handicap": (
            jc_handicap_contract.get("line_semantics") or {}
        ).get("not_asian_handicap"),
    }


def _rounded_probability(value: Any) -> float | None:
    """Match the model's six-decimal display rows without changing the state."""

    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def audit(limit: int = 200) -> dict[str, Any]:
    legacy = _audit_legacy_records(limit)
    probe = _probe_current_capture()
    source_authority = _audit_official_source_fixture()
    historical_rewrite_count, changed_historical_files = _historical_rewrite_count()
    legacy["historical_rewrite_count"] = historical_rewrite_count
    if (
        historical_rewrite_count
        or not probe.get("capture_contract_valid")
        or not probe.get("formal_exact_log_score_on_frozen_cell")
        or not probe.get("out_of_support_fail_closed")
        or not probe.get("top1_to_top5_parity")
        or not probe.get("jc_total_goals_formal_truth")
        or probe.get("jc_total_goals_order") != list(JC_TOTAL_GOALS_BUCKET_ORDER)
        or probe.get("jc_total_goals_normalization") != "NORMALIZED_FROM_FROZEN_EXACT_DISTRIBUTION"
        or probe.get("same_time_official_market_baseline_status") != "NOT_AVAILABLE"
        or probe.get("jc_total_goals_boundary_6") != "6"
        or probe.get("jc_total_goals_boundary_7") != "7+"
        or probe.get("jc_total_goals_high_score") != "7+"
        or not probe.get("jc_handicap_formal_truth")
        or probe.get("jc_handicap_order") != list(JC_HANDICAP_SELECTION_ORDER)
        or probe.get("jc_handicap_line") != -1
        or probe.get("jc_handicap_normalization") != "NORMALIZED_FROM_FROZEN_EFFECTIVE_EXACT_DISTRIBUTION"
        or probe.get("same_time_official_handicap_market_baseline_status") != "AVAILABLE"
        or probe.get("jc_handicap_source_provider") != "sporttery.cn"
        or probe.get("jc_handicap_not_asian_handicap") is not True
        or source_authority.get("current_source_status") != "AVAILABLE"
        or source_authority.get("request_url")
        != "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu"
        or source_authority.get("request_params")
        != {"channel": "c", "poolCode": "had,hhad,crs,ttg,hafu"}
        or source_authority.get("http_status") != 200
        or not source_authority.get("response_sha256_present")
        or not source_authority.get("official_rows_returned")
        or not source_authority.get("hhad_line_available")
        or not source_authority.get("hhad_three_prices_available")
        or source_authority.get("delivery_decision") != "JC_HANDICAP_FORMAL_TRUTH_READY"
        or (source_authority.get("binding_funnel") or {}).get("exact_bound")
        != (source_authority.get("binding_funnel") or {}).get("jc_fixtures")
        or (source_authority.get("binding_funnel") or {}).get("ambiguous")
        or (source_authority.get("binding_funnel") or {}).get("unmatched")
        or source_authority.get("parser_source_field") != "hhad.goalLine"
    ):
        decision = DECISION_FAIL_CLOSED
    elif probe.get("tail_diagnostic_status") != "EXACT_TAIL_RESOLVED":
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_READY
    return {
        "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "network_used": False,
        "read_scope": [
            "data/model_governance/predictions/*.json (bounded latest sample)",
            "tests/fixtures/exact_distribution/current_model_input.json",
            "scripts/automatic_model_core.py effective matrix capture",
            "scripts/exact_distribution.py frozen JC total-goals projection",
            "scripts/official_jc_handicap.py exact Sporttery RQSPF binding",
            "scripts/official_jc_handicap_source_audit.py bounded current source evidence",
            "tests/fixtures/jc_handicap/official_source_audit.json parser/source evidence",
            "scripts/exact_distribution.py frozen JC handicap projection",
        ],
        "LEGACY_RECONSTRUCTION_COVERAGE": legacy,
        "PROSPECTIVE_CAPTURE_CAPABILITY": probe,
        "OFFICIAL_JC_HANDICAP_SOURCE_AUTHORITY": source_authority,
        "historical_rewrite_count": historical_rewrite_count,
        "changed_historical_files": changed_historical_files,
        "readiness_decision": decision,
        "decision_rule": "FAIL_CLOSED on capture/rewrite failure; PARTIAL when immutable finite grid is valid but exact infinite-support tail remains unresolved; READY only when both are resolved.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200, help="latest frozen records to inspect; 0 means all")
    parser.add_argument("--output", type=Path, help="optional JSON output outside data stores")
    args = parser.parse_args()
    result = audit(args.limit)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
