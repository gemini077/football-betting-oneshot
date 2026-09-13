#!/usr/bin/env python3
"""Acceptance-only intake and report checks for Issue #293."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from daily_schedule_workspace import _nowscore_schedule_payload
from nowscore_markets import fetch_nowscore_jc_schedule
from nowscore_prematch_evidence import _future_fixture, _parse_timestamp
from prediction_universe import (
    trusted_nowscore_source_identity,
    update_prediction_universe,
)


DEFAULT_COHORT_PATH = Path("artifacts/issue-293-acceptance-cohort.json")
DEFAULT_INTAKE_PATH = Path("artifacts/issue-293-r38-intake.json")
ACCEPTANCE_REASON = "TRUSTED_IDENTITY_FUTURE_FIXTURES_ACCEPTANCE_ONLY"


def _fixture_id(fixture: Mapping[str, Any], identity: Mapping[str, Any] | None = None) -> Any:
    identity = identity or {}
    return (
        identity.get("nowscore_id")
        or fixture.get("nowscore_id")
        or fixture.get("nowscoreId")
        or fixture.get("matchId")
    )


def _competition_key(fixture: Mapping[str, Any]) -> str:
    for key in ("sclassId", "sclass_id", "nowscore_sclass_id"):
        value = fixture.get(key)
        if value not in (None, ""):
            return str(value)
    value = fixture.get("league")
    return str(value) if isinstance(value, (str, int, float)) and str(value).strip() else ""


def select_acceptance_cohort(
    snapshot: Mapping[str, Any],
    *,
    business_date: str,
    cutoff: datetime,
    max_matches: int,
) -> dict[str, Any]:
    """Select trusted future fixtures without changing production slate semantics."""

    fixtures = [
        fixture
        for fixture in snapshot.get("fixtures") or []
        if isinstance(fixture, Mapping)
    ]
    identity_coverage: list[dict[str, Any]] = []
    future_trusted: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for index, fixture in enumerate(fixtures):
        identity = trusted_nowscore_source_identity(fixture)
        future = _future_fixture(fixture, cutoff)
        raw_identity = fixture.get("nowscore_source_identity")
        identity_coverage.append({
            "fixture_index": index,
            "fixture_id": _fixture_id(fixture, identity),
            "competition_key": _competition_key(fixture),
            "future_for_acceptance": future,
            "source_identity_status": (
                raw_identity.get("status") if isinstance(raw_identity, Mapping) else None
            ),
            "trusted": identity is not None,
            "trusted_nowscore_source_identity": identity,
        })
        if identity is not None and future:
            future_trusted.append((fixture, identity))

    ordered_candidates = sorted(
        future_trusted,
        key=lambda item: (item[1]["kickoff_local"], item[1]["nowscore_id"]),
    )
    cohort_limit = min(max(int(max_matches), 1), 6)
    acceptance_fixtures: list[Mapping[str, Any]] = []
    acceptance_ids: set[Any] = set()
    seen_competitions: set[str] = set()
    for fixture, identity in ordered_candidates:
        current_id = _fixture_id(fixture, identity)
        competition = _competition_key(fixture)
        if current_id in acceptance_ids or (competition and competition in seen_competitions):
            continue
        acceptance_fixtures.append(fixture)
        acceptance_ids.add(current_id)
        if competition:
            seen_competitions.add(competition)
        if len(acceptance_fixtures) >= cohort_limit:
            break
    for fixture, identity in ordered_candidates:
        if len(acceptance_fixtures) >= cohort_limit:
            break
        current_id = _fixture_id(fixture, identity)
        if current_id in acceptance_ids:
            continue
        acceptance_fixtures.append(fixture)
        acceptance_ids.add(current_id)

    if not acceptance_fixtures:
        raise ValueError("selected snapshot has no trusted future fixture for acceptance")
    if len(identity_coverage) != len(fixtures):
        raise ValueError("selected snapshot identity coverage is incomplete")
    if not all(
        trusted_nowscore_source_identity(fixture) is not None
        and _future_fixture(fixture, cutoff)
        for fixture in acceptance_fixtures
    ):
        raise ValueError("acceptance cohort contains an untrusted or non-future fixture")

    acceptance_selection = {
        "reason": ACCEPTANCE_REASON,
        "production_fixture_selection_authority": False,
        "source_snapshot_business_date": business_date,
        "candidate_count": len(ordered_candidates),
        "candidate_fixture_ids": [
            _fixture_id(fixture, identity)
            for fixture, identity in ordered_candidates
        ],
        "selected_fixture_ids": [
            _fixture_id(fixture, trusted_nowscore_source_identity(fixture))
            for fixture in acceptance_fixtures
        ],
        "limit": cohort_limit,
    }
    selected_ids = set(acceptance_selection["selected_fixture_ids"])
    for row in identity_coverage:
        row["selected_for_acceptance"] = row["fixture_id"] in selected_ids

    return {
        "fixtures": acceptance_fixtures,
        "identity_coverage": identity_coverage,
        "acceptance_selection": acceptance_selection,
        "trusted_identity_count": sum(
            trusted_nowscore_source_identity(fixture) is not None for fixture in fixtures
        ),
    }


def refresh_acceptance_intake(
    *,
    probe_business_date: str,
    as_of: str | None = None,
    max_matches: int = 12,
    cohort_path: str | Path = DEFAULT_COHORT_PATH,
    intake_path: str | Path = DEFAULT_INTAKE_PATH,
    github_env: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh two source snapshots and write the acceptance-only artifacts."""

    base_date = date.fromisoformat(probe_business_date)
    now = now or datetime.now().astimezone()
    snapshots: list[dict[str, Any]] = []
    snapshot_payloads: dict[str, Mapping[str, Any]] = {}
    for offset in (0, 1):
        business_date = (base_date + timedelta(days=offset)).isoformat()
        fetched = fetch_nowscore_jc_schedule(business_date, now=now)
        payload = _nowscore_schedule_payload(business_date, fetched)
        snapshot = update_prediction_universe(business_date, payload)
        snapshot_payloads[business_date] = snapshot
        identities = [
            trusted_nowscore_source_identity(row)
            for row in snapshot.get("fixtures") or []
        ]
        snapshots.append({
            "business_date": business_date,
            "source_status": fetched.get("status"),
            "snapshot_status": snapshot.get("status"),
            "fixture_count": snapshot.get("fixture_count", 0),
            "persisted_identity_count": sum(identity is not None for identity in identities),
            "calendar_dates": sorted({
                identity["calendar_date"]
                for identity in identities
                if identity is not None
            }),
        })

    eligible = [
        snapshot
        for snapshot in snapshots
        if snapshot["source_status"] == "OK"
        and snapshot["snapshot_status"] == "READY"
        and snapshot["persisted_identity_count"] > 0
    ]
    if not eligible:
        raise ValueError(
            "no current-run source-accepted JC snapshot; "
            f"candidates: {json.dumps(snapshots, ensure_ascii=False)}"
        )
    selected = min(eligible, key=lambda snapshot: snapshot["business_date"])
    selected_business_date = selected["business_date"]
    selected_snapshot = snapshot_payloads[selected_business_date]
    selected_fixtures = [
        fixture
        for fixture in selected_snapshot.get("fixtures") or []
        if isinstance(fixture, Mapping)
    ]
    selected_identity_count = sum(
        trusted_nowscore_source_identity(fixture) is not None
        for fixture in selected_fixtures
    )
    if selected_identity_count != selected["persisted_identity_count"]:
        raise ValueError("selected snapshot identity coverage count drifted")

    cutoff = _parse_timestamp(as_of) if as_of else now
    if cutoff is None:
        raise ValueError(f"invalid acceptance cutoff: {as_of}")
    selected_cohort = select_acceptance_cohort(
        selected_snapshot,
        business_date=selected_business_date,
        cutoff=cutoff,
        max_matches=max_matches,
    )
    acceptance_selection = selected_cohort["acceptance_selection"]
    cohort_path = Path(cohort_path)
    intake_path = Path(intake_path)
    cohort_path.parent.mkdir(parents=True, exist_ok=True)
    intake_path.parent.mkdir(parents=True, exist_ok=True)
    cohort_path.write_text(
        json.dumps({
            "status": "READY",
            "source": selected_snapshot.get("source", "nowscore_public_jc"),
            "business_date": selected_business_date,
            "acceptance_only": True,
            "production_fixture_selection_authority": False,
            "selection": acceptance_selection,
            "fixtures": selected_cohort["fixtures"],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    selection = {
        "reason": "EARLIEST_ELIGIBLE_FOR_ACCEPTANCE_ONLY",
        "eligible_candidates": eligible,
        "production_active_slate_authority": False,
    }
    intake_path.write_text(
        json.dumps({
            "business_date": selected_business_date,
            "probe_business_date": probe_business_date,
            "captured_at": now.isoformat(),
            "snapshots": snapshots,
            "selection": selection,
            "selected_snapshot": {
                "business_date": selected_business_date,
                "source_status": selected["source_status"],
                "snapshot_status": selected["snapshot_status"],
                "fixture_count": len(selected_fixtures),
                "trusted_identity_count": selected_identity_count,
                "identity_coverage": selected_cohort["identity_coverage"],
                "acceptance_selection": acceptance_selection,
            },
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if github_env:
        with Path(github_env).open("a", encoding="utf-8") as env:
            env.write(f"ACCEPTANCE_ONLY_COHORT_PATH={cohort_path}\n")
            env.write(f"ACCEPTANCE_ONLY_COHORT_COUNT={len(selected_cohort['fixtures'])}\n")

    return {
        "candidates": snapshots,
        "selection": selection,
        "selected_snapshot": {
            "fixture_count": len(selected_fixtures),
            "trusted_identity_count": selected_identity_count,
        },
        "acceptance_selection": acceptance_selection,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_live_report(
    report: Mapping[str, Any],
    intake: Mapping[str, Any],
    *,
    expected_head: str,
) -> dict[str, Any]:
    """Verify the accepted live-spine contract without changing its evidence."""

    report_run = report["run"]
    _require(report_run["exact_head"] == expected_head, "spine exact_head does not match checked-out HEAD")
    _require(
        report_run["cohort_source_path"] == "artifacts/issue-293-acceptance-cohort.json",
        "spine did not consume the acceptance-only cohort",
    )
    selected_snapshot = intake["selected_snapshot"]
    _require(
        len(selected_snapshot["identity_coverage"]) == selected_snapshot["fixture_count"],
        "selected snapshot identity coverage report is incomplete",
    )
    _require(selected_snapshot["trusted_identity_count"] > 0, "selected snapshot has no trusted identity coverage")
    _require(report_run["natural_cohort_count"] > 0, "natural cohort is empty")

    api = report["api_football"]
    _require(api["credential_state"] == "PRESENT", "API-Football secret was not exercised")
    _require(api["request_count"] <= api["request_cap"] and api["request_cap"] == 100, "API-Football request cap failed")
    _require("/fixtures/statistics" not in api["endpoint_counts"], "future fixture statistics endpoint was called")

    before = report["identity_registry"]["summary_before"]
    after = report["identity_registry"]["summary_after"]
    _require(not (sum(before.values()) == 0 and sum(after.values()) == 0), "empty registry bootstrap produced no accepted mapping")
    _require(report["nowscore"]["persisted_identity_count"] > 0, "R38 intake persisted no exact source identities")
    _require(
        report["nowscore"]["strict_backfill_fixture_count"] == 0
        and report["nowscore"]["alias_surface_request_count"] == 0,
        "acceptance-only cohort was not limited to trusted source identities",
    )
    _require(api["binding_counts"].get("BOUND", 0) > 0, "R38 live cohort produced no BOUND fixture")
    _require(
        api["endpoint_counts"].get("/leagues", 0) > 0
        and api["endpoint_counts"].get("/teams/statistics", 0) > 0,
        "R38 live cohort did not enter enrichment endpoints",
    )
    _require(
        any(
            reason in {
                "PERSISTED_ACCEPTED_MAPPING",
                "UNIQUE_ORIENTED_FIXTURE_WITH_BOOTSTRAP_EVIDENCE",
            }
            and count > 0
            for reason, count in api["binding_reason_counts"].items()
        ),
        "registry bootstrap/reuse evidence is missing",
    )
    _require(
        sum(api["binding_counts"].values()) == report_run["natural_cohort_count"],
        "binding counts do not cover the cohort",
    )
    for field in ("standings", "injuries", "suspensions", "sidelined", "coach", "lineup", "stats"):
        _require(
            sum(api["field_state_counts"].get(field, {}).values()) == report_run["natural_cohort_count"],
            f"field states do not cover cohort: {field}",
        )

    proof = report["boundary_proof"]
    for key in (
        "raw_body_persistence_count",
        "raw_body_output_marker_count",
        "secret_leakage_count",
        "name_similarity_acceptance_count",
        "ambiguous_mapping_acceptance_count",
        "orientation_swap_acceptance_count",
    ):
        _require(proof[key] == 0, f"boundary proof failed: {key}={proof[key]}")
    for key in (
        "fuzzy_matching_used",
        "api_prediction_used",
        "production_enrichment_written",
        "article_changed",
        "ui_changed",
        "model_changed",
        "champion_changed",
        "serving_changed",
    ):
        _require(proof[key] is False, f"boundary proof failed: {key}={proof[key]}")

    return {
        "natural_cohort_count": report_run["natural_cohort_count"],
        "identity_registry": report["identity_registry"],
        "binding_counts": api["binding_counts"],
        "field_state_counts": api["field_state_counts"],
        "api_request_count": api["request_count"],
        "api_cache_hits": api["cache_hits"],
        "api_endpoint_counts": api["endpoint_counts"],
        "boundary_proof": proof,
    }


def _exact_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--probe-business-date", required=True)
    prepare.add_argument("--as-of", default="")
    prepare.add_argument("--max-matches", type=int, default=12)

    verify = commands.add_parser("verify")
    verify.add_argument("--report", default="artifacts/issue-293-multi-source-evidence-spine.json")
    verify.add_argument("--intake", default=str(DEFAULT_INTAKE_PATH))
    verify.add_argument("--expected-head", default="")

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            summary = refresh_acceptance_intake(
                probe_business_date=args.probe_business_date,
                as_of=args.as_of,
                max_matches=args.max_matches,
                github_env=os.environ.get("GITHUB_ENV"),
            )
        else:
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
            intake = json.loads(Path(args.intake).read_text(encoding="utf-8"))
            summary = verify_live_report(
                report,
                intake,
                expected_head=args.expected_head or _exact_head(),
            )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"issue #293 acceptance {args.command} failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
