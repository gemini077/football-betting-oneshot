#!/usr/bin/env python3
"""Exact-head live audit for the Issue #284 analysis_page field slice."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from nowscore_prematch_evidence import (
    STATE_NAMES,
    STATE_SET,
    run_natural_cohort,
)


TARGET_FIELDS = (
    "standings_context",
    "future_schedule_rest",
    "availability_summary",
)
SENSITIVE_AVAILABILITY_KEYS = frozenset({
    "player",
    "player_name",
    "player_names",
    "name",
    "jersey",
    "jersey_no",
})
RAW_KEYS = frozenset({
    "body",
    "html",
    "raw_body",
    "raw_html",
    "response_body",
})


def _exact_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _match_evidence(match: Mapping[str, Any]) -> Mapping[str, Any]:
    value = match.get("prematch_evidence")
    return value if isinstance(value, Mapping) else {}


def _field(match: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    fields = _match_evidence(match).get("fields")
    value = fields.get(name) if isinstance(fields, Mapping) else None
    return value if isinstance(value, Mapping) else {
        "state": "ABSENT",
        "reason_code": "NO_FIELD_EVIDENCE",
        "record_count": 0,
        "value": None,
    }


def _identity_eligible(match: Mapping[str, Any]) -> bool:
    identity = match.get("identity_verification")
    provenance = match.get("trusted_jc_provenance")
    return bool(
        isinstance(identity, Mapping)
        and identity.get("trusted") is True
        and isinstance(provenance, Mapping)
        and provenance.get("trusted") is True
    )


def _state_counts(matches: list[Mapping[str, Any]], field: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for match in matches:
        state = str(_field(match, field).get("state") or "ABSENT")
        counts[state if state in STATE_SET else "PARSE_UNCERTAIN"] += 1
    return counts


def _reject_counts(matches: list[Mapping[str, Any]], field: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    accepted = {"PRESENT", "SECTION_PRESENT_EMPTY"}
    for match in matches:
        item = _field(match, field)
        if str(item.get("state") or "ABSENT") not in accepted:
            counts[str(item.get("reason_code") or "UNKNOWN_REJECT")] += 1
    return counts


def _sanitized_value(field: str, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if field == "standings_context":
        teams = value.get("teams") if isinstance(value.get("teams"), Mapping) else {}
        return {
            "team_sides": sorted(str(side) for side in teams if side in {"home", "away"}),
            "split_keys": {
                str(side): sorted(
                    str(split)
                    for split in ((teams.get(side) or {}).get("splits") or {})
                )
                for side in ("home", "away")
                if isinstance(teams.get(side), Mapping)
            },
            "competition_binding": value.get("competition_binding"),
            "source_semantics": value.get("source_semantics"),
        }
    if field == "future_schedule_rest":
        fixtures = value.get("fixtures") if isinstance(value.get("fixtures"), list) else []
        return {
            "future_fixture_count": int(value.get("future_fixture_count") or 0),
            "target_orientations": [
                item.get("target_orientation")
                for item in fixtures
                if isinstance(item, Mapping)
            ],
            "interval_days": [
                item.get("interval_days")
                for item in fixtures
                if isinstance(item, Mapping)
            ],
            "date_delta_days": [
                item.get("date_delta_days")
                for item in fixtures
                if isinstance(item, Mapping)
            ],
            "interval_sources": [
                item.get("interval_source")
                for item in fixtures
                if isinstance(item, Mapping)
            ],
            "interval_consistency": [
                item.get("interval_consistency")
                for item in fixtures
                if isinstance(item, Mapping)
            ],
            "source_semantics": value.get("source_semantics"),
        }
    if field == "availability_summary":
        return {
            "counts": value.get("counts"),
            "position_category_counts": value.get("position_category_counts"),
            "observed_sections": value.get("observed_sections"),
            "side_binding": value.get("side_binding"),
            "source_semantics": value.get("source_semantics"),
        }
    return None


def _sanitized_records(matches: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for field in TARGET_FIELDS:
        for match in matches:
            item = _field(match, field)
            records.append({
                "nowscore_id": match.get("nowscore_id"),
                "field": field,
                "state": item.get("state"),
                "reason_code": item.get("reason_code"),
                "record_count": int(item.get("record_count") or 0),
                "value": _sanitized_value(field, item.get("value")),
            })
            break
    return records[:3]


def _walk_key_hits(value: Any, *, path: tuple[str, ...] = ()) -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text.casefold() in RAW_KEYS:
                hits.append(".".join(path + (key_text,)))
            hits.extend(_walk_key_hits(child, path=path + (key_text,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_walk_key_hits(child, path=path + (str(index),)))
    return hits


def _walk_sensitive_availability_keys(value: Any, *, path: tuple[str, ...] = ()) -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text.casefold() in SENSITIVE_AVAILABILITY_KEYS:
                hits.append(".".join(path + (key_text,)))
            hits.extend(_walk_sensitive_availability_keys(child, path=path + (key_text,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_walk_sensitive_availability_keys(child, path=path + (str(index),)))
    return hits


def _side_binding_violations(matches: list[Mapping[str, Any]]) -> int:
    violations = 0
    for match in matches:
        for field in TARGET_FIELDS:
            item = _field(match, field)
            if item.get("state") != "PRESENT":
                continue
            value = item.get("value")
            if field == "standings_context":
                teams = value.get("teams") if isinstance(value, Mapping) else None
                if not isinstance(teams, Mapping) or set(teams) != {"home", "away"}:
                    violations += 1
            elif field == "future_schedule_rest":
                fixtures = value.get("fixtures") if isinstance(value, Mapping) else None
                if not isinstance(fixtures, list) or any(
                    not isinstance(row, Mapping)
                    or row.get("target_orientation") not in {"home", "away"}
                    for row in fixtures
                ):
                    violations += 1
            elif field == "availability_summary":
                if not isinstance(value, Mapping) or value.get("side_binding") != "EXPLICIT_RESULT_BAR_OR_SIDE_COLUMN":
                    violations += 1
    return violations


def build_audit_report(natural: Mapping[str, Any], *, exact_head: str) -> dict[str, Any]:
    matches = [item for item in natural.get("matches") or [] if isinstance(item, Mapping)]
    field_reports: dict[str, Any] = {}
    for field in TARGET_FIELDS:
        states = _state_counts(matches, field)
        eligible = sum(_identity_eligible(match) for match in matches)
        present = int(states.get("PRESENT", 0))
        field_reports[field] = {
            "eligible_fixture_count": eligible,
            "present_count": present,
            "present_fraction": round(present / eligible, 4) if eligible else 0.0,
            "state_counts": {state: int(states.get(state, 0)) for state in STATE_NAMES},
            "reject_counts": dict(sorted(_reject_counts(matches, field).items())),
        }

    serialized_matches = json.dumps(matches, ensure_ascii=False, sort_keys=True)
    raw_marker_hits = [
        marker
        for marker in ("<html", "<script", "var h_data", "<!doctype")
        if marker.casefold() in serialized_matches.casefold()
    ]
    media_marker_hits = [
        marker
        for marker in ("媒体分析", "media analysis")
        if marker.casefold() in serialized_matches.casefold()
    ]
    raw_key_hits = _walk_key_hits(matches)
    availability_key_hits = _walk_sensitive_availability_keys([
        _field(match, "availability_summary").get("value")
        for match in matches
    ])
    identity_violations = sum(not _identity_eligible(match) for match in matches)
    boundary = natural.get("change_boundary") if isinstance(natural.get("change_boundary"), Mapping) else {}
    return {
        "audit_version": "nowscore_context_depth_audit.v1",
        "run": {
            "execution": "github_actions_live",
            "exact_head": exact_head,
            "as_of": (natural.get("run") or {}).get("as_of"),
            "max_matches": (natural.get("run") or {}).get("max_matches"),
        },
        "cohort": natural.get("cohort"),
        "coverage": {
            "selected_fixture_count": len(matches),
            "fields": field_reports,
        },
        "sanitized_records": _sanitized_records(matches),
        "boundary_proof": {
            "identity_violation_count": int(identity_violations),
            "side_binding_violation_count": _side_binding_violations(matches),
            "raw_body_persistence_count": len(raw_key_hits),
            "raw_marker_count": len(raw_marker_hits),
            "media_analysis_promotion_count": len(media_marker_hits),
            "player_name_persistence_count": len(availability_key_hits),
            "raw_key_paths": raw_key_hits,
            "raw_markers": raw_marker_hits,
            "media_markers": media_marker_hits,
            "availability_sensitive_key_paths": availability_key_hits,
            "rights": natural.get("rights"),
            "change_boundary": boundary,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path")
    parser.add_argument("--business-date")
    parser.add_argument("--as-of")
    parser.add_argument("--max-matches", type=int, default=12)
    parser.add_argument("--output", default="nowscore-context-depth-audit.json")
    args = parser.parse_args(argv)
    try:
        natural = run_natural_cohort(
            cohort_path=args.cohort_path,
            business_date=args.business_date,
            as_of=args.as_of,
            max_matches=args.max_matches,
        )
        report = build_audit_report(natural, exact_head=_exact_head())
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"nowscore context depth audit failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(output),
        "exact_head": report["run"]["exact_head"],
        "selected_fixture_count": report["coverage"]["selected_fixture_count"],
        "fields": report["coverage"]["fields"],
        "boundary_proof": report["boundary_proof"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
