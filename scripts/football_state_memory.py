"""Versioned, prospective-only football history capture.

This module is deliberately source-facing and model-independent.  It turns
the already captured Nowscore evidence into an additive State Memory object;
it does not fetch data, resolve identities from names, or read post-match
results.  The legacy ``prospective_football_evidence.v1`` sidecar remains
readable and keeps its original ``recent_matches`` shape.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


FOOTBALL_EVIDENCE_CONTRACT_VERSION = "prospective_football_evidence.v1"
STATE_MEMORY_CONTRACT_VERSION = "football_state_memory.v1"
STATE_MEMORY_NORMALIZATION_VERSION = "football_state_memory_normalization.v1"
DEFAULT_FOOTBALL_EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[1] / "data" / "prospective" / "football_evidence"
)

LEGACY_MATCH_FIELDS = (
    "source_date",
    "match_date",
    "home_team_id",
    "home_team_name",
    "away_team_id",
    "away_team_name",
    "home_goals",
    "away_goals",
)
STATE_MEMORY_PROVIDERS = ("nowscore", "500.com")
COMPETITION_CLASS_CLUB_FRIENDLY = "CLUB_FRIENDLY"
COMPETITION_CLASS_INTERNATIONAL_FRIENDLY = "INTERNATIONAL_FRIENDLY"
COMPETITION_CLASS_FORMAL = "FORMAL_COMPETITION"
COMPETITION_CLASS_UNKNOWN = "UNKNOWN"

_UNKNOWN_LABELS = frozenset({
    "",
    "-",
    "--",
    "?",
    "na",
    "n/a",
    "nil",
    "none",
    "null",
    "unknown",
    "unavailable",
    "未提供",
    "未知",
    "不詳",
})
_CLUB_FRIENDLY_LABELS = frozenset({
    "球會友誼",
    "球会友谊",
    "俱樂部友誼賽",
    "俱乐部友谊赛",
    "club friendly",
    "club friendlies",
    "club-friendlies",
})
_INTERNATIONAL_FRIENDLY_LABELS = frozenset({
    "國際友誼",
    "国际友谊",
    "國際友誼賽",
    "国际友谊赛",
    "international friendly",
    "international friendlies",
})
_AMBIGUOUS_FRIENDLY_LABELS = frozenset({
    "友誼賽",
    "友谊赛",
    "friendly",
    "friendlies",
})
_CLASS_ALIASES = {
    "CLUB_FRIENDLY": COMPETITION_CLASS_CLUB_FRIENDLY,
    "club_friendly": COMPETITION_CLASS_CLUB_FRIENDLY,
    "INTERNATIONAL_FRIENDLY": COMPETITION_CLASS_INTERNATIONAL_FRIENDLY,
    "international_friendly": COMPETITION_CLASS_INTERNATIONAL_FRIENDLY,
    "FORMAL_COMPETITION": COMPETITION_CLASS_FORMAL,
    "formal_competition": COMPETITION_CLASS_FORMAL,
    "UNKNOWN": COMPETITION_CLASS_UNKNOWN,
    "unknown": COMPETITION_CLASS_UNKNOWN,
}
_POSTMATCH_KEYS = frozenset({
    "actual",
    "result",
    "settlement",
    "verified_result",
    "postmatch",
    "post_match",
})


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _first(value: Any, *keys: str) -> Any:
    if not isinstance(value, dict):
        return None
    for key in keys:
        candidate = value.get(key)
        if _present(candidate):
            return candidate
    return None


def _canonical_id(value: Any) -> int | str | None:
    """Preserve provider identifiers without converting names into IDs."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if not text or text.casefold() in _UNKNOWN_LABELS:
        return None
    if re.fullmatch(r"\d+", text):
        parsed = int(text)
        return parsed if parsed > 0 else None
    return text


def _identifier_key(value: Any) -> str | None:
    canonical = _canonical_id(value)
    return str(canonical) if canonical is not None else None


