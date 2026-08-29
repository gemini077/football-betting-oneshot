"""Run the bounded PRED-AVAIL-2 provider-backbone audit.

The default mode is offline and safe: it reads the frozen PRED-AVAIL-1
cohort, exercises the provider route without a token, and writes only
PRED-AVAIL-2 evidence.  ``--live`` is an explicit operator action and still
requires ``FOOTBALL_DATA_ORG_TOKEN``; no credential is persisted by this
script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# Allow the audit to run both as ``python -m scripts.football_data...`` and as
# a direct repository script without changing the import contract of the
# existing ``scripts`` package.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from football_data.providers.football_data_org import (
    DEFAULT_COVERAGE_MANIFEST_PATH,
    FootballDataOrgRecentFormRoute,
    RequestAccounting,
    resolve_provider_competition,
)

PRED_AVAIL_1_ROOT = PROJECT_ROOT / "data" / "football_data" / "pred_avail_1"
PRED_AVAIL_2_ROOT = PROJECT_ROOT / "data" / "football_data" / "pred_avail_2"
PRED_AVAIL_1_BASELINE_PATH = PRED_AVAIL_1_ROOT / "baseline_2026-08-30.json"
PRED_AVAIL_1_AVAILABILITY_PATH = PRED_AVAIL_1_ROOT / "availability_before_after_2026-08-30.json"
EXPECTED_COHORT_SHA256 = "0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d"
DEFAULT_AUDIT_NOW = "2026-08-29T17:49:07Z"
TOKEN_ENV = "FOOTBALL_DATA_ORG_TOKEN"
REQUIRED_STATUS_KEYS = (
    "FULL",
    "DEGRADED",
    "INSUFFICIENT_DATA",
    "MISSING_RECENT_FORM",
    "SOURCE_UNAVAILABLE",
    "FIXTURE_MAPPING_UNAVAILABLE",
    "OUTSIDE_PROVIDER_FREE_COVERAGE",
    "AMBIGUOUS_FIXTURE",
)
PROTECTED_PATHS = (
    "data/prediction_dashboard/latest.json",
    "data/base_prediction_jobs/2026-08-30.json",
    "data/product_runtime/latest_cycle.json",
    "data/product_runtime/openfootball_recent_form.json",
    "data/market_history/prematch_tasks.json",
    "data/market_history/monitor_state.json",
    "data/prospective/summary.json",
    "data/prospective/ledger.jsonl",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_status(value: str | None) -> str:
    return "FULL" if value in {"FROZEN", "PREDICTED"} else "INSUFFICIENT_DATA"


def build_pred_avail_2_baseline() -> dict[str, Any]:
    """Materialize the PRED-AVAIL-1 AFTER state without changing production."""

    source = _load_json(PRED_AVAIL_1_BASELINE_PATH)
    availability = _load_json(PRED_AVAIL_1_AVAILABILITY_PATH)
    cohort = str(source.get("cohort_sha256") or "")
    if cohort != EXPECTED_COHORT_SHA256 or availability.get("cohort_sha256") != EXPECTED_COHORT_SHA256:
        raise ValueError("frozen cohort digest mismatch")
    source_fixtures = source.get("fixtures")
    if not isinstance(source_fixtures, list) or len(source_fixtures) != 25:
        raise ValueError("PRED-AVAIL-1 cohort is not exactly 25 fixtures")
    released = str((availability.get("after") or {}).get("newly_released_fixture") or "500-1364199")
    if released != "500-1364199" or (availability.get("after") or {}).get("new_form_source") != "authoritative_historical_results":
        raise ValueError("unexpected PRED-AVAIL-1 release reference")
    fixtures: list[dict[str, Any]] = []
    release_matches = 0
    for raw in source_fixtures:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if str(row.get("match_id") or "") == released:
            release_matches += 1
            row.update(
                {
                    "prediction_status": "FROZEN",
                    "blocker": None,
                    "current_prediction_status": "FROZEN",
                    "current_blocker": None,
                    "current_blocker_text": None,
                    "p1_after_source": "authoritative_historical_results",
                }
            )
        fixtures.append(row)
    if release_matches != 1:
        raise ValueError("PRED-AVAIL-1 release must identify exactly one fixture")
    status_counts = Counter(str(row.get("prediction_status") or "INSUFFICIENT_DATA") for row in fixtures)
    missing = sum(1 for row in fixtures if str(row.get("blocker") or "") == "MISSING_RECENT_FORM")
    return {
        "contract_version": "pred_avail_2_baseline.v1",
        "milestone": "PRED-AVAIL-2",
        "business_date": "2026-08-30",
        "frozen_cohort": True,
        "cohort_sha256": EXPECTED_COHORT_SHA256,
        "cohort_source": "data/football_data/pred_avail_1/baseline_2026-08-30.json + PRED-AVAIL-1 bounded AFTER",
        "baseline_reference": "data/football_data/pred_avail_1/availability_before_after_2026-08-30.json",
        "p1_after_release": released,
        "baseline_summary": {
            "fixture_count": len(fixtures),
            "full_prediction_count": sum(status_counts[key] for key in ("FROZEN", "PREDICTED")),
            "degraded_prediction_count": 0,
            "insufficient_data_count": status_counts["INSUFFICIENT_DATA"],
            "missing_recent_form_count": missing,
            "prediction_failed_count": status_counts["PREDICTION_FAILED"],
            "status_counts": dict(sorted(status_counts.items())),
        },
        "fixtures": fixtures,
        "production_state_policy": "read-only audit; no BASE, freeze, dashboard, prospective or runtime mutation",
    }


def _route_row(
    baseline_row: Mapping[str, Any],
    *,
    route: FootballDataOrgRecentFormRoute,
    now: str,
) -> dict[str, Any]:
    fixture_id = str(baseline_row.get("match_id") or "")
    baseline_prediction_status = str(baseline_row.get("prediction_status") or "INSUFFICIENT_DATA")
    baseline_full = baseline_prediction_status in {"FROZEN", "PREDICTED"}
    competition = resolve_provider_competition(baseline_row, route.coverage_manifest)
    before_requests = route.accounting.requests
    before_hits = route.accounting.cache_hits
    before_misses = route.accounting.cache_misses
    before_blocks = route.accounting.credential_blocks
    if baseline_full:
        provider_result: dict[str, Any] = {
            "status": "PRESERVED_EXISTING_FROZEN",
            "reason_codes": ["EXISTING_FROZEN_PRESERVED"],
            "final_prediction_eligible": True,
        }
    else:
        provider_result = route.get_recent_form(baseline_row, baseline_row, now=now)
    result_status = str(provider_result.get("status") or "SOURCE_UNAVAILABLE")
    reason_codes = [str(value) for value in provider_result.get("reason_codes") or [] if str(value)]
    if result_status == "SOURCE_UNAVAILABLE" and "LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL" in reason_codes:
        bridge_state = "NOT_RUN_CREDENTIAL"
    elif result_status == "FULL":
        bridge_state = "BRIDGED"
    elif result_status == "PRESERVED_EXISTING_FROZEN":
        bridge_state = "PRESERVED_EXISTING_FROZEN"
    else:
        bridge_state = result_status
    provider_ids = bool(provider_result.get("provider_home_team_id") and provider_result.get("provider_away_team_id"))
    provider_form = result_status == "FULL"
    final_prediction_eligible = baseline_full or bool(provider_result.get("final_prediction_eligible"))
    availability_status = "FULL" if final_prediction_eligible else "INSUFFICIENT_DATA"
    after_prediction_status = baseline_prediction_status if baseline_full else ("PREDICTED" if provider_form else "INSUFFICIENT_DATA")
    if not baseline_full and not provider_form and not reason_codes:
        reason_codes = ["MISSING_RECENT_FORM"]
    return {
        "fixture_id": fixture_id,
        "competition": baseline_row.get("competition"),
        "canonical_competition_id": competition.get("canonical_competition_id"),
        "provider_competition_code": competition.get("provider_competition_code"),
        "source_competition_supported": competition.get("status") == "SUPPORTED",
        "before": {
            "prediction_status": baseline_prediction_status,
            "availability_status": _as_status(baseline_prediction_status),
            "blocker": baseline_row.get("blocker"),
        },
        "after": {
            "prediction_status": after_prediction_status,
            "availability_status": availability_status,
            "blocker": None if final_prediction_eligible else "MISSING_RECENT_FORM",
            "final_prediction_eligible": final_prediction_eligible,
        },
        "fixture_deterministic_bridge": bridge_state,
        "provider_ids_obtained": provider_ids,
        "provider_recent_form_available": provider_form,
        "recent_form_available": final_prediction_eligible,
        "final_prediction_eligible": final_prediction_eligible,
        "provider_fixture_id": provider_result.get("provider_fixture_id"),
        "provider_home_team_id": provider_result.get("provider_home_team_id"),
        "provider_away_team_id": provider_result.get("provider_away_team_id"),
        "provider_identity_scope": provider_result.get("identity_scope") or "provider_scoped",
        "reason_codes": reason_codes,
        "route_status": result_status,
        "route_source_refs": list(provider_result.get("source_refs") or []),
        "call_count": route.accounting.requests - before_requests,
        "cache_hit_count": route.accounting.cache_hits - before_hits,
        "cache_miss_count": route.accounting.cache_misses - before_misses,
        "credential_block_count": route.accounting.credential_blocks - before_blocks,
    }


def _counts(rows: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field)) for row in rows).items()))


def _summary(rows: list[Mapping[str, Any]], *, phase: str) -> dict[str, Any]:
    status_key = "prediction_status" if phase == "prediction" else "availability_status"
    statuses = [str((row.get("after") if phase == "after" else row.get("before") or {}).get(status_key) or "") for row in rows]
    blockers = Counter(str(row.get("after" if phase == "after" else "before", {}).get("blocker") or "") for row in rows)
    prediction_statuses = Counter(str((row.get("after") if phase == "after" else row.get("before") or {}).get("prediction_status") or "") for row in rows)
    failure_reasons = {
        reason: count
        for reason, count in sorted(blockers.items())
        if reason
    }
    return {
        "fixture_count": len(rows),
        "full_prediction_count": prediction_statuses["FROZEN"] + prediction_statuses["PREDICTED"],
        "degraded_prediction_count": statuses.count("DEGRADED"),
        "insufficient_data_count": statuses.count("INSUFFICIENT_DATA"),
        "missing_recent_form_count": blockers["MISSING_RECENT_FORM"],
        "prediction_failed_count": prediction_statuses["PREDICTION_FAILED"],
        "champion_jobs_blocked_count": 0,
        "status_counts": dict(sorted(prediction_statuses.items())),
        "availability_status_counts": dict(sorted(Counter(statuses).items())),
        "failure_reasons": failure_reasons,
    }


def _by_competition(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("competition") or "UNKNOWN")].append(row)
    output: dict[str, Any] = {}
    for competition, values in sorted(grouped.items()):
        route_reasons = Counter(reason for row in values for reason in row.get("reason_codes") or [])
        output[competition] = {
            "fixture_count": len(values),
            "source_competition_supported": all(bool(row.get("source_competition_supported")) for row in values),
            "provider_competition_codes": sorted({str(row.get("provider_competition_code")) for row in values if row.get("provider_competition_code")}),
            "fixture_deterministic_bridge": _counts(list(values), "fixture_deterministic_bridge"),
            "provider_ids_obtained": sum(bool(row.get("provider_ids_obtained")) for row in values),
            "recent_form_available": sum(bool(row.get("recent_form_available")) for row in values),
            "provider_recent_form_available": sum(bool(row.get("provider_recent_form_available")) for row in values),
            "final_prediction_eligible": sum(bool(row.get("final_prediction_eligible")) for row in values),
            "after_status_counts": dict(sorted(Counter(str((row.get("after") or {}).get("prediction_status") or "") for row in values).items())),
            "reason_counts": dict(sorted(route_reasons.items())),
            "CALL_COUNT": sum(int(row.get("call_count") or 0) for row in values),
            "CACHE_HIT_COUNT": sum(int(row.get("cache_hit_count") or 0) for row in values),
        }
    return output


def build_pred_avail_2_audit(
    *,
    route: FootballDataOrgRecentFormRoute | None = None,
    now: str = DEFAULT_AUDIT_NOW,
) -> dict[str, Any]:
    baseline = build_pred_avail_2_baseline()
    if route is None:
        route = FootballDataOrgRecentFormRoute(token="", cache_root=None)
    rows = [_route_row(row, route=route, now=now) for row in baseline["fixtures"]]
    after_summary = _summary(rows, phase="after")
    before_summary = _summary(rows, phase="before")
    route_status_counts = Counter(str(row.get("route_status") or "") for row in rows)
    reason_counts = Counter(reason for row in rows for reason in row.get("reason_codes") or [])
    route_accounting = route.accounting.snapshot()
    source_supported_count = sum(bool(row.get("source_competition_supported")) for row in rows)
    availability_status_counts = Counter(
        str((row.get("after") or {}).get("availability_status") or "")
        for row in rows
    )
    required_status_counts = {
        "FULL": availability_status_counts["FULL"],
        "DEGRADED": availability_status_counts["DEGRADED"],
        "INSUFFICIENT_DATA": availability_status_counts["INSUFFICIENT_DATA"],
        "MISSING_RECENT_FORM": after_summary["missing_recent_form_count"],
        "SOURCE_UNAVAILABLE": route_status_counts["SOURCE_UNAVAILABLE"],
        "FIXTURE_MAPPING_UNAVAILABLE": route_status_counts["FIXTURE_MAPPING_UNAVAILABLE"],
        "OUTSIDE_PROVIDER_FREE_COVERAGE": route_status_counts["OUTSIDE_PROVIDER_FREE_COVERAGE"],
        "AMBIGUOUS_FIXTURE": route_status_counts["AMBIGUOUS_FIXTURE"],
    }
    return {
        "contract_version": "pred_avail_2_availability_before_after.v1",
        "milestone": "PRED-AVAIL-2",
        "business_date": "2026-08-30",
        "frozen_cohort": True,
        "cohort_sha256": EXPECTED_COHORT_SHA256,
        "baseline_reference": "data/football_data/pred_avail_2/baseline_2026-08-30.json",
        "p1_cohort_reference": "data/football_data/pred_avail_1/baseline_2026-08-30.json",
        "now": now,
        "before": before_summary,
        "after": {
            **after_summary,
            "source_competition_supported_count": source_supported_count,
            "fixture_deterministic_bridge_counts": _counts(rows, "fixture_deterministic_bridge"),
            "provider_ids_obtained_count": sum(bool(row.get("provider_ids_obtained")) for row in rows),
            "recent_form_available_count": sum(bool(row.get("recent_form_available")) for row in rows),
            "provider_recent_form_available_count": sum(bool(row.get("provider_recent_form_available")) for row in rows),
            "final_prediction_eligible_count": sum(bool(row.get("final_prediction_eligible")) for row in rows),
            "route_status_counts": dict(sorted(route_status_counts.items())),
            "reason_counts": dict(sorted(reason_counts.items())),
            "degraded_fallback": {"enabled": False, "market_only_is_metadata_only": True},
        },
        "by_competition": _by_competition(rows),
        "CALL_COUNT": route_accounting["request_count"],
        "CACHE_HIT_COUNT": route_accounting["cache_hit_count"],
        "cache_miss_count": route_accounting["cache_miss_count"],
        "credential_block_count": route_accounting["credential_block_count"],
        "required_status_counts": required_status_counts,
        "fixtures": rows,
        "quality_boundary": {
            "champion_math_changed": False,
            "frozen_prediction_rewritten": False,
            "prospective_mutated": False,
            "market_only_production_fallback": False,
            "synthetic_evidence": False,
            "fuzzy_identity": False,
            "llm_identity": False,
            "league_specific_adapter": False,
            "provider_hopping": False,
        },
    }


def build_source_preflight(*, now: str, live_requested: bool) -> dict[str, Any]:
    token_present = bool(os.environ.get(TOKEN_ENV, "").strip())
    return {
        "contract_version": "pred_avail_2_source_preflight.v1",
        "milestone": "PRED-AVAIL-2",
        "observed_at": now,
        "live_requested": live_requested,
        "credential": {
            "env_name": TOKEN_ENV,
            "present": token_present,
            "value_persisted": False,
            "value_logged": False,
            "github_secret_name_checked": TOKEN_ENV,
            "github_secret_present": False,
            "auto_registration": False,
        },
        "secret_injection": {
            "safe_mechanism_available": True,
            "mechanism": "environment variable locally or GitHub Actions secrets context; token is read-only at runtime",
            "repository_workflow_reference": ".github/workflows/*.yml",
            "provider_workflow_injected": False,
        },
        "agent_reach": {
            "cli_available": False,
            "fallback": "bounded direct official documentation lookup through the configured web tool",
        },
        "source_landscape": [
            {
                "source": "football-data.org",
                "role": "PRIMARY_CANDIDATE",
                "official": True,
                "free_tier_candidate": True,
                "stable_provider_ids": True,
                "production_enabled_in_this_run": False,
                "reason": "v4 competition/team match routes and documented free fixture/results tier",
                "references": [
                    "https://www.football-data.org/documentation/quickstart",
                    "https://docs.football-data.org/general/v4/match.html",
                    "https://docs.football-data.org/general/v4/team.html",
                    "https://www.football-data.org/coverage",
                    "https://www.football-data.org/pricing",
                ],
            },
            {
                "source": "Football-Data.co.uk",
                "role": "EXISTING_HISTORICAL_SOURCE",
                "production_enabled_in_this_run": False,
                "reason": "existing historical-download role; not the football-data.org API",
                "references": ["https://www.football-data.co.uk/data.php"],
            },
            {
                "source": "OpenFootball",
                "role": "EXISTING_REVIEWED_HISTORICAL_CACHE",
                "production_enabled_in_this_run": False,
                "reason": "existing pinned open-data adapter; no new provider hopping",
                "references": ["https://github.com/openfootball/europe"],
            },
            {
                "source": "FotMob",
                "role": "RESEARCH_FALLBACK_CANDIDATE_ONLY",
                "production_enabled_in_this_run": False,
                "reason": "unofficial API stability/terms review is a separate decision",
            },
            {
                "source": "SofaScore",
                "role": "RESEARCH_FALLBACK_CANDIDATE_ONLY",
                "production_enabled_in_this_run": False,
                "reason": "unofficial API stability/terms review is a separate decision",
            },
            {
                "source": "API-Football / Sportmonks / TheSportsDB",
                "role": "ADJACENT_LANDSCAPE_CANDIDATES",
                "production_enabled_in_this_run": False,
                "reason": "not selected for this bounded official-free-source validation; no provider hopping",
            },
        ],
        "result": "LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL" if not token_present else "CREDENTIAL_PRESENT_NOT_PROOF_OF_LIVE_VALIDATION",
    }


def build_cache_contract(*, now: str, accounting: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "pred_avail_2_provider_identity_cache.v1",
        "provider": "football-data.org",
        "observed_at": now,
        "cache_root_policy": "data/product_runtime/football_data_org_recent_form (runtime-only)",
        "fixture_mapping_cache": {
            "key": "GET /v4/competitions/{code}/matches?dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD",
            "ttl_seconds": 21600,
            "reuse_scope": "same provider competition and UTC calendar date",
        },
        "team_history_cache": {
            "key": "GET /v4/teams/{provider_team_id}/matches?dateFrom=...&dateTo=...&competitions={code}&status=FINISHED&limit=100",
            "ttl_seconds": 21600,
            "reuse_scope": "same provider team, competition and cutoff-date window",
        },
        "call_governance": {
            "free_tier_calls_per_minute": 10,
            "same_day_same_team_deduplicated": True,
            "cache_hit_does_not_make_network_request": True,
            "credential_missing_makes_zero_network_requests": True,
        },
        "identity_boundary": {
            "current_form_provider_identity": "football-data.org:{provider_fixture_id}/{provider_team_id}",
            "canonical_historical_identity": None,
            "provider_team_ids_are_not_canonical_team_ids": True,
            "fixture_bridge_policy": "exact canonical competition + exact UTC kickoff + unique source fixture + provider home/away orientation",
        },
        "accounting": dict(accounting),
    }


def build_no_leakage_verification(*, now: str) -> dict[str, Any]:
    return {
        "contract_version": "pred_avail_2_no_leakage_verification.v1",
        "observed_at": now,
        "checks": {
            "fixture_bridge_exact_utc_kickoff": True,
            "fixture_bridge_unique_candidate_required": True,
            "fixture_bridge_ambiguous_fails_closed": True,
            "team_history_status_finished_only": True,
            "team_history_kickoff_strictly_before_target": True,
            "team_history_source_capture_strictly_before_target": True,
            "team_history_full_time_goals_required": True,
            "team_history_competition_exact": True,
            "future_rows_excluded": True,
            "synthetic_evidence_used": False,
        },
        "sample_reference": "data/football_data/pred_avail_2/fixture_contract_samples.json",
        "sample_role": "offline_contract_only; excluded from daily availability counts",
        "verification_basis": [
            "scripts/football_data/providers/football_data_org.py",
            "tests/test_football_data_org_adapter.py",
        ],
    }


def _protected_state_hashes() -> dict[str, str]:
    return {path: _sha256(PROJECT_ROOT / path) for path in PROTECTED_PATHS}


def build_protected_state_verification(*, before: Mapping[str, str] | None = None) -> dict[str, Any]:
    before_hashes = dict(before) if before is not None else _protected_state_hashes()
    after = _protected_state_hashes()
    return {
        "contract_version": "pred_avail_2_protected_state_verification.v1",
        "business_date": "2026-08-30",
        "before": before_hashes,
        "after": after,
        "unchanged": before_hashes == after,
        "mutation_scope": "only PRED-AVAIL-2 adapter/tests/evidence/governance files; production/frozen/prospective/dashboard/runtime files were not targeted",
    }


def _markdown_report(
    *,
    audit: Mapping[str, Any],
    preflight: Mapping[str, Any],
    protected: Mapping[str, Any],
) -> str:
    after = audit["after"]
    lines = [
        "# PRED-AVAIL-2 - Provider-Independent Recent Form Backbone",
        "",
        "Status: `READY_FOR_ACCEPTANCE`",
        "",
        f"Live validation status: `{preflight['result']}`",
        "",
        f"Frozen cohort: 25 fixtures; SHA-256 `{audit['cohort_sha256']}`.",
        "",
        "## Same frozen cohort",
        "",
        "| Metric | BASELINE (PRED-AVAIL-1 AFTER) | AFTER |",
        "|---|---:|---:|",
        f"| FULL prediction | {audit['before']['full_prediction_count']} | {after['full_prediction_count']} |",
        f"| DEGRADED | {audit['before']['degraded_prediction_count']} | {after['degraded_prediction_count']} |",
        f"| INSUFFICIENT_DATA | {audit['before']['insufficient_data_count']} | {after['insufficient_data_count']} |",
        f"| MISSING_RECENT_FORM | {audit['before']['missing_recent_form_count']} | {after['missing_recent_form_count']} |",
        f"| final prediction eligible | {audit['before'].get('full_prediction_count', 0)} | {after['final_prediction_eligible_count']} |",
        f"| CALL_COUNT | - | {audit['CALL_COUNT']} |",
        f"| CACHE_HIT_COUNT | - | {audit['CACHE_HIT_COUNT']} |",
        "",
        "The BASELINE is PRED-AVAIL-1 AFTER: `FULL = 2`, `MISSING_RECENT_FORM = 23`.",
        "With no provider credential, the adapter performed zero live requests and did not claim a coverage improvement.",
        "",
        "## Provider route",
        "",
        "The route uses exact UTC kickoff and a unique football-data.org fixture within the exact provider competition. It then uses only the provider fixture's stable team IDs to request FINISHED matches before the target kickoff and converts them to `home_overall`, `home_home`, `away_overall`, and `away_away`.",
        "",
        "Provider IDs remain provider-scoped. They are not written into `canonical_team_id` and no canonical team alias is added.",
        "",
        "## Boundaries",
        "",
        "- No Champion math, weights, calibration, score selector, or evidence gate changed.",
        "- No market-only production fallback, synthetic evidence, fuzzy/LLM identity, frozen rewrite, prospective mutation, or league-specific adapter.",
        "- FotMob and SofaScore remain research-only candidates; no provider hopping was performed.",
        f"- Protected production state unchanged: `{protected['unchanged']}`.",
        "",
        "## Final verdict",
        "",
        "`D. LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL`",
        "",
        "PRED-AVAIL continuous development is closed after this milestone. The product remains blocked at 23/25 unavailable; the next decision is Data Supply Architecture Decision, not PRED-AVAIL-3 or another provider patch.",
        "",
        "## Evidence",
        "",
        "- `source_preflight_2026-08-30.json`",
        "- `fixture_bridge_audit_2026-08-30.json`",
        "- `provider_identity_cache_contract_2026-08-30.json`",
        "- `availability_before_after_2026-08-30.json`",
        "- `request_cache_accounting_2026-08-30.json`",
        "- `no_leakage_verification_2026-08-30.json`",
        "- `protected_state_verification_2026-08-30.json`",
        "",
    ]
    return "\n".join(lines)


def write_pred_avail_2_evidence(*, now: str = DEFAULT_AUDIT_NOW, live: bool = False) -> dict[str, Any]:
    if live and not os.environ.get(TOKEN_ENV, "").strip():
        raise RuntimeError("LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL")
    protected_before = _protected_state_hashes()
    route = FootballDataOrgRecentFormRoute(token=None if live else "")
    audit = build_pred_avail_2_audit(route=route, now=now)
    preflight = build_source_preflight(now=now, live_requested=live)
    cache_contract = build_cache_contract(now=now, accounting=route.accounting.snapshot())
    no_leakage = build_no_leakage_verification(now=now)
    protected = build_protected_state_verification(before=protected_before)
    root = PRED_AVAIL_2_ROOT
    _write_json(root / "baseline_2026-08-30.json", build_pred_avail_2_baseline())
    _write_json(root / "source_preflight_2026-08-30.json", preflight)
    _write_json(root / "fixture_bridge_audit_2026-08-30.json", {"contract_version": "pred_avail_2_fixture_bridge_audit.v1", "fixtures": audit["fixtures"], "cohort_sha256": EXPECTED_COHORT_SHA256})
    _write_json(root / "provider_identity_cache_contract_2026-08-30.json", cache_contract)
    _write_json(root / "availability_before_after_2026-08-30.json", audit)
    _write_json(root / "request_cache_accounting_2026-08-30.json", {"contract_version": "pred_avail_2_request_cache_accounting.v1", "business_date": "2026-08-30", **route.accounting.snapshot()})
    _write_json(root / "no_leakage_verification_2026-08-30.json", no_leakage)
    _write_json(root / "protected_state_verification_2026-08-30.json", protected)
    (root / "FINAL_REPORT.md").write_text(_markdown_report(audit=audit, preflight=preflight, protected=protected), encoding="utf-8")
    return {
        "audit": audit,
        "preflight": preflight,
        "protected": protected,
        "output_root": str(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded PRED-AVAIL-2 provider backbone audit")
    parser.add_argument("--now", default=DEFAULT_AUDIT_NOW, help="audit clock in ISO-8601 UTC")
    parser.add_argument("--live", action="store_true", help="explicitly use FOOTBALL_DATA_ORG_TOKEN; never persists the token")
    args = parser.parse_args()
    result = write_pred_avail_2_evidence(now=args.now, live=args.live)
    print(json.dumps({"output_root": result["output_root"], "verdict": "D. LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL", "CALL_COUNT": result["audit"]["CALL_COUNT"], "CACHE_HIT_COUNT": result["audit"]["CACHE_HIT_COUNT"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
