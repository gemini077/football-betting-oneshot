"""Materialize the final, bounded Phase 2B coverage closure report.

The command reads the existing project-demand audit and shared Data Home.  It
does not download data, mutate identity truth, or write any Champion input.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .data_home import resolve_football_data_home
from .final_coverage import build_final_identity_gap_summary, weighted_final_coverage
from .final_source_decisions import build_final_source_discovery
from .verify_data_home import verify_data_home


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "data" / "football_data"
DOC_ROOT = ROOT / "docs" / "team-strength"
AVAILABILITY_PATH = OUTPUT_ROOT / "p0_p1_demand_availability.json"
PROJECT_EVIDENCE_PATH = resolve_football_data_home() / "identity" / "project_provider_identity_candidates.json"
HEALTH_PATH = OUTPUT_ROOT / "team_strength_health.json"
FINAL_IDENTITY_PATH = OUTPUT_ROOT / "final_identity_gap_summary.json"
FINAL_WEIGHTED_PATH = OUTPUT_ROOT / "p0_p1_final_weighted_coverage.json"
FINAL_SOURCE_PATH = OUTPUT_ROOT / "final_source_discovery.json"
FINAL_DOC_PATH = DOC_ROOT / "PHASE2B_FINAL_COVERAGE.md"


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _identity_gap_rows(audits: list[dict[str, Any]], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    targets = evidence.get("target_evidence") or {}
    rows: list[dict[str, Any]] = []
    for audit in audits:
        if str(audit.get("status") or "").upper() != "IDENTITY_MISSING":
            continue
        target_id = str(audit.get("target_match_id") or "")
        target = targets.get(target_id) or {}
        rows.append(
            {
                "target_match_id": target_id,
                "competition": audit.get("competition_key"),
                "kickoff": audit.get("kickoff"),
                "project_home_name": audit.get("home"),
                "project_away_name": audit.get("away"),
                "provider": target.get("provider"),
                "provider_match_id": target.get("provider_match_id"),
            }
        )
    return rows


def _source_summary(source: dict[str, Any]) -> str:
    rows = {row["source"]: row for row in source.get("sources", [])}
    uefa = rows["openfootball/champions-league"]
    k_league = rows["K League official/public"]
    api = source["api_football"]
    return "\n".join(
        [
            "## Source closure",
            "",
            f"- OpenFootball UEFA prior season: `{uefa['prior_season_status']}`; current 2026/27: `{uefa['current_2026_27_status']}`.",
            f"- K League official/public: `{k_league['status']}`; demand remains in the denominator.",
            f"- football-data.org: `{rows['football-data.org']['status']}`; no authenticated capture was executed.",
            f"- API-Football: `{api['status']}`; requests `{api['requests_used']}`; real ingestion `{api['real_ingestion_executed']}`.",
            "",
        ]
    )


def _data_home_summary(verification: dict[str, Any]) -> dict[str, Any]:
    datasets = verification.get("datasets") or {}
    historical = datasets.get("historical_results") or {}
    team_strength = datasets.get("team_strength") or {}
    return {
        "status": verification.get("status"),
        "historical_records": historical.get("actual_record_count"),
        "historical_digest": historical.get("actual_dataset_sha256"),
        "snapshot_records": team_strength.get("actual_record_count"),
        "snapshot_digest": team_strength.get("actual_dataset_sha256"),
    }


def _write_doc(*, identity: dict[str, Any], weighted: dict[str, Any], source: dict[str, Any], generated_at: str) -> None:
    blocker_lines = [
        "| Blocker | Side count |",
        "| --- | ---: |",
    ]
    for key, value in identity.get("blocker_counts", {}).items():
        blocker_lines.append(f"| `{key}` | {value} |")
    lines = [
        "# Phase 2B.5 Final Coverage",
        "",
        f"Generated at `{generated_at}` from the existing P0/P1 demand audit and shared Football Data Home.",
        "",
        "This is the final Phase 2B data-layer closure report. It does not create a Challenger, change the Champion, or validate any feature for model use.",
        "",
        f"Demand denominator: `{weighted['demand_weight']}`. Strict ready `{weighted['strict_ready_weight']}`; verified bridge `{weighted['verified_bridge_weight']}`; ready plus bridge `{weighted['ready_plus_bridge_weight']}` (`{weighted['ready_plus_bridge_rate']:.6%}`).",
        "",
        f"The fixed 80% gate requires `{weighted['gate_threshold_weight']}` demand weight. Passed: `{weighted['eighty_percent_gate_passed']}`. `PHASE2B_COVERAGE_LIMIT_REACHED={weighted['phase2b_coverage_limit_reached']}`.",
        f"Shared Data Home verification: historical `{weighted['data_home_verification']['historical_records']}` records with digest `{weighted['data_home_verification']['historical_digest']}`; snapshots `{weighted['data_home_verification']['snapshot_records']}` with digest `{weighted['data_home_verification']['snapshot_digest']}`.",
        "",
        "## Track A — project identity",
        "",
        f"The current identity-missing set contains `{identity['starting_identity_missing']}` fixtures. Auto-resolved `{identity['auto_resolved_fixture_count']}`, review required `{identity['review_required_fixture_count']}`, conflict `{identity['conflict_fixture_count']}`, still unresolved `{identity['still_unresolved_fixture_count']}`.",
        "",
        "Blocker counts below are side-level evidence counts; one side may have more than one blocker.",
        "",
        *blocker_lines,
        "",
        "No new project-provider mapping is promoted without a unique reviewed ID/alias/context chain. Detailed candidate graphs remain outside Git under `${FOOTBALL_DATA_HOME}/identity/`.",
        "",
        _source_summary(source),
        "## Final status",
        "",
        "- Historical result store is unchanged and remains immutable.",
        "- No raw source or bulk result rows were added in this closure.",
        "- `validated_for_model=true` count remains `0`.",
        "- Phase 2B is complete; remaining gaps are a frozen coverage backlog for later governance review, not a new Phase 2B phase.",
    ]
    FINAL_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINAL_DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(*, captured_at: str = "2026-08-11T00:00:00Z") -> dict[str, Any]:
    data_home_check = verify_data_home()
    if data_home_check.get("status") != "OK":
        raise RuntimeError(f"shared Football Data Home verification failed: {data_home_check.get('status')}")
    data_home = _data_home_summary(data_home_check)

    availability = _load(AVAILABILITY_PATH, {})
    audits = list(availability.get("audits") or [])
    if len(audits) != 152:
        raise RuntimeError(f"expected 152 P0/P1 audits, found {len(audits)}")
    evidence = _load(PROJECT_EVIDENCE_PATH, {})
    if not isinstance(evidence.get("target_evidence"), dict):
        raise RuntimeError("project identity evidence is unavailable in the shared Data Home")

    identity = build_final_identity_gap_summary(
        _identity_gap_rows(audits, evidence),
        evidence["target_evidence"],
        generated_at=captured_at,
    )
    weighted = weighted_final_coverage(audits)
    weighted["data_home_verification"] = data_home
    api_key_present = bool(os.environ.get("API_FOOTBALL_KEY", "").strip())
    source = build_final_source_discovery(checked_at=captured_at, api_key_present=api_key_present)

    _write(FINAL_IDENTITY_PATH, identity)
    _write(
        FINAL_WEIGHTED_PATH,
        {
            "contract_version": "phase2b_final_weighted_coverage.v1",
            "generated_at": captured_at,
            "data_home_verification": data_home,
            **weighted,
        },
    )
    _write(FINAL_SOURCE_PATH, source)

    health = _load(HEALTH_PATH, {})
    health["phase2b_final_coverage"] = {
        "demand_weight": weighted["demand_weight"],
        "strict_ready_weight": weighted["strict_ready_weight"],
        "verified_bridge_weight": weighted["verified_bridge_weight"],
        "ready_plus_bridge_weight": weighted["ready_plus_bridge_weight"],
        "ready_plus_bridge_rate": weighted["ready_plus_bridge_rate"],
        "identity_missing_weight": weighted["identity_missing_weight"],
        "source_missing_weight": weighted["source_missing_weight"],
        "scope_partial_weight": weighted["scope_partial_weight"],
        "stale_weight": weighted["stale_weight"],
        "conflict_weight": weighted["conflict_weight"],
        "eighty_percent_gate_passed": weighted["eighty_percent_gate_passed"],
        "phase2b_coverage_limit_reached": weighted["phase2b_coverage_limit_reached"],
        "phase2b_complete": True,
        "validated_for_model": False,
        "last_updated_at": captured_at,
    }
    health["phase2b_final_sources"] = {
        "source_count": len(source.get("sources", [])),
        "api_football_status": source["api_football"]["status"],
        "k_league_source_gap": source["k_league_source_gap"],
        "last_updated_at": captured_at,
        "validated_for_model": False,
    }
    _write(HEALTH_PATH, health)
    _write_doc(identity=identity, weighted=weighted, source=source, generated_at=captured_at)
    return {
        "identity": identity,
        "weighted": weighted,
        "source": source,
        "data_home_verification": data_home,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captured-at", default="2026-08-11T00:00:00Z")
    args = parser.parse_args()
    # Keep the CLI usable under Windows' default code pages.  The reports on
    # disk retain their real Unicode names; stdout is an escaped machine
    # readable summary so a GBK console cannot abort a successful run.
    print(json.dumps(run(captured_at=args.captured_at), ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
