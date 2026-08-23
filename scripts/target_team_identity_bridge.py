"""Prospective target-team identity evidence for the base freeze path.

Only the target-specific Nowscore analysis result is accepted here.  The
historical ``panlu`` table is deliberately not an identity source.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from football_data.competition_resolution import CompetitionEntityResolver
from football_data.project_identity import ProjectProviderIdentityResolver


CONTRACT_VERSION = "target_team_identity_bridge.v1"
PROVIDER = "nowscore"
CROSSWALK_RELATIVE_PATH = "data/football_data/verified_project_provider_crosswalk.json"
COMPETITION_REGISTRY_RELATIVE_PATH = "data/football_data/competition_registry.json"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _provider_id(value: Any) -> str | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    text = _text(value)
    if not text.isdigit() or int(text) <= 0:
        return None
    return str(int(text))


def _timestamp(value: Any) -> str | None:
    return _text(value) or None


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _source_snapshot(context: Mapping[str, Any]) -> dict[str, Any] | None:
    source = (context.get("source_snapshots") or {}).get(PROVIDER) or {}
    snapshots = source.get("snapshots") if isinstance(source, dict) else None
    return snapshots[0] if isinstance(snapshots, list) and snapshots and isinstance(snapshots[0], dict) else None


def _crosswalk(root: Path) -> tuple[list[dict[str, Any]], str]:
    path = root / CROSSWALK_RELATIVE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    mappings = payload.get("mappings") if isinstance(payload, dict) else None
    if not isinstance(mappings, list):
        raise ValueError("TARGET_IDENTITY_CROSSWALK_INVALID")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return [row for row in mappings if isinstance(row, dict)], digest


def _provider_competition_season(source: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Read only explicit provider IDs from the target source payload."""

    return (
        _text(source.get("provider_competition_id")) or None,
        _text(source.get("provider_season_id")) or None,
    )


def _provider_identity_evidence_failure(
    source: Mapping[str, Any],
    provider_match_id: str | None,
    provider_competition_id: str | None,
    provider_season_id: str | None,
    cutoff_time: datetime | None,
    kickoff_time: datetime | None,
) -> str | None:
    evidence = source.get("provider_identity_evidence")
    if evidence is None:
        return None
    if not isinstance(evidence, Mapping) or evidence.get("status") != "OK":
        return "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
    if _text(evidence.get("provider_match_id")) != _text(provider_match_id):
        return "TARGET_PROVIDER_IDENTITY_MATCH_ID_MISMATCH"
    for section_name in ("schedule", "season"):
        section = evidence.get(section_name)
        if not isinstance(section, Mapping) or section.get("status") != "OK":
            return "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
        if not _text(section.get("source_ref")):
            return "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
        raw_sha256 = _text(section.get("raw_sha256"))
        if not re.fullmatch(r"[0-9a-fA-F]{64}", raw_sha256):
            return "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
        if section_name == "season":
            if not _text(section.get("season_list_source_ref")):
                return "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
            season_list_sha256 = _text(section.get("season_list_raw_sha256"))
            if not re.fullmatch(r"[0-9a-fA-F]{64}", season_list_sha256):
                return "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
        section_time = _time(section.get("fetched_at"))
        if section_time is None:
            return "TARGET_IDENTITY_PROVIDER_EVIDENCE_TIME_INVALID"
        if cutoff_time is not None and section_time > cutoff_time:
            return "TARGET_IDENTITY_PROVIDER_EVIDENCE_AFTER_CUTOFF"
        if kickoff_time is not None and section_time >= kickoff_time:
            return "TARGET_IDENTITY_PROVIDER_EVIDENCE_POST_KICKOFF"
        if section_name == "schedule":
            if _text(section.get("provider_match_id")) != _text(provider_match_id):
                return "TARGET_PROVIDER_IDENTITY_MATCH_ID_MISMATCH"
            if _text(section.get("provider_competition_id")) != _text(provider_competition_id):
                return "TARGET_PROVIDER_IDENTITY_COMPETITION_ID_MISMATCH"
        else:
            if _text(section.get("provider_competition_id")) != _text(provider_competition_id):
                return "TARGET_PROVIDER_IDENTITY_COMPETITION_ID_MISMATCH"
            if _text(section.get("provider_season_id")) != _text(provider_season_id):
                return "TARGET_PROVIDER_IDENTITY_SEASON_ID_MISMATCH"
    return None


