"""Batch the Phase2C1 research candidate into the existing pair-capture path.

The caller supplies a future schedule contract, strictly prematch history, and
already-frozen Champion records.  This module only produces research-only
candidate files and delegates pairing to ``capture_forward_pairs``; it does
not fetch data, settle matches, or promote a model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from model_governance import canonical_json, prediction_content_hash
from prospective_pair_capture import (
    BASE_DIR,
    DEFAULT_CHALLENGER_ROOT,
    DEFAULT_PAIR_ROOT,
    DEFAULT_RAW_FROZEN_PATH,
    capture_forward_pairs,
)
from football_data.phase2c1_prospective_candidate import (
    build_prospective_candidate_record,
    validate_candidate_record,
)


DEFAULT_PROSPECTIVE_ROOT = BASE_DIR / "data" / "prospective"


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE_ISO8601")
    return parsed.astimezone(timezone.utc)


def _match_key(record: Mapping[str, Any]) -> str:
    identity = record.get("match_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    return str(record.get("match_key") or identity.get("match_key") or "").strip()


def _schedule_rows(schedule: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if schedule is None:
        return []
    if isinstance(schedule, Mapping):
        fixtures = schedule.get("fixtures")
        if isinstance(fixtures, list):
            return [row for row in fixtures if isinstance(row, Mapping)]
        return [schedule]
    return [row for row in schedule if isinstance(row, Mapping)]


def _unique_index(records: Iterable[Mapping[str, Any]], *, duplicate_code: str) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    errors: dict[str, str] = {}
    for record in records:
        key = _match_key(record)
        if not key:
            errors[f"row-{len(errors) + 1}"] = "MATCH_KEY_MISSING"
        elif key in indexed:
            errors[key] = duplicate_code
        else:
            indexed[key] = record
    return indexed, errors


def _enrich_business_date(record: dict[str, Any], business_date: str | None) -> dict[str, Any]:
    if not business_date:
        return validate_candidate_record(record)
    enriched = dict(record)
    enriched["business_date"] = str(business_date)
    enriched["prediction_sha256"] = prediction_content_hash(enriched)
    return validate_candidate_record(enriched)


def persist_candidate_records(records: Iterable[Mapping[str, Any]], root: Path) -> dict[str, int]:
    """Persist only candidate JSON records, idempotently and hash-checked."""

    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    created = 0
    existing = 0
    for raw in records:
        record = validate_candidate_record(raw)
        prediction_id = str(record.get("prediction_id") or "").strip()
        if not prediction_id:
            raise ValueError("CANDIDATE_PREDICTION_ID_MISSING")
        path = destination / f"{prediction_id}.json"
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("CANDIDATE_FILE_UNREADABLE") from error
            validate_candidate_record(saved)
            if saved.get("prediction_sha256") != record.get("prediction_sha256"):
                raise ValueError("CANDIDATE_FILE_CONTENT_CONFLICT")
            existing += 1
            continue
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        created += 1
    return {"created": created, "existing": existing}


def run_phase2c1_future_batch(
    future_schedule: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    prematch_history: Iterable[Mapping[str, Any]],
    champion_records: Iterable[Mapping[str, Any]],
    *,
    now: str | datetime,
    business_date: str | None = None,
    candidate_root: Path = DEFAULT_CHALLENGER_ROOT,
    pair_root: Path = DEFAULT_PAIR_ROOT,
    raw_frozen_path: Path = DEFAULT_RAW_FROZEN_PATH,
    prospective_root: Path = DEFAULT_PROSPECTIVE_ROOT,
    persist: bool = True,
    capture_pairs: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate future-only candidates and delegate legal pair capture."""

    current = _parse_time(now)
    schedule = _schedule_rows(future_schedule)
    champions, champion_errors = _unique_index(champion_records, duplicate_code="DUPLICATE_CHAMPION_MATCH_KEY")
    candidates: list[dict[str, Any]] = []
    paired_champions: list[dict[str, Any]] = []
    rejections: dict[str, str] = dict(champion_errors)
    seen_schedule: set[str] = set()
    history = [dict(row) for row in prematch_history]

    for index, target in enumerate(schedule):
        key = _match_key(target)
        if not key:
            rejections[f"schedule-{index + 1}"] = "SCHEDULE_MATCH_KEY_MISSING"
            continue
        if key in seen_schedule:
            rejections[key] = "DUPLICATE_SCHEDULE_MATCH_KEY"
            continue
        seen_schedule.add(key)
        champion = champions.get(key)
        if champion is None:
            rejections[key] = "CHAMPION_RECORD_NOT_FOUND"
            continue
        try:
            identity = champion.get("match_identity")
            if not isinstance(identity, Mapping):
                raise ValueError("CHAMPION_MATCH_IDENTITY_MISSING")
            kickoff = _parse_time(identity.get("kickoff_at"))
            source_cutoff = _parse_time(champion.get("source_cutoff_at"))
            if not source_cutoff < current < kickoff:
                raise ValueError("CURRENT_OUTSIDE_PROSPECTIVE_WINDOW")
            candidate = build_prospective_candidate_record(
                target,
                history,
                match_identity=identity,
                source_cutoff_at=source_cutoff,
                prediction_created_at=current,
                freeze_created_at=current,
                now=current,
            )
            candidate_date = business_date or target.get("business_date") or champion.get("business_date")
            candidate = _enrich_business_date(candidate, str(candidate_date) if candidate_date else None)
        except (TypeError, ValueError, OSError) as error:
            rejections[key] = str(error)
            continue
        candidates.append(candidate)
        paired_champions.append(dict(champion))

    persistence = {"created": 0, "existing": 0}
    if persist and candidates:
        persistence = persist_candidate_records(candidates, Path(candidate_root))

    pair_result: dict[str, Any] | None = None
    if capture_pairs:
        pair_result = capture_forward_pairs(
            paired_champions,
            candidates,
            now=current,
            pair_root=Path(pair_root),
            business_date=business_date,
            dry_run=dry_run,
            challenger_source_exists=bool(candidates),
            raw_frozen_path=Path(raw_frozen_path),
            prospective_root=Path(prospective_root),
            formal_rows=[],
        )

    return {
        "research_only": True,
        "production_registration": False,
        "automatic_promotion": False,
        "evidence_scope": "future_prematch_schedule_only",
        "settlement_status": "UNSETTLED_ONLY",
        "settled_evidence_count": 0,
        "business_date": business_date,
        "schedule_rows": len(schedule),
        "candidates_frozen": len(candidates),
        "candidate_records": candidates,
        "persistence": persistence,
        "rejections": dict(sorted(rejections.items())),
        "pair_capture": pair_result,
    }


__all__ = [
    "persist_candidate_records",
    "run_phase2c1_future_batch",
]
