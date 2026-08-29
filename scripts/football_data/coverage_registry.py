"""League-agnostic historical coverage registry.

The registry is a routing and audit artifact.  It combines exact competition
catalog entries, captured source manifests, reviewed provider capabilities and
the authoritative historical-result store.  It never downloads data and never
changes the Champion input path.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .storage import HistoricalResultStore, content_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "config" / "football_data_coverage.json"
DEFAULT_COMPETITION_REGISTRY_PATH = PROJECT_ROOT / "data" / "football_data" / "competition_registry.json"
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "data" / "football_data"
DEFAULT_REGISTRY_PATH = DEFAULT_SOURCE_ROOT / "hc_auto_1" / "coverage_registry.json"
CONTRACT_VERSION = "historical_coverage_registry.v1"

STATUS_SUPPORTED = "SUPPORTED"
STATUS_DEGRADED = "DEGRADED"
STATUS_UNSUPPORTED = "UNSUPPORTED"
COVERAGE_STATUSES = frozenset({STATUS_SUPPORTED, STATUS_DEGRADED, STATUS_UNSUPPORTED})

REASON_CODES = frozenset({
    "COMPETITION_UNSUPPORTED",
    "IDENTITY_UNAVAILABLE",
    "HISTORY_INSUFFICIENT",
    "SOURCE_STALE",
    "SOURCE_UNAVAILABLE",
    "CURRENT_SEASON_PARTIAL",
})


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


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
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _season_key(value: Any) -> tuple[int, str]:
    text = _text(value)
    years = re.findall(r"\d{4}", text)
    return (int(years[-1]) if years else -1, text)


def _season_label(value: Any) -> str:
    text = _text(value)
    return text.rsplit(":", 1)[-1] if text.startswith("season:") else text


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def _append_once(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def discover_source_manifests(source_root: str | Path = DEFAULT_SOURCE_ROOT) -> list[Path]:
    """Discover only source-manifest files, not arbitrary repository files."""

    root = Path(source_root)
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*source_manifest.json") if path.is_file())


def load_coverage_catalog(path: str | Path = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    """Load exact aliases and provider capabilities from the data manifest."""

    payload = _read_json(path)
    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for raw in payload.get("competitions", []):
        if not isinstance(raw, Mapping):
            continue
        key = _text(raw.get("competition_key"))
        if not key:
            continue
        row = {
            "competition_key": key,
            "competition_id": _text(raw.get("canonical_competition_id")) or f"competition:{key}",
            "canonical_name": _text(raw.get("canonical_name")) or key,
            "country": _text(raw.get("country")),
            "entity_type": _text(raw.get("entity_type")) or "club",
            "competition_type": _text(raw.get("competition_type")) or "league",
            "aliases": _unique(raw.get("aliases", [])),
        }
        rows.append(row)
        by_id[row["competition_id"]] = row
        by_key[key] = row
        for alias in row["aliases"]:
            aliases[_normal(alias)] = row["competition_id"]
    return {
        "contract_version": _text(payload.get("contract_version")),
        "policy": dict(payload.get("policy") or {}),
        "adapter_capabilities": {
            _text(provider): dict(capability)
            for provider, capability in (payload.get("adapter_capabilities") or {}).items()
            if _text(provider) and isinstance(capability, Mapping)
        },
        "competitions": rows,
        "by_id": by_id,
        "by_key": by_key,
        "aliases": aliases,
        "path": str(path),
    }


def _merge_competition_registry(catalog: dict[str, Any], path: str | Path) -> None:
    """Add reviewed canonical competitions not yet present in the routing catalog."""

    try:
        payload = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    for raw in payload.get("competitions", []):
        if not isinstance(raw, Mapping):
            continue
        competition_id = _text(raw.get("canonical_competition_id"))
        if not competition_id or competition_id in catalog["by_id"]:
            continue
        key = competition_id.removeprefix("competition:")
        row = {
            "competition_key": key,
            "competition_id": competition_id,
            "canonical_name": _text(raw.get("canonical_name")) or key,
            "country": _text(raw.get("country")),
            "entity_type": _text(raw.get("entity_type")) or "club",
            "competition_type": _text(raw.get("competition_type")) or "league",
            "aliases": [],
        }
        catalog["competitions"].append(row)
        catalog["by_id"][competition_id] = row
        catalog["by_key"][key] = row


def _source_failure_codes(source: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    status_values = {
        _text(source.get("source_completeness_status")).upper(),
        _text(source.get("result_coverage")).upper(),
        _text(source.get("current_season_coverage")).upper(),
        _text(source.get("status")).upper(),
    }
    if "UNAVAILABLE" in status_values or "FAILED" in status_values:
        codes.append("SOURCE_UNAVAILABLE")
    return codes


def _load_manifest_sources(
    paths: Iterable[str | Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for raw_path in paths:
        path = Path(raw_path)
        try:
            payload = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures.append({
                "path": _relative(path),
                "reason_code": "SOURCE_UNAVAILABLE",
                "error": f"{type(error).__name__}: {error}",
            })
            continue
        provider = _text(payload.get("provider")) or _text(payload.get("source")) or "unknown_provider"
        captured_at = _text(payload.get("captured_at")) or _text(payload.get("generated_at")) or _text(payload.get("updated_at"))
        rows = payload.get("sources")
        if not isinstance(rows, list):
            rows = payload.get("entries")
        if not isinstance(rows, list):
            failures.append({
                "path": _relative(path),
                "reason_code": "SOURCE_UNAVAILABLE",
                "error": "manifest has no sources list",
            })
            continue
        for raw_source in rows:
            if not isinstance(raw_source, Mapping):
                continue
            source = dict(raw_source)
            competition_key = _text(source.get("competition_key"))
            if not competition_key:
                failures.append({
                    "path": _relative(path),
                    "reason_code": "COMPETITION_UNSUPPORTED",
                    "error": "source row has no competition_key",
                })
                continue
            source["_provider"] = _text(source.get("provider")) or provider
            source["_captured_at"] = captured_at
            source["_manifest_path"] = _relative(path)
            source["_manifest_source_url_template"] = _text(payload.get("source_url_template"))
            source["_manifest_license"] = _text(payload.get("license"))
            source["_manifest_attribution_required"] = bool(payload.get("attribution_required"))
            source["_manifest_commercial_use_review"] = _text(payload.get("commercial_use_review"))
            source["_manifest_raw_redistribution"] = payload.get("raw_redistribution")
            source["_manifest_internal_analysis_only"] = payload.get("internal_analysis_only")
            identity = (
                competition_key,
                source["_provider"],
                _text(source.get("provider_competition_id")),
                _text(source.get("provider_season_id")),
                _text(source.get("source_file")),
                _text(source.get("raw_sha256")),
            )
            if identity in seen:
                continue
            seen.add(identity)
            sources.append(source)
    return sources, failures


def _records_from_inputs(
    historical_records: Iterable[Mapping[str, Any]] | None,
    historical_store: HistoricalResultStore | None,
) -> list[dict[str, Any]]:
    if historical_records is not None:
        return [dict(record) for record in historical_records if isinstance(record, Mapping)]
    if historical_store is not None:
        return [dict(record) for record in historical_store.iter_records()]
    try:
        return [dict(record) for record in HistoricalResultStore().iter_records()]
    except Exception:
        # A missing optional local bulk store is itself an auditable source gap;
        # registry generation must still serve competitions with other evidence.
        return []


def _historical_stats(records: Iterable[Mapping[str, Any]], now: datetime, policy: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        competition_id = _text(record.get("competition_id"))
        if not competition_id:
            continue
        stats = grouped.setdefault(competition_id, {
            "historical_match_count": 0,
            "eligible_match_count": 0,
            "resolved_match_count": 0,
            "unresolved_match_count": 0,
            "team_match_counts": {},
            "team_latest": {},
            "seasons": set(),
            "kickoffs": [],
            "quality_counts": {},
            "providers": set(),
            "source_conflict_count": 0,
        })
        stats["historical_match_count"] += 1
        season = _text(record.get("season_id"))
        if season:
            stats["seasons"].add(_season_label(season))
        provider = _text(record.get("provider"))
        if provider:
            stats["providers"].add(provider)
        quality = _text(record.get("quality")) or "UNKNOWN"
        stats["quality_counts"][quality] = stats["quality_counts"].get(quality, 0) + 1
        if bool(record.get("source_conflict")):
            stats["source_conflict_count"] += 1
        home = _text(record.get("home_team_id"))
        away = _text(record.get("away_team_id"))
        resolved = bool(home and away and _text(record.get("canonical_match_id")) and record.get("resolution_status", "resolved") not in {"unresolved", "ambiguous"})
        if resolved:
            stats["resolved_match_count"] += 1
            for team_id in (home, away):
                stats["team_match_counts"][team_id] = stats["team_match_counts"].get(team_id, 0) + 1
        else:
            stats["unresolved_match_count"] += 1
        if record.get("eligible_for_team_strength") is True:
            stats["eligible_match_count"] += 1
        kickoff = _parse_time(record.get("kickoff_at"))
        if kickoff is not None:
            stats["kickoffs"].append(kickoff)
            if resolved:
                for team_id in (home, away):
                    latest = stats["team_latest"].get(team_id)
                    if latest is None or kickoff > latest:
                        stats["team_latest"][team_id] = kickoff
    output: dict[str, dict[str, Any]] = {}
    max_age = int(policy.get("current_max_history_age_days", 60))
    for competition_id, stats in grouped.items():
        kickoffs = stats["kickoffs"]
        team_counts = stats["team_match_counts"]
        latest = max(kickoffs) if kickoffs else None
        age_days = round((now - latest).total_seconds() / 86400, 6) if latest else None
        status = "CURRENT" if age_days is not None and age_days <= max_age else "STALE" if age_days is not None else "UNKNOWN"
        output[competition_id] = {
            "historical_match_count": stats["historical_match_count"],
            "eligible_match_count": stats["eligible_match_count"],
            "resolved_match_count": stats["resolved_match_count"],
            "unresolved_match_count": stats["unresolved_match_count"],
            "team_count": len(team_counts),
            "team_match_counts": dict(sorted(team_counts.items())),
            "team_latest_historical_match_at": {team: _iso(value) for team, value in sorted(stats["team_latest"].items())},
            "seasons": sorted(stats["seasons"], key=_season_key),
            "earliest_historical_match_at": _iso(min(kickoffs)) if kickoffs else None,
            "latest_historical_match_at": _iso(latest),
            "freshness": {
                "state": status,
                "age_days": age_days,
                "max_age_days": max_age,
            },
            "quality_counts": dict(sorted(stats["quality_counts"].items())),
            "best_quality": next((grade for grade in ("A", "B", "C", "D") if stats["quality_counts"].get(grade)), "UNKNOWN"),
            "providers": sorted(stats["providers"]),
            "source_conflict_count": stats["source_conflict_count"],
        }
    return output


def _source_row(
    source: Mapping[str, Any],
    capability: Mapping[str, Any],
    *,
    competition_id: str,
) -> dict[str, Any]:
    source_failures = _source_failure_codes(source)
    captured_at = _text(source.get("_captured_at")) or None
    commercial_review = _text(source.get("commercial_use_review")) or _text(source.get("_manifest_commercial_use_review")) or _text(capability.get("commercial_use_review")) or "not_reviewed"
    return {
        "competition_id": competition_id,
        "provider": _text(source.get("_provider")) or "unknown_provider",
        "provider_competition_id": _text(source.get("provider_competition_id")) or None,
        "provider_competition_name": _text(source.get("provider_competition_name")) or None,
        "provider_season_id": _text(source.get("provider_season_id")) or None,
        "provider_season_name": _text(source.get("provider_season_name")) or None,
        "source_file": _text(source.get("source_file")) or None,
        "source_url": _text(source.get("source_url")) or _text(source.get("source_url_template")) or _text(source.get("_manifest_source_url_template")) or None,
        "source_manifest": _text(source.get("_manifest_path")) or None,
        "raw_sha256": _text(source.get("raw_sha256")) or None,
        "season_status": _text(source.get("season_status")).lower() or ("completed" if _text(source.get("source_completeness_status")).upper() == "COMPLETE" else "unknown"),
        "listed_match_count": source.get("listed_match_count"),
        "parsed_result_count": source.get("parsed_result_count"),
        "result_completion_ratio": source.get("result_completion_ratio"),
        "source_completeness_status": _text(source.get("source_completeness_status")).upper() or "UNKNOWN",
        "result_coverage": _text(source.get("result_coverage")).upper() or "UNKNOWN",
        "current_season_coverage": _text(source.get("current_season_coverage")).upper() or "UNKNOWN",
        "automatic_import_capability": bool(capability.get("automatic_import")),
        "source_quality": _text(capability.get("source_quality")) or "unknown",
        "commercial_use_restrictions": {
            "license": _text(_first_present(source.get("license"), source.get("_manifest_license"))) or None,
            "commercial_use_review": commercial_review,
            "attribution_required": bool(_first_present(source.get("attribution_required"), source.get("_manifest_attribution_required"), capability.get("attribution_required"))),
            "raw_redistribution": _first_present(source.get("raw_redistribution"), source.get("_manifest_raw_redistribution"), capability.get("raw_redistribution")),
            "internal_analysis_only": _first_present(source.get("internal_analysis_only"), source.get("_manifest_internal_analysis_only"), capability.get("internal_analysis_only")),
        },
        "last_successful_refresh": captured_at if not source_failures else None,
        "failure_reason": source_failures,
    }


def _new_catalog_row(competition_key: str, source: Mapping[str, Any]) -> dict[str, Any]:
    competition_id = _text(source.get("canonical_competition_id") or source.get("competition_id")) or f"competition:{competition_key}"
    return {
        "competition_key": competition_key,
        "competition_id": competition_id,
        "canonical_name": _text(source.get("provider_competition_name")) or competition_key,
        "country": _text(source.get("country")),
        "entity_type": _text(source.get("entity_type")) or "club",
        "competition_type": _text(source.get("competition_type")) or "league",
        "aliases": [],
    }


class CoverageRegistryBuilder:
    """Build one deterministic registry from manifests and immutable history."""

    def __init__(
        self,
        *,
        catalog_path: str | Path = DEFAULT_CATALOG_PATH,
        competition_registry_path: str | Path = DEFAULT_COMPETITION_REGISTRY_PATH,
        manifest_paths: Iterable[str | Path] | None = None,
        source_root: str | Path = DEFAULT_SOURCE_ROOT,
        historical_records: Iterable[Mapping[str, Any]] | None = None,
        historical_store: HistoricalResultStore | None = None,
        now: datetime | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.competition_registry_path = Path(competition_registry_path)
        self.manifest_paths = [Path(path) for path in manifest_paths] if manifest_paths is not None else discover_source_manifests(source_root)
        self.historical_records = historical_records
        self.historical_store = historical_store
        self.now = now or datetime.now(timezone.utc)

    def build(self) -> dict[str, Any]:
        catalog = load_coverage_catalog(self.catalog_path)
        _merge_competition_registry(catalog, self.competition_registry_path)
        manifest_sources, manifest_failures = _load_manifest_sources(self.manifest_paths)
        history = _historical_stats(_records_from_inputs(self.historical_records, self.historical_store), self.now, catalog["policy"])

        by_id = catalog["by_id"]
        sources_by_id: dict[str, list[dict[str, Any]]] = {}
        for source in manifest_sources:
            key = _text(source.get("competition_key"))
            row = catalog["by_key"].get(key)
            if row is None:
                row = _new_catalog_row(key, source)
                catalog["competitions"].append(row)
                catalog["by_key"][key] = row
                catalog["by_id"][row["competition_id"]] = row
            competition_id = row["competition_id"]
            by_id[competition_id] = row
            capability = catalog["adapter_capabilities"].get(_text(source.get("_provider")), {})
            sources_by_id.setdefault(competition_id, []).append(_source_row(source, capability, competition_id=competition_id))

        competitions: list[dict[str, Any]] = []
        minimum_history = int(catalog["policy"].get("minimum_history_matches_per_team", 5))
        for row in sorted(catalog["competitions"], key=lambda item: str(item["competition_id"])):
            competition_id = row["competition_id"]
            stats = history.get(competition_id, {})
            source_rows = sources_by_id.get(competition_id, [])
            source_rows = sorted(source_rows, key=lambda item: (
                _season_key(item.get("provider_season_id")),
                str(item.get("provider") or ""),
                str(item.get("source_file") or ""),
            ))
            source_seasons = [row.get("provider_season_id") for row in source_rows]
            seasons_available = sorted(_unique([*stats.get("seasons", []), *source_seasons]), key=_season_key)
            completed = [item.get("provider_season_id") for item in source_rows if item.get("season_status") == "completed"]
            current_candidates = [item for item in source_rows if item.get("provider_season_id")]
            current = max(current_candidates, key=lambda item: _season_key(item.get("provider_season_id"))) if current_candidates else None
            last_refreshes = [_parse_time(item.get("last_successful_refresh")) for item in source_rows]
            last_refreshes = [value for value in last_refreshes if value is not None]
            source_failures = [code for item in source_rows for code in item.get("failure_reason", [])]
            failure_reason: list[str] = []
            if not source_rows:
                _append_once(failure_reason, "SOURCE_UNAVAILABLE")
            for code in source_failures:
                _append_once(failure_reason, code)
            if stats.get("historical_match_count", 0) == 0 and source_rows and not source_failures:
                _append_once(failure_reason, "HISTORY_INSUFFICIENT")
            if stats.get("unresolved_match_count", 0):
                _append_once(failure_reason, "IDENTITY_UNAVAILABLE")
            team_counts = stats.get("team_match_counts", {})
            min_team_matches = min(team_counts.values()) if team_counts else 0
            automatic = any(bool(item.get("automatic_import_capability")) for item in source_rows)
            quality_counts = stats.get("quality_counts", {})
            restrictions = {
                "commercial_use_review": _unique(item.get("commercial_use_restrictions", {}).get("commercial_use_review") for item in source_rows)[0] if len(_unique(item.get("commercial_use_restrictions", {}).get("commercial_use_review") for item in source_rows)) == 1 else "mixed" if source_rows else "unknown",
                "licenses": _unique(item.get("commercial_use_restrictions", {}).get("license") for item in source_rows),
                "attribution_required": any(bool(item.get("commercial_use_restrictions", {}).get("attribution_required")) for item in source_rows),
                "raw_redistribution": any(item.get("commercial_use_restrictions", {}).get("raw_redistribution") is True for item in source_rows),
                "internal_analysis_only": all(item.get("commercial_use_restrictions", {}).get("internal_analysis_only") is True for item in source_rows) if source_rows else True,
            }
            competitions.append({
                "competition_id": competition_id,
                "competition_key": row["competition_key"],
                "canonical_name": row["canonical_name"],
                "country": row["country"],
                "entity_type": row["entity_type"],
                "competition_type": row["competition_type"],
                "aliases": row["aliases"],
                "provider_source_availability": source_rows,
                "seasons_available": seasons_available,
                "latest_completed_season": max(completed, key=_season_key) if completed else None,
                "current_season_status": current.get("season_status") if current else "unknown",
                "historical_match_count": int(stats.get("historical_match_count", 0)),
                "team_count": int(stats.get("team_count", 0)),
                "identity_coverage": {
                    "historical_record_count": int(stats.get("historical_match_count", 0)),
                    "resolved_record_count": int(stats.get("resolved_match_count", 0)),
                    "unresolved_record_count": int(stats.get("unresolved_match_count", 0)),
                    "ratio": round(stats.get("resolved_match_count", 0) / stats["historical_match_count"], 6) if stats.get("historical_match_count", 0) else 0.0,
                },
                "history_depth": {
                    "eligible_match_count": int(stats.get("eligible_match_count", 0)),
                    "earliest_historical_match_at": stats.get("earliest_historical_match_at"),
                    "latest_historical_match_at": stats.get("latest_historical_match_at"),
                    "minimum_team_match_count": min_team_matches,
                    "minimum_required_per_team": minimum_history,
                    "team_match_counts": stats.get("team_match_counts", {}),
                    "team_latest_historical_match_at": stats.get("team_latest_historical_match_at", {}),
                },
                "freshness": stats.get("freshness", {
                    "state": "UNKNOWN",
                    "age_days": None,
                    "max_age_days": int(catalog["policy"].get("current_max_history_age_days", 60)),
                }),
                "source_quality": {
                    "quality_counts": quality_counts,
                    "best_grade": stats.get("best_quality", "UNKNOWN"),
                    "source_providers": stats.get("providers", []),
                    "source_conflict_count": int(stats.get("source_conflict_count", 0)),
                },
                "commercial_use_restrictions": restrictions,
                "automatic_import_capability": automatic,
                "last_successful_refresh": _iso(max(last_refreshes)) if last_refreshes else None,
                "failure_reason": failure_reason,
            })

        registry = {
            "contract_version": CONTRACT_VERSION,
            "generated_at": _iso(self.now),
            "builder": "CoverageRegistryBuilder.v1",
            "policy": dict(catalog["policy"]),
            "catalog_source": _relative(self.catalog_path),
            "source_inventory": {
                "manifest_count": len(self.manifest_paths),
                "manifest_paths": [_relative(path) for path in self.manifest_paths],
                "source_row_count": len(manifest_sources),
                "manifest_failures": manifest_failures,
            },
            "competition_count": len(competitions),
            "competitions": competitions,
        }
        validate_coverage_registry(registry)
        registry["registry_digest"] = content_sha256(registry)
        return registry


def validate_coverage_registry(registry: Mapping[str, Any]) -> None:
    """Validate the required stable fields without adding a JSON dependency."""

    if registry.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unexpected historical coverage registry contract version")
    rows = registry.get("competitions")
    if not isinstance(rows, list):
        raise ValueError("coverage registry competitions must be a list")
    required = {
        "competition_id",
        "provider_source_availability",
        "seasons_available",
        "latest_completed_season",
        "current_season_status",
        "historical_match_count",
        "team_count",
        "identity_coverage",
        "history_depth",
        "freshness",
        "source_quality",
        "commercial_use_restrictions",
        "automatic_import_capability",
        "last_successful_refresh",
        "failure_reason",
    }
    for row in rows:
        if not isinstance(row, Mapping) or not required.issubset(row):
            raise ValueError("coverage registry competition row is missing required fields")
        if row["competition_id"] in (None, ""):
            raise ValueError("coverage registry competition_id is required")


def load_coverage_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    registry = _read_json(path)
    validate_coverage_registry(registry)
    return registry


def write_coverage_registry(registry: Mapping[str, Any], path: str | Path = DEFAULT_REGISTRY_PATH) -> Path:
    validate_coverage_registry(registry)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


__all__ = [
    "CONTRACT_VERSION",
    "COVERAGE_STATUSES",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_REGISTRY_PATH",
    "CoverageRegistryBuilder",
    "discover_source_manifests",
    "load_coverage_catalog",
    "load_coverage_registry",
    "validate_coverage_registry",
    "write_coverage_registry",
]
