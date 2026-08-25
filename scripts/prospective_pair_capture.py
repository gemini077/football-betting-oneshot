#!/usr/bin/env python3
"""Capture legally paired prospective Champion/Challenger predictions.

This module does not produce a Challenger.  It accepts only independently frozen
standard governance records and appends immutable capture/settlement events to a
single JSONL ledger.  The derived pair state is intentionally separate from the
Champion prospective settlement ledger.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from postmatch_queue import parse_datetime
from prospective_settlement import FROZEN_STATUSES, is_formally_eligible, normalize_result


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PAIR_ROOT = BASE_DIR / "data" / "prospective" / "pairs"
DEFAULT_CHALLENGER_ROOT = BASE_DIR / "data" / "model_governance" / "challenger_predictions"
DEFAULT_RAW_FROZEN_PATH = BASE_DIR / "data" / "paper_ledger" / "frozen.json"
PAIR_LEDGER_NAME = "ledger.jsonl"
PAIR_SUMMARY_NAME = "summary.json"
PAIR_SCHEMA_VERSION = "1.0"
PAIR_CONTRACT_VERSION = "prospective_pair.v1"
GOVERNANCE_COUNT_SCOPE = "TOTAL_SNAPSHOT_AS_OF"
SHANGHAI = timezone(timedelta(hours=8))

_COUNT_SEMANTICS = (
    ("RAW_FROZEN_TICKETS", "total_snapshot_authoritative_raw_frozen_ticket_source", "Total snapshot count of raw frozen ticket rows from data/paper_ledger/frozen.json."),
    ("FORMAL_FROZEN", "total_snapshot_unique_formally_eligible_champion_frozen_predictions", "Total snapshot of Champion frozen records passing the existing formal eligibility policy."),
    ("FORMAL_PROSPECTIVE", "total_snapshot_unique_rows_in_immutable_formal_prospective_ledger", "Total snapshot of formal Champion rows already present in data/prospective/ledger.jsonl."),
    ("SETTLED", "total_snapshot_unique_formal_prospective_rows_with_verified_result", "Total snapshot of formal prospective rows with one verified regulation-90m actual result."),
    ("RESULT_UNRESOLVED", "total_snapshot_formal_frozen_not_in_ledger_past_kickoff", "Total snapshot of formal frozen predictions at or after kickoff not in the formal ledger."),
    ("FUTURE_SCHEDULED_FORMAL", "total_snapshot_formal_frozen_not_in_ledger_future_kickoff", "Total snapshot of formal frozen predictions before kickoff not in the formal ledger."),
    ("CHAMPION_EVALUABLE", "total_snapshot_valid_pair_capture_events", "Total snapshot of unique pair captures containing a contract-valid Champion member; not all Champion forecasts."),
    ("CHALLENGER_EVALUABLE", "total_snapshot_valid_pair_capture_events", "Total snapshot of unique pair captures containing a contract-valid research-only Challenger member."),
    ("TRUE_PAIRED", "total_snapshot_valid_pair_capture_events_with_shared_verified_result", "Total snapshot of pair captures later settled by one shared verified regulation-90m result."),
)
COUNT_SEMANTICS = {
    name: {"scope": scope, "definition": definition}
    for name, scope, definition in _COUNT_SEMANTICS
}


class PairValidationError(ValueError):
    """A pair or shared result violates the immutable capture contract."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PairConflictError(RuntimeError):
    """An immutable pair event id was reused with different content."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _as_now(value: datetime | None) -> datetime:
    current = value or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def _timestamp(value: Any, code: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise PairValidationError(code)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _iso(value: datetime) -> str:
    return value.astimezone(SHANGHAI).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identity(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("match_identity")
    return value if isinstance(value, dict) else {}


def _match_key(record: dict[str, Any]) -> str:
    identity = _identity(record)
    return _text(record.get("match_key") or identity.get("match_key"))


def _probabilities(record: dict[str, Any]) -> dict[str, Any] | None:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    values = record.get("probabilities") or output.get("probabilities")
    if not isinstance(values, dict):
        return None
    if any(key not in values or not isinstance(values[key], (int, float)) for key in ("home", "draw", "away")):
        return None
    return values


def _validated_member(
    record: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PairValidationError(f"{role.upper()}_RECORD_NOT_OBJECT")
    if record.get("model_role") != role:
        raise PairValidationError(f"{role.upper()}_ROLE_MISMATCH")
    if record.get("prediction_status") not in FROZEN_STATUSES:
        raise PairValidationError(f"{role.upper()}_NOT_FROZEN")
    for field in ("prediction_id", "prediction_sha256", "model_source_fingerprint", "model_run_fingerprint"):
        if record.get(field) in (None, ""):
            raise PairValidationError(f"{role.upper()}_{field.upper()}_MISSING")
    if role == "champion" and not is_formally_eligible(record):
        raise PairValidationError("CHAMPION_NOT_FORMAL")
    if role == "champion" and record.get("challenger_id") not in (None, ""):
        raise PairValidationError("CHAMPION_CANNOT_HAVE_CHALLENGER_ID")
    if role == "challenger":
        if _text(record.get("challenger_id")) == "":
            raise PairValidationError("CHALLENGER_ID_MISSING")
        if _probabilities(record) is None:
            raise PairValidationError("CHALLENGER_OUTPUT_MISSING")
    match_key = _match_key(record)
    if not match_key:
        raise PairValidationError(f"{role.upper()}_CANONICAL_MATCH_KEY_MISSING")
    kickoff = _timestamp(record.get("kickoff_at") or _identity(record).get("kickoff_at"), f"{role.upper()}_KICKOFF_MISSING")
    cutoff = _timestamp(record.get("source_cutoff_at"), f"{role.upper()}_SOURCE_CUTOFF_MISSING")
    created = _timestamp(record.get("prediction_created_at"), f"{role.upper()}_CREATED_AT_MISSING")
    freeze = _timestamp(record.get("freeze_created_at"), f"{role.upper()}_FREEZE_AT_MISSING")
    if not cutoff < created <= freeze < kickoff:
        raise PairValidationError(f"{role.upper()}_TEMPORAL_ORDER_INVALID")
    return {
        "record": record,
        "match_key": match_key,
        "kickoff": kickoff,
        "source_cutoff": cutoff,
        "prediction_created": created,
        "freeze": freeze,
    }


def _pair_identity(
    champion: dict[str, Any],
    challenger: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    champion_info = _validated_member(champion, role="champion")
    challenger_info = _validated_member(challenger, role="challenger")
    if champion_info["match_key"] != challenger_info["match_key"]:
        raise PairValidationError("CANONICAL_MATCH_MISMATCH")
    if champion_info["kickoff"] != challenger_info["kickoff"]:
        raise PairValidationError("KICKOFF_MISMATCH")
    if champion_info["source_cutoff"] != challenger_info["source_cutoff"]:
        raise PairValidationError("EVIDENCE_CUTOFF_MISMATCH")
    for name in ("home", "away"):
        left = _text(_identity(champion).get(name)).casefold()
        right = _text(_identity(challenger).get(name)).casefold()
        if left and right and left != right:
            raise PairValidationError("CANONICAL_TEAM_IDENTITY_MISMATCH")
    if champion_info["record"].get("model_run_fingerprint") == challenger_info["record"].get("model_run_fingerprint"):
        raise PairValidationError("SAME_MODEL_IDENTITY")
    same_model_signature = all(
        champion_info["record"].get(field) == challenger_info["record"].get(field)
        for field in ("model_source_fingerprint", "model_family", "model_core_version")
    )
    if same_model_signature:
        raise PairValidationError("SAME_MODEL_IDENTITY")
    return champion_info, challenger_info


def _member_ref(info: dict[str, Any]) -> dict[str, Any]:
    record = info["record"]
    return {
        "prediction_id": record["prediction_id"],
        "prediction_sha256": record["prediction_sha256"],
        "model_role": record["model_role"],
        "challenger_id": record.get("challenger_id"),
        "model_family": record.get("model_family"),
        "model_core_version": record.get("model_core_version"),
        "model_source_fingerprint": record["model_source_fingerprint"],
        "model_run_fingerprint": record["model_run_fingerprint"],
        "canonical_model_input_sha256": record.get("canonical_model_input_sha256"),
        "model_input_snapshot_ref": record.get("model_input_snapshot_ref"),
        "source_cutoff_at": _iso(info["source_cutoff"]),
        "prediction_created_at": _iso(info["prediction_created"]),
        "freeze_created_at": _iso(info["freeze"]),
    }


def deterministic_pair_id(champion: dict[str, Any], challenger: dict[str, Any]) -> str:
    """Return an id independent of capture time, result, or ledger ordering."""
    champion_info, challenger_info = _pair_identity(champion, challenger)
    material = {
        "contract": PAIR_CONTRACT_VERSION,
        "match_key": champion_info["match_key"],
        "kickoff_at": _iso(champion_info["kickoff"]),
        "evidence_cutoff_at": _iso(champion_info["source_cutoff"]),
        "champion_prediction_id": champion_info["record"]["prediction_id"],
        "champion_prediction_sha256": champion_info["record"]["prediction_sha256"],
        "challenger_prediction_id": challenger_info["record"]["prediction_id"],
        "challenger_prediction_sha256": challenger_info["record"]["prediction_sha256"],
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return f"FBOS-PAIR-{digest[:24]}"


def build_pair_capture(
    champion: dict[str, Any],
    challenger: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _as_now(now)
    champion_info, challenger_info = _pair_identity(champion, challenger)
    if current >= champion_info["kickoff"]:
        raise PairValidationError("RETROACTIVE_PAIR_FORBIDDEN")
    if champion_info["freeze"] > current or challenger_info["freeze"] > current:
        raise PairValidationError("NOT_FROZEN_AT_CAPTURE")
    pair_id = deterministic_pair_id(champion, challenger)
    identity = _identity(champion)
    return {
        "schema_version": PAIR_SCHEMA_VERSION,
        "contract": PAIR_CONTRACT_VERSION,
        "event_type": "PAIR_CAPTURED",
        "pair_id": pair_id,
        "captured_at": _iso(current),
        "match": {
            "match_key": champion_info["match_key"],
            "match_id": champion.get("match_id") or identity.get("match_id"),
            "home": identity.get("home"),
            "away": identity.get("away"),
            "kickoff_at": _iso(champion_info["kickoff"]),
        },
        "evidence_cutoff_at": _iso(champion_info["source_cutoff"]),
        "champion": _member_ref(champion_info),
        "challenger": _member_ref(challenger_info),
        "research_only": True,
        "settlement_status": "UNSETTLED",
    }


def build_pair_settlement(
    pair_capture: dict[str, Any],
    result: dict[str, Any],
    *,
    settled_at: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(pair_capture, dict) or pair_capture.get("event_type") != "PAIR_CAPTURED":
        raise PairValidationError("PAIR_CAPTURE_EVENT_REQUIRED")
    try:
        normalized = normalize_result(result)
    except (TypeError, ValueError) as error:
        message = str(error)
        if "object" in message:
            code = "SHARED_RESULT_NOT_OBJECT"
        elif "scope" in message:
            code = "SHARED_RESULT_NOT_REGULATION_90M"
        elif "score" in message:
            code = "SHARED_RESULT_SCORE_MISSING"
        else:
            code = "SHARED_RESULT_NOT_VERIFIED"
        raise PairValidationError(code) from error
    verified_at = _timestamp(normalized.get("result_verified_at"), "SHARED_RESULT_VERIFIED_AT_MISSING")
    kickoff = _timestamp((pair_capture.get("match") or {}).get("kickoff_at"), "PAIR_KICKOFF_MISSING")
    if verified_at < kickoff:
        raise PairValidationError("SHARED_RESULT_BEFORE_KICKOFF")
    candidate_key = _text(result.get("match_key") or result.get("canonical_match_id"))
    match_key = _text((pair_capture.get("match") or {}).get("match_key"))
    if candidate_key and candidate_key != match_key:
        raise PairValidationError("SHARED_RESULT_MATCH_MISMATCH")
    settled = _as_now(settled_at)
    return {
        "schema_version": PAIR_SCHEMA_VERSION,
        "contract": PAIR_CONTRACT_VERSION,
        "event_type": "PAIR_SETTLED",
        "pair_id": pair_capture["pair_id"],
        "match_key": match_key,
        "shared_result": {
            "home_score_90m": normalized["home_score_90m"],
            "away_score_90m": normalized["away_score_90m"],
            "scope": normalized["scope"],
            "result_verified_at": _iso(verified_at),
            "source": result.get("source"),
        },
        "settled_at": _iso(settled),
    }


def _event_identity(event: dict[str, Any]) -> str:
    return canonical_json({key: value for key, value in event.items() if key not in {"captured_at", "settled_at"}})


def _json_objects(path: Path, *, strict: bool = False) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    objects: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            if strict:
                raise PairConflictError(f"pair ledger JSON error on line {line_number}") from error
            continue
        if isinstance(value, dict):
            objects.append(value)
        elif strict:
            raise PairConflictError(f"pair ledger event on line {line_number} is not an object")
    return objects


def _append_event(path: Path, event: dict[str, Any]) -> dict[str, Any]:
    events = _json_objects(path, strict=True)
    pair_id = _text(event.get("pair_id"))
    event_type = _text(event.get("event_type"))
    for existing in events:
        if _text(existing.get("pair_id")) == pair_id and _text(existing.get("event_type")) == event_type:
            if _event_identity(existing) != _event_identity(event):
                raise PairConflictError(f"PAIR_EVENT_CONFLICT:{event_type}:{pair_id}")
            return {"status": "existing", "event": existing, "pair_id": pair_id}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return {"status": "created", "event": event, "pair_id": pair_id}


class PairLedger:
    """Append-only pair capture/settlement event store."""

    def __init__(self, root: Path = DEFAULT_PAIR_ROOT):
        self.root = Path(root)
        self.path = self.root / PAIR_LEDGER_NAME

    def capture(self, champion: dict[str, Any], challenger: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        event = build_pair_capture(champion, challenger, now=now)
        return _append_event(self.path, event)

    def settle(
        self,
        pair_id: str,
        result: dict[str, Any],
        *,
        settled_at: datetime | None = None,
    ) -> dict[str, Any]:
        state = self.states().get(pair_id)
        if state is None:
            raise PairValidationError("PAIR_CAPTURE_NOT_FOUND")
        event = build_pair_settlement(state["capture"], result, settled_at=settled_at)
        return _append_event(self.path, event)

    def states(self) -> dict[str, dict[str, Any]]:
        captures: dict[str, dict[str, Any]] = {}
        settlements: dict[str, dict[str, Any]] = {}
        for event in _json_objects(self.path, strict=True):
            pair_id = _text(event.get("pair_id"))
            if not pair_id:
                continue
            if event.get("event_type") == "PAIR_CAPTURED":
                captures[pair_id] = event
            elif event.get("event_type") == "PAIR_SETTLED":
                settlements[pair_id] = event
        return {
            pair_id: {
                "pair_id": pair_id,
                "capture": capture,
                "settlement": settlements.get(pair_id),
                "CHAMPION_EVALUABLE": True,
                "CHALLENGER_EVALUABLE": True,
                "TRUE_PAIRED": pair_id in settlements,
                "shared_result": (settlements.get(pair_id) or {}).get("shared_result"),
            }
            for pair_id, capture in captures.items()
        }


def _json_records(root: Path, business_date: str | None = None) -> list[dict[str, Any]]:
    if not Path(root).is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(Path(root).glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        if business_date and str(value.get("business_date") or "") != business_date:
            continue
        records.append(value)
    return records


def _raw_frozen_rows(path: Path) -> tuple[list[Any], str]:
    if not Path(path).is_file():
        return [], "MISSING"
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], "INVALID"
    if isinstance(payload, list):
        return payload, "OK"
    if isinstance(payload, dict) and isinstance(payload.get("tickets"), list):
        return payload["tickets"], "OK"
    return [], "INVALID_SHAPE"


def _row_prediction_id(row: dict[str, Any]) -> str:
    return _text(row.get("prediction_id") or row.get("id"))


def _is_settled_row(row: dict[str, Any]) -> bool:
    actual = row.get("actual")
    return (
        isinstance(actual, dict)
        and actual.get("home_score") is not None
        and actual.get("away_score") is not None
        and bool(row.get("result_verified_at") or row.get("result_source") or row.get("result_ref"))
    )


def build_governance_counts(
    frozen_records: Iterable[dict[str, Any]],
    formal_rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    raw_frozen_path: Path = DEFAULT_RAW_FROZEN_PATH,
    pair_root: Path = DEFAULT_PAIR_ROOT,
) -> dict[str, Any]:
    current = _as_now(now)
    records = [row for row in frozen_records if isinstance(row, dict)]
    champion_formal = {
        _row_prediction_id(row): row
        for row in records
        if _row_prediction_id(row) and is_formally_eligible(row)
    }
    rows_by_id = {
        _row_prediction_id(row): row
        for row in formal_rows
        if isinstance(row, dict) and _row_prediction_id(row)
        and row.get("formal_prospective_eligible", True) is not False
    }
    settled_ids = {pid for pid, row in rows_by_id.items() if _is_settled_row(row)}
    future = 0
    unresolved = 0
    for record in champion_formal.values():
        prediction_id = _row_prediction_id(record)
        if prediction_id in rows_by_id:
            continue
        kickoff = parse_datetime(record.get("kickoff_at") or _identity(record).get("kickoff_at"))
        if kickoff is not None and kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=SHANGHAI)
        if kickoff is not None and kickoff.astimezone(SHANGHAI) > current:
            future += 1
        else:
            unresolved += 1
    raw_rows, raw_status = _raw_frozen_rows(Path(raw_frozen_path))
    states = PairLedger(pair_root).states()
    pair_count = len(states)
    true_paired = sum(1 for state in states.values() if state["TRUE_PAIRED"])
    counts = {
        "RAW_FROZEN_TICKETS": len(raw_rows),
        "FORMAL_FROZEN": len(champion_formal),
        "FORMAL_PROSPECTIVE": len(rows_by_id),
        "SETTLED": len(settled_ids),
        "RESULT_UNRESOLVED": unresolved,
        "FUTURE_SCHEDULED_FORMAL": future,
        "CHAMPION_EVALUABLE": pair_count,
        "CHALLENGER_EVALUABLE": pair_count,
        "TRUE_PAIRED": true_paired,
        "CHAMPION_EVALUABLE_PAIR_CONTRACT": pair_count,
        "governance_count_scope": GOVERNANCE_COUNT_SCOPE,
        "raw_frozen_source_status": raw_status,
        "pair_ledger_path": str(Path(pair_root) / PAIR_LEDGER_NAME),
        "as_of": _iso(current),
        "semantics": deepcopy(COUNT_SEMANTICS),
    }
    return counts


def capture_forward_pairs(
    champion_records: Iterable[dict[str, Any]],
    challenger_records: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    pair_root: Path = DEFAULT_PAIR_ROOT,
    business_date: str | None = None,
    dry_run: bool = False,
    challenger_source_exists: bool | None = None,
    raw_frozen_path: Path = DEFAULT_RAW_FROZEN_PATH,
    prospective_root: Path = BASE_DIR / "data" / "prospective",
    formal_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = _as_now(now)
    champion = [
        row for row in champion_records
        if isinstance(row, dict)
        and (not business_date or str(row.get("business_date") or "") == business_date)
    ]
    challenger = [
        row for row in challenger_records
        if isinstance(row, dict)
        and (not business_date or str(row.get("business_date") or "") == business_date)
    ]
    by_match: dict[str, list[dict[str, Any]]] = {}
    for row in challenger:
        key = _match_key(row)
        if key:
            by_match.setdefault(key, []).append(row)
    ledger = PairLedger(pair_root)
    rejections: Counter[str] = Counter()
    captured_this_run = 0
    would_capture = 0
    for row in champion:
        if row.get("prediction_status") not in FROZEN_STATUSES:
            continue
        if not is_formally_eligible(row):
            rejections["CHAMPION_NOT_FORMAL"] += 1
            continue
        key = _match_key(row)
        if not key:
            rejections["CHAMPION_CANONICAL_MATCH_KEY_MISSING"] += 1
            continue
        candidates = by_match.get(key, [])
        if not candidates:
            rejections["CHALLENGER_NOT_AVAILABLE"] += 1
            continue
        if len(candidates) != 1:
            rejections["MULTIPLE_CHALLENGER_CANDIDATES"] += 1
            continue
        try:
            event = build_pair_capture(row, candidates[0], now=current)
        except PairValidationError as error:
            rejections[error.code] += 1
            continue
        if dry_run:
            would_capture += 1
            continue
        outcome = _append_event(ledger.path, event)
        if outcome["status"] == "created":
            captured_this_run += 1
    counts = build_governance_counts(
        [*champion, *challenger],
        list(formal_rows) if formal_rows is not None else _json_objects(Path(prospective_root) / "ledger.jsonl"),
        now=current,
        raw_frozen_path=raw_frozen_path,
        pair_root=pair_root,
    )
    source_exists = bool(challenger) if challenger_source_exists is None else challenger_source_exists
    return {
        "readiness": "READY_FOR_FORWARD_CAPTURE",
        "challenger_producer": "AVAILABLE" if source_exists else "NOT_CONFIGURED",
        "dry_run": dry_run,
        "pairs_captured_this_run": captured_this_run,
        "pairs_would_capture": would_capture,
        "pair_rejections": dict(sorted(rejections.items())),
        **counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="business date in YYYY-MM-DD")
    parser.add_argument("--now", help="deterministic current time")
    parser.add_argument("--champion-root", type=Path, default=BASE_DIR / "data" / "model_governance" / "predictions")
    parser.add_argument("--challenger-root", type=Path, default=DEFAULT_CHALLENGER_ROOT)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--prospective-root", type=Path, default=BASE_DIR / "data" / "prospective")
    parser.add_argument("--raw-frozen-path", type=Path, default=DEFAULT_RAW_FROZEN_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(SHANGHAI)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    champion = _json_records(args.champion_root, args.date)
    challenger = _json_records(args.challenger_root, args.date)
    formal_rows = _json_objects(args.prospective_root / "ledger.jsonl")
    payload = capture_forward_pairs(
        champion,
        challenger,
        now=now,
        pair_root=args.pair_root,
        business_date=args.date,
        dry_run=args.dry_run,
        challenger_source_exists=bool(challenger),
        prospective_root=args.prospective_root,
        formal_rows=formal_rows,
    )
    payload["business_date"] = args.date
    if not args.dry_run:
        args.pair_root.mkdir(parents=True, exist_ok=True)
        (args.pair_root / PAIR_SUMMARY_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
