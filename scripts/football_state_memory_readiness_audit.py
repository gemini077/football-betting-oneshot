#!/usr/bin/env python3
"""Audit current tracked evidence for prospective State Memory readiness.

The audit is intentionally offline.  It reads only the current tracked
football evidence, frozen prediction records, and embedded deterministic
input snapshots.  It never contacts a provider and never writes under the
prospective, frozen, or model-governance data directories.
"""

from __future__ import annotations

import argparse
import copy
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
                if "500" in str(source_name).casefold():
                    fallback_snapshots += 1
                    if isinstance(snapshots, list) and snapshots and isinstance(snapshots[0], dict):
                        source_payload = snapshots[0]
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
    fallback_gap = fallback_snapshots > 0 and fallback_with_history < fallback_snapshots
    missing_capability = list(FALLBACK_MISSING_FIELDS) if fallback_gap or fallback_snapshots == 0 else []
    if not selected or rows == 0 or nowscore_sources == 0:
        decision = DECISION_FAIL_CLOSED
    elif fallback_gap or resolved < rows or totals["source_fixture_id"] < rows:
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_READY

    return {
        "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "state_memory_contract_version": STATE_MEMORY_CONTRACT_VERSION,
        "read_scope": [
            "data/prospective/football_evidence/*.json",
            "data/model_governance/predictions/*.json",
            "embedded input_snapshot.source_snapshots",
        ],
        "network_used": False,
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
                "source_snapshots": fallback_snapshots,
                "snapshots_with_per_fixture_history": fallback_with_history,
                "history_rows": fallback_history_rows,
                "can_populate_full_contract": not fallback_gap and fallback_snapshots > 0,
                "missing_fields": missing_capability,
                "note": "Existing fallback exposes aggregate recent_form only; no new provider or network path was added.",
            },
        },
        "state_capture_status_counts": dict(state_status),
        "known_gaps": [
            "legacy persisted sidecars predate State Memory v1 and are not rewritten",
            "current deterministic input snapshots intentionally project away raw recent-match rows; audit joins them from the persisted research sidecar and existing panlu context",
            *(["500.com fallback lacks per-fixture history identity/competition fields"] if fallback_gap or fallback_snapshots == 0 else []),
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
