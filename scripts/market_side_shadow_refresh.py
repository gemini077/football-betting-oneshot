#!/usr/bin/env python3
"""Refresh the Market-Side shadow evaluation from existing verified results."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import (  # noqa: E402
    DEFAULT_PAIR_ROOT,
    build_shadow_document,
    load_persisted_pairs,
)
from postmatch_result import RESULT_ROOT as POSTMATCH_RESULT_ROOT  # noqa: E402
from postmatch_queue import parse_datetime  # noqa: E402
from prospective_settlement import (  # noqa: E402
    _is_verified_result_artifact,
    normalize_result,
)


MILESTONE = "MARKET-SIDE-SHADOW-1"
REFRESH_SCHEMA_VERSION = "market_side_shadow_1.refresh.v2"
DEFAULT_RESULT_ROOT = POSTMATCH_RESULT_ROOT
DEFAULT_OUTPUT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
RESULT_SOURCE_LABEL = "data/postmatch_automation/results/*.json"
FINAL_SCOPES = {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _result_identity_key(result: Mapping[str, Any]) -> str:
    return str(result.get("match_key") or result.get("canonical_match_id") or "").strip()


def _result_signature(result: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _result_identity_key(result),
        result.get("home_score_90m"),
        result.get("away_score_90m"),
        result.get("scope"),
    )


def discover_verified_results(result_root: Path = DEFAULT_RESULT_ROOT) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Read only existing final regulation-result artifacts."""

    catalog: dict[str, dict[str, Any]] = {}
    conflicted: set[str] = set()
    stats = {
        "result_files_scanned": 0,
        "result_files_accepted": 0,
        "result_files_rejected": 0,
        "result_identity_conflicts": 0,
    }
    for path in sorted(Path(result_root).glob("*.json")):
        stats["result_files_scanned"] += 1
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["result_files_rejected"] += 1
            continue
        if not isinstance(raw, dict) or not _is_verified_result_artifact(raw):
            stats["result_files_rejected"] += 1
            continue
        try:
            normalized = normalize_result(raw)
        except (TypeError, ValueError):
            stats["result_files_rejected"] += 1
            continue
        key = _result_identity_key(normalized)
        if not key or normalized.get("scope") not in FINAL_SCOPES:
            stats["result_files_rejected"] += 1
            continue
        if key in conflicted:
            stats["result_files_rejected"] += 1
            continue
        existing = catalog.get(key)
        if existing is not None:
            if _result_signature(existing) != _result_signature(normalized):
                catalog.pop(key, None)
                conflicted.add(key)
                stats["result_identity_conflicts"] += 1
            else:
                stats["result_files_rejected"] += 1
            continue
        catalog[key] = normalized
        stats["result_files_accepted"] += 1
    return catalog, stats


