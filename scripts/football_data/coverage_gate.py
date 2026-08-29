"""Automatic historical coverage gate for the daily fixture pipeline.

The gate is deliberately conservative: competition and team identity are
exact-only, historical records are filtered strictly before kickoff, and an
unusable historical challenger never removes the current Champion job.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .coverage_registry import (
    CONTRACT_VERSION,
    DEFAULT_REGISTRY_PATH,
    STATUS_DEGRADED,
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
    load_coverage_registry,
)
from .storage import HistoricalResultStore, content_sha256
from .team_strength import classify_history_recency


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CROSSWALK_PATH = PROJECT_ROOT / "data" / "football_data" / "verified_project_provider_crosswalk.json"
DEFAULT_IDENTITY_EVIDENCE_PATH = PROJECT_ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
LOCAL_TZ = timezone(timedelta(hours=8))
REVIEWED_IDENTITY_METHODS = frozenset({
    "manual_verified",
    "provider_id_exact",
    "existing_crosswalk",
    "exact_alias",
    "project_alias_context_verified",
    "project_provider_context_verified",
})


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _normal(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=LOCAL_TZ)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first(fixture: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if fixture.get(key) not in (None, ""):
            return fixture[key]
    return None


def _fixture_kickoff(fixture: Mapping[str, Any]) -> datetime | None:
    direct = _first(fixture, "kickoff", "kickoff_local", "kickoff_at")
    if direct not in (None, ""):
        return _parse_time(direct)
    date_text = _text(_first(fixture, "matchDate", "match_date", "businessDate"))[:10]
    time_text = _text(_first(fixture, "matchTime", "match_time"))[:8]
    if not date_text or not time_text:
        return None
    if len(time_text) == 5:
        time_text += ":00"
    return _parse_time(f"{date_text}T{time_text}+08:00")


def _valid_team_id(value: Any) -> bool:
    return _text(value).startswith("team:")


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class ExactCoverageIdentityResolver:
    """Resolve fixture teams only from explicit reviewed evidence."""

    def __init__(
        self,
        *,
        crosswalk_path: str | Path = DEFAULT_CROSSWALK_PATH,
        identity_evidence_path: str | Path = DEFAULT_IDENTITY_EVIDENCE_PATH,
    ) -> None:
        self.crosswalk_path = Path(crosswalk_path)
        self.identity_evidence_path = Path(identity_evidence_path)
        self.by_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.by_provider_id: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self.by_match_id: dict[str, dict[str, Any]] = {}
        crosswalk = _json_object(self.crosswalk_path)
        for raw in crosswalk.get("mappings", []):
            if not isinstance(raw, Mapping) or raw.get("verified") is not True:
                continue
            competition_id = _text(raw.get("competition") or raw.get("competition_id"))
            team_id = _text(raw.get("canonical_team_id"))
            provider = _normal(raw.get("provider"))
            team_name = _normal(raw.get("provider_team_name"))
            provider_team_id = _text(raw.get("provider_team_id"))
            if not competition_id or not _valid_team_id(team_id):
                continue
            mapping = dict(raw)
            mapping["canonical_team_id"] = team_id
            if provider and team_name:
                self.by_name.setdefault((competition_id, team_name), []).append(mapping)
                self.by_name.setdefault((competition_id, f"{provider}:{team_name}"), []).append(mapping)
            if provider and provider_team_id:
                self.by_provider_id.setdefault((competition_id, provider, provider_team_id), []).append(mapping)

        evidence = _json_object(self.identity_evidence_path)
        for raw in evidence.get("matches", []):
            if not isinstance(raw, Mapping) or raw.get("verified") is not True:
                continue
            for key in ("id", "provider_match_id", "nowscore_match_id"):
                value = _text(raw.get(key))
                if value:
                    self.by_match_id[value] = dict(raw)

    @staticmethod
    def _explicit_identity(fixture: Mapping[str, Any]) -> dict[str, Any] | None:
        nested = fixture.get("identity")
        nested = nested if isinstance(nested, Mapping) else {}
        verified = fixture.get("identity_verified") is True or nested.get("verified") is True or _normal(fixture.get("identity_resolution_status") or nested.get("status")) in {"verified", "resolved"}
        method = _text(fixture.get("resolution_method") or nested.get("resolution_method"))
        if not verified or (method and method not in REVIEWED_IDENTITY_METHODS):
            return None
        home = _text(fixture.get("home_team_id") or nested.get("home_team_id"))
        away = _text(fixture.get("away_team_id") or nested.get("away_team_id"))
        if not (_valid_team_id(home) and _valid_team_id(away)):
            return None
        return {
            "home_team_id": home,
            "away_team_id": away,
            "status": "resolved",
            "resolution_method": method or "explicit_reviewed_fixture",
            "evidence": ["fixture_explicit_reviewed_identity"],
        }

    def resolve(self, fixture: Mapping[str, Any], competition_id: str) -> dict[str, Any]:
        explicit = self._explicit_identity(fixture)
        if explicit is not None:
            return explicit

        match_ids = [
            _text(_first(fixture, "matchId", "match_id", "id")),
            _text(fixture.get("nowscoreId")),
        ]
        for match_id in match_ids:
            evidence = self.by_match_id.get(match_id)
            if evidence is None or _text(evidence.get("competition_id")) not in {"", competition_id}:
                continue
            home = _text(evidence.get("home_team_id"))
            away = _text(evidence.get("away_team_id"))
            if _valid_team_id(home) and _valid_team_id(away):
                return {
                    "home_team_id": home,
                    "away_team_id": away,
                    "status": "resolved",
                    "resolution_method": _text(evidence.get("resolution_method")) or "current_match_evidence",
                    "evidence": ["current_match_identity_evidence", match_id],
                }

        resolved: dict[str, str | None] = {"home_team_id": None, "away_team_id": None}
        evidence_refs: list[str] = []
        for side, name_keys in {
            "home": ("nowscoreProviderHome", "provider_home_team", "homeTeam", "home_team", "home"),
            "away": ("nowscoreProviderAway", "provider_away_team", "awayTeam", "away_team", "away"),
        }.items():
            provider = _normal(fixture.get("identity_provider") or fixture.get("provider") or "")
            provider_id = _text(_first(
                fixture,
                f"{side}_provider_team_id",
                f"provider_{side}_team_id",
            ))
            if provider and provider_id:
                provider_candidates = self.by_provider_id.get((competition_id, provider, provider_id), [])
                if len(provider_candidates) == 1:
                    resolved[f"{side}_team_id"] = _text(provider_candidates[0].get("canonical_team_id"))
                    evidence_refs.append(_text(provider_candidates[0].get("verification_evidence_digest")) or "verified_identity_crosswalk")
                    continue
            name = _normal(_first(fixture, *name_keys))
            if not name:
                continue
            candidates = self.by_name.get((competition_id, name), [])
            if len(candidates) == 1:
                mapping = candidates[0]
                resolved[f"{side}_team_id"] = _text(mapping.get("canonical_team_id"))
                evidence_refs.append(_text(mapping.get("verification_evidence_digest")) or "verified_identity_crosswalk")
                continue
            # A provider-qualified exact key allows two providers to carry the
            # same display name without ever falling back to fuzzy matching.
            qualified = self.by_name.get((competition_id, f"{provider}:{name}"), []) if provider else []
            if len(qualified) == 1:
                resolved[f"{side}_team_id"] = _text(qualified[0].get("canonical_team_id"))
                evidence_refs.append(_text(qualified[0].get("verification_evidence_digest")) or "verified_identity_crosswalk")
        status = "resolved" if all(_valid_team_id(resolved[key]) for key in ("home_team_id", "away_team_id")) else "partial" if any(resolved.values()) else "unresolved"
        return {
            **resolved,
            "status": status,
            "resolution_method": "existing_crosswalk" if status == "resolved" else "unresolved",
            "evidence": evidence_refs,
        }


def _competition_index(registry: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    by_alias: dict[str, list[Mapping[str, Any]]] = {}
    for row in registry.get("competitions", []):
        if not isinstance(row, Mapping):
            continue
        competition_id = _text(row.get("competition_id") or row.get("canonical_competition_id"))
        if not competition_id:
            continue
        by_id[competition_id] = row
        aliases = [row.get("canonical_name"), row.get("competition_key"), *list(row.get("aliases") or [])]
        for alias in aliases:
            normalized = _normal(alias)
            if normalized and all(existing is not row for existing in by_alias.get(normalized, [])):
                by_alias.setdefault(normalized, []).append(row)
    return by_id, by_alias


def _resolve_competition(fixture: Mapping[str, Any], registry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    by_id, by_alias = _competition_index(registry)
    explicit = _text(fixture.get("competition_id"))
    if explicit:
        return by_id.get(explicit)
    key = _text(fixture.get("competition_key"))
    if key:
        exact = [row for row in registry.get("competitions", []) if isinstance(row, Mapping) and _text(row.get("competition_key")) == key]
        if len(exact) == 1:
            return exact[0]
    raw = _normal(_first(fixture, "league", "competition"))
    candidates = by_alias.get(raw, []) if raw else []
    return candidates[0] if len(candidates) == 1 else None


def _history_for_team(
    records: Iterable[Mapping[str, Any]],
    *,
    competition_id: str,
    team_id: str,
    target: datetime | None,
) -> tuple[int, datetime | None, list[str]]:
    selected: list[tuple[datetime, str]] = []
    for raw in records:
        record = dict(raw)
        if _text(record.get("competition_id")) != competition_id or record.get("eligible_for_team_strength") is not True:
            continue
        if record.get("duplicate_status") in {"possible_duplicate", "duplicate_conflict"}:
            continue
        if team_id not in {_text(record.get("home_team_id")), _text(record.get("away_team_id"))}:
            continue
        kickoff = _parse_time(record.get("kickoff_at"))
        if kickoff is None or (target is not None and kickoff >= target):
            continue
        selected.append((kickoff, _text(record.get("canonical_match_id"))))
    selected.sort(key=lambda item: (item[0], item[1]))
    return len(selected), selected[-1][0] if selected else None, [match_id for _, match_id in selected if match_id]


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def audit_fixture(
    fixture: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    historical_records: Iterable[Mapping[str, Any]] | None = None,
    identity_resolver: ExactCoverageIdentityResolver | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Audit one fixture and preserve Champion eligibility for every status."""

    current_time = now or datetime.now(timezone.utc)
    records = list(historical_records or [])
    resolver = identity_resolver or ExactCoverageIdentityResolver()
    row = _resolve_competition(fixture, registry)
    fixture_id = _text(_first(fixture, "matchId", "match_id", "id")) or _text(fixture.get("match_num")) or "fixture:unknown"
    result: dict[str, Any] = {
        "fixture_id": fixture_id,
        "status": STATUS_UNSUPPORTED,
        "competition_id": _text(row.get("competition_id")) if row else None,
        "competition_key": _text(row.get("competition_key")) if row else None,
        "identity": {},
        "history": {},
        "reason_codes": [],
        "blocking_reason_codes": [],
        "warning_codes": [],
        "reasons": [],
        "historical_challenger_allowed": False,
        "champion_prediction_allowed": True,
        "blocked": False,
        "evaluated_at": _iso(current_time),
        "coverage_contract_version": CONTRACT_VERSION,
    }
    if row is None:
        result["reason_codes"].append("COMPETITION_UNSUPPORTED")
        result["blocking_reason_codes"].append("COMPETITION_UNSUPPORTED")
        result["reasons"].append(_reason("COMPETITION_UNSUPPORTED", "no exact competition entry in coverage registry"))
        return result

    competition_id = _text(row.get("competition_id"))
    identity = resolver.resolve(fixture, competition_id)
    result["identity"] = identity
    if not (_valid_team_id(identity.get("home_team_id")) and _valid_team_id(identity.get("away_team_id"))):
        result["reason_codes"].append("IDENTITY_UNAVAILABLE")
        result["blocking_reason_codes"].append("IDENTITY_UNAVAILABLE")
        result["reasons"].append(_reason("IDENTITY_UNAVAILABLE", "both teams require exact reviewed canonical IDs"))
        return result

    target = _fixture_kickoff(fixture)
    policy = registry.get("policy") if isinstance(registry.get("policy"), Mapping) else {}
    minimum_history = int(policy.get("minimum_history_matches_per_team", 5))
    current_max_age = int(policy.get("current_max_history_age_days", 60))
    history: dict[str, Any] = {}
    reasons: list[dict[str, str]] = []
    reason_codes: list[str] = []
    blocking_reason_codes: list[str] = []
    for side in ("home", "away"):
        team_id = _text(identity.get(f"{side}_team_id"))
        count, latest, match_ids = _history_for_team(records, competition_id=competition_id, team_id=team_id, target=target)
        recency = classify_history_recency(
            _iso(latest),
            _iso(target) or "",
            rules={
                "current_max_history_age_days": current_max_age,
                "offseason_bridge_max_history_age_days": int(policy.get("offseason_bridge_max_history_age_days", 180)),
                "bridge_requires_verified_evidence": True,
            },
        ) if target is not None else {"history_recency_status": "unknown", "history_age_days": None, "current_strength_ready": False}
        history[side] = {
            "team_id": team_id,
            "match_count": count,
            "latest_historical_match_at": _iso(latest),
            "history_age_days": recency.get("history_age_days"),
            "history_recency_status": recency.get("history_recency_status"),
            "source_match_ids": match_ids,
        }
        if count < minimum_history:
            if "HISTORY_INSUFFICIENT" not in reason_codes:
                reason_codes.append("HISTORY_INSUFFICIENT")
                blocking_reason_codes.append("HISTORY_INSUFFICIENT")
                reasons.append(_reason("HISTORY_INSUFFICIENT", f"{side} team has {count} eligible matches; {minimum_history} required"))
        elif recency.get("history_recency_status") != "current":
            if "SOURCE_STALE" not in reason_codes:
                reason_codes.append("SOURCE_STALE")
                blocking_reason_codes.append("SOURCE_STALE")
                reasons.append(_reason("SOURCE_STALE", f"{side} team history is not within the current freshness window"))

    registry_row = row
    if int(registry_row.get("historical_match_count", 0) or 0) == 0:
        source_rows = list(registry_row.get("provider_source_availability") or [])
        unavailable = not source_rows or all(
            "SOURCE_UNAVAILABLE" in set(source.get("failure_reason") or []) or not source.get("automatic_import_capability")
            for source in source_rows if isinstance(source, Mapping)
        )
        code = "SOURCE_UNAVAILABLE" if unavailable else "HISTORY_INSUFFICIENT"
        if code not in reason_codes:
            reason_codes.append(code)
            blocking_reason_codes.append(code)
            reasons.append(_reason(code, "no authoritative historical result coverage is available for this competition"))

    current_status = _normal(registry_row.get("current_season_status"))
    if current_status in {"in_progress", "partial"}:
        reason_codes.append("CURRENT_SEASON_PARTIAL")
        result["warning_codes"].append("CURRENT_SEASON_PARTIAL")
        reasons.append(_reason("CURRENT_SEASON_PARTIAL", "current source season is still in progress; current history remains usable"))

    result["history"] = history
    result["reason_codes"] = reason_codes
    result["blocking_reason_codes"] = blocking_reason_codes
    result["reasons"] = reasons
    result["status"] = STATUS_DEGRADED if blocking_reason_codes else STATUS_SUPPORTED
    result["historical_challenger_allowed"] = result["status"] == STATUS_SUPPORTED
    return result


