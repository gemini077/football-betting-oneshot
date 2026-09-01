"""Run the Champion once for every eligible BASE job and freeze it.

This runner is deliberately smaller than the deep-analysis pipeline.  Its
only output authority is the existing model-governance store; it does not
create a second prediction or report format.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from automatic_model_core import (  # noqa: E402
    MODEL_FAMILY,
    _consensus_probabilities,
    build_automatic_model,
)
from fetch_and_parse import DEFAULT_CACHE_DIR, fetch_and_parse  # noqa: E402
from fetch_trade_matches import fetch_trade_matches  # noqa: E402
from match_identity import canonical_match_id  # noqa: E402
from model_governance import (  # noqa: E402
    DEFAULT_INPUT_SNAPSHOT_ROOT,
    DEFAULT_RECORD_ROOT,
    PredictionConflictError,
    build_deterministic_model_input_snapshot,
    build_prediction_record,
    freeze_prediction,
    load_config,
    load_frozen_prediction,
    prediction_content_hash,
)
from nowscore_markets import fetch_match_markets  # noqa: E402
from prediction_universe import load_prediction_universe  # noqa: E402
from prediction_quality import recent_form_is_usable  # noqa: E402
from recent_form_cache import (  # noqa: E402
    load_authoritative_recent_form,
    load_recent_form_cache,
    refresh_recent_form_cache,
)


JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"
ANALYSIS_INPUT_ROOT = PROJECT_ROOT / "data" / "analysis_inputs" / "automated"
UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"
LOCAL_TZ = timezone(timedelta(hours=8))
RETRYABLE_STATUSES = {"PENDING", "INSUFFICIENT_DATA", "PREDICTION_FAILED", "FROZEN"}
TERMINAL_STATUSES = {"MISSED_PREMATCH_WINDOW", "PREDICTED"}
UNIVERSE_STATUSES = {"READY", "EMPTY_CONFIRMED"}
FOOTBALL_EVIDENCE_CONTRACT_VERSION = "prospective_football_evidence.v1"
DEFAULT_FOOTBALL_EVIDENCE_ROOT = PROJECT_ROOT / "data" / "prospective" / "football_evidence"
DEFAULT_MARKET_SIDE_SHADOW_ROOT = PROJECT_ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
_FOOTBALL_EVIDENCE_MATCH_FIELDS = (
    "source_date", "match_date", "home_team_id", "home_team_name",
    "away_team_id", "away_team_name", "home_goals", "away_goals",
)
INPUT_PROVENANCE_DIAGNOSTIC_SCHEMA = "input_provenance_diagnostic.v1"
PROVENANCE_STAGE_SOURCE_HAS_NO_USABLE_RECENT_FORM = "SOURCE_HAS_NO_USABLE_RECENT_FORM"
PROVENANCE_STAGE_SOURCE_FETCH_FAILED = "SOURCE_FETCH_FAILED"
PROVENANCE_STAGE_SOURCE_OBSERVATION_TIMESTAMP_INVALID = "SOURCE_OBSERVATION_TIMESTAMP_MISSING_OR_INVALID"
PROVENANCE_STAGE_CACHE_PROVENANCE_INVALID = "CACHE_PROVENANCE_INVALID"
PROVENANCE_STAGE_EXISTING_FORM_TIMESTAMP_INVALID = "EXISTING_FORM_TIMESTAMP_INVALID"
PROVENANCE_STAGE_OFFICIAL_MARKET_TIMESTAMP_INVALID = "OFFICIAL_MARKET_TIMESTAMP_INVALID"
PROVENANCE_STAGE_DETERMINISTIC_SNAPSHOT_FAILED = "DETERMINISTIC_INPUT_SNAPSHOT_CONSTRUCTION_FAILED"
PROVENANCE_STAGE_SOURCE_CUTOFF_FAILED = "SOURCE_CUTOFF_FAILED"
PROVENANCE_STAGE_MARKET_CUTOFF_FAILED = "MARKET_SNAPSHOT_CUTOFF_FAILED"
PROVENANCE_STAGE_OTHER = "OTHER_DETERMINISTIC_CAUSE"


_PROVENANCE_DIAGNOSTIC_PRIORITY = (
    PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
    PROVENANCE_STAGE_SOURCE_OBSERVATION_TIMESTAMP_INVALID,
    PROVENANCE_STAGE_SOURCE_CUTOFF_FAILED,
    PROVENANCE_STAGE_EXISTING_FORM_TIMESTAMP_INVALID,
    PROVENANCE_STAGE_CACHE_PROVENANCE_INVALID,
    PROVENANCE_STAGE_OFFICIAL_MARKET_TIMESTAMP_INVALID,
    PROVENANCE_STAGE_DETERMINISTIC_SNAPSHOT_FAILED,
    PROVENANCE_STAGE_MARKET_CUTOFF_FAILED,
    PROVENANCE_STAGE_SOURCE_HAS_NO_USABLE_RECENT_FORM,
    PROVENANCE_STAGE_OTHER,
)


class GovernanceContractBlocker(RuntimeError):
    """The existing governance contract rejected the minimum BASE payload."""


def _diagnostic_detail(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    return text[:300] if text else None


def _provenance_diagnostic(
    stage: str,
    *,
    error_code: str,
    source: str | None = None,
    status: str | None = None,
    detail: Any = None,
    captured_at: Any = None,
    expected_before: Any = None,
    references: list[str] | None = None,
    pages: list[str] | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "schema_version": INPUT_PROVENANCE_DIAGNOSTIC_SCHEMA,
        "stage": stage,
        "error_code": error_code,
    }
    if source:
        diagnostic["source"] = str(source)
    if status:
        diagnostic["status"] = str(status)
    normalized_detail = _diagnostic_detail(detail)
    if normalized_detail:
        diagnostic["detail"] = normalized_detail
    captured = _iso(captured_at)
    if captured:
        diagnostic["captured_at"] = captured
    expected = _iso(expected_before)
    if expected:
        diagnostic["expected_before"] = expected
    if references:
        diagnostic["references"] = list(dict.fromkeys(str(value) for value in references if value))
    if pages:
        diagnostic["pages"] = list(dict.fromkeys(str(value) for value in pages if value))
    return diagnostic


def _nowscore_identity_diagnostic(result: dict[str, Any], references: list[str]) -> dict[str, Any]:
    """Persist the identity gate evidence instead of reducing it to a generic failure."""

    page_identity = result.get("page_identity") or result.get("identity") or {}
    page_provider_id = result.get("page_provider_id")
    if page_provider_id is None and isinstance(page_identity, dict):
        page_provider_id = page_identity.get("page_provider_id")
    availability_state = result.get("page_provider_id_availability_state")
    if availability_state is None and isinstance(page_identity, dict):
        availability_state = page_identity.get("page_provider_id_availability_state")
    page_provider_id_reason = result.get("page_provider_id_reason")
    if page_provider_id_reason is None and isinstance(page_identity, dict):
        page_provider_id_reason = page_identity.get("page_provider_id_reason")
    diagnostic = _provenance_diagnostic(
        PROVENANCE_STAGE_OTHER,
        error_code="INPUT_PROVENANCE_UNVERIFIED",
        source="nowscore",
        status=str(result.get("status") or "IDENTITY_MISMATCH"),
        detail="nowscore identity verification rejected",
        references=references,
    )
    identity_verification = copy.deepcopy(result.get("identity_verification"))
    trusted_jc_provenance = copy.deepcopy(result.get("trusted_jc_provenance"))
    diagnostic.update({
        "nowscore_status": result.get("status"),
        "resolution": copy.deepcopy(result.get("resolution")),
        "identity_errors": copy.deepcopy(result.get("identity_errors") or []),
        "identity_verification": identity_verification,
        "identity_verification_status": (
            identity_verification.get("status")
            if isinstance(identity_verification, dict)
            else None
        ),
        "identity_verification_reasons": (
            copy.deepcopy(identity_verification.get("reasons") or [])
            if isinstance(identity_verification, dict)
            else []
        ),
        "trusted_jc_provenance": trusted_jc_provenance,
        "trusted_jc_provenance_reasons": (
            copy.deepcopy(trusted_jc_provenance.get("reasons") or [])
            if isinstance(trusted_jc_provenance, dict)
            else []
        ),
        "page_identity": copy.deepcopy(page_identity),
        "parsed_page_provider_id": page_provider_id,
        "page_provider_id": page_provider_id,
        "page_provider_id_availability_state": availability_state,
        "page_provider_id_reason": page_provider_id_reason,
    })
    return diagnostic


def _normalized_signal(value: Any, *, source: str, references: list[str] | None = None) -> dict[str, Any] | None:
    if isinstance(value, dict) and value.get("stage"):
        signal = copy.deepcopy(value)
        signal.setdefault("schema_version", INPUT_PROVENANCE_DIAGNOSTIC_SCHEMA)
        if references and not signal.get("references"):
            signal["references"] = list(dict.fromkeys(str(ref) for ref in references if ref))
        return signal
    if value:
        return _provenance_diagnostic(
            PROVENANCE_STAGE_OTHER,
            error_code="INPUT_PROVENANCE_UNVERIFIED",
            source=source,
            detail="source adapter returned an unclassified failure signal",
            references=references,
        )
    return None


def _failure_result(
    error_code: str,
    stage: str,
    diagnostics: list[dict[str, Any]],
    *,
    source: str | None = None,
    detail: Any = None,
    captured_at: Any = None,
    expected_before: Any = None,
) -> tuple[None, dict[str, Any], str]:
    attempts = [copy.deepcopy(item) for item in diagnostics if isinstance(item, dict) and item.get("stage")]
    selected = next((item for item in reversed(attempts) if item.get("stage") == stage), None)
    if selected is None:
        selected = _provenance_diagnostic(
            stage,
            error_code=error_code,
            source=source,
            detail=detail,
            captured_at=captured_at,
            expected_before=expected_before,
        )
        attempts.append(copy.deepcopy(selected))
    else:
        selected = copy.deepcopy(selected)
        selected["error_code"] = error_code
        if detail and not selected.get("detail"):
            normalized_detail = _diagnostic_detail(detail)
            if normalized_detail:
                selected["detail"] = normalized_detail
        if captured_at and not selected.get("captured_at"):
            normalized_capture = _iso(captured_at)
            if normalized_capture:
                selected["captured_at"] = normalized_capture
        if expected_before and not selected.get("expected_before"):
            normalized_expected = _iso(expected_before)
            if normalized_expected:
                selected["expected_before"] = normalized_expected
    selected["attempts"] = attempts
    return None, {"input_provenance_diagnostic": selected}, error_code


def _select_failure_stage(diagnostics: list[dict[str, Any]]) -> str | None:
    stages = {str(item.get("stage")) for item in diagnostics if isinstance(item, dict) and item.get("stage")}
    return next((stage for stage in _PROVENANCE_DIAGNOSTIC_PRIORITY if stage in stages), None)


def _looks_like_fetch_failure(value: Any) -> bool:
    text = str(value or "").casefold()
    return bool(text) and any(
        marker in text
        for marker in (
            "fetch failed",
            "url error",
            "http error",
            "connection refused",
            "connectionrefused",
            "connection error",
            "timeout",
            "timed out",
            "unreachable",
        )
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _remember_prediction_id(job: dict[str, Any], prediction_id: Any) -> None:
    """Keep an append-only audit pointer while retaining legacy single-pointer jobs."""
    history = job.get("prediction_ids")
    if not isinstance(history, list):
        history = []
    current = str(job.get("prediction_id") or "").strip()
    if current and current not in history:
        history.append(current)
    value = str(prediction_id or "").strip()
    if value and value not in history:
        history.append(value)
    job["prediction_ids"] = history


_FRESHNESS_KEYS = frozenset({"fetched_at", "captured_at", "source_timestamp", "source_time"})


def _stable_model_input_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_model_input_projection(child)
            for key, child in value.items()
            if str(key).casefold() not in _FRESHNESS_KEYS
        }
    if isinstance(value, list):
        return [_stable_model_input_projection(child) for child in value]
    return value


def _stable_model_input_hash(input_snapshot: dict[str, Any] | None) -> str:
    projection = None
    if isinstance(input_snapshot, dict):
        projection = input_snapshot.get("projection") or input_snapshot.get("input")
    if not isinstance(projection, dict):
        return ""
    canonical = json.dumps(
        _stable_model_input_projection(projection),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _same_deterministic_input(
    job: dict[str, Any],
    input_snapshot: dict[str, Any],
    kickoff: datetime,
    record_root: Path,
    input_snapshot_root: Path,
) -> dict[str, Any] | None:
    """Return the current frozen record when the new deterministic input is identical."""
    prediction_id = str(job.get("prediction_id") or "").strip()
    if not prediction_id:
        return None
    existing = load_frozen_prediction(prediction_id, Path(record_root))
    if not isinstance(existing, dict):
        return None
    if existing.get("job_id") and existing.get("job_id") != job.get("job_id"):
        return None
    if existing.get("match_id") and existing.get("match_id") != job.get("match_id"):
        return None
    existing_kickoff = _parse_timestamp(existing.get("kickoff_at"))
    if existing_kickoff is None or existing_kickoff != kickoff:
        return None
    existing_freeze = _parse_timestamp(existing.get("freeze_created_at"))
    if existing_freeze is None or existing_freeze >= kickoff:
        return None
    new_hash = _stable_model_input_hash(input_snapshot)
    existing_hash = str(existing.get("model_input_stable_sha256") or "").strip()
    if not existing_hash:
        existing_hash = _stable_model_input_hash(existing.get("input_snapshot"))
    if not existing_hash:
        snapshot = existing.get("input_snapshot")
        snapshot_hash = snapshot.get("canonical_input_sha256") if isinstance(snapshot, dict) else None
        if snapshot_hash:
            legacy_snapshot = _load_json(Path(input_snapshot_root) / f"{snapshot_hash}.json")
            existing_hash = _stable_model_input_hash(legacy_snapshot)
    if not existing_hash:
        # Legacy records without a stored projection retain the old hash
        # fallback; new records always use the stable projection hash above.
        existing_hash = str(
            existing.get("canonical_model_input_sha256")
            or existing.get("canonical_input_sha256")
            or existing.get("input_sha256")
            or ""
        ).strip()
    return existing if new_hash and existing_hash and new_hash == existing_hash else None


def _as_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now().astimezone()
    return value.replace(tzinfo=LOCAL_TZ) if value.tzinfo is None else value


def _utc_now() -> datetime:
    """Return the wall-clock instant used for shadow capture auditing."""
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed


def _iso(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed else None


def _present(value: Any) -> bool:
    return value not in (None, "")


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if _present(row.get(key)):
            return row[key]
    return None


def _relative_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _source_ref(path: Path, captured_at: Any = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": _relative_ref(path)}
    normalized = _iso(captured_at)
    if normalized:
        value["captured_at"] = normalized
    return value


def _kickoff(job: dict[str, Any]) -> str:
    return str(job.get("kickoff") or "")


def _job_fixture(universe: dict[str, Any], job: dict[str, Any]) -> dict[str, Any] | None:
    fixtures = universe.get("fixtures") or []
    target_id = str(job.get("match_id") or "")
    if target_id:
        for fixture in fixtures:
            if isinstance(fixture, dict) and str(_first(fixture, "matchId", "match_id", "id") or "") == target_id:
                return fixture
    target_num = str(job.get("match_num") or "")
    for fixture in fixtures:
        if isinstance(fixture, dict) and str(_first(fixture, "matchNum", "match_num") or "") == target_num:
            return fixture
    return None


def _form_is_usable(form: Any) -> bool:
    return recent_form_is_usable(form)


def _valid_spf(odds: Any) -> dict[str, float] | None:
    if not isinstance(odds, dict):
        return None
    try:
        values = {key: float(odds[key]) for key in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 1.0 for value in values.values()):
        return None
    return values


def _fair_probabilities(odds: dict[str, float]) -> dict[str, float]:
    inverse = {key: 1.0 / value for key, value in odds.items()}
    total = sum(inverse.values())
    return {key: round(value / total, 9) for key, value in inverse.items()}


def _official_market_baseline(
    universe: dict[str, Any], fixture: dict[str, Any], kickoff: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    odds = _valid_spf(fixture.get("spf"))
    if odds is None:
        return None, "MISSING_MARKET_INTELLIGENCE"
    captured_at = _parse_timestamp(
        fixture.get("captured_at") or fixture.get("fetched_at") or universe.get("fetched_at")
    )
    if captured_at is None or captured_at >= kickoff:
        return None, "INPUT_TIMESTAMP_UNVERIFIED"
    fair = _fair_probabilities(odds)
    return {
        "source": "sporttery_spf",
        "captured_at": captured_at.isoformat(),
        "source_odds": odds,
        "fair_probabilities": fair,
        "role": "official_market_baseline_only_not_model_probability",
    }, None


def _official_market_failure_signal(
    universe: dict[str, Any],
    fixture: dict[str, Any],
    kickoff: datetime,
    now: datetime,
    error_code: str | None,
    reference: str | None = None,
) -> dict[str, Any] | None:
    if error_code != "INPUT_TIMESTAMP_UNVERIFIED":
        return None
    raw = fixture.get("captured_at") or fixture.get("fetched_at") or universe.get("fetched_at")
    captured_at = _parse_timestamp(raw)
    if captured_at is None:
        return _provenance_diagnostic(
            PROVENANCE_STAGE_OFFICIAL_MARKET_TIMESTAMP_INVALID,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="sporttery_spf",
            detail="official market baseline has no parseable capture timestamp",
            references=[reference or _relative_ref(UNIVERSE_ROOT)],
        )
    return _provenance_diagnostic(
        PROVENANCE_STAGE_MARKET_CUTOFF_FAILED,
        error_code="INPUT_TIMESTAMP_UNVERIFIED",
        source="sporttery_spf",
        status="POST_KICKOFF" if captured_at >= kickoff else "CAPTURE_AFTER_RUN_CLOCK",
        detail="official market capture is not strictly before the prematch cutoff",
        captured_at=captured_at,
        expected_before=min(kickoff, now),
        references=[reference or _relative_ref(UNIVERSE_ROOT)],
    )


def _snapshot_capture(snapshot: dict[str, Any]) -> datetime | None:
    for key in ("fetched_at", "captured_at", "source_timestamp", "source_time"):
        captured = _parse_timestamp(snapshot.get(key))
        if captured:
            return captured
    return None


def _valid_bookmakers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((snapshot.get("ouzhi") or {}).get("bookmakers") or [])
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or _valid_spf(row.get("spf_current")) is None:
            continue
        valid.append(row)
    return valid


def _company_name(row: dict[str, Any]) -> str | None:
    for key in ("name", "company", "company_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    value = str(row.get("cid") or "").strip()
    return f"cid:{value}" if value else None


def _valid_handicap_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((snapshot.get("yazhi") or {}).get("companies") or [])
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not _company_name(row):
            continue
        line_present = row.get("current_handicap") not in (None, "") or row.get("current_handicap_str") not in (None, "")
        if not line_present:
            continue
        try:
            waters = [float(row[key]) for key in ("current_water_home", "current_water_away")]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in waters):
            valid.append(row)
    return valid


def _valid_total_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((snapshot.get("daxiao") or {}).get("companies") or [])
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not _company_name(row):
            continue
        # A display-only line string is not enough to reconstruct a current
        # total line; keep the market fail-closed rather than guessing.
        try:
            current_line = float(row.get("current_line"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(current_line):
            continue
        try:
            waters = [float(row[key]) for key in ("current_over_water", "current_under_water")]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in waters):
            valid.append(row)
    return valid


def _market_families(snapshot: dict[str, Any]) -> list[str]:
    families: list[str] = []
    if _valid_bookmakers(snapshot):
        families.append("1x2")
    if _valid_handicap_rows(snapshot):
        families.append("asian_handicap")
    if _valid_total_rows(snapshot):
        families.append("totals")
    return families


def _market_bookmakers(snapshot: dict[str, Any]) -> list[str]:
    names: list[str] = []
    rows = [
        *_valid_bookmakers(snapshot),
        *_valid_handicap_rows(snapshot),
        *_valid_total_rows(snapshot),
    ]
    for row in rows:
        name = _company_name(row)
        if name and name not in names:
            names.append(name)
    return names


def _market_provider(name: str, snapshot: dict[str, Any] | None = None) -> str:
    providers = _effective_market_providers(snapshot, name) if isinstance(snapshot, dict) else []
    return providers[0] if providers else {"500_deep": "500.com", "nowscore": "nowscore"}.get(name, name)


def _canonical_market_provider(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()
    if lowered.startswith("nowscore"):
        return "nowscore"
    if lowered in {"500_deep", "500.com"} or lowered.startswith("500.com"):
        return "500.com"
    return raw


def _effective_market_providers(snapshot: dict[str, Any], default_name: str | None = None) -> list[str]:
    """Use merged market evidence provenance instead of the cache filename."""
    providers: list[str] = []

    def add(value: object) -> None:
        provider = _canonical_market_provider(value)
        if provider and provider not in providers:
            providers.append(provider)

    provenance = snapshot.get("source_provenance") or {}
    add(provenance.get("market_primary"))
    for value in provenance.get("effective_market_providers") or []:
        add(value)
    for page in ("ouzhi", "yazhi", "daxiao"):
        data = snapshot.get(page)
        if not isinstance(data, dict):
            continue
        rows_key = "bookmakers" if page == "ouzhi" else "companies"
        rows = [row for row in data.get(rows_key) or [] if isinstance(row, dict)]
        if not rows:
            continue
        for row in rows:
            add(row.get("source") or row.get("provider") or row.get("market_source"))
        for value in data.get("sources") or []:
            add(value)
        add(data.get("source"))
    if not providers:
        add(default_name)
    return providers


def _has_full_market(snapshot: dict[str, Any]) -> bool:
    return len(_valid_bookmakers(snapshot)) >= 2 and set(("1x2", "asian_handicap", "totals")) <= set(
        _market_families(snapshot)
    )


def _market_only_baseline(
    snapshot: dict[str, Any], source: str | list[str], source_refs: list[str]
) -> dict[str, Any] | None:
    probabilities = _consensus_probabilities(snapshot)
    if not probabilities:
        return None
    sources = [source] if isinstance(source, str) else list(source)
    return {
        "home": round(float(probabilities["home"]), 9),
        "draw": round(float(probabilities["draw"]), 9),
        "away": round(float(probabilities["away"]), 9),
        "method": "existing_multibook_consensus_devig",
        "sources": [*sources, *source_refs],
    }


def _find_existing_form(
    job: dict[str, Any], kickoff: datetime, now: datetime
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """Reuse only an existing named prematch snapshot with a verifiable time."""
    if not ANALYSIS_INPUT_ROOT.is_dir():
        return None, None, []
    match_id = str(job.get("match_id") or "")
    invalid_signal: dict[str, Any] | None = None
    refs: list[str] = []
    for path in sorted(ANALYSIS_INPUT_ROOT.glob("*.json")):
        payload = _load_json(path)
        if not payload:
            continue
        match = payload.get("match") or {}
        candidate_ids = {
            str(match.get("match_id") or ""),
            str(match.get("canonical_match_id") or ""),
        }
        if match_id and match_id not in candidate_ids:
            continue
        form = (payload.get("fundamentals") or {}).get("recent_form")
        if not _form_is_usable(form):
            continue
        captured_raw = (
            (payload.get("report") or {}).get("analysis_timestamp")
            or payload.get("prediction_created_at")
            or payload.get("fetched_at")
        )
        captured_at = _parse_timestamp(captured_raw)
        refs.append(_relative_ref(path))
        if captured_at is None or captured_at >= now or captured_at >= kickoff:
            if invalid_signal is None:
                invalid_signal = _provenance_diagnostic(
                    PROVENANCE_STAGE_EXISTING_FORM_TIMESTAMP_INVALID,
                    error_code="INPUT_TIMESTAMP_UNVERIFIED",
                    source="existing_prematch_snapshot",
                    status="MISSING_OR_INVALID" if captured_at is None else "OUT_OF_CUTOFF",
                    detail="existing form snapshot timestamp is missing, invalid, or not prematch",
                    captured_at=captured_at,
                    expected_before=min(now, kickoff),
                    references=[_relative_ref(path)],
                )
            continue
        return {
            "recent_form": form,
            "source": "existing_prematch_snapshot",
            "captured_at": captured_at.isoformat(),
            "references": [_source_ref(path, captured_at)],
        }, invalid_signal, refs
    return None, invalid_signal, refs


def _trade_row(
    job: dict[str, Any], fixture: dict[str, Any], payload: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not payload:
        return None
    target_num = str(job.get("match_num") or "")
    target_id = str(_first(fixture, "shujuId", "shuju_id") or "")
    for row in payload.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if target_num and str(row.get("match_num") or "") == target_num:
            return row
        if target_id and str(row.get("shuju_id") or "") == target_id:
            return row
    return None


def _nowscore_source(
    job: dict[str, Any], fixture: dict[str, Any], kickoff: datetime, now: datetime | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    nowscore_id = _first(fixture, "nowscoreId", "nowscore_id")
    status = str(_first(fixture, "nowscoreMatchStatus", "nowscore_match_status") or "")
    if not nowscore_id or status in {"NO_EXACT_MATCH", "AMBIGUOUS_MATCH", "LOW_CONFIDENCE_MATCH"}:
        return None, None, []
    try:
        nowscore_numeric_id = int(nowscore_id)
    except (TypeError, ValueError):
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_OTHER,
            error_code="INPUT_PROVENANCE_UNVERIFIED",
            source="nowscore",
            status="INVALID_PROVIDER_ID",
            detail="nowscore fixture ID is not an integer",
        ), []
    refs = [
        _relative_ref(PROJECT_ROOT / "data" / "source_cache" / "nowscore" / "raw" / f"{nowscore_numeric_id}_3in1.html"),
        _relative_ref(PROJECT_ROOT / "data" / "source_cache" / "nowscore" / "raw" / f"{nowscore_numeric_id}_analysis.js"),
    ]
    try:
        result = fetch_match_markets(
            str(job.get("home") or ""),
            str(job.get("away") or ""),
            job.get("kickoff"),
            explicit_id=nowscore_numeric_id,
            no_cache=False,
            fixture=fixture,
        )
    except Exception as error:
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
            error_code="SOURCE_FETCH_FAILED",
            source="nowscore",
            status="EXCEPTION",
            detail=f"{type(error).__name__}: {error}",
            references=refs,
        ), refs
    if not isinstance(result, dict):
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
            error_code="SOURCE_FETCH_FAILED",
            source="nowscore",
            status="INVALID_RESULT",
            detail="nowscore adapter returned a non-object result",
            references=refs,
        ), refs
    status = str(result.get("status") or "UNKNOWN")
    for key in ("source_url", "analysis_source_url"):
        if result.get(key):
            refs.append(str(result[key]))
    if status != "OK":
        stage = PROVENANCE_STAGE_SOURCE_FETCH_FAILED if status == "FETCH_ERROR" else PROVENANCE_STAGE_OTHER
        error_code = "SOURCE_FETCH_FAILED" if stage == PROVENANCE_STAGE_SOURCE_FETCH_FAILED else "INPUT_PROVENANCE_UNVERIFIED"
        if status == "IDENTITY_MISMATCH":
            return None, _nowscore_identity_diagnostic(result, refs), refs
        return None, _provenance_diagnostic(
            stage,
            error_code=error_code,
            source="nowscore",
            status=status,
            detail=result.get("error") or result.get("resolution") or "nowscore source did not return a usable match",
            references=refs,
        ), refs
    captured_at = _snapshot_capture(result)
    if captured_at is None:
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_OBSERVATION_TIMESTAMP_INVALID,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="nowscore",
            status="MISSING_OR_INVALID",
            detail="nowscore result has no parseable observation timestamp",
            references=refs,
        ), refs
    if captured_at >= kickoff or (now is not None and captured_at > now):
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_CUTOFF_FAILED,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="nowscore",
            status="POST_KICKOFF" if captured_at >= kickoff else "AFTER_RUN_CLOCK",
            detail="nowscore observation is not strictly before the prematch cutoff",
            captured_at=captured_at,
            expected_before=kickoff if now is None else min(kickoff, now),
            references=refs,
        ), refs
    analysis_error = result.get("analysis_error")
    analysis_signal = None
    if analysis_error and _looks_like_fetch_failure(analysis_error):
        analysis_signal = _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
            error_code="SOURCE_FETCH_FAILED",
            source="nowscore",
            status="RECENT_FORM_FETCH_FAILED",
            detail=analysis_error,
            references=refs,
        )
    return {
        "name": "nowscore",
        "snapshot": result,
        "captured_at": captured_at,
        "references": refs,
    }, analysis_signal, refs


def _five_hundred_source(
    business_date: str,
    job: dict[str, Any],
    fixture: dict[str, Any],
    trade_payload: dict[str, Any] | None,
    kickoff: datetime,
    now: datetime | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    trade = _trade_row(job, fixture, trade_payload)
    shuju_id = _first(fixture, "shujuId", "shuju_id") or (trade or {}).get("shuju_id")
    if not shuju_id:
        return None, None, []
    try:
        shuju_numeric_id = int(shuju_id)
    except (TypeError, ValueError):
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_OTHER,
            error_code="INPUT_PROVENANCE_UNVERIFIED",
            source="500_deep",
            status="INVALID_PROVIDER_ID",
            detail="500 deep fixture ID is not an integer",
        ), []
    path = PROJECT_ROOT / "data" / "source_cache" / "shared-football" / "parsed" / f"{business_date}_{shuju_numeric_id}.json"
    refs = [_relative_ref(path)]
    try:
        result = fetch_and_parse(shuju_numeric_id, business_date, DEFAULT_CACHE_DIR, False)
    except Exception as error:
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
            error_code="SOURCE_FETCH_FAILED",
            source="500_deep",
            status="EXCEPTION",
            detail=f"{type(error).__name__}: {error}",
            references=refs,
        ), refs
    if not isinstance(result, dict):
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
            error_code="SOURCE_FETCH_FAILED",
            source="500_deep",
            status="INVALID_RESULT",
            detail="500 deep adapter returned a non-object result",
            references=refs,
        ), refs
    captured_at = _snapshot_capture(result)
    if captured_at is None:
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_OBSERVATION_TIMESTAMP_INVALID,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="500_deep",
            status="MISSING_OR_INVALID",
            detail="500 deep result has no parseable observation timestamp",
            references=refs,
        ), refs
    if captured_at >= kickoff or (now is not None and captured_at > now):
        return None, _provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_CUTOFF_FAILED,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="500_deep",
            status="POST_KICKOFF" if captured_at >= kickoff else "AFTER_RUN_CLOCK",
            detail="500 deep observation is not strictly before the prematch cutoff",
            captured_at=captured_at,
            expected_before=kickoff if now is None else min(kickoff, now),
            references=refs,
        ), refs
    # ``fetch_and_parse`` preserves a capture timestamp even when every 500
    # page failed.  Do not project that error envelope as a usable source
    # snapshot or let it move the deterministic input cutoff.
    fetch_error_pages: list[str] = []
    other_error_pages: list[str] = []
    for page in ("ouzhi", "yazhi", "rangqiu", "daxiao", "shuju", "touzhu"):
        value = result.get(page)
        if not isinstance(value, dict) or not value.get("error"):
            continue
        if _looks_like_fetch_failure(value.get("error")) or _looks_like_fetch_failure(value.get("detail")):
            fetch_error_pages.append(page)
        else:
            other_error_pages.append(page)
    form_usable = _form_is_usable((result.get("shuju") or {}).get("recent_form"))
    market_usable = bool(_market_families(result))
    if not form_usable:
        # ``shuju`` is the 500 page that carries recent form.  A partial
        # snapshot may still contain usable market rows, but it must retain
        # the source-fetch diagnostic when that form page failed.
        if "shuju" in fetch_error_pages:
            signal = _provenance_diagnostic(
                PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
                error_code="SOURCE_FETCH_FAILED",
                source="500_deep",
                status="FETCH_ERROR",
                detail="500 deep recent-form page fetch failed before usable form evidence was built",
                captured_at=captured_at,
                references=refs,
                pages=fetch_error_pages,
            )
            return ({
                "name": "500_deep",
                "snapshot": result,
                "captured_at": captured_at,
                "references": refs,
            } if market_usable else None), signal, refs
        if "shuju" in other_error_pages:
            signal = _provenance_diagnostic(
                PROVENANCE_STAGE_OTHER,
                error_code="INPUT_PROVENANCE_UNVERIFIED",
                source="500_deep",
                status="PARSE_ERROR",
                detail="500 deep recent-form page did not produce usable form evidence",
                captured_at=captured_at,
                references=refs,
                pages=other_error_pages,
            )
            return ({
                "name": "500_deep",
                "snapshot": result,
                "captured_at": captured_at,
                "references": refs,
            } if market_usable else None), signal, refs
        if not market_usable:
            if fetch_error_pages:
                return None, _provenance_diagnostic(
                    PROVENANCE_STAGE_SOURCE_FETCH_FAILED,
                    error_code="SOURCE_FETCH_FAILED",
                    source="500_deep",
                    status="FETCH_ERROR",
                    detail="500 deep page fetch failed before a usable form or market snapshot was built",
                    captured_at=captured_at,
                    references=refs,
                    pages=fetch_error_pages,
                ), refs
            if other_error_pages:
                return None, _provenance_diagnostic(
                    PROVENANCE_STAGE_OTHER,
                    error_code="INPUT_PROVENANCE_UNVERIFIED",
                    source="500_deep",
                    status="PARSE_ERROR",
                    detail="500 deep pages did not produce a usable form or market snapshot",
                    captured_at=captured_at,
                    references=refs,
                    pages=other_error_pages,
                ), refs
            return None, None, refs
    return {
        # Keep the governance/model contract key for source selection; the
        # effective provider is derived from this snapshot's provenance below.
        "name": "500_deep",
        "snapshot": result,
        "captured_at": captured_at,
        "references": refs,
    }, None, refs


def _source_form(source: dict[str, Any]) -> dict[str, Any] | None:
    return ((source.get("snapshot") or {}).get("shuju") or {}).get("recent_form")


def _strip_source_form(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(snapshot)
    shuju = value.get("shuju")
    if isinstance(shuju, dict):
        shuju.pop("recent_form", None)
    return value


def _nowscore_snapshot(source_snapshots: Any) -> dict[str, Any] | None:
    if not isinstance(source_snapshots, dict):
        return None
    source = source_snapshots.get("nowscore")
    snapshots = source.get("snapshots") if isinstance(source, dict) else []
    if not isinstance(snapshots, list) or not snapshots or not isinstance(snapshots[0], dict):
        return None
    return snapshots[0]


def _nowscore_recent_matches(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    shuju = snapshot.get("shuju")
    recent_matches = shuju.get("recent_matches") if isinstance(shuju, dict) else None
    if not isinstance(recent_matches, dict):
        return None
    result: dict[str, list[dict[str, Any]]] = {}
    for group in ("home_team", "away_team"):
        rows = recent_matches.get(group)
        if not isinstance(rows, list):
            return None
        result[group] = []
        for row in rows:
            if not isinstance(row, dict) or not all(
                field in row for field in _FOOTBALL_EVIDENCE_MATCH_FIELDS
            ):
                continue
            result[group].append({
                field: copy.deepcopy(row[field])
                for field in _FOOTBALL_EVIDENCE_MATCH_FIELDS
            })
    return result


def _build_football_evidence_audit(source_snapshots: Any) -> dict[str, Any] | None:
    snapshot = _nowscore_snapshot(source_snapshots)
    if snapshot is None:
        return None
    recent_matches = _nowscore_recent_matches(snapshot)
    if recent_matches is None:
        return None
    evidence: dict[str, Any] = {
        "source_provider": "nowscore",
        "recent_matches": recent_matches,
    }
    nowscore_id = _first(snapshot, "nowscore_id", "nowscoreId")
    if nowscore_id not in (None, ""):
        try:
            nowscore_id = int(nowscore_id)
        except (TypeError, ValueError):
            nowscore_id = str(nowscore_id)
        evidence["nowscore_id"] = nowscore_id
    captured_at = _snapshot_capture(snapshot)
    if captured_at is not None:
        evidence["evidence_captured_at"] = captured_at.isoformat()
    return evidence


def build_football_evidence_sidecar(
    record: dict[str, Any],
    source_snapshots: Any,
    *,
    business_date: str | None = None,
) -> dict[str, Any] | None:
    """Build research-only football evidence without copying the frozen result."""
    evidence = _build_football_evidence_audit(source_snapshots)
    if evidence is None:
        return None
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
    sidecar: dict[str, Any] = {
        "contract_version": FOOTBALL_EVIDENCE_CONTRACT_VERSION,
        "prediction_id": record.get("prediction_id"),
        "match_id": record.get("match_id") or identity.get("match_id"),
        "business_date": business_date or record.get("business_date"),
        "home": record.get("home") or identity.get("home"),
        "away": record.get("away") or identity.get("away"),
        "kickoff_at": record.get("kickoff_at") or identity.get("kickoff_at"),
        "source_provider": "nowscore",
        "evidence_captured_at": evidence.get("evidence_captured_at"),
        "recent_matches": evidence["recent_matches"],
    }
    match_key = record.get("match_key") or identity.get("match_key")
    if match_key not in (None, ""):
        sidecar["match_key"] = match_key
    for key in ("prediction_created_at", "freeze_created_at", "source_cutoff_at"):
        if record.get(key) not in (None, ""):
            sidecar[key] = record[key]
    if "nowscore_id" in evidence:
        sidecar["nowscore_id"] = evidence["nowscore_id"]
    return sidecar


def write_football_evidence_sidecar(
    record: dict[str, Any],
    source_snapshots: Any,
    *,
    evidence_root: Path | None = None,
    business_date: str | None = None,
) -> dict[str, Any]:
    """Write one exclusive research sidecar keyed by prediction_id."""
    try:
        sidecar = build_football_evidence_sidecar(record, source_snapshots, business_date=business_date)
    except Exception as error:
        return {"status": "failed", "reason": f"{type(error).__name__}"}
    if sidecar is None:
        return {"status": "skipped", "reason": "NOWSCORE_RECENT_MATCHES_UNAVAILABLE"}
    prediction_id = str(sidecar.get("prediction_id") or "").strip()
    if not prediction_id:
        return {"status": "skipped", "reason": "MISSING_PREDICTION_ID"}
    root = Path(evidence_root) if evidence_root is not None else DEFAULT_FOOTBALL_EVIDENCE_ROOT
    target = root / f"{prediction_id}.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n"
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
            return {"status": "created", "path": target, "record": sidecar}
        except FileExistsError:
            try:
                existing = _load_json(target)
            except (OSError, json.JSONDecodeError):
                return {"status": "conflict", "path": target, "reason": "EXISTING_SIDECAR_UNREADABLE"}
            if existing == sidecar:
                return {"status": "existing", "path": target, "record": existing}
            return {"status": "conflict", "path": target, "reason": "SIDECAR_CONTENT_CONFLICT"}
    except (OSError, TypeError, ValueError) as error:
        return {"status": "failed", "reason": f"{type(error).__name__}"}


def _resolve_football_evidence_root(record_root: Path, evidence_root: Path | None) -> Path:
    if evidence_root is not None:
        return Path(evidence_root)
    record_path = Path(record_root)
    if record_path.resolve() == DEFAULT_RECORD_ROOT.resolve():
        return DEFAULT_FOOTBALL_EVIDENCE_ROOT
    # A custom governance root is a test/research boundary; keep its sidecar
    # beside that root instead of silently writing into repository data.
    return record_path.parent / "football_evidence"


def _record_football_evidence_status(job: dict[str, Any], result: Any) -> None:
    if not isinstance(result, dict):
        result = {"status": "failed", "reason": "INVALID_WRITER_RESULT"}
    status = str(result.get("status") or "failed")
    job["football_evidence_status"] = status
    path = result.get("path") or result.get("ref")
    if path:
        job["football_evidence_ref"] = str(path)
    if status in {"failed", "conflict"}:
        job["football_evidence_error"] = str(result.get("reason") or "FOOTBALL_EVIDENCE_WRITE_FAILED")
    else:
        job["football_evidence_error"] = None


def _assemble_context(
    business_date: str,
    job: dict[str, Any],
    fixture: dict[str, Any],
    universe: dict[str, Any],
    now: datetime,
    trade_payload: dict[str, Any] | None,
    *,
    real_time: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    kickoff = _parse_timestamp(_kickoff(job))
    if kickoff is None:
        return _failure_result(
            "INPUT_TIMESTAMP_UNVERIFIED",
            PROVENANCE_STAGE_OTHER,
            [],
            source="fixture",
            detail="job kickoff is missing or not parseable",
        )

    source_clock = _as_now(None) if real_time else now
    official, official_error = _official_market_baseline(universe, fixture, kickoff)
    official_capture = _parse_timestamp((official or {}).get("captured_at")) if official else None
    if official is not None and (official_capture is None or official_capture > source_clock):
        official = None
        official_error = "INPUT_TIMESTAMP_UNVERIFIED"
    diagnostics: list[dict[str, Any]] = []
    official_signal = _official_market_failure_signal(
        universe,
        fixture,
        kickoff,
        source_clock,
        official_error,
        _relative_ref(UNIVERSE_ROOT / f"{business_date}.json"),
    )
    if official_signal:
        diagnostics.append(official_signal)
    existing_form, existing_signal, existing_refs = _find_existing_form(job, kickoff, source_clock)
    normalized_existing_signal = _normalized_signal(
        existing_signal,
        source="existing_prematch_snapshot",
        references=existing_refs,
    )
    if normalized_existing_signal:
        diagnostics.append(normalized_existing_signal)
    source_infos: list[dict[str, Any]] = []
    source_refs: list[str] = [
        _relative_ref(UNIVERSE_ROOT / f"{business_date}.json"),
        *existing_refs,
    ]

    nowscore, nowscore_signal, nowscore_refs = _nowscore_source(
        job,
        fixture,
        kickoff,
        None if real_time else source_clock,
    )
    normalized_nowscore_signal = _normalized_signal(
        nowscore_signal,
        source="nowscore",
        references=nowscore_refs,
    )
    if normalized_nowscore_signal:
        diagnostics.append(normalized_nowscore_signal)
    source_refs.extend(nowscore_refs)
    if nowscore:
        source_infos.append(nowscore)

    def has_full_market() -> bool:
        return any(_has_full_market(info["snapshot"]) for info in source_infos)

    def has_form() -> bool:
        return bool(existing_form) or any(_form_is_usable(_source_form(info)) for info in source_infos)

    if not has_full_market() or not has_form():
        five_hundred, five_hundred_signal, five_hundred_refs = _five_hundred_source(
            business_date,
            job,
            fixture,
            trade_payload,
            kickoff,
            None if real_time else source_clock,
        )
        normalized_five_hundred_signal = _normalized_signal(
            five_hundred_signal,
            source="500_deep",
            references=five_hundred_refs,
        )
        if normalized_five_hundred_signal:
            diagnostics.append(normalized_five_hundred_signal)
        source_refs.extend(five_hundred_refs)
        if five_hundred:
            source_infos.append(five_hundred)

    source_refs = list(dict.fromkeys(source_refs))
    source_snapshots: dict[str, dict[str, Any]] = {}
    for info in source_infos:
        source_snapshots[info["name"]] = {
            "snapshots": [info["snapshot"]],
            "source_reference": info["references"][0] if info["references"] else info["name"],
        }

    form = existing_form
    form_source = None
    form_captured_at = None
    form_refs: list[dict[str, Any]] = []
    if form:
        form_source = form["source"]
        form_captured_at = form["captured_at"]
        form_refs = list(form.get("references") or [])
        # The existing snapshot is the declared form source.  Do not allow a
        # later source snapshot to silently replace it in the deterministic
        # projection.
        for value in source_snapshots.values():
            value["snapshots"][0] = _strip_source_form(value["snapshots"][0])
    else:
        for name in ("nowscore", "500_deep"):
            info = next((item for item in source_infos if item["name"] == name), None)
            candidate = _source_form(info) if info else None
            if info and _form_is_usable(candidate):
                form = {
                    "recent_form": candidate,
                    "source": name,
                    "captured_at": info["captured_at"].isoformat(),
                    "references": [_source_ref(Path(ref)) if not ref.startswith(("http://", "https://")) else {"url": ref} for ref in info["references"]],
                }
                form_source = name
                form_captured_at = form["captured_at"]
                form_refs = list(form["references"])
                break

    if not form:
        cache_diagnostics: list[dict[str, Any]] = []
        cached_form = load_recent_form_cache(
            job,
            kickoff.isoformat(),
            source_clock,
            diagnostics=cache_diagnostics,
        )
        for item in cache_diagnostics:
            normalized_cache_signal = _normalized_signal(item, source="recent_form_cache")
            if normalized_cache_signal:
                diagnostics.append(normalized_cache_signal)
        if cached_form:
            form = cached_form
            form_source = cached_form.get("source")
            form_captured_at = cached_form.get("captured_at")
            form_refs = list(cached_form.get("references") or [])
            source_refs.extend(str(ref) for ref in cached_form.get("source_refs") or [])

    if not form:
        authoritative_form = load_authoritative_recent_form(
            job,
            fixture,
            kickoff.isoformat(),
            source_clock,
        )
        if authoritative_form:
            form = authoritative_form
            form_source = authoritative_form.get("source")
            form_captured_at = authoritative_form.get("captured_at")
            form_refs = list(authoritative_form.get("references") or [])
            source_refs.extend(str(ref) for ref in authoritative_form.get("source_refs") or [])

    if not form or not _form_is_usable(form.get("recent_form")):
        stage = _select_failure_stage(diagnostics) or PROVENANCE_STAGE_SOURCE_HAS_NO_USABLE_RECENT_FORM
        error_code = "INPUT_TIMESTAMP_UNVERIFIED"
        if stage == PROVENANCE_STAGE_SOURCE_FETCH_FAILED:
            error_code = "SOURCE_FETCH_FAILED"
        elif stage == PROVENANCE_STAGE_SOURCE_HAS_NO_USABLE_RECENT_FORM:
            error_code = "MISSING_RECENT_FORM"
        elif stage == PROVENANCE_STAGE_CACHE_PROVENANCE_INVALID:
            error_code = "CACHE_PROVENANCE_INVALID"
        elif stage == PROVENANCE_STAGE_OTHER:
            error_code = "INPUT_PROVENANCE_UNVERIFIED"
        return _failure_result(
            error_code,
            stage,
            diagnostics,
            source="recent_form",
            detail="no eligible prematch recent-form source remained after deterministic validation",
            expected_before=kickoff,
        )

    full_source = next((info for info in source_infos if _has_full_market(info["snapshot"])), None)
    market_source = next(
        (info for info in source_infos if "1x2" in _market_families(info["snapshot"])),
        None,
    )
    market_quality = "FULL" if full_source else "LIMITED"
    market_sources: list[str]
    market_data_providers: list[str]
    market_bookmakers: list[str]
    market_families: list[str]
    market_only: dict[str, Any] | None
    market_sources = []
    if full_source:
        market_sources = _effective_market_providers(full_source["snapshot"], full_source["name"])
        market_data_providers = list(market_sources)
        market_bookmakers = _market_bookmakers(full_source["snapshot"])
        market_families = _market_families(full_source["snapshot"])
        market_only = _market_only_baseline(full_source["snapshot"], market_sources, full_source["references"])
        if market_only is None:
            full_source = None
            market_quality = "LIMITED"
    if not full_source:
        market_data_providers = []
        market_bookmakers = []
        market_families = []
        market_only = None
        if market_source:
            market_sources = _effective_market_providers(market_source["snapshot"], market_source["name"])
            market_only = _market_only_baseline(
                market_source["snapshot"], market_sources, market_source["references"]
            )
            if market_only is not None:
                market_data_providers = list(market_sources)
                market_bookmakers = _market_bookmakers(market_source["snapshot"])
                market_families = _market_families(market_source["snapshot"])
        if market_only is None:
            if official is None:
                if official_error == "INPUT_TIMESTAMP_UNVERIFIED":
                    stage = (
                        PROVENANCE_STAGE_OFFICIAL_MARKET_TIMESTAMP_INVALID
                        if official_signal and official_signal.get("stage") == PROVENANCE_STAGE_OFFICIAL_MARKET_TIMESTAMP_INVALID
                        else PROVENANCE_STAGE_MARKET_CUTOFF_FAILED
                    )
                    return _failure_result(
                        official_error,
                        stage,
                        diagnostics,
                        source="sporttery_spf",
                        detail="official market baseline cannot establish a prematch market snapshot",
                        expected_before=kickoff,
                    )
                return None, None, official_error or "MISSING_MARKET_INTELLIGENCE"
            market_sources = ["sporttery_spf"]
            market_data_providers = ["sporttery"]
            market_bookmakers = []
            market_families = ["1x2"]
            market_only = {
                "home": official["fair_probabilities"]["home"],
                "draw": official["fair_probabilities"]["draw"],
                "away": official["fair_probabilities"]["away"],
                "method": "sporttery_spf_devig",
                "sources": ["sporttery_spf", _relative_ref(UNIVERSE_ROOT / f"{business_date}.json")],
            }

    prediction_time = _as_now(None) if real_time else now
    context: dict[str, Any] = {
        "request": {"match_id": str(job.get("match_id") or "")},
        "selected_workspace_match": {
            "id": str(job.get("match_id") or ""),
            "home": job.get("home"),
            "away": job.get("away"),
        },
        "source_snapshots": source_snapshots,
        "official_market_baseline": official or {},
        "prematch_fundamentals": {
            "recent_form": form["recent_form"],
            "form_source": form_source,
            "captured_at": form_captured_at,
        },
        "source_timestamps": {
            **{
                name: info["captured_at"].isoformat()
                for name, info in ((item["name"], item) for item in source_infos)
                if info.get("captured_at")
            },
            "prematch_fundamentals": form_captured_at,
            "official_market_baseline": official.get("captured_at") if official else None,
        },
        "model_input_source_refs": source_refs,
        "prediction_created_at": prediction_time.isoformat(),
    }
    if not source_snapshots:
        context["source_snapshots"] = {}

    try:
        input_snapshot = build_deterministic_model_input_snapshot(
            context,
            prediction_created_at=prediction_time.isoformat(),
            repository_root=PROJECT_ROOT,
        )
    except Exception as error:
        diagnostics.append(_provenance_diagnostic(
            PROVENANCE_STAGE_DETERMINISTIC_SNAPSHOT_FAILED,
            error_code="INPUT_SNAPSHOT_CONSTRUCTION_FAILED",
            source="model_governance",
            status="EXCEPTION",
            detail=f"{type(error).__name__}: {error}",
            references=source_refs,
        ))
        return _failure_result(
            "INPUT_SNAPSHOT_CONSTRUCTION_FAILED",
            PROVENANCE_STAGE_DETERMINISTIC_SNAPSHOT_FAILED,
            diagnostics,
            source="model_governance",
        )

    if not isinstance(input_snapshot, dict):
        diagnostics.append(_provenance_diagnostic(
            PROVENANCE_STAGE_DETERMINISTIC_SNAPSHOT_FAILED,
            error_code="INPUT_SNAPSHOT_CONSTRUCTION_FAILED",
            source="model_governance",
            status="INVALID_RESULT",
            detail="deterministic snapshot builder returned a non-object result",
            references=source_refs,
        ))
        return _failure_result(
            "INPUT_SNAPSHOT_CONSTRUCTION_FAILED",
            PROVENANCE_STAGE_DETERMINISTIC_SNAPSHOT_FAILED,
            diagnostics,
            source="model_governance",
        )

    source_cutoff = _parse_timestamp(input_snapshot.get("source_cutoff_at"))
    market_snapshot = _parse_timestamp(input_snapshot.get("market_snapshot_at"))
    source_cutoff_invalid = (
        source_cutoff is None
        or source_cutoff >= prediction_time
        or source_cutoff >= kickoff
    )
    market_snapshot_invalid = (
        market_snapshot is None
        or market_snapshot >= prediction_time
        or market_snapshot >= kickoff
    )
    if source_cutoff_invalid:
        diagnostics.append(_provenance_diagnostic(
            PROVENANCE_STAGE_SOURCE_CUTOFF_FAILED,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="deterministic_input_snapshot",
            status="MISSING_OR_OUT_OF_CUTOFF" if source_cutoff is None else "OUT_OF_CUTOFF",
            detail="deterministic source cutoff is missing or not strictly prematch",
            captured_at=source_cutoff,
            expected_before=min(prediction_time, kickoff),
            references=source_refs,
        ))
    if market_snapshot_invalid:
        diagnostics.append(_provenance_diagnostic(
            PROVENANCE_STAGE_MARKET_CUTOFF_FAILED,
            error_code="INPUT_TIMESTAMP_UNVERIFIED",
            source="deterministic_input_snapshot",
            status="MISSING_OR_OUT_OF_CUTOFF" if market_snapshot is None else "OUT_OF_CUTOFF",
            detail="deterministic market snapshot cutoff is missing or not strictly prematch",
            captured_at=market_snapshot,
            expected_before=min(prediction_time, kickoff),
            references=source_refs,
        ))
    if source_cutoff_invalid or market_snapshot_invalid:
        stage = PROVENANCE_STAGE_SOURCE_CUTOFF_FAILED if source_cutoff_invalid else PROVENANCE_STAGE_MARKET_CUTOFF_FAILED
        return _failure_result(
            "INPUT_TIMESTAMP_UNVERIFIED",
            stage,
            diagnostics,
            source="deterministic_input_snapshot",
        )

    metadata = {
        "input_snapshot": input_snapshot,
        "market_intelligence_quality": market_quality,
        "market_sources": market_sources,
        "market_data_providers": market_data_providers,
        "market_bookmakers": market_bookmakers,
        "market_families": market_families,
        "market_source_references": source_refs,
        "market_only_baseline": market_only,
        "form_source": form_source,
        "form_captured_at": form_captured_at,
        "prediction_created_at": prediction_time.isoformat(),
        "source_references": [
            _source_ref(UNIVERSE_ROOT / f"{business_date}.json", universe.get("fetched_at")),
            *form_refs,
        ],
        "data_quality": {
            "status": "PREMATCH_INPUTS_VERIFIED",
            "market_intelligence_quality": market_quality,
            "recent_form": "READY",
            "missing": [],
        },
    }
    football_evidence = _build_football_evidence_audit(source_snapshots)
    if football_evidence is not None:
        metadata["audit"] = {"research_only": {"football_evidence": football_evidence}}
    return context, metadata, None


def _build_payload(
    business_date: str,
    job: dict[str, Any],
    result: dict[str, Any],
    input_snapshot: dict[str, Any],
    now: datetime,
    freeze_created_at: datetime,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    config = load_config()
    model = result.get("model") if isinstance(result, dict) else None
    if not isinstance(model, dict):
        raise ValueError("MODEL_RETURNED_NO_PREDICTION")
    decisions = result.get("decisions") or {}
    return {
        "report": {
            "report_type": "base_prediction_minimal",
            "model_version": config["champion"]["release_version"],
            "analysis_timestamp": now.isoformat(),
            "snapshot_timestamp": input_snapshot.get("source_cutoff_at"),
            "freeze_created_at": freeze_created_at.isoformat(),
        },
        "match": {
            "canonical_match_id": canonical_match_id({
                "home": job.get("home"),
                "away": job.get("away"),
                "kickoff_local": job.get("kickoff"),
            }),
            "match_id": str(job.get("match_id") or ""),
            "home": job.get("home"),
            "away": job.get("away"),
            "kickoff_local": job.get("kickoff"),
        },
        "data_quality": {
            "missing": [],
            "market_intelligence_quality": metadata["market_intelligence_quality"],
        },
        "model": model,
        "decisions": decisions,
        "fundamentals": {
            "lineup_status": "unavailable_by_time",
        },
        "betting": {"candidates": []},
        "automation": {
            "provider": "fixed-python-core",
            "prompt_version": config["versions"]["prompt_version"],
            "model_input_snapshot": input_snapshot,
        },
        "business_date": business_date,
    }


def _decorate_record(
    record: dict[str, Any],
    business_date: str,
    job: dict[str, Any],
    result: dict[str, Any],
    metadata: dict[str, Any],
    now: datetime,
    kickoff: datetime,
) -> dict[str, Any]:
    model = result["model"]
    decisions = result.get("decisions") or {}
    trace = decisions.get("score_selection_trace") or {}
    record.update({
        "product_role": "FUSION_BASELINE_V0",
        "business_date": business_date,
        "job_id": job.get("job_id"),
        "match_id": job.get("match_id"),
        "freeze_created_at": now.isoformat(),
        "minutes_to_kickoff_at_freeze": round((kickoff - now).total_seconds() / 60.0, 3),
        "input_snapshot_ref": record.get("model_input_snapshot_ref"),
        "model_input_stable_sha256": _stable_model_input_hash(metadata.get("input_snapshot")),
        "market_intelligence_quality": metadata["market_intelligence_quality"],
        "market_sources": metadata["market_sources"],
        "market_data_providers": metadata["market_data_providers"],
        "market_bookmakers": metadata["market_bookmakers"],
        "market_families": metadata["market_families"],
        "market_source_references": metadata["market_source_references"],
        "market_only_baseline": metadata["market_only_baseline"],
        "data_quality": {
            **metadata["data_quality"],
            "data_grade": record.get("data_grade"),
            "generic_data_grade": record.get("generic_data_grade"),
            "base_input_quality": record.get("base_input_quality"),
        },
        "source_references": metadata["source_references"],
        "fusion_1X2": model.get("probabilities"),
        "totals": model.get("total_goals_buckets"),
        "btts": model.get("btts"),
        "score_distribution": model.get("score_probabilities"),
        "unique_score": decisions.get("unique_score"),
        "top_scores": list(model.get("score_probabilities") or [])[:10],
        "uncertainty": {
            "confidence_label": trace.get("confidence"),
            "main_risk": trace.get("main_risk"),
            "status": "QUALITATIVE_ONLY",
            "reason": "No calibrated numeric predictive uncertainty is available in the current Champion contract.",
        },
    })
    record["prediction_sha256"] = prediction_content_hash(record)
    return record


def _refresh_counts(ledger: dict[str, Any]) -> None:
    jobs = [job for job in ledger.get("jobs", []) if isinstance(job, dict)]
    counts = Counter(str(job.get("status") or "") for job in jobs)
    ledger["job_count"] = len(jobs)
    ledger["pending_count"] = counts["PENDING"]
    ledger["frozen_count"] = counts["FROZEN"]
    ledger["predicted_count"] = counts["PREDICTED"]
    ledger["insufficient_data_count"] = counts["INSUFFICIENT_DATA"]
    ledger["prediction_failed_count"] = counts["PREDICTION_FAILED"]
    ledger["missed_prematch_count"] = counts["MISSED_PREMATCH_WINDOW"]
    reasons = Counter(
        str(job.get("last_error"))
        for job in jobs
        if job.get("status") in {"INSUFFICIENT_DATA", "PREDICTION_FAILED"} and job.get("last_error")
    )
    ledger["failure_reasons"] = dict(reasons)
    stage_counts = Counter(
        str((job.get("input_provenance_diagnostic") or {}).get("stage"))
        for job in jobs
        if isinstance(job.get("input_provenance_diagnostic"), dict)
        and (job.get("input_provenance_diagnostic") or {}).get("stage")
    )
    ledger["input_provenance_failure_stages"] = dict(stage_counts)


def _blocked_summary(business_date: str, ledger: dict[str, Any] | None) -> dict[str, Any]:
    blocked = {
        "schema_version": "1.0",
        "business_date": business_date,
        "status": "BLOCKED_UNIVERSE",
        "fixture_count": 0,
        "job_count": 0,
        "jobs": [],
    }
    return {
        "business_date": business_date,
        "universe": 0,
        "jobs": int((ledger or {}).get("job_count") or 0),
        "attempted": 0,
        "frozen": 0,
        "predicted": 0,
        "insufficient_data": 0,
        "prediction_failed": 0,
        "missed_prematch": 0,
        "failure_reasons": {"BLOCKED_UNIVERSE": 1},
        "ledger": blocked,
    }


def _capture_market_direction_shadow(
    record: dict[str, Any],
    *,
    input_snapshot_root: Path,
    shadow_prediction_root: Path,
) -> dict[str, Any]:
    """Capture research shadow without changing the formal Champion path."""
    try:
        from baseline_production import run_market_direction_shadow_for_frozen_prediction

        capture_time = _utc_now()
        return run_market_direction_shadow_for_frozen_prediction(
            record,
            shadow_created_at=capture_time,
            snapshot_root=Path(input_snapshot_root),
            prediction_root=Path(shadow_prediction_root),
            repository_root=PROJECT_ROOT,
        )
    except Exception as error:  # shadow is failure-isolated from formal freeze
        return {"status": "failed", "reason": f"shadow_exception:{type(error).__name__}:{error}"}


def _capture_market_side_shadow(
    record: dict[str, Any],
    *,
    input_snapshot_root: Path,
    shadow_pair_root: Path,
) -> dict[str, Any]:
    """Capture locked Challenger C without mutating the formal Champion path."""
    try:
        from market_side_shadow import capture_pair, persist_pair

        pair = capture_pair(
            record,
            snapshot_root=Path(input_snapshot_root),
            production_automatic_capture=True,
        )
        written = persist_pair(pair, Path(shadow_pair_root))
        return {
            "status": written["status"],
            "pair_status": pair.get("pair_status"),
            "pair_id": pair.get("pair_id"),
            "path": str(written["path"]),
            "reason": pair.get("challenger_abstain_reason"),
        }
    except Exception as error:  # Challenger failure is isolated from formal freeze
        return {"status": "failed", "reason": f"shadow_exception:{type(error).__name__}:{error}"}


def run_base_prediction_jobs(
    business_date: str,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = JOBS_ROOT,
    now: datetime | None = None,
    record_root: Path = DEFAULT_RECORD_ROOT,
    input_snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    job_id: str | None = None,
    shadow_prediction_root: Path | None = None,
    market_side_shadow_root: Path | None = None,
    football_evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Attempt all retryable pre-kickoff BASE jobs for one business date."""
    current_time = _as_now(now)
    real_time = now is None
    shadow_prediction_root = Path(shadow_prediction_root or PROJECT_ROOT / "data" / "model_benchmarks" / "predictions")
    record_root_path = Path(record_root)
    if market_side_shadow_root is None:
        market_side_shadow_root = (
            DEFAULT_MARKET_SIDE_SHADOW_ROOT
            if record_root_path.resolve() == DEFAULT_RECORD_ROOT.resolve()
            else record_root_path.parent / "market_side_shadow_1" / "pairs"
        )
    market_side_shadow_root = Path(market_side_shadow_root)
    football_evidence_root = _resolve_football_evidence_root(Path(record_root), football_evidence_root)
    shadow_counts = Counter()
    shadow_failure_reasons: Counter[str] = Counter()
    market_side_shadow_counts = Counter()
    market_side_shadow_failure_reasons: Counter[str] = Counter()

    def capture_shadow(record: dict[str, Any], job: dict[str, Any]) -> None:
        shadow_counts["attempted"] += 1
        result = _capture_market_direction_shadow(
            record,
            input_snapshot_root=Path(input_snapshot_root),
            shadow_prediction_root=shadow_prediction_root,
        )
        status = str(result.get("status") or "failed")
        job["shadow_status"] = status
        job["shadow_comparison_id"] = result.get("comparison_id")
        job["shadow_failure_reason"] = result.get("reason") if status == "failed" else None
        if status == "created":
            shadow_counts["created"] += 1
        elif status == "existing":
            shadow_counts["existing"] += 1
        else:
            shadow_counts["failed"] += 1
            shadow_failure_reasons[str(result.get("reason") or "shadow_unknown_failure")] += 1

    def capture_market_side_shadow(record: dict[str, Any]) -> None:
        market_side_shadow_counts["attempted"] += 1
        result = _capture_market_side_shadow(
            record,
            input_snapshot_root=Path(input_snapshot_root),
            shadow_pair_root=market_side_shadow_root,
        )
        status = str(result.get("status") or "failed")
        pair_status = str(result.get("pair_status") or "")
        if status == "created":
            market_side_shadow_counts["created"] += 1
        elif status == "existing":
            market_side_shadow_counts["existing"] += 1
        else:
            market_side_shadow_counts["failed"] += 1
            market_side_shadow_failure_reasons[str(result.get("reason") or "shadow_unknown_failure")] += 1
        if pair_status == "PAIRED":
            market_side_shadow_counts["paired"] += 1
        elif pair_status == "CHALLENGER_ABSTAIN":
            market_side_shadow_counts["abstain"] += 1

    def capture_football_evidence(
        record: dict[str, Any], source_snapshots: Any, job: dict[str, Any]
    ) -> None:
        try:
            result = write_football_evidence_sidecar(
                record,
                source_snapshots,
                evidence_root=football_evidence_root,
                business_date=business_date,
            )
        except Exception as error:  # research sidecar is isolated from Champion freeze
            result = {"status": "failed", "reason": f"{type(error).__name__}"}
        _record_football_evidence_status(job, result)

    ledger_path = Path(jobs_root) / f"{business_date}.json"
    ledger = _load_json(ledger_path)
    universe = load_prediction_universe(business_date, Path(universe_root))
    if not universe or universe.get("business_date") != business_date or universe.get("status") not in UNIVERSE_STATUSES:
        return _blocked_summary(business_date, ledger)
    if not ledger or ledger.get("status") not in UNIVERSE_STATUSES:
        return _blocked_summary(business_date, ledger)

    jobs = [job for job in ledger.get("jobs", []) if isinstance(job, dict)]
    # One demand-driven refresh per business-date run; the loader below still
    # validates an existing cache when GitHub/raw access is unavailable.
    refresh_recent_form_cache(business_date, jobs=jobs, now=current_time)
    attempted = 0
    trade_payload: dict[str, Any] | None = None
    trade_loaded = False
    for job in jobs:
        if job_id and job.get("job_id") != job_id:
            continue
        status = str(job.get("status") or "PENDING")
        if status in TERMINAL_STATUSES:
            continue
        kickoff = _parse_timestamp(_kickoff(job))
        if kickoff is None:
            if status in RETRYABLE_STATUSES:
                attempted += 1
                job["status"] = "INSUFFICIENT_DATA"
                job["last_error"] = "INPUT_TIMESTAMP_UNVERIFIED"
                job["input_provenance_diagnostic"] = _provenance_diagnostic(
                    PROVENANCE_STAGE_OTHER,
                    error_code="INPUT_TIMESTAMP_UNVERIFIED",
                    source="fixture",
                    detail="job kickoff is missing or not parseable",
                )
                job["updated_at"] = current_time.isoformat()
            continue
        if current_time >= kickoff:
            # A frozen prematch version is already the last legal artifact;
            # after kickoff it must remain untouched rather than be replaced
            # or relabelled as a newly missed prediction.
            if status in RETRYABLE_STATUSES and status != "FROZEN":
                job["status"] = "MISSED_PREMATCH_WINDOW"
                job["last_error"] = "MISSED_PREMATCH_WINDOW"
                job.pop("input_provenance_diagnostic", None)
                job["updated_at"] = current_time.isoformat()
            continue
        if status not in RETRYABLE_STATUSES:
            continue
        attempted += 1
        job.pop("input_provenance_diagnostic", None)
        fixture = _job_fixture(universe, job)
        if fixture is None:
            job["status"] = "INSUFFICIENT_DATA"
            job["last_error"] = "MISSING_UNIVERSE_FIXTURE"
            job["updated_at"] = current_time.isoformat()
            continue
        if not trade_loaded:
            trade_loaded = True
            try:
                trade_payload = fetch_trade_matches(business_date, no_cache=False)
            except Exception:
                trade_payload = None
        context, metadata, assembly_error = _assemble_context(
            business_date,
            job,
            fixture,
            universe,
            current_time,
            trade_payload,
            real_time=real_time,
        )
        if assembly_error:
            job["status"] = "INSUFFICIENT_DATA"
            job["last_error"] = assembly_error
            diagnostic = metadata.get("input_provenance_diagnostic") if isinstance(metadata, dict) else None
            if isinstance(diagnostic, dict):
                job["input_provenance_diagnostic"] = diagnostic
            job["updated_at"] = current_time.isoformat()
            continue
        assert context is not None and metadata is not None
        input_snapshot = metadata["input_snapshot"]
        prediction_time = _parse_timestamp(metadata.get("prediction_created_at")) or current_time
        if prediction_time >= kickoff:
            job["status"] = "MISSED_PREMATCH_WINDOW"
            job["last_error"] = "MISSED_PREMATCH_WINDOW"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        kickoff_at = _parse_timestamp(_kickoff(job))
        assert kickoff_at is not None
        unchanged = _same_deterministic_input(
            job,
            input_snapshot,
            kickoff_at,
            Path(record_root),
            Path(input_snapshot_root),
        )
        if unchanged is not None:
            _remember_prediction_id(job, unchanged.get("prediction_id"))
            job["status"] = "FROZEN"
            job["prediction_id"] = unchanged.get("prediction_id")
            job["prediction_created_at"] = unchanged.get("prediction_created_at")
            job["freeze_created_at"] = unchanged.get("freeze_created_at")
            job["last_error"] = None
            job.pop("input_provenance_diagnostic", None)
            capture_shadow(unchanged, job)
            capture_market_side_shadow(unchanged)
            job["updated_at"] = current_time.isoformat()
            continue
        try:
            # The projection is the exact deterministic input that is frozen;
            # no report or deep-language layer participates in the model call.
            result = build_automatic_model(input_snapshot["projection"])
        except Exception as error:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = f"MODEL_EXCEPTION_{type(error).__name__}"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        if not isinstance(result, dict) or not isinstance(result.get("model"), dict):
            job["status"] = "INSUFFICIENT_DATA"
            job["last_error"] = "MODEL_RETURNED_NO_PREDICTION"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        model = result["model"]
        if model.get("method") != MODEL_FAMILY:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "MODEL_IDENTITY_MISMATCH"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        try:
            freeze_time = _as_now(None) if real_time else current_time
            if freeze_time >= kickoff_at:
                job["status"] = "MISSED_PREMATCH_WINDOW"
                job["last_error"] = "MISSED_PREMATCH_WINDOW"
                job.pop("input_provenance_diagnostic", None)
                job["updated_at"] = freeze_time.isoformat()
                continue
            payload = _build_payload(
                business_date,
                job,
                result,
                input_snapshot,
                prediction_time,
                freeze_time,
                metadata,
            )
            record = build_prediction_record(
                payload,
                input_payload=input_snapshot,
                repository_root=PROJECT_ROOT,
            )
            if record.get("model_role") != "champion" or not record.get("formal_eligible"):
                raise GovernanceContractBlocker(
                    "governance rejected BASE payload as non-formal: "
                    + ",".join(record.get("missing_critical_fields") or [])
                )
            record = _decorate_record(record, business_date, job, result, metadata, freeze_time, kickoff_at)
            frozen = freeze_prediction(
                record,
                Path(record_root),
                input_snapshot_root=Path(input_snapshot_root),
            )
        except PredictionConflictError:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "PREDICTION_CONFLICT"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        except GovernanceContractBlocker:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "GOVERNANCE_CONTRACT_BLOCKER"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        except (TypeError, ValueError, OSError):
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "GOVERNANCE_CONTRACT_BLOCKER"
            job.pop("input_provenance_diagnostic", None)
            job["updated_at"] = current_time.isoformat()
            continue
        stored = frozen.get("record") or record
        capture_football_evidence(stored, context.get("source_snapshots"), job)
        capture_shadow(stored, job)
        capture_market_side_shadow(stored)
        job["status"] = "FROZEN"
        _remember_prediction_id(job, stored.get("prediction_id"))
        job["prediction_id"] = stored.get("prediction_id")
        job["prediction_created_at"] = stored.get("prediction_created_at")
        job["freeze_created_at"] = stored.get("freeze_created_at")
        job["last_error"] = None
        job.pop("input_provenance_diagnostic", None)
        job["updated_at"] = current_time.isoformat()

    ledger["last_run_at"] = current_time.isoformat()
    _refresh_counts(ledger)
    _write_json(ledger_path, ledger)
    return {
        "business_date": business_date,
        "universe": int(universe.get("fixture_count") or len(universe.get("fixtures") or [])),
        "jobs": len(jobs),
        "attempted": attempted,
        "frozen": ledger.get("frozen_count", 0),
        "predicted": ledger.get("predicted_count", 0),
        "insufficient_data": ledger.get("insufficient_data_count", 0),
        "prediction_failed": ledger.get("prediction_failed_count", 0),
        "missed_prematch": ledger.get("missed_prematch_count", 0),
        "pending": ledger.get("pending_count", 0),
        "failure_reasons": ledger.get("failure_reasons", {}),
        "input_provenance_failure_stages": ledger.get("input_provenance_failure_stages", {}),
        "shadow_attempted": int(shadow_counts["attempted"]),
        "shadow_created": int(shadow_counts["created"]),
        "shadow_existing": int(shadow_counts["existing"]),
        "shadow_failed": int(shadow_counts["failed"]),
        "shadow_failure_reasons": dict(shadow_failure_reasons),
        "market_side_shadow_attempted": int(market_side_shadow_counts["attempted"]),
        "market_side_shadow_created": int(market_side_shadow_counts["created"]),
        "market_side_shadow_existing": int(market_side_shadow_counts["existing"]),
        "market_side_shadow_paired": int(market_side_shadow_counts["paired"]),
        "market_side_shadow_abstain": int(market_side_shadow_counts["abstain"]),
        "market_side_shadow_failed": int(market_side_shadow_counts["failed"]),
        "market_side_shadow_failure_reasons": dict(market_side_shadow_failure_reasons),
        "ledger": ledger,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze minimum formal BASE predictions for one Prediction Day")
    parser.add_argument("--date", required=True, help="Business date YYYY-MM-DD")
    parser.add_argument("--job-id", help="Optional single-job debug selector")
    args = parser.parse_args()
    summary = run_base_prediction_jobs(args.date, job_id=args.job_id)
    print(json.dumps({key: value for key, value in summary.items() if key != "ledger"}, ensure_ascii=False, indent=2))
    return 1 if summary.get("failure_reasons", {}).get("BLOCKED_UNIVERSE") else 0


if __name__ == "__main__":
    raise SystemExit(main())