def _result_matches_pair(pair: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    expected_key = str(pair.get("match_key") or "").strip()
    candidate_key = _result_identity_key(result)
    if not expected_key or candidate_key != expected_key:
        return False
    expected_id = str(pair.get("match_id") or "").strip()
    candidate_ids = {
        str(result.get(field)).strip()
        for field in ("prediction_match_id", "match_id", "provider_match_id", "sporttery_match_id")
        if result.get(field) not in (None, "")
    }
    if expected_id and candidate_ids and expected_id not in candidate_ids:
        return False
    expected_kickoff = parse_datetime(pair.get("kickoff_at"))
    candidate_kickoff = parse_datetime(result.get("kickoff_local") or result.get("kickoff_at"))
    if expected_kickoff and candidate_kickoff and expected_kickoff != candidate_kickoff:
        return False
    return True


def build_identity_safe_result_map(
    pairs: Iterable[Mapping[str, Any]],
    result_catalog: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Map a verified artifact to a pair only after exact canonical identity checks."""

    result_map: dict[str, dict[str, Any]] = {}
    stats = {
        "matched_pair_count": 0,
        "unmatched_pair_count": 0,
        "result_identity_mismatches": 0,
    }
    for pair in pairs:
        if pair.get("pair_status") != "PAIRED":
            continue
        key = str(pair.get("match_key") or "").strip()
        result = result_catalog.get(key)
        if result is None:
            stats["unmatched_pair_count"] += 1
            continue
        if not _result_matches_pair(pair, result):
            stats["result_identity_mismatches"] += 1
            continue
        pair_id = str(pair.get("pair_id") or "").strip()
        match_id = str(pair.get("match_id") or "").strip()
        if pair_id:
            result_map[pair_id] = dict(result)
        if match_id:
            result_map[match_id] = dict(result)
        stats["matched_pair_count"] += 1
    return result_map, stats


def _atomic_persist(document: Mapping[str, Any], output: Path) -> str:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    existed = output.exists()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return "REPLACED" if existed else "CREATED"


def refresh_shadow(
    *,
    pair_root: Path = DEFAULT_PAIR_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    output: Path = DEFAULT_OUTPUT,
    refreshed_at: str | None = None,
) -> dict[str, Any]:
    pairs = load_persisted_pairs(Path(pair_root))
    catalog, discovery = discover_verified_results(Path(result_root))
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    document = build_shadow_document(
        pairs,
        result_map,
        source_manifest={
            "result_source": RESULT_SOURCE_LABEL,
            "result_files_scanned": discovery["result_files_scanned"],
            "result_files_accepted": discovery["result_files_accepted"],
            "matched_pair_count": matching["matched_pair_count"],
        },
    )
    document["refresh_schema_version"] = REFRESH_SCHEMA_VERSION
    document["refresh"] = {
        "source": RESULT_SOURCE_LABEL,
        "refreshed_at": refreshed_at or datetime.now(timezone.utc).astimezone(SHANGHAI).isoformat(),
        **discovery,
        **matching,
        "actual_results_persisted": False,
    }
    latest_status = _atomic_persist(document, Path(output))
    evaluation = document["evaluation"]
    return {
        "status": "SUCCESS",
        "milestone": MILESTONE,
        "market_side_shadow_status": "REFRESHED",
        "paired_count": document["counts"]["paired"],
        "challenger_abstain_count": document["counts"]["challenger_abstain"],
        "promotion_eligible_pairs": document["counts"]["promotion_eligible_pairs"],
        "excluded_non_promotion_pair_count": document["counts"]["excluded_non_promotion_pair_count"],
        "verified_paired_count": evaluation["verified_paired_count"],
        "total_pair_version_rows": document["counts"]["total_pair_version_rows"],
        "promotion_eligible_pair_version_rows": document["counts"]["promotion_eligible_pair_version_rows"],
        "verified_pair_version_rows": document["counts"]["verified_pair_version_rows"],
        "promotion_eligible_unique_matches": document["counts"]["promotion_eligible_unique_matches"],
        "verified_unique_matches": document["counts"]["verified_unique_matches"],
        "version_history_match_groups": document["counts"]["version_history_match_groups"],
        "extra_version_rows": document["counts"]["extra_version_rows"],
        "checkpoint_status": document["checkpoint"]["status"],
        "early_stop_status": evaluation["early_kill"]["status"],
        "latest_status": latest_status,
        "result_files_scanned": discovery["result_files_scanned"],
        "result_files_accepted": discovery["result_files_accepted"],
        "result_files_rejected": discovery["result_files_rejected"],
        "result_identity_conflicts": discovery["result_identity_conflicts"],
        "result_identity_mismatches": matching["result_identity_mismatches"],
        "unmatched_pair_count": matching["unmatched_pair_count"],
        "auto_promote": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refreshed-at", help="Deterministic refresh timestamp for smoke/tests")
    args = parser.parse_args()
    try:
        summary = refresh_shadow(
            pair_root=args.pair_root,
            result_root=args.result_root,
            output=args.output,
            refreshed_at=args.refreshed_at,
        )
    except Exception as error:  # Optional research step reports a bounded failure to its caller.
        summary = {
            "status": "DEGRADED",
            "milestone": MILESTONE,
            "market_side_shadow_status": "FAILED",
            "error": f"{type(error).__name__}: {error}",
            "auto_promote": False,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