def _normalise_label(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    raw = str(value)
    normalized = unicodedata.normalize("NFKC", raw).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized or normalized.casefold() in _UNKNOWN_LABELS:
        return raw, None
    return raw, normalized


def _competition_key(value: str) -> str:
    value = value.casefold().replace("（", "(").replace("）", ")")
    value = re.sub(r"[\-_–—]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_competition_label(
    raw_label: Any,
    explicit_class: Any = None,
) -> dict[str, Any]:
    """Normalize only the supplied competition label.

    The friendly classifications use an exact alias table.  A non-empty
    direct source label that is not an exact friendly label is retained as a
    formal competition bucket; no team name, league token, score, or target
    outcome is consulted.  Missing/ambiguous labels remain explicit UNKNOWN.
    """
    raw, normalized = _normalise_label(raw_label)
    explicit_text = str(explicit_class).strip() if _present(explicit_class) else ""
    explicit = _CLASS_ALIASES.get(explicit_text)
    if explicit == COMPETITION_CLASS_UNKNOWN:
        classification = explicit
        reason = "explicit_unknown"
    elif explicit:
        classification = explicit
        reason = "explicit_source_class"
    elif normalized is None:
        classification = COMPETITION_CLASS_UNKNOWN
        reason = "competition_label_missing"
    else:
        key = _competition_key(normalized)
        if key in {_competition_key(label) for label in _CLUB_FRIENDLY_LABELS}:
            classification = COMPETITION_CLASS_CLUB_FRIENDLY
            reason = "exact_club_friendly_alias"
        elif key in {_competition_key(label) for label in _INTERNATIONAL_FRIENDLY_LABELS}:
            classification = COMPETITION_CLASS_INTERNATIONAL_FRIENDLY
            reason = "exact_international_friendly_alias"
        elif key in {_competition_key(label) for label in _AMBIGUOUS_FRIENDLY_LABELS}:
            classification = COMPETITION_CLASS_UNKNOWN
            reason = "ambiguous_friendly_label"
        else:
            classification = COMPETITION_CLASS_FORMAL
            reason = "direct_source_label_present"
    is_club_friendly: bool | None
    if classification == COMPETITION_CLASS_CLUB_FRIENDLY:
        is_club_friendly = True
    elif classification in {
        COMPETITION_CLASS_INTERNATIONAL_FRIENDLY,
        COMPETITION_CLASS_FORMAL,
    }:
        is_club_friendly = False
    else:
        is_club_friendly = None
    return {
        "raw_competition_label": raw,
        "normalized_competition_label": normalized,
        "normalized_competition_class": classification,
        "is_club_friendly": is_club_friendly,
        "competition_resolution_status": (
            "RESOLVED" if classification != COMPETITION_CLASS_UNKNOWN else "UNKNOWN"
        ),
        "competition_resolution_reason": reason,
        "normalization_version": STATE_MEMORY_NORMALIZATION_VERSION,
    }


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    short_date = re.match(r"(\d{2})-(\d{2})-(\d{2})", text)
    if short_date:
        text = "20" + "-".join(short_date.groups()) + text[8:]
    else:
        text = text.replace("/", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if parsed.tzinfo is None:
        # Nowscore/500 kickoff strings are provider-local China time when no
        # offset is published.  Keep that deterministic rather than silently
        # treating a local source value as UTC.
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.isoformat(timespec="seconds")


def _date_text(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _snapshot(source_snapshots: Any, provider: str = "nowscore") -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(source_snapshots, dict):
        return None, {}
    source = source_snapshots.get(provider)
    if not isinstance(source, dict):
        return None, {}
    snapshots = source.get("snapshots")
    if not isinstance(snapshots, list):
        return None, source
    value = snapshots[0] if snapshots and isinstance(snapshots[0], dict) else None
    return value, source


def _legacy_matches(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    shuju = snapshot.get("shuju")
    value = shuju.get("recent_matches") if isinstance(shuju, dict) else None
    if not isinstance(value, dict):
        return None
    result: dict[str, list[dict[str, Any]]] = {}
    for group in ("home_team", "away_team"):
        rows = value.get(group)
        if not isinstance(rows, list):
            return None
        result[group] = []
        for row in rows:
            if not isinstance(row, dict) or not all(field in row for field in LEGACY_MATCH_FIELDS):
                continue
            result[group].append({field: copy.deepcopy(row[field]) for field in LEGACY_MATCH_FIELDS})
    return result


def _history_matches(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    shuju = snapshot.get("shuju")
    value = None
    if isinstance(shuju, dict):
        value = shuju.get("state_memory_matches") or shuju.get("recent_matches")
    if value is None:
        value = snapshot.get("state_memory_matches") or snapshot.get("recent_matches")
    if not isinstance(value, dict):
        return None
    result: dict[str, list[dict[str, Any]]] = {}
    for group in ("home_team", "away_team"):
        rows = value.get(group)
        if not isinstance(rows, list):
            return None
        result[group] = [copy.deepcopy(row) for row in rows if isinstance(row, dict)]
    return result


def _panlu_matches(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    context = snapshot.get("context") or snapshot.get("nowscore_context")
    if not isinstance(context, dict):
        return []
    panlu = context.get("panlu")
    if not isinstance(panlu, dict):
        return []
    matches = panlu.get("matches")
    return [row for row in matches if isinstance(row, dict)] if isinstance(matches, list) else []


def _row_fixture_id(row: dict[str, Any]) -> int | str | None:
    return _canonical_id(_first(
        row,
        "source_fixture_id",
        "provider_match_id",
        "source_match_id",
        "match_id",
        "fixture_id",
    ))


def _row_team_id(row: dict[str, Any], side: str) -> int | str | None:
    return _canonical_id(row.get(f"{side}_team_id"))


def _row_date(row: dict[str, Any]) -> str | None:
    return _date_text(_first(row, "match_date", "source_date", "date"))


def _panlu_date(row: dict[str, Any]) -> str | None:
    return _date_text(_first(row, "match_date", "source_date", "date", "kickoff"))


def _same_history_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_home = _identifier_key(_row_team_id(left, "home"))
    right_home = _identifier_key(_row_team_id(right, "home"))
    left_away = _identifier_key(_row_team_id(left, "away"))
    right_away = _identifier_key(_row_team_id(right, "away"))
    if not left_home or not left_away or left_home != right_home or left_away != right_away:
        return False
    left_date, right_date = _row_date(left), _panlu_date(right)
    return bool(left_date and right_date and left_date == right_date)


def _match_panlu(row: dict[str, Any], panlu: list[dict[str, Any]]) -> dict[str, Any] | None:
    fixture_id = _identifier_key(_row_fixture_id(row))
    if fixture_id:
        exact = [candidate for candidate in panlu if _identifier_key(_row_fixture_id(candidate)) == fixture_id]
        if len(exact) == 1:
            return exact[0]
        # A published fixture ID is the strongest source identity.  Do not
        # replace an ID mismatch with a weaker date/team join.
        return None
    exact = [candidate for candidate in panlu if _same_history_row(row, candidate)]
    return exact[0] if len(exact) == 1 else None


def _target_identity(
    record: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    state_identity = snapshot.get("state_memory_identity")
    source_identity = state_identity if isinstance(state_identity, dict) else snapshot.get("identity")
    source_identity = source_identity if isinstance(source_identity, dict) else {}
    shuju = snapshot.get("shuju") if isinstance(snapshot.get("shuju"), dict) else {}
    team_ids = shuju.get("team_ids") if isinstance(shuju.get("team_ids"), dict) else {}
    match_identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}

    def get(*keys: str) -> Any:
        return _first(source_identity, *keys) or _first(match_identity, *keys)

    home_id = _canonical_id(
        get("home_team_id", "home_id")
        or team_ids.get("home")
        or _first(record, "home_team_id")
    )
    away_id = _canonical_id(
        get("away_team_id", "away_id")
        or team_ids.get("away")
        or _first(record, "away_team_id")
    )
    target_fixture_id = _canonical_id(
        get("source_fixture_id", "provider_match_id", "nowscore_id", "match_id")
        or _first(snapshot, "nowscore_id", "nowscoreId")
        or _first(record, "source_fixture_id", "nowscore_id")
    )
    home_name = get("home_team", "home_team_name", "home") or _first(record, "home")
    away_name = get("away_team", "away_team_name", "away") or _first(record, "away")
    kickoff = _timestamp(
        get("kickoff_at", "kickoff_local", "kickoff")
        or _first(record, "kickoff_at", "kickoff")
    )
    raw_competition = get("raw_competition_label", "competition", "competition_name", "league")
    return {
        "source_fixture_id": target_fixture_id,
        "provider_match_id": target_fixture_id,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name": str(home_name) if _present(home_name) else None,
        "away_team_name": str(away_name) if _present(away_name) else None,
        "kickoff_at": kickoff,
        **normalize_competition_label(raw_competition),
    }


def _source_reference(wrapper: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    value = _first(
        snapshot,
        "source_record_ref",
        "source_url",
        "analysis_source_url",
        "source_reference",
    )
    if value is None:
        value = _first(wrapper, "source_reference", "source_url", "source_record_ref")
    return str(value) if _present(value) else None


def _source_references(wrapper: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in (
        wrapper.get("source_reference"),
        snapshot.get("source_record_ref"),
        snapshot.get("source_url"),
        snapshot.get("analysis_source_url"),
    ):
        if _present(value) and str(value) not in refs:
            refs.append(str(value))
    extra = wrapper.get("references")
    if isinstance(extra, list):
        for value in extra:
            if _present(value) and str(value) not in refs:
                refs.append(str(value))
    return refs


def _subject_fields(
    row_home_id: int | str | None,
    row_away_id: int | str | None,
    target_home_id: int | str | None,
    target_away_id: int | str | None,
) -> tuple[int | str | None, int | str | None, str | None, str]:
    row_home, row_away = _identifier_key(row_home_id), _identifier_key(row_away_id)
    home_target, away_target = _identifier_key(target_home_id), _identifier_key(target_away_id)
    if not row_home or not row_away or not (home_target or away_target):
        return None, None, None, "UNKNOWN"
    matches_home_target = row_home == home_target or row_away == home_target
    matches_away_target = row_home == away_target or row_away == away_target
    if matches_home_target == matches_away_target:
        return None, None, None, "AMBIGUOUS" if matches_home_target else "UNKNOWN"
    target_id = target_home_id if matches_home_target else target_away_id
    if row_home == _identifier_key(target_id):
        return target_id, row_away_id, "home", "RESOLVED"
    return target_id, row_home_id, "away", "RESOLVED"


def _score(row: dict[str, Any], panlu: dict[str, Any] | None) -> tuple[int | float | None, int | float | None]:
    home = _first(row, "home_goals_90m", "home_goals", "home_score_90m")
    away = _first(row, "away_goals_90m", "away_goals", "away_score_90m")
    if (home is None or away is None) and isinstance(panlu, dict):
        full_time = panlu.get("full_time")
        if isinstance(full_time, dict):
            home = home if home is not None else full_time.get("home")
            away = away if away is not None else full_time.get("away")
    def integer(value: Any) -> int | float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return integer(home), integer(away)


def _state_memory_row(
    row: dict[str, Any],
    panlu: dict[str, Any] | None,
    *,
    target: dict[str, Any],
    source_provider: str,
    captured_at: str | None,
    source_cutoff_at: str | None,
    source_reference: str | None,
) -> dict[str, Any]:
    home_id = _row_team_id(row, "home")
    away_id = _row_team_id(row, "away")
    home_name = _first(row, "home_team_name", "home_team")
    away_name = _first(row, "away_team_name", "away_team")
    if isinstance(panlu, dict):
        home_id = home_id or _canonical_id(panlu.get("home_team_id"))
        away_id = away_id or _canonical_id(panlu.get("away_team_id"))
        home_name = home_name or panlu.get("home_team")
        away_name = away_name or panlu.get("away_team")
    fixture_id = _row_fixture_id(row)
    if fixture_id is None and isinstance(panlu, dict):
        fixture_id = _row_fixture_id(panlu)
    match_date = _row_date(row) or (_panlu_date(panlu) if isinstance(panlu, dict) else None)
    kickoff = _timestamp(panlu.get("kickoff")) if isinstance(panlu, dict) else None
    home_score, away_score = _score(row, panlu)
    raw_competition = _first(
        row,
        "raw_competition_label",
        "competition",
        "competition_name",
        "league",
    )
    if raw_competition is None and isinstance(panlu, dict):
        raw_competition = _first(panlu, "raw_competition_label", "competition", "competition_name", "league")
    competition = normalize_competition_label(raw_competition)
    subject_id, opponent_id, venue, subject_status = _subject_fields(
        home_id,
        away_id,
        target.get("home_team_id"),
        target.get("away_team_id"),
    )
    result = {
        "source_fixture_id": fixture_id,
        "provider_match_id": fixture_id,
        "home_team_id": home_id,
        "home_team_name": str(home_name) if _present(home_name) else None,
        "away_team_id": away_id,
        "away_team_name": str(away_name) if _present(away_name) else None,
        "source_date": _first(row, "source_date", "date"),
        "match_date": match_date,
        "kickoff_at": kickoff,
        "home_goals_90m": home_score,
        "away_goals_90m": away_score,
        "score_semantics": "SOURCE_HISTORICAL_90M_EVIDENCE",
        **competition,
        "subject_team_id": subject_id,
        "opponent_team_id": opponent_id,
        "subject_venue": venue,
        "subject_identity_status": subject_status,
        "source_provider": source_provider,
        "source_captured_at": captured_at,
        "captured_at": captured_at,
        "source_cutoff_at": source_cutoff_at,
        "source_reference": source_reference,
        "source_record_ref": source_reference,
    }
    # Do not let a source payload smuggle post-match/result fields into the
    # additive contract, even if a future parser receives an expanded row.
    for key in list(result):
        if key.casefold() in _POSTMATCH_KEYS:
            result.pop(key, None)
    return result


def _prematch_status(
    kickoff_at: str | None,
    captured_at: str | None,
    source_cutoff_at: str | None,
    prediction_created_at: str | None,
    freeze_created_at: str | None,
) -> tuple[bool | None, str]:
    kickoff = _timestamp(kickoff_at)
    values = [_timestamp(value) for value in (
        captured_at,
        source_cutoff_at,
        prediction_created_at,
        freeze_created_at,
    )]
    if kickoff is None or any(value is None for value in values):
        return None, "UNKNOWN"
    kickoff_dt = datetime.fromisoformat(kickoff)
    return all(datetime.fromisoformat(value) < kickoff_dt for value in values if value), "VERIFIED"


def build_state_memory(
    record: dict[str, Any],
    source_snapshots: Any,
) -> dict[str, Any] | None:
    """Build the additive State Memory v1 object from captured source data."""
    snapshot, wrapper = _snapshot(source_snapshots, "nowscore")
    source_provider = "nowscore"
    if snapshot is None:
        snapshot, wrapper = _snapshot(source_snapshots, "500_deep")
        source_provider = "500.com"
    if snapshot is None:
        return None
    groups = _history_matches(snapshot)
    if groups is None:
        return None
    panlu = _panlu_matches(snapshot)
    captured_at = _timestamp(_first(snapshot, "fetched_at", "captured_at", "source_timestamp", "source_time"))
    source_cutoff_at = _timestamp(
        _first(record, "source_cutoff_at")
        or _first(snapshot, "source_cutoff_at", "source_as_of_at", "as_of_at")
    )
    source_reference = _source_reference(wrapper, snapshot)
    target = _target_identity(record, snapshot)
    history: dict[str, list[dict[str, Any]]] = {}
    for group, rows in groups.items():
        history[group] = [
            _state_memory_row(
                row,
                _match_panlu(row, panlu),
                target=target,
                source_provider=source_provider,
                captured_at=captured_at,
                source_cutoff_at=source_cutoff_at,
                source_reference=source_reference,
            )
            for row in rows
        ]
    rows = [row for group in history.values() for row in group]
    kickoff_at = target.get("kickoff_at")
    prematch_verified, prematch_status = _prematch_status(
        kickoff_at,
        captured_at,
        source_cutoff_at,
        _first(record, "prediction_created_at"),
        _first(record, "freeze_created_at"),
    )
    competition_resolved = sum(
        row.get("competition_resolution_status") == "RESOLVED" for row in rows
    )
    fixture_id_count = sum(row.get("source_fixture_id") is not None for row in rows)
    team_id_count = sum(
        row.get("home_team_id") is not None and row.get("away_team_id") is not None
        for row in rows
    )
    date_count = sum(row.get("match_date") is not None for row in rows)
    score_count = sum(
        row.get("home_goals_90m") is not None and row.get("away_goals_90m") is not None
        for row in rows
    )
    subject_count = sum(row.get("subject_identity_status") == "RESOLVED" for row in rows)
    required_ready = bool(rows) and all(
        row.get("home_team_id") is not None
        and row.get("away_team_id") is not None
        and row.get("match_date") is not None
        and row.get("home_goals_90m") is not None
        and row.get("away_goals_90m") is not None
        and row.get("competition_resolution_status") != "UNKNOWN"
        for row in rows
    )
    return {
        "contract_version": STATE_MEMORY_CONTRACT_VERSION,
        "normalization_version": STATE_MEMORY_NORMALIZATION_VERSION,
        "capture_status": "READY" if required_ready else "PARTIAL",
        "source": {
            "provider": source_provider,
            "snapshot_captured_at": captured_at,
            "captured_at": captured_at,
            "source_cutoff_at": source_cutoff_at,
            "prediction_created_at": _first(record, "prediction_created_at"),
            "freeze_created_at": _first(record, "freeze_created_at"),
            "prematch_verified": prematch_verified,
            "prematch_status": prematch_status,
            "source_references": _source_references(wrapper, snapshot),
        },
        "target_fixture": target,
        "history": history,
        "coverage": {
            "history_row_count": len(rows),
            "source_fixture_id_count": fixture_id_count,
            "team_id_count": team_id_count,
            "match_date_count": date_count,
            "score_90m_count": score_count,
            "competition_resolved_count": competition_resolved,
            "subject_identity_resolved_count": subject_count,
        },
    }


def build_football_evidence_audit(source_snapshots: Any) -> dict[str, Any] | None:
    snapshot, _ = _snapshot(source_snapshots, "nowscore")
    if snapshot is None:
        return None
    recent_matches = _legacy_matches(snapshot)
    if recent_matches is None:
        return None
    evidence: dict[str, Any] = {
        "source_provider": "nowscore",
        "recent_matches": recent_matches,
    }
    nowscore_id = _canonical_id(_first(snapshot, "nowscore_id", "nowscoreId"))
    if nowscore_id is not None:
        evidence["nowscore_id"] = nowscore_id
    captured_at = _timestamp(_first(snapshot, "fetched_at", "captured_at", "source_timestamp", "source_time"))
    if captured_at:
        evidence["evidence_captured_at"] = captured_at
    state_memory = build_state_memory({}, source_snapshots)
    if state_memory is not None:
        evidence["state_memory"] = state_memory
    return evidence


def build_football_evidence_sidecar(
    record: dict[str, Any],
    source_snapshots: Any,
    *,
    business_date: str | None = None,
) -> dict[str, Any] | None:
    """Build legacy evidence plus additive State Memory without target results."""
    evidence = build_football_evidence_audit(source_snapshots)
    if evidence is None:
        return None
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
    sidecar: dict[str, Any] = {
        "contract_version": FOOTBALL_EVIDENCE_CONTRACT_VERSION,
        "state_memory_contract_version": STATE_MEMORY_CONTRACT_VERSION,
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
    state_memory = build_state_memory(record, source_snapshots)
    if state_memory is not None:
        sidecar["state_memory"] = state_memory
    return sidecar


def write_football_evidence_sidecar(
    record: dict[str, Any],
    source_snapshots: Any,
    *,
    evidence_root: Path | None = None,
    business_date: str | None = None,
) -> dict[str, Any]:
    """Write one exclusive, idempotent research sidecar."""
    try:
        sidecar = build_football_evidence_sidecar(record, source_snapshots, business_date=business_date)
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__}
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
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"status": "conflict", "path": target, "reason": "EXISTING_SIDECAR_UNREADABLE"}
            if existing == sidecar:
                return {"status": "existing", "path": target, "record": existing}
            return {"status": "conflict", "path": target, "reason": "SIDECAR_CONTENT_CONFLICT"}
    except (OSError, TypeError, ValueError) as error:
        return {"status": "failed", "reason": type(error).__name__}