def _competition_registry(
    root: Path,
    registry_path: Path | None,
) -> tuple[CompetitionEntityResolver | None, str | None]:
    path = registry_path or root / COMPETITION_REGISTRY_RELATIVE_PATH
    try:
        return CompetitionEntityResolver(path), hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, json.JSONDecodeError, ValueError):
        return None, None


def _competition_context(
    resolver: ProjectProviderIdentityResolver,
    provider_ids: tuple[str, str],
    explicit: str | None,
) -> tuple[str | None, str]:
    contexts = []
    for provider_id in provider_ids:
        values = {
            _text(row.get("competition_id") or row.get("competition"))
            for row in resolver.mappings
            if row.get("provider") == PROVIDER
            and _text(row.get("provider_team_id")) == provider_id
            and _text(row.get("competition_id") or row.get("competition"))
        }
        contexts.append(values)
    if not contexts[0] or not contexts[1]:
        return None, "no_reviewed_mapping"
    if len(contexts[0]) != 1 or len(contexts[1]) != 1 or contexts[0] != contexts[1]:
        return None, "missing_or_ambiguous_reviewed_competition"
    reviewed_competition = next(iter(contexts[0]))
    if explicit and explicit != reviewed_competition:
        return None, "explicit_competition_conflicts_with_reviewed_crosswalk"
    if explicit:
        return explicit, "fixture_or_job_and_reviewed_crosswalk"
    return reviewed_competition, "reviewed_crosswalk"


def _side_evidence(result: Any, provider_id: str, provider_name: str) -> dict[str, Any]:
    return {
        "provider_team_id": provider_id,
        "provider_team_name": provider_name or None,
        "canonical_team_id": result.canonical_team_id,
        "canonical_name": result.canonical_name,
        "resolution_status": result.resolution_status,
        "resolution_method": result.resolution_method,
        "reason": result.reason,
    }


