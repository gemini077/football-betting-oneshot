"""Deterministic current-job resolution shared by serving projections.

The current job ledger is durable serving state.  A row identity such as
``job_id`` must never decide whether two rows represent two matches: match
identity is resolved from match_id, match_key, or the canonical fixture
fallback, in that order.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


def _first(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _normalise_text(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def current_job_identity(job: dict[str, Any] | None) -> dict[str, Any]:
    """Return the identity fields used by all current-serving consumers."""

    source = job if isinstance(job, dict) else {}
    nested = source.get("match_identity")
    nested = nested if isinstance(nested, dict) else {}

    def value(*keys: str) -> Any:
        return _first(source, *keys) or _first(nested, *keys)

    return {
        "job_id": value("job_id", "jobId"),
        "match_id": value("match_id", "matchId", "live_match_id", "liveMatchId"),
        "match_key": value(
            "match_key",
            "matchKey",
            "canonical_match_id",
            "canonicalMatchId",
        ),
        "home": value("home", "home_team", "homeTeam"),
        "away": value("away", "away_team", "awayTeam"),
        "kickoff_at": value(
            "kickoff_at",
            "kickoffAt",
            "kickoff",
            "kickoff_local",
            "kickoffLocal",
        ),
    }


def current_match_key(job: dict[str, Any] | None) -> str:
    """Return the stable unique-match key, never using job_id as match identity."""

    identity = current_job_identity(job)
    match_id = _text(identity.get("match_id"))
    if match_id:
        return f"match_id:{match_id}"
    match_key = _text(identity.get("match_key"))
    if match_key:
        return f"match_key:{match_key}"

    kickoff = _parse_timestamp(identity.get("kickoff_at"))
    home = _normalise_text(identity.get("home"))
    away = _normalise_text(identity.get("away"))
    if kickoff and home and away:
        return f"fallback:{kickoff.isoformat()}|{home}|{away}"
    return "UNRESOLVED_CURRENT_JOB"


def _fallback_token(identity: dict[str, Any]) -> str | None:
    kickoff = _parse_timestamp(identity.get("kickoff_at"))
    home = _normalise_text(identity.get("home"))
    away = _normalise_text(identity.get("away"))
    if not kickoff or not home or not away:
        return None
    return f"fallback:{kickoff.isoformat()}|{home}|{away}"


def _identity_tokens(identity: dict[str, Any]) -> set[str]:
    tokens = set()
    match_id = _text(identity.get("match_id"))
    match_key = _text(identity.get("match_key"))
    if match_id:
        tokens.add(f"match_id:{match_id}")
    if match_key:
        tokens.add(f"match_key:{match_key}")
    if match_id and match_key:
        return tokens
    fallback = _fallback_token(identity)
    if fallback:
        tokens.add(fallback)
    return tokens


def _row_sort_key(job: dict[str, Any]) -> tuple[str, ...]:
    identity = current_job_identity(job)
    return (
        current_match_key(job),
        _text(identity.get("job_id")),
        _text(identity.get("match_id")),
        _text(identity.get("match_key")),
        _text(_first(job, "status", "job_status")),
    )


def _common_identity(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    identities = [current_job_identity(job) for job in jobs]
    common: dict[str, Any] = {}
    for field in ("job_id", "match_id", "match_key", "home", "away", "kickoff_at"):
        values = {_text(identity.get(field)) for identity in identities if _text(identity.get(field))}
        if len(values) == 1:
            common[field] = next(iter(values))
    return common


def _job_ids(jobs: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({
        _text(current_job_identity(job).get("job_id"))
        for job in jobs
        if _text(current_job_identity(job).get("job_id"))
    })


def _statuses(jobs: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({
        _text(_first(job, "status", "job_status")) or "PENDING"
        for job in jobs
    })


def group_current_jobs(jobs: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Group current rows by unique match identity in a row-order invariant way."""

    rows = [job for job in (jobs or []) if isinstance(job, dict)]
    if not rows:
        return []

    parents = list(range(len(rows)))
    token_owner: dict[str, int] = {}

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for index, row in enumerate(rows):
        identity = current_job_identity(row)
        tokens = _identity_tokens(identity)
        if not tokens:
            tokens = {"UNRESOLVED_CURRENT_JOB"}
        for token in tokens:
            owner = token_owner.setdefault(token, index)
            union(index, owner)

    components: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        components[find(index)].append(row)

    groups: list[dict[str, Any]] = []
    for component_rows in components.values():
        ordered_rows = sorted(component_rows, key=_row_sort_key)
        row_keys = sorted({current_match_key(row) for row in ordered_rows})
        group_key = row_keys[0] if len(row_keys) == 1 else "|".join(row_keys)
        identity = _common_identity(ordered_rows)
        groups.append({
            "match_key": group_key,
            "group_key": group_key,
            "jobs": ordered_rows,
            "row_count": len(ordered_rows),
            "job_ids": _job_ids(ordered_rows),
            "statuses": _statuses(ordered_rows),
            "identity": identity,
        })

    return sorted(groups, key=lambda group: str(group["match_key"]))


def _fixture_matches_group(
    fixture_identity: dict[str, Any] | None,
    group: dict[str, Any],
) -> bool:
    target = current_job_identity(fixture_identity)
    target_match_id = _text(target.get("match_id"))
    target_match_key = _text(target.get("match_key"))
    target_has_durable_identity = bool(target_match_id or target_match_key)

    for job in group.get("jobs") or []:
        identity = current_job_identity(job)
        if target_match_id and target_match_id == _text(identity.get("match_id")):
            return True
        if target_match_key and target_match_key == _text(identity.get("match_key")):
            return True

    if target_has_durable_identity:
        return False

    target_fallback = _fallback_token(target)
    if not target_fallback:
        return False
    return target_fallback in {
        token
        for job in group.get("jobs") or []
        for token in _identity_tokens(current_job_identity(job))
    }


def _resolution(
    status: str,
    *,
    match_key: str,
    jobs: Iterable[dict[str, Any]] = (),
    conflict_reason: str | None = None,
) -> dict[str, Any]:
    rows = [job for job in jobs if isinstance(job, dict)]
    return {
        "status": status,
        "selected_job": rows[0] if status == "UNIQUE" and rows else None,
        "row_count": len(rows),
        "job_ids": _job_ids(rows),
        "statuses": _statuses(rows),
        "match_key": match_key,
        "conflict_reason": conflict_reason,
    }


def resolve_current_job_for_match(
    jobs: Iterable[dict[str, Any]] | None,
    fixture_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve a fixture to exactly one current row, or fail closed."""

    groups = group_current_jobs(jobs)
    target_key = current_match_key(fixture_identity)
    matched = [group for group in groups if _fixture_matches_group(fixture_identity, group)]
    if not matched:
        return _resolution(
            "MISSING",
            match_key=target_key,
            conflict_reason="CURRENT_JOB_MISSING",
        )

    if len(matched) > 1:
        rows = [job for group in matched for job in group.get("jobs") or []]
        return _resolution(
            "CONFLICT",
            match_key="|".join(sorted(str(group["match_key"]) for group in matched)),
            jobs=rows,
            conflict_reason="MULTIPLE_CURRENT_MATCH_GROUPS",
        )

    group = matched[0]
    rows = group.get("jobs") or []
    if len(rows) != 1:
        return _resolution(
            "CONFLICT",
            match_key=str(group["match_key"]),
            jobs=rows,
            conflict_reason="DUPLICATE_CURRENT_JOB_STATE",
        )

    return _resolution(
        "UNIQUE",
        match_key=str(group["match_key"]),
        jobs=rows,
    )
