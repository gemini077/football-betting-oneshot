"""Offline Phase 2B.4 project-team identity population.

This command consumes only already captured project metadata and the shared
historical DuckDB.  It never downloads a source, creates predictions, or
rewrites the Champion input surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .data_home import resolve_football_data_home
from .historical_results import HistoricalResultLedger
from .identity_artifacts import persist_identity_artifacts
from .p0_p1_coverage import audit_retrospective_availability, weighted_ready_coverage
from .p0_p1_identity import normalize_source_team_name
from .project_identity import build_project_identity_output
from .populate_p0_p1_coverage import (
    DOC_ROOT,
    OUTPUT_ROOT,
    P01_KEYS,
    PROJECT_CROSSWALK_PATH,
    PROJECT_GAP_PATH,
    PROJECT_BASELINE_PATH,
    PROJECT_REVIEW_QUEUE_PATH,
    PROJECT_ALIAS_SOURCE_PATH,
    USAGE_PATH,
    _demand_targets,
    _fetch_translation_index,
    _json,
    _load,
    _project_identity_gap_summary,
)


def _load_or_create_baseline(previous: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    """Keep the pre-sprint availability baseline stable across reruns."""

    path = PROJECT_BASELINE_PATH
    if path.exists():
        saved = _load(path, {})
        if isinstance(saved.get("audits"), list):
            return saved
    baseline = {
        "contract_version": "project_identity_baseline_availability.v1",
        "captured_at": previous.get("generated_at") or generated_at,
        "source": "pre_project_identity_sprint_availability",
        "audits": previous.get("audits", []),
    }
    _json(path, baseline)
    return baseline


def _canonical_name_index(rows: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    ambiguous: set[str] = set()
    for row in rows:
        if row.get("verified") is not True:
            continue
        team_id = str(row.get("canonical_team_id") or "")
        if not team_id:
            continue
        for name in (row.get("provider_team_name"), row.get("canonical_name")):
            key = normalize_source_team_name(str(name or ""))
            if not key:
                continue
            if key in index and index[key] != team_id:
                ambiguous.add(key)
            else:
                index[key] = team_id
    for key in ambiguous:
        index.pop(key, None)
    return index


def _write_identity_doc(*, gap: dict[str, Any], weighted: dict[str, Any], mapping_summary: dict[str, Any], generated_at: str) -> None:
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 2B.4 Project Team Identity",
        "",
        f"Generated at `{generated_at}` from existing project demand metadata and the shared historical result store.",
        "",
        "This is a shadow data-layer identity audit. It does not modify the Champion, create predictions, or validate any feature for model use.",
        "",
        f"Starting identity-missing fixtures: `{gap.get('starting_identity_missing', 0)}`; fixtures with both project sides resolved by this sprint: `{gap.get('resolved_fixture_count', 0)}`.",
        "",
        f"Verified project mappings: `{mapping_summary.get('AUTO_VERIFIED', 0)}`; review required `{mapping_summary.get('REVIEW_REQUIRED', 0)}`; conflicts `{mapping_summary.get('CONFLICT', 0)}`; unresolved `{mapping_summary.get('UNRESOLVED', 0)}`.",
        "",
        f"P0/P1 demand remains `{weighted.get('demand_weight', 0)}`. Strict ready `{weighted.get('strict_ready_weight', 0)}`; verified bridge `{weighted.get('verified_bridge_weight', 0)}`; identity-missing `{weighted.get('identity_missing_weight', 0)}`; source-missing `{weighted.get('source_missing_weight', 0)}`.",
        "",
        "500 match IDs are not treated as 500 team IDs. Nowscore team IDs remain in the Nowscore namespace; an exact bound capture may provide cross-provider context, but its ID is never copied into a 500 mapping.",
        "",
        "Detailed candidate evidence and the stable pre-sprint baseline are local-only under `${FOOTBALL_DATA_HOME}/identity/`; Git retains only compact verified truth and a compact review queue.",
        "",
        "All new mappings remain `validated_for_model=false`.",
    ]
    (DOC_ROOT / "PROJECT_TEAM_IDENTITY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(*, captured_at: str | None = None) -> dict[str, Any]:
    generated_at = captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    previous = _load(OUTPUT_ROOT / "p0_p1_demand_availability.json", {})
    baseline = _load_or_create_baseline(previous, generated_at=generated_at)
    usage = _load(USAGE_PATH, {})
    events = [
        event
        for event in usage.get("recovered_events", [])
        if (event.get("competition") or {}).get("competition_key") in P01_KEYS
    ]
    provider_ids = {
        str(value)
        for event in events
        for value in event.get("provider_match_ids", [])
        if value
    }
    source_crosswalk = _load(OUTPUT_ROOT / "verified_identity_crosswalk.json", {})
    source_mappings = list(source_crosswalk.get("mappings", []))
    project_identity = build_project_identity_output(
        events=events,
        translations=_fetch_translation_index(provider_ids),
        canonical_mappings=source_mappings,
        project_alias_rows=_load(PROJECT_ALIAS_SOURCE_PATH, {}).get("teams", []),
    )
    canonical_by_name = _canonical_name_index(source_mappings)
    targets, target_summary = _demand_targets(canonical_by_name, project_identity=project_identity)
    ledger = HistoricalResultLedger(resolve_football_data_home())
    audits = audit_retrospective_availability(targets, ledger.records(), captured_at=generated_at)
    for target, audit in zip(targets, audits):
        if target.get("source_available") is False:
            audit["status"] = "SOURCE_MISSING"
            audit["strict_ready"] = False
            audit["strength_ready"] = False
            reasons = list(audit.get("reason") or [])
            if "source_missing_for_competition" not in reasons:
                reasons.append("source_missing_for_competition")
            audit["reason"] = reasons
    weighted = weighted_ready_coverage(audits)
    project_artifacts = persist_identity_artifacts(
        project_identity,
        generated_at=generated_at,
        detail_path=resolve_football_data_home() / "identity" / "project_provider_identity_candidates.json",
        crosswalk_path=PROJECT_CROSSWALK_PATH,
        review_queue_path=PROJECT_REVIEW_QUEUE_PATH,
    )
    gap = _project_identity_gap_summary(
        previous_audits=baseline.get("audits", []),
        targets=targets,
        project_identity=project_identity,
        generated_at=generated_at,
    )
    _json(PROJECT_GAP_PATH, gap)
    _json(OUTPUT_ROOT / "p0_p1_identity_evidence.json", target_summary)
    _json(
        OUTPUT_ROOT / "p0_p1_demand_availability.json",
        {
            "contract_version": "p0_p1_demand_availability.v1",
            "generated_at": generated_at,
            "audits": audits,
        },
    )
    _json(
        OUTPUT_ROOT / "p0_p1_weighted_coverage.json",
        {
            "contract_version": "p0_p1_weighted_coverage.v1",
            "generated_at": generated_at,
            **weighted,
        },
    )
    health_path = OUTPUT_ROOT / "team_strength_health.json"
    health = _load(health_path, {})
    health["p0_p1_retrospective"] = {
        "demand_weight": weighted["demand_weight"],
        **weighted,
        "audited_matches": len(audits),
        "last_updated_at": generated_at,
        "validated_for_model": False,
    }
    health["project_identity_sprint"] = {
        "starting_identity_missing": gap["starting_identity_missing"],
        "resolved_fixture_count": gap["resolved_fixture_count"],
        "verified_project_mapping_count": project_artifacts["verified_mapping_count"],
        "last_updated_at": generated_at,
        "validated_for_model": False,
    }
    _json(health_path, health)
    _write_identity_doc(
        gap=gap,
        weighted=weighted,
        mapping_summary=project_identity.get("summary", {}),
        generated_at=generated_at,
    )
    return {
        "project_identity": project_identity,
        "project_identity_gap": gap,
        "target_summary": target_summary,
        "audits": audits,
        "weighted": weighted,
        "historical_count": ledger.count(),
        "historical_digest": ledger.dataset_digest(),
        "project_artifacts": project_artifacts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captured-at")
    args = parser.parse_args()
    result = run(captured_at=args.captured_at)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(
        json.dumps(
            {
                "gap": result["project_identity_gap"],
                "target_summary": result["target_summary"],
                "weighted": result["weighted"],
                "historical_count": result["historical_count"],
                "historical_digest": result["historical_digest"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