def resolve_target_team_identity(
    *,
    job: Mapping[str, Any],
    fixture: Mapping[str, Any],
    context: Mapping[str, Any],
    input_snapshot: Mapping[str, Any],
    repository_root: Path,
    competition_registry_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve one future target from the raw Nowscore analysis snapshot.

    The function returns audit evidence even when resolution is blocked.  It
    has no write side effects and never consults ``context.panlu``.
    """

    source = _source_snapshot(context)
    shuju = (source or {}).get("shuju") if isinstance(source, dict) else None
    team_ids = shuju.get("team_ids") if isinstance(shuju, dict) else None
    provider_home_id = _provider_id((team_ids or {}).get("home")) if isinstance(team_ids, dict) else None
    provider_away_id = _provider_id((team_ids or {}).get("away")) if isinstance(team_ids, dict) else None
    target = (source or {}).get("target") if isinstance(source, dict) else {}
    page_identity = (source or {}).get("identity") if isinstance(source, dict) else {}
    target = target if isinstance(target, dict) else {}
    page_identity = page_identity if isinstance(page_identity, dict) else {}
    provider_match_id = _text(
        (source or {}).get("nowscore_id")
        or page_identity.get("nowscore_id")
    ) or None
    expected_match_id = _text(fixture.get("nowscoreId")) or None
    source_at = _timestamp((source or {}).get("fetched_at"))
    cutoff = _timestamp(input_snapshot.get("source_cutoff_at"))
    provider_competition_id, provider_season_id = _provider_competition_season(source or {})
    source_info = {
        "provider": PROVIDER,
        "source_status": (source or {}).get("status"),
        "parser": "parse_analysis_data",
        "field": "shuju.team_ids",
        "analysis_arrays": ["h_data", "a_data"],
        "analysis_source_url": (source or {}).get("analysis_source_url"),
        "source_ref": (source or {}).get("source_url") or (source or {}).get("analysis_source_url"),
        "provider_match_id": provider_match_id,
        "captured_at": source_at,
        "source_cutoff_at": cutoff,
        "provider_competition_id": provider_competition_id,
        "provider_season_id": provider_season_id,
        "provider_identity_evidence": deepcopy((source or {}).get("provider_identity_evidence")),
        "crosswalk_ref": CROSSWALK_RELATIVE_PATH,
        "panlu_used": False,
    }
    evidence: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "status": "TARGET_PROVIDER_TEAM_IDS_MISSING",
        "provider": PROVIDER,
        "provider_match_id": provider_match_id,
        "canonical_match_id": _text(job.get("match_id")) or None,
        "home": {"provider_team_id": provider_home_id},
        "away": {"provider_team_id": provider_away_id},
        "source": source_info,
    }
    if not source or not provider_home_id or not provider_away_id or provider_home_id == provider_away_id:
        return {"canonical_team_identity": None, "evidence": evidence}
    if source.get("status") != "OK":
        evidence["status"] = "TARGET_PROVIDER_SOURCE_NOT_VERIFIED"
        return {"canonical_team_identity": None, "evidence": evidence}
    if not provider_match_id:
        evidence["status"] = "TARGET_PROVIDER_MATCH_ID_MISSING"
        return {"canonical_team_identity": None, "evidence": evidence}
    if expected_match_id and provider_match_id and expected_match_id != provider_match_id:
        evidence["status"] = "TARGET_PROVIDER_MATCH_ID_MISMATCH"
        return {"canonical_team_identity": None, "evidence": evidence}
    if target:
        expected_teams = (_text(job.get("home")), _text(job.get("away")))
        observed_teams = (_text(target.get("home")), _text(target.get("away")))
        if any(expected and observed and expected != observed for expected, observed in zip(expected_teams, observed_teams)):
            evidence["status"] = "TARGET_PROVIDER_MATCH_MISMATCH"
            return {"canonical_team_identity": None, "evidence": evidence}
        target_kickoff = _time(target.get("kickoff"))
        job_kickoff = _time(job.get("kickoff"))
        if target_kickoff and job_kickoff and target_kickoff != job_kickoff:
            evidence["status"] = "TARGET_PROVIDER_KICKOFF_MISMATCH"
            return {"canonical_team_identity": None, "evidence": evidence}
    source_time = _time(source_at)
    cutoff_time = _time(cutoff)
    if source_time is None:
        evidence["status"] = "TARGET_IDENTITY_SOURCE_TIME_INVALID"
        return {"canonical_team_identity": None, "evidence": evidence}
    if cutoff_time is None:
        evidence["status"] = "TARGET_IDENTITY_CUTOFF_TIME_INVALID"
        return {"canonical_team_identity": None, "evidence": evidence}
    kickoff_time = _time(job.get("kickoff"))
    if source_time > cutoff_time:
        evidence["status"] = "TARGET_IDENTITY_SOURCE_AFTER_CUTOFF"
        return {"canonical_team_identity": None, "evidence": evidence}
    if source_time and kickoff_time and source_time >= kickoff_time:
        evidence["status"] = "TARGET_IDENTITY_POST_KICKOFF"
        return {"canonical_team_identity": None, "evidence": evidence}

    if not provider_competition_id or not provider_season_id:
        evidence["status"] = "TARGET_IDENTITY_SEASON_CONTEXT_MISSING"
        evidence["source"]["season_context"] = "provider_competition_id_and_provider_season_id_required"
        return {"canonical_team_identity": None, "evidence": evidence}

    identity_evidence_status = _provider_identity_evidence_failure(
        source or {},
        provider_match_id,
        provider_competition_id,
        provider_season_id,
        cutoff_time,
        kickoff_time,
    )
    if identity_evidence_status:
        evidence["status"] = identity_evidence_status
        return {"canonical_team_identity": None, "evidence": evidence}

    competition_resolver, competition_registry_digest = _competition_registry(
        repository_root, competition_registry_path
    )
    if competition_resolver is None:
        evidence["status"] = "TARGET_IDENTITY_COMPETITION_REGISTRY_UNAVAILABLE"
        return {"canonical_team_identity": None, "evidence": evidence}
    competition_result = competition_resolver.resolve(
        provider=PROVIDER,
        provider_competition_id=provider_competition_id,
        provider_competition_name=_text((source or {}).get("provider_competition_name")) or None,
        provider_season_id=provider_season_id,
        provider_season_name=_text((source or {}).get("provider_season_name")) or None,
    )
    evidence["source"]["competition_registry_sha256"] = competition_registry_digest
    evidence["source"]["competition_resolution"] = competition_result.to_dict()
    if competition_result.resolution_status != "resolved":
        evidence["status"] = "TARGET_IDENTITY_SEASON_CONTEXT_UNRESOLVED"
        return {"canonical_team_identity": None, "evidence": evidence}
    registry_competition_id = competition_result.canonical_competition_id
    explicit_competition = _text(
        fixture.get("canonical_competition_id")
        or job.get("canonical_competition_id")
        or (source or {}).get("canonical_competition_id")
    ) or None
    if explicit_competition and explicit_competition != registry_competition_id:
        evidence["status"] = "TARGET_IDENTITY_CONTEXT_AMBIGUOUS"
        evidence["source"]["competition_context"] = "explicit_competition_conflicts_with_competition_registry"
        return {"canonical_team_identity": None, "evidence": evidence}

    try:
        mappings, crosswalk_digest = _crosswalk(repository_root)
    except (OSError, json.JSONDecodeError, ValueError):
        evidence["status"] = "TARGET_IDENTITY_CROSSWALK_UNAVAILABLE"
        return {"canonical_team_identity": None, "evidence": evidence}
    resolver = ProjectProviderIdentityResolver(mappings)
    competition_id, competition_source = _competition_context(
        resolver, (provider_home_id, provider_away_id), None
    )
    if not competition_id:
        evidence["status"] = (
            "TARGET_IDENTITY_UNRESOLVED"
            if competition_source == "no_reviewed_mapping"
            else "TARGET_IDENTITY_CONTEXT_AMBIGUOUS"
        )
        reason = "no reviewed provider ID mapping" if competition_source == "no_reviewed_mapping" else competition_source
        for side in ("home", "away"):
            evidence[side].update({"resolution_status": "unresolved", "resolution_method": "unresolved", "reason": reason})
        evidence["source"]["competition_context"] = competition_source
        return {"canonical_team_identity": None, "evidence": evidence}
    if competition_id != registry_competition_id:
        evidence["status"] = "TARGET_IDENTITY_CONTEXT_AMBIGUOUS"
        evidence["source"]["competition_context"] = "project_crosswalk_conflicts_with_competition_registry"
        return {"canonical_team_identity": None, "evidence": evidence}
    season_id = competition_result.canonical_season_id
    season_context = {
        "canonical_season_id": season_id,
        "source": "competition_registry",
        "registry_ref": str(competition_registry_path or repository_root / COMPETITION_REGISTRY_RELATIVE_PATH),
        "registry_sha256": competition_registry_digest,
        "provider": PROVIDER,
        "provider_competition_id": provider_competition_id,
        "provider_season_id": provider_season_id,
        "resolution_method": competition_result.resolution_method,
    }
    provider_names = {
        "home": _text(target.get("home") or page_identity.get("home_team") or job.get("home")),
        "away": _text(target.get("away") or page_identity.get("away_team") or job.get("away")),
    }
    results = {
        "home": resolver.resolve_team(
            PROVIDER, provider_names["home"], provider_home_id, competition_id=competition_id
        ),
        "away": resolver.resolve_team(
            PROVIDER, provider_names["away"], provider_away_id, competition_id=competition_id
        ),
    }
    evidence["home"] = _side_evidence(results["home"], provider_home_id, provider_names["home"])
    evidence["away"] = _side_evidence(results["away"], provider_away_id, provider_names["away"])
    evidence["source"]["competition_context"] = competition_source
    evidence["source"]["crosswalk_sha256"] = crosswalk_digest
    if any(result.canonical_team_id is None for result in results.values()):
        evidence["status"] = "TARGET_IDENTITY_UNRESOLVED"
        return {"canonical_team_identity": None, "evidence": evidence}

    evidence["status"] = "RESOLVED"
    evidence["source"]["season_context"] = season_context
    canonical = {
        "contract_version": "canonical_team_identity.v1",
        "provider": PROVIDER,
        "provider_match_id": provider_match_id,
        "competition_id": competition_id,
        "season_id": season_id,
        "home_team_id": results["home"].canonical_team_id,
        "away_team_id": results["away"].canonical_team_id,
        "home_team_name": results["home"].canonical_name,
        "away_team_name": results["away"].canonical_name,
        "provider_home_team_id": provider_home_id,
        "provider_away_team_id": provider_away_id,
        "provider_home_team_name": provider_names["home"],
        "provider_away_team_name": provider_names["away"],
        "resolution_method": {
            "home": results["home"].resolution_method,
            "away": results["away"].resolution_method,
        },
        "evidence": deepcopy(source_info) | {
            "crosswalk_sha256": crosswalk_digest,
            "competition_context": competition_source,
            "season_context": season_context,
        },
    }
    return {"canonical_team_identity": canonical, "evidence": evidence}


__all__ = ["resolve_target_team_identity"]
