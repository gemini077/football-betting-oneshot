#!/usr/bin/env python3
"""Audit current evidence and a representative current-source parser fixture.

The audit is intentionally offline.  It reads the current tracked football
evidence, frozen prediction records, embedded deterministic input snapshots,
and an existing local Nowscore source cache when present.  CI uses the
committed representative source fixture when that cache is absent.  It never
contacts a provider and never writes under the prospective, frozen, or
model-governance data directories.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from football_state_memory import (  # noqa: E402
    STATE_MEMORY_CONTRACT_VERSION,
    build_state_memory,
)
from nowscore_markets import (  # noqa: E402
    _analysis_array,
    _decode,
    parse_analysis_data,
    parse_panlu_page,
    parse_three_in_one,
)


AUDIT_CONTRACT_VERSION = "football_state_memory_readiness.v1"
DECISION_READY = "PROSPECTIVE_STATE_MEMORY_READY"
DECISION_PARTIAL = "PROSPECTIVE_STATE_MEMORY_PARTIAL"
DECISION_FAIL_CLOSED = "FAIL_CLOSED"
FALLBACK_MISSING_FIELDS = [
    "source_fixture_id",
    "per_fixture_home_away_team_ids",
    "match_date",
    "raw_competition_label",
    "is_club_friendly",
]
CURRENT_SOURCE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "nowscore_state_memory" / "current_source_sample.json"
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _snapshot_from_prediction(prediction: dict[str, Any]) -> dict[str, Any] | None:
    supplied = prediction.get("input_snapshot")
    if isinstance(supplied, dict) and (
        isinstance(supplied.get("input"), dict)
        or isinstance(supplied.get("projection"), dict)
    ):
        return supplied
    reference = (
        (supplied or {}).get("snapshot_ref")
        if isinstance(supplied, dict)
        else None
    ) or prediction.get("model_input_snapshot_ref") or prediction.get("input_snapshot_ref")
    if not reference:
        return None
    path = ROOT / str(reference)
    return _load_json(path)


def _projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input") or snapshot.get("projection")
    return value if isinstance(value, dict) else {}


def _source_snapshots(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = _projection(snapshot).get("source_snapshots")
    return value if isinstance(value, dict) else {}


def _nowscore_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    sources = _source_snapshots(snapshot)
    source = sources.get("nowscore")
    if not isinstance(source, dict):
        return None, {}
    snapshots = source.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots or not isinstance(snapshots[0], dict):
        return None, source
    return snapshots[0], source


def _state_for_sidecar(
    sidecar: dict[str, Any],
    prediction: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    existing = sidecar.get("state_memory")
    if isinstance(existing, dict) and existing.get("contract_version") == STATE_MEMORY_CONTRACT_VERSION:
        return copy.deepcopy(existing), "captured_state_memory"
    snapshot = _snapshot_from_prediction(prediction or {}) if prediction else None
    if snapshot is None:
        return None, "missing_input_snapshot"
    source_snapshot, wrapper = _nowscore_snapshot(snapshot)
    if source_snapshot is None:
        return None, "nowscore_snapshot_unavailable"
    enriched = copy.deepcopy(source_snapshot)
    shuju = enriched.get("shuju")
    if not isinstance(shuju, dict):
        shuju = {}
        enriched["shuju"] = shuju
    # Current deterministic snapshots intentionally omit raw recent rows from
    # the Champion projection.  Reattach only the legacy research sidecar
    # rows for this offline audit; the capture path itself receives them
    # before projection.
    shuju["recent_matches"] = copy.deepcopy(sidecar.get("recent_matches") or {})
    enriched["context"] = copy.deepcopy(enriched.get("nowscore_context") or {})
    source_wrapper = copy.deepcopy(wrapper)
    source_wrapper["snapshots"] = [enriched]
    source_wrapper.setdefault("source_reference", "current_input_snapshot")
    source_snapshots = {"nowscore": source_wrapper}
    record = {
        "prediction_id": sidecar.get("prediction_id"),
        "match_id": sidecar.get("match_id"),
        "business_date": sidecar.get("business_date"),
        "home": sidecar.get("home"),
        "away": sidecar.get("away"),
        "kickoff_at": sidecar.get("kickoff_at"),
        "nowscore_id": sidecar.get("nowscore_id"),
        "prediction_created_at": sidecar.get("prediction_created_at"),
        "freeze_created_at": sidecar.get("freeze_created_at"),
        "source_cutoff_at": sidecar.get("source_cutoff_at"),
        "match_identity": {
            "home": sidecar.get("home"),
            "away": sidecar.get("away"),
            "kickoff_at": sidecar.get("kickoff_at"),
        },
    }
    return build_state_memory(record, source_snapshots), "rebuilt_from_current_input_snapshot"


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percent(numerator: int, denominator: int) -> str:
    return f"{_ratio(numerator, denominator) * 100:.2f}%"


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_current_nowscore_source() -> dict[str, Any] | None:
    """Load the existing local source pair, with a committed source fixture fallback."""
    raw_root = ROOT / "data" / "source_cache" / "nowscore" / "raw"
    candidates: list[Path] = []
    preferred = raw_root / "2991818_analysis.js"
    if preferred.is_file():
        candidates.append(preferred)
    if raw_root.is_dir():
        candidates.extend(
            path for path in sorted(raw_root.glob("*_analysis.js")) if path not in candidates
        )
    for analysis_path in candidates:
        stem = analysis_path.name.removesuffix("_analysis.js")
        panlu_path = raw_root / f"{stem}_panlu.html"
        if not panlu_path.is_file():
            continue
        try:
            source_match_id = int(stem)
        except ValueError:
            source_match_id = None
        paths = {
            "analysis": _relative_path(analysis_path),
            "panlu": _relative_path(panlu_path),
        }
        three_path = raw_root / f"{stem}_3in1.html"
        if three_path.is_file():
            paths["three_in_one"] = _relative_path(three_path)
        hashes = {
            "analysis": _sha256(analysis_path),
            "panlu": _sha256(panlu_path),
        }
        if three_path.is_file():
            hashes["three_in_one"] = _sha256(three_path)
        return {
            "source_mode": "LOCAL_CURRENT_SOURCE_CACHE",
            "source_match_id": source_match_id,
            "source_paths": paths,
            "source_sha256": hashes,
            "fixture_payload_sha256": None,
            "analysis_text": _decode(analysis_path.read_bytes()),
            "panlu_text": _decode(panlu_path.read_bytes()),
            "three_in_one_text": (
                _decode(three_path.read_bytes()) if three_path.is_file() else None
            ),
            "fixture_contract_version": None,
        }

    fixture = _load_json(CURRENT_SOURCE_FIXTURE)
    if not fixture:
        return None
    analysis_text = fixture.get("analysis_js")
    panlu_text = fixture.get("panlu_html")
    if not isinstance(analysis_text, str) or not isinstance(panlu_text, str):
        return None
    return {
        "source_mode": "COMMITTED_CURRENT_SOURCE_FIXTURE",
        "source_match_id": _positive_int(fixture.get("source_match_id")),
        "source_paths": {
            "fixture": _relative_path(CURRENT_SOURCE_FIXTURE),
            **(
                fixture.get("source_paths")
                if isinstance(fixture.get("source_paths"), dict)
                else {}
            ),
        },
        "source_sha256": fixture.get("source_sha256") or {},
        "fixture_payload_sha256": fixture.get("fixture_payload_sha256") or {},
        "analysis_text": analysis_text,
        "panlu_text": panlu_text,
        "three_in_one_text": fixture.get("three_in_one_html"),
        "target_identity_fixture": fixture.get("target_identity"),
        "fixture_contract_version": fixture.get("fixture_contract_version"),
    }


def _source_target_identity(source: dict[str, Any]) -> dict[str, Any]:
    parsed_identity: dict[str, Any] = {}
    three_in_one_text = source.get("three_in_one_text")
    if isinstance(three_in_one_text, str) and three_in_one_text:
        try:
            value = parse_three_in_one(three_in_one_text).get("identity")
            if isinstance(value, dict):
                parsed_identity = value
        except (AttributeError, TypeError, ValueError):
            parsed_identity = {}
    fixture_identity = source.get("target_identity_fixture")
    fixture_identity = fixture_identity if isinstance(fixture_identity, dict) else {}

    def choose(*values: Any) -> Any:
        for value in values:
            if value is not None and (not isinstance(value, str) or value.strip()):
                return value
        return None

    source_id = choose(
        source.get("source_match_id"),
        parsed_identity.get("nowscore_id"),
        fixture_identity.get("source_fixture_id"),
    )
    return {
        "source_fixture_id": source_id,
        "provider_match_id": source_id,
        "home_team_id": choose(
            parsed_identity.get("home_team_id"), fixture_identity.get("home_team_id")
        ),
        "away_team_id": choose(
            parsed_identity.get("away_team_id"), fixture_identity.get("away_team_id")
        ),
        "home_team_name": choose(
            parsed_identity.get("home_team"), fixture_identity.get("home_team_name")
        ),
        "away_team_name": choose(
            parsed_identity.get("away_team"), fixture_identity.get("away_team_name")
        ),
        "kickoff_at": choose(
            parsed_identity.get("kickoff_local"), fixture_identity.get("kickoff_at")
        ),
        "identity_source": (
            "parse_three_in_one._identity"
            if parsed_identity
            else "committed_current_source_fixture.target_identity"
        ),
    }


def _source_identity_matches(row: list[Any], panlu: dict[str, Any]) -> bool:
    try:
        row_home, row_away = int(row[4]), int(row[6])
    except (TypeError, ValueError, IndexError):
        return False
    kickoff = str(panlu.get("kickoff") or "")
    return (
        row_home == _positive_int(panlu.get("home_team_id"))
        and row_away == _positive_int(panlu.get("away_team_id"))
        and str(row[0]).strip() == kickoff[:8]
    )


def _source_truth_probe(source: dict[str, Any]) -> dict[str, Any]:
    analysis_text = str(source.get("analysis_text") or "")
    panlu_text = str(source.get("panlu_text") or "")
    analysis_rows = _analysis_array(analysis_text, "h_data") + _analysis_array(
        analysis_text, "a_data"
    )
    panlu_rows = parse_panlu_page(panlu_text).get("matches") or []
    panlu_by_id: dict[str, list[dict[str, Any]]] = {}
    for panlu in panlu_rows:
        fixture_id = _positive_int(panlu.get("match_id")) if isinstance(panlu, dict) else None
        if fixture_id is not None:
            panlu_by_id.setdefault(str(fixture_id), []).append(panlu)

    row20_nonnull = 0
    row20_null = 0
    row20_exact_match = 0
    row20_unpaired = 0
    row20_team_date_confirmed = 0
    row20_id_conflict = 0
    row20_examples: list[dict[str, Any]] = []
    row_one_values: Counter[str] = Counter()
    for row in analysis_rows:
        if len(row) > 1 and row[1] not in (None, ""):
            row_one_values[str(row[1])] += 1
        candidate = _positive_int(row[20]) if len(row) > 20 else None
        if candidate is None:
            row20_null += 1
            continue
        row20_nonnull += 1
        exact = panlu_by_id.get(str(candidate), [])
        if len(exact) != 1:
            row20_unpaired += 1
            if len(row20_examples) < 5:
                row20_examples.append({
                    "row20": candidate,
                    "source_date": row[0] if row else None,
                    "home_team_id": row[4] if len(row) > 4 else None,
                    "away_team_id": row[6] if len(row) > 6 else None,
                })
            continue
        row20_exact_match += 1
        if _source_identity_matches(row, exact[0]):
            row20_team_date_confirmed += 1
        else:
            row20_id_conflict += 1

    if not analysis_rows:
        row20_status = "FAIL_CLOSED_NO_SOURCE_ROWS"
    elif row20_unpaired or row20_id_conflict:
        row20_status = "PARTIAL_PROOF_FAIL_CLOSED_OUTLIERS"
    else:
        row20_status = "PROVEN_BY_EXACT_CURRENT_SOURCE_JOIN"

    return {
        "source_mode": source.get("source_mode"),
        "source_match_id": source.get("source_match_id"),
        "source_paths": source.get("source_paths") or {},
        "source_sha256": source.get("source_sha256") or {},
        "fixture_payload_sha256": source.get("fixture_payload_sha256"),
        "analysis_rows_sampled": len(analysis_rows),
        "panlu_rows_sampled": len(panlu_rows),
        "row_20_source_fixture_id": {
            "status": row20_status,
            "semantic_conclusion": (
                "row[20] equals parse_panlu_page(...).match_id for exact paired rows; "
                "unpaired or conflicting values are unverified and remain null"
            ),
            "nonnull_count": row20_nonnull,
            "null_or_invalid_count": row20_null,
            "exact_panlu_match_count": row20_exact_match,
            "team_orientation_date_confirmed_count": row20_team_date_confirmed,
            "id_conflict_count": row20_id_conflict,
            "unpaired_count": row20_unpaired,
            "promotion_policy": "PROMOTE_ONLY_EXACT_PANLU_MATCH; OTHERWISE_NULL",
            "unpaired_examples": row20_examples,
        },
        "row_1_source_competition_id": {
            "status": "DROPPED_FAIL_CLOSED",
            "retained": False,
            "semantic_conclusion": None,
            "reason": (
                "Observed row[1] values are not persisted because this source sample has "
                "no independently documented field-level semantic for that position."
            ),
            "observed_value_counts": dict(row_one_values),
        },
    }


def _capture_probe(source: dict[str, Any]) -> dict[str, Any]:
    analysis_text = str(source.get("analysis_text") or "")
    parsed = parse_analysis_data(analysis_text)
    target_identity = _source_target_identity(source)
    panlu = parse_panlu_page(str(source.get("panlu_text") or ""))
    source_reference = " | ".join(
        str(value) for value in (source.get("source_paths") or {}).values()
    )
    snapshot = {
        "nowscore_id": source.get("source_match_id"),
        "state_memory_identity": target_identity,
        "shuju": parsed,
        "context": {"panlu": panlu},
        "source_record_ref": source_reference or None,
    }
    record = {
        "prediction_id": "current-source-capture-probe",
        "match_id": "current-source-capture-probe",
        "home": target_identity.get("home_team_name"),
        "away": target_identity.get("away_team_name"),
        "kickoff_at": target_identity.get("kickoff_at"),
        "match_identity": target_identity,
    }
    state = build_state_memory(record, {"nowscore": {"snapshots": [snapshot]}})
    if not state:
        return {
            "status": "FAIL_CLOSED",
            "capture_available": False,
            "reason": "current source parser did not produce a buildable State Memory object",
            "target_team_identity": target_identity,
        }

    target = state.get("target_fixture") if isinstance(state.get("target_fixture"), dict) else {}
    rows = [
        row
        for group in ("home_team", "away_team")
        for row in ((state.get("history") or {}).get(group) or [])
        if isinstance(row, dict)
    ]
    subject_resolved = sum(row.get("subject_identity_status") == "RESOLVED" for row in rows)
    subject_unresolved = len(rows) - subject_resolved
    subject_status_counts = Counter(str(row.get("subject_identity_status") or "UNKNOWN") for row in rows)
    analysis_team_ids = parsed.get("team_ids") if isinstance(parsed, dict) else {}
    analysis_team_ids = analysis_team_ids if isinstance(analysis_team_ids, dict) else {}
    target_ids_match = (
        target.get("home_team_id") is not None
        and target.get("away_team_id") is not None
        and str(target.get("home_team_id")) == str(analysis_team_ids.get("home"))
        and str(target.get("away_team_id")) == str(analysis_team_ids.get("away"))
    )
    return {
        "status": "READY" if state.get("capture_status") == "READY" else "PARTIAL",
        "capture_available": bool(rows and target_ids_match),
        "capture_status": state.get("capture_status"),
        "source_mode": source.get("source_mode"),
        "source_paths": source.get("source_paths") or {},
        "target_team_identity": {
            "source_fixture_id": target.get("source_fixture_id"),
            "home_team_id": target.get("home_team_id"),
            "away_team_id": target.get("away_team_id"),
            "home_team_name": target.get("home_team_name"),
            "away_team_name": target.get("away_team_name"),
            "identity_source": target_identity.get("identity_source"),
            "analysis_team_ids": analysis_team_ids,
            "verified_by_source_identity_and_analysis_ids": target_ids_match,
        },
        "subject_opponent_identity": {
            "resolved_count": subject_resolved,
            "unresolved_count": subject_unresolved,
            "status_counts": dict(subject_status_counts),
            "coverage": _ratio(subject_resolved, len(rows)),
            "coverage_percent": _percent(subject_resolved, len(rows)),
            "sample": [
                {
                    "group": group,
                    "source_fixture_id": row.get("source_fixture_id"),
                    "subject_team_id": row.get("subject_team_id"),
                    "opponent_team_id": row.get("opponent_team_id"),
                    "subject_venue": row.get("subject_venue"),
                    "status": row.get("subject_identity_status"),
                }
                for group in ("home_team", "away_team")
                for row in (((state.get("history") or {}).get(group) or [])[:1])
                if isinstance(row, dict)
            ],
        },
        "competition": {
            "resolved_count": int(state["coverage"]["competition_resolved_count"]),
            "unresolved_count": len(rows) - int(state["coverage"]["competition_resolved_count"]),
            "resolved_coverage": _ratio(
                int(state["coverage"]["competition_resolved_count"]), len(rows)
            ),
            "resolved_coverage_percent": _percent(
                int(state["coverage"]["competition_resolved_count"]), len(rows)
            ),
        },
        "history": {
            "row_count": len(rows),
            "source_fixture_id_count": int(state["coverage"]["source_fixture_id_count"]),
            "team_id_pair_count": int(state["coverage"]["team_id_count"]),
            "score_90m_count": int(state["coverage"]["score_90m_count"]),
        },
    }


def _audit(limit: int) -> dict[str, Any]:
    evidence_root = ROOT / "data" / "prospective" / "football_evidence"
    prediction_root = ROOT / "data" / "model_governance" / "predictions"
    paths = list(evidence_root.glob("*.json")) if evidence_root.is_dir() else []
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        sidecar = _load_json(path)
        if sidecar:
            loaded.append((path, sidecar))
    loaded.sort(
        key=lambda item: (
            _timestamp(item[1].get("evidence_captured_at")) or datetime.min.replace(tzinfo=timezone.utc),
            item[0].name,
        ),
        reverse=True,
    )
    selected = loaded if limit <= 0 else loaded[:limit]

    totals = Counter()
    providers: Counter[str] = Counter()
    source_modes: Counter[str] = Counter()
    state_status: Counter[str] = Counter()
    fallback_history_rows = 0
    fallback_snapshots = 0
    fallback_with_history = 0
    source_snapshot_count = 0
    current_target_identity_count = 0
    current_target_fixture_count = 0
    sample_records: list[dict[str, Any]] = []

    for path, sidecar in selected:
        prediction_path = prediction_root / f"{path.stem}.json"
        prediction = _load_json(prediction_path)
        snapshot = _snapshot_from_prediction(prediction or {}) if prediction else None
        if snapshot:
            sources = _source_snapshots(snapshot)
            source_snapshot_count += len(sources)
            for source_name, source in sources.items():
                provider = "500.com" if "500" in str(source_name).casefold() else str(source_name)
                providers[provider] += 1
                snapshots = source.get("snapshots") if isinstance(source, dict) else []
                snapshot_rows = [
                    item for item in snapshots
                    if isinstance(item, dict)
                ] if isinstance(snapshots, list) else []
                if "500" in str(source_name).casefold():
                    fallback_snapshots += len(snapshot_rows)
                    for source_payload in snapshot_rows:
                        shuju = source_payload.get("shuju") if isinstance(source_payload.get("shuju"), dict) else {}
                        history = shuju.get("recent_matches") or shuju.get("state_memory_matches")
                        if isinstance(history, dict) and any(isinstance(rows, list) and rows for rows in history.values()):
                            fallback_with_history += 1
                            fallback_history_rows += sum(
                                len(rows) for rows in history.values() if isinstance(rows, list)
                            )

        state, mode = _state_for_sidecar(sidecar, prediction)
        source_modes[mode] += 1
        if not state:
            continue
        state_status[str(state.get("capture_status") or "UNKNOWN")] += 1
        target = state.get("target_fixture") if isinstance(state.get("target_fixture"), dict) else {}
        if target.get("source_fixture_id") is not None:
            current_target_fixture_count += 1
        if target.get("home_team_id") is not None and target.get("away_team_id") is not None:
            current_target_identity_count += 1
        for group in ("home_team", "away_team"):
            rows = ((state.get("history") or {}).get(group) or [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                totals["history_rows"] += 1
                if row.get("source_fixture_id") is not None:
                    totals["source_fixture_id"] += 1
                if row.get("home_team_id") is not None and row.get("away_team_id") is not None:
                    totals["team_id_pairs"] += 1
                if row.get("match_date"):
                    totals["match_date"] += 1
                if row.get("kickoff_at"):
                    totals["kickoff_at"] += 1
                if row.get("home_goals_90m") is not None and row.get("away_goals_90m") is not None:
                    totals["score_90m"] += 1
                if row.get("raw_competition_label") not in (None, ""):
                    totals["competition_direct"] += 1
                if row.get("competition_resolution_status") == "RESOLVED":
                    totals["competition_resolved"] += 1
                if row.get("is_club_friendly") is True:
                    totals["club_friendly"] += 1
                if row.get("subject_identity_status") == "RESOLVED":
                    totals["subject_identity"] += 1
        if len(sample_records) < 3:
            sample_records.append({
                "prediction_id": sidecar.get("prediction_id"),
                "state_mode": mode,
                "state_capture_status": state.get("capture_status"),
                "history_row_count": (state.get("coverage") or {}).get("history_row_count"),
            })

    rows = int(totals["history_rows"])
    resolved = int(totals["competition_resolved"])
    nowscore_sources = int(providers.get("nowscore", 0))
    source = _load_current_nowscore_source()
    source_probe = _source_truth_probe(source) if source else {
        "status": "FAIL_CLOSED_NO_CURRENT_SOURCE",
        "analysis_rows_sampled": 0,
        "panlu_rows_sampled": 0,
        "row_20_source_fixture_id": {
            "status": "FAIL_CLOSED_NO_CURRENT_SOURCE",
            "semantic_conclusion": None,
            "nonnull_count": 0,
            "null_or_invalid_count": 0,
            "exact_panlu_match_count": 0,
            "team_orientation_date_confirmed_count": 0,
            "id_conflict_count": 0,
            "unpaired_count": 0,
            "promotion_policy": "PROMOTE_ONLY_EXACT_PANLU_MATCH; OTHERWISE_NULL",
            "unpaired_examples": [],
        },
        "row_1_source_competition_id": {
            "status": "DROPPED_FAIL_CLOSED",
            "retained": False,
            "semantic_conclusion": None,
            "reason": "No current source sample was available.",
            "observed_value_counts": {},
        },
    }
    capture_probe = _capture_probe(source) if source else {
        "status": "FAIL_CLOSED",
        "capture_available": False,
        "reason": "No current Nowscore source pair or committed source fixture was available.",
    }
    row20 = source_probe.get("row_20_source_fixture_id") or {}
    source_unpaired = int(row20.get("unpaired_count") or 0)
    source_conflicts = int(row20.get("id_conflict_count") or 0)
    capture_target = capture_probe.get("target_team_identity") or {}
    capture_subject = capture_probe.get("subject_opponent_identity") or {}
    capture_competition = capture_probe.get("competition") or {}
    known_fallback_capability_gap = bool(FALLBACK_MISSING_FIELDS)
    fallback_missing_capability = list(FALLBACK_MISSING_FIELDS)
    fallback_gap_observed_in_sample = fallback_snapshots > 0 and fallback_with_history < fallback_snapshots
    if (
        not source
        or not source_probe.get("analysis_rows_sampled")
        or not capture_probe.get("capture_available")
    ):
        decision = DECISION_FAIL_CLOSED
    elif (
        source_unpaired > 0
        or source_conflicts > 0
        or not capture_target.get("verified_by_source_identity_and_analysis_ids")
        or int(capture_subject.get("unresolved_count") or 0) > 0
        or int(capture_competition.get("unresolved_count") or 0) > 0
        or known_fallback_capability_gap
    ):
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_READY

    legacy_coverage = {
        "sample": {
            "available_sidecars": len(loaded),
            "selected_sidecars": len(selected),
            "selection": "latest evidence_captured_at descending; filename tie-break",
        },
        "competition": {
            "direct_label_count": int(totals["competition_direct"]),
            "resolved_count": resolved,
            "unresolved_count": rows - resolved,
            "resolved_coverage": _ratio(resolved, rows),
            "resolved_coverage_percent": _percent(resolved, rows),
        },
        "identity": {
            "source_fixture_id_count": int(totals["source_fixture_id"]),
            "source_fixture_id_coverage": _ratio(int(totals["source_fixture_id"]), rows),
            "team_id_pair_count": int(totals["team_id_pairs"]),
            "team_id_pair_coverage": _ratio(int(totals["team_id_pairs"]), rows),
            "history_subject_identity_count": int(totals["subject_identity"]),
            "history_subject_identity_coverage": _ratio(int(totals["subject_identity"]), rows),
            "current_target_fixture_identity_count": current_target_fixture_count,
            "current_target_team_identity_count": current_target_identity_count,
            "current_target_team_identity_coverage": _ratio(current_target_identity_count, len(selected)),
        },
        "history": {
            "row_count": rows,
            "match_date_count": int(totals["match_date"]),
            "match_date_coverage": _ratio(int(totals["match_date"]), rows),
            "kickoff_at_count": int(totals["kickoff_at"]),
            "score_90m_count": int(totals["score_90m"]),
        },
        "club_friendly": {
            "count": int(totals["club_friendly"]),
            "share": _ratio(int(totals["club_friendly"]), resolved),
            "share_percent": _percent(int(totals["club_friendly"]), resolved),
            "denominator": "resolved competition rows",
        },
        "source_usage": {
            "source_snapshot_count": source_snapshot_count,
            "providers": dict(providers),
            "state_capture_status_counts": dict(state_status),
            "source_modes": dict(source_modes),
        },
        "interpretation": "Legacy reconstruction coverage only; it does not rewrite or certify historical/frozen data as prospective capture.",
    }
    fallback_usage = {
        "source_snapshots": fallback_snapshots,
        "snapshots_with_per_fixture_history": fallback_with_history,
        "history_rows": fallback_history_rows,
        "observed": fallback_snapshots > 0,
        "observed_gap_in_selected_sample": fallback_gap_observed_in_sample,
    }
    fallback_capability = {
        "status": "KNOWN_GAP",
        "can_populate_full_contract": False,
        "missing_fields": fallback_missing_capability,
        "basis": "Existing 500.com fallback path exposes aggregate recent_form only; no per-fixture history identity/competition path is present.",
    }
    prospective_capability = {
        "source_truth": source_probe,
        "capture": capture_probe,
        "500.com": {
            "latest_sample_observed_usage": fallback_usage,
            "KNOWN_FALLBACK_CAPABILITY_GAP": fallback_capability,
        },
        "readiness_inputs": {
            "current_source_rows_available": bool(source_probe.get("analysis_rows_sampled")),
            "row20_unpaired_count": source_unpaired,
            "row20_id_conflict_count": source_conflicts,
            "target_team_identity_verified": bool(
                capture_target.get("verified_by_source_identity_and_analysis_ids")
            ),
            "subject_opponent_unresolved_count": int(capture_subject.get("unresolved_count") or 0),
            "competition_unresolved_count": int(capture_competition.get("unresolved_count") or 0),
            "known_fallback_capability_gap": known_fallback_capability_gap,
        },
        "decision_rule": "FAIL_CLOSED when current source/capture is unavailable; PARTIAL when any source/capture coverage or known fallback capability gap remains; READY only when all current-source checks pass and no known gap remains.",
        "readiness_decision": decision,
    }

    return {
        "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "state_memory_contract_version": STATE_MEMORY_CONTRACT_VERSION,
        "read_scope": [
            "data/prospective/football_evidence/*.json",
            "data/model_governance/predictions/*.json",
            "embedded input_snapshot.source_snapshots",
            "data/source_cache/nowscore/raw/*_analysis.js + *_panlu.html + *_3in1.html (read-only if present)",
            "tests/fixtures/nowscore_state_memory/current_source_sample.json (committed fallback)",
        ],
        "network_used": False,
        "LEGACY_RECONSTRUCTION_COVERAGE": legacy_coverage,
        "PROSPECTIVE_CAPTURE_CAPABILITY": prospective_capability,
        "sample": {
            "available_sidecars": len(loaded),
            "selected_sidecars": len(selected),
            "selection": "latest evidence_captured_at descending; filename tie-break",
        },
        "readiness_decision": decision,
        "competition": {
            "direct_label_count": int(totals["competition_direct"]),
            "resolved_count": resolved,
            "unresolved_count": rows - resolved,
            "resolved_coverage": _ratio(resolved, rows),
            "resolved_coverage_percent": _percent(resolved, rows),
        },
        "identity": {
            "source_fixture_id_count": int(totals["source_fixture_id"]),
            "source_fixture_id_coverage": _ratio(int(totals["source_fixture_id"]), rows),
            "team_id_pair_count": int(totals["team_id_pairs"]),
            "team_id_pair_coverage": _ratio(int(totals["team_id_pairs"]), rows),
            "history_subject_identity_count": int(totals["subject_identity"]),
            "history_subject_identity_coverage": _ratio(int(totals["subject_identity"]), rows),
            "current_target_fixture_identity_count": current_target_fixture_count,
            "current_target_team_identity_count": current_target_identity_count,
            "current_target_team_identity_coverage": _ratio(current_target_identity_count, len(selected)),
        },
        "history": {
            "row_count": rows,
            "match_date_count": int(totals["match_date"]),
            "match_date_coverage": _ratio(int(totals["match_date"]), rows),
            "kickoff_at_count": int(totals["kickoff_at"]),
            "score_90m_count": int(totals["score_90m"]),
        },
        "club_friendly": {
            "count": int(totals["club_friendly"]),
            "share": _ratio(int(totals["club_friendly"]), resolved),
            "share_percent": _percent(int(totals["club_friendly"]), resolved),
            "denominator": "resolved competition rows",
        },
        "sources": {
            "source_snapshot_count": source_snapshot_count,
            "providers": dict(providers),
            "nowscore_primary": {
                "source_snapshots": nowscore_sources,
                "history_rows_from_current_panlu": rows,
                "direct_competition_supported": bool(totals["competition_direct"]),
                "stable_fixture_identity_supported": bool(totals["source_fixture_id"]),
            },
            "500_fallback": {
                **fallback_usage,
                **fallback_capability,
                "note": "Latest sample usage is reported separately from the known fallback capability gap; no new provider or network path was added.",
            },
        },
        "state_capture_status_counts": dict(state_status),
        "known_gaps": [
            "legacy persisted sidecars predate State Memory v1 and are not rewritten",
            "current deterministic input snapshots intentionally project away raw recent-match rows; audit joins them from the persisted research sidecar and existing panlu context",
            "Nowscore analysis row[20] is promoted only after exact panlu match_id corroboration; unpaired values remain null",
            "Nowscore analysis row[1] is dropped fail-closed because its field-level semantic is not independently proven",
            "500.com fallback lacks per-fixture history identity/competition fields (known capability gap; separate from latest sample usage)",
            "500.com fallback capability gap is recorded in PROSPECTIVE_CAPTURE_CAPABILITY",
        ],
        "sample_records": sample_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200, help="latest sidecars to inspect; 0 means all")
    parser.add_argument("--output", type=Path, help="optional JSON output path outside data stores")
    args = parser.parse_args()
    result = _audit(args.limit)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