def _default_records() -> list[dict[str, Any]]:
    try:
        return list(HistoricalResultStore().iter_records())
    except Exception:
        return []


def audit_fixture_set(
    fixtures: Iterable[Mapping[str, Any]],
    registry: Mapping[str, Any],
    *,
    historical_records: Iterable[Mapping[str, Any]] | None = None,
    identity_resolver: ExactCoverageIdentityResolver | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Audit every fixture in one pass; unsupported rows never short-circuit."""

    records = list(historical_records) if historical_records is not None else _default_records()
    resolver = identity_resolver or ExactCoverageIdentityResolver()
    rows = [
        audit_fixture(
            fixture,
            registry,
            historical_records=records,
            identity_resolver=resolver,
            now=now,
        )
        for fixture in fixtures
        if isinstance(fixture, Mapping)
    ]
    status_counts = {status: sum(row.get("status") == status for row in rows) for status in (STATUS_SUPPORTED, STATUS_DEGRADED, STATUS_UNSUPPORTED)}
    reason_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    for row in rows:
        for code in row.get("reason_codes", []):
            reason_counts[code] = reason_counts.get(code, 0) + 1
        for code in row.get("warning_codes", []):
            warning_counts[code] = warning_counts.get(code, 0) + 1
    return {
        "contract_version": "daily_coverage_audit.v1",
        "evaluated_at": _iso(now or datetime.now(timezone.utc)),
        "coverage_registry_digest": registry.get("registry_digest") or content_sha256(registry),
        "fixture_count": len(rows),
        "fixtures": rows,
        "summary": {
            "status_counts": status_counts,
            "reason_counts": dict(sorted(reason_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "historical_challenger_allowed_count": sum(row.get("historical_challenger_allowed") is True for row in rows),
            "champion_prediction_allowed_count": sum(row.get("champion_prediction_allowed") is True for row in rows),
            "blocked_count": sum(row.get("blocked") is True for row in rows),
            "non_blocking": all(row.get("blocked") is not True for row in rows),
        },
    }


def load_default_coverage_context() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the committed registry and optional shared history for daily jobs."""

    try:
        registry = load_coverage_registry(DEFAULT_REGISTRY_PATH)
    except (OSError, ValueError, json.JSONDecodeError):
        registry = {
            "contract_version": "historical_coverage_registry.v1",
            "policy": {"minimum_history_matches_per_team": 5, "current_max_history_age_days": 60},
            "competitions": [],
        }
    return registry, _default_records()


__all__ = [
    "ExactCoverageIdentityResolver",
    "audit_fixture",
    "audit_fixture_set",
    "load_default_coverage_context",
]
