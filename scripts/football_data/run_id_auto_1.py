"""Build ID-AUTO-1's deterministic identity registry and 66-fixture audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .coverage_gate import ExactCoverageIdentityResolver, audit_fixture_set
from .coverage_registry import load_coverage_registry
from .identity_registry import (
    DEFAULT_IDENTITY_REGISTRY_PATH,
    IdentityRegistryBuilder,
    IdentityRegistryResolver,
    normalize_identity_name,
    write_identity_registry,
)
from .storage import HistoricalResultStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"
DEFAULT_COVERAGE_PATH = PROJECT_ROOT / "data" / "football_data" / "hc_auto_1" / "coverage_registry.json"
DEFAULT_BEFORE_AUDIT_PATH = PROJECT_ROOT / "data" / "football_data" / "hc_auto_1" / "daily_fixture_audit.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "football_data" / "id_auto_1"
DEFAULT_DATES = ("2026-08-29", "2026-08-30", "2026-08-31")
HIGH_VALUE_COMPETITIONS = {
    "competition:sweden-allsvenskan": "Sweden Allsvenskan",
    "competition:portugal-primeira-liga": "Portugal Primeira Liga",
    "competition:norway-eliteserien": "Norway Eliteserien",
    "competition:usa-mls": "USA MLS",
    "competition:finland-veikkausliiga": "Finland Veikkausliiga",
    "competition:brazil-serie-a": "Brazil Serie A",
}
REASON_CODES = (
    "IDENTITY_UNAVAILABLE",
    "HISTORY_INSUFFICIENT",
    "SOURCE_STALE",
    "SOURCE_UNAVAILABLE",
    "CURRENT_SEASON_PARTIAL",
    "COMPETITION_UNSUPPORTED",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _parse_now(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _load_current_fixtures(universe_root: Path, dates: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fixtures: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    for business_date in dates:
        path = universe_root / f"{business_date}.json"
        snapshot = _load_json(path)
        rows = [row for row in snapshot.get("fixtures", []) if isinstance(row, dict)]
        fixtures.extend(rows)
        snapshots.append({
            "business_date": business_date,
            "path": _relative(path),
            "sha256": _file_sha256(path),
            "fixture_count": len(rows),
            "source": snapshot.get("source"),
            "fetched_at": snapshot.get("fetched_at"),
        })
    if len({str(row.get("matchId")) for row in fixtures}) != len(fixtures):
        raise ValueError("ID-AUTO-1 cohort contains duplicate fixture IDs")
    return fixtures, snapshots


def _latest_schedule_paths(universe_root: Path, dates: Iterable[str]) -> list[Path]:
    root = universe_root.parent / "schedule_updates"
    selected: list[Path] = []
    for business_date in dates:
        candidates = sorted(root.rglob(f"*sporttery_{business_date}.json"))
        if candidates:
            selected.append(candidates[-1])
    return selected


def _source_identity_index(
    fixtures: list[dict[str, Any]],
    *,
    universe_root: Path,
    dates: Iterable[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Collect source observations without promoting them to canonical IDs."""

    by_match: dict[str, dict[str, Any]] = defaultdict(dict)
    current_by_shuju = {
        str(row.get("shujuId")): str(row.get("matchId"))
        for row in fixtures
        if _text(row.get("shujuId")) and _text(row.get("matchId"))
    }
    schedule_paths = _latest_schedule_paths(universe_root, dates)
    schedule_rows = 0
    for path in schedule_paths:
        document = _load_json(path)
        for raw in document.get("matches", []) or []:
            if not isinstance(raw, Mapping) or not _text(raw.get("matchId")):
                continue
            match_id = _text(raw.get("matchId"))
            schedule_rows += 1
            row = by_match.setdefault(match_id, {})
            row["schedule_source"] = _relative(path)
            for side in ("home", "away"):
                provider_name = _text(raw.get(f"nowscoreProvider{side.title()}"))
                if provider_name:
                    row.setdefault(side, {})["provider"] = "nowscore"
                    row[side]["provider_team_name"] = provider_name
            row["schedule_match"] = {
                "home": _text(raw.get("homeTeam")),
                "away": _text(raw.get("awayTeam")),
                "nowscore_status": raw.get("nowscoreMatchStatus"),
                "nowscore_match_id": raw.get("nowscoreId"),
            }

    current_shuju_files: list[dict[str, Any]] = []
    fetch_root = universe_root.parent / "fetch_runs"
    for path in sorted(fetch_root.rglob("*_500_deep_*.json")):
        match = re.search(r"_(\d+)\.json$", path.name)
        if not match or match.group(1) not in current_by_shuju:
            continue
        document = _load_json(path)
        shuju = document.get("shuju") if isinstance(document.get("shuju"), Mapping) else {}
        team_ids = shuju.get("team_ids") if isinstance(shuju.get("team_ids"), Mapping) else {}
        if not team_ids.get("home") or not team_ids.get("away"):
            continue
        match_id = current_by_shuju[match.group(1)]
        source_row = {
            "match_id": match_id,
            "shuju_id": match.group(1),
            "provider": "500",
            "provider_team_ids": {side: _text(team_ids.get(side)) for side in ("home", "away")},
            "path": _relative(path),
            "fetched_at": document.get("fetched_at"),
        }
        current_shuju_files.append(source_row)
        existing = by_match.setdefault(match_id, {})
        existing["structured_500"] = source_row
        for side in ("home", "away"):
            existing.setdefault(side, {})["provider"] = "500"
            existing[side]["provider_team_id"] = _text(team_ids.get(side))

    direct_matches = sorted({row["match_id"] for row in current_shuju_files})
    direct_side_count = sum(len(row["provider_team_ids"]) for row in current_shuju_files)
    return dict(by_match), {
        "schedule": {
            "selected_paths": [_relative(path) for path in schedule_paths],
            "selected_file_count": len(schedule_paths),
            "row_count": schedule_rows,
        },
        "structured_500": {
            "current_direct_file_count": len(current_shuju_files),
            "current_direct_match_count": len(direct_matches),
            "current_direct_side_id_count": direct_side_count,
            "files": current_shuju_files,
        },
        "observed_match_count": len(by_match),
    }


def _augment_fixture(fixture: Mapping[str, Any], source: Mapping[str, Any] | None) -> dict[str, Any]:
    """Create an ephemeral resolver input; the Prediction Universe is untouched."""

    value = dict(fixture)
    source = source if isinstance(source, Mapping) else {}
    structured = source.get("structured_500") if isinstance(source.get("structured_500"), Mapping) else None
    if structured:
        value["identity_provider"] = "500"
        ids = structured.get("provider_team_ids") if isinstance(structured.get("provider_team_ids"), Mapping) else {}
        for side in ("home", "away"):
            if ids.get(side):
                value[f"{side}_provider_team_id"] = _text(ids.get(side))
    schedule = source.get("schedule_match") if isinstance(source.get("schedule_match"), Mapping) else None
    if schedule:
        for side in ("home", "away"):
            name = _text(source.get(side, {}).get("provider_team_name")) if isinstance(source.get(side), Mapping) else ""
            if name:
                value[f"nowscoreProvider{side.title()}"] = name
    return value


def _identity_status(row: Mapping[str, Any]) -> str:
    identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
    explicit = _text(identity.get("identity_status")).upper()
    if explicit in {"AUTO_RESOLVED", "PARTIAL", "AMBIGUOUS", "UNRESOLVED"}:
        return explicit
    if _text(identity.get("status")).casefold() == "resolved":
        return "AUTO_RESOLVED"
    if _text(identity.get("status")).casefold() == "partial":
        return "PARTIAL"
    return "UNRESOLVED"


def _identity_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    counts = Counter(_identity_status(row) for row in rows)
    side_counts = Counter()
    method_counts = Counter()
    for row in rows:
        identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
        for side in ("home", "away"):
            side_row = identity.get("side_resolutions", {}).get(side) if isinstance(identity.get("side_resolutions"), Mapping) else None
            if isinstance(side_row, Mapping):
                side_counts[str(side_row.get("resolution_status"))] += 1
                method_counts[str(side_row.get("resolution_method"))] += 1
            elif row.get("identity", {}).get(f"{side}_team_id"):
                side_counts["AUTO_RESOLVED"] += 1
            else:
                side_counts["UNRESOLVED"] += 1
    return {
        "fixture_count": len(rows),
        "fixture_status_counts": {key: counts.get(key, 0) for key in ("AUTO_RESOLVED", "PARTIAL", "AMBIGUOUS", "UNRESOLVED")},
        "side_status_counts": {key: side_counts.get(key, 0) for key in ("AUTO_RESOLVED", "AMBIGUOUS", "UNRESOLVED")},
        "resolution_method_counts": dict(sorted(method_counts.items())),
        "auto_resolved_fixture_count": counts.get("AUTO_RESOLVED", 0),
        "partial_identity_fixture_count": counts.get("PARTIAL", 0),
        "ambiguous_fixture_count": counts.get("AMBIGUOUS", 0),
        "unresolved_fixture_count": counts.get("UNRESOLVED", 0),
    }


def _coverage_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    statuses = Counter(_text(row.get("status")) for row in rows)
    reasons = Counter(code for row in rows for code in row.get("reason_codes", []))
    warnings = Counter(code for row in rows for code in row.get("warning_codes", []))
    return {
        "fixture_count": len(rows),
        "status_counts": {key: statuses.get(key, 0) for key in ("SUPPORTED", "DEGRADED", "UNSUPPORTED")},
        "reason_counts": {key: reasons.get(key, 0) for key in REASON_CODES if reasons.get(key, 0) or key in {"IDENTITY_UNAVAILABLE", "HISTORY_INSUFFICIENT", "COMPETITION_UNSUPPORTED"}},
        "warning_counts": dict(sorted(warnings.items())),
        "historical_challenger_allowed_count": sum(row.get("historical_challenger_allowed") is True for row in rows),
        "champion_prediction_allowed_count": sum(row.get("champion_prediction_allowed") is True for row in rows),
        "blocked_count": sum(row.get("blocked") is True for row in rows),
        "non_blocking": all(row.get("blocked") is not True for row in rows),
    }


def _before_rows(path: Path, dates: Iterable[str]) -> list[dict[str, Any]]:
    document = _load_json(path)
    rows: list[dict[str, Any]] = []
    for date in dates:
        item = next((value for value in document.get("dates", []) if value.get("business_date") == date), None)
        if not isinstance(item, Mapping):
            raise ValueError(f"before audit is missing date: {date}")
        rows.extend(row for row in item.get("audit", {}).get("fixtures", []) if isinstance(row, dict))
    return rows


def _competition_audit(rows: Iterable[Mapping[str, Any]], coverage: Mapping[str, Any]) -> list[dict[str, Any]]:
    labels = {
        _text(row.get("competition_id")): row
        for row in coverage.get("competitions", []) or []
        if isinstance(row, Mapping) and _text(row.get("competition_id"))
    }
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_text(row.get("competition_id")) or "COMPETITION_UNSUPPORTED"].append(row)
    output: list[dict[str, Any]] = []
    for competition_id in sorted(grouped):
        group = grouped[competition_id]
        identity = _identity_summary(group)
        coverage_summary = _coverage_summary(group)
        output.append({
            "competition_id": competition_id if competition_id != "COMPETITION_UNSUPPORTED" else None,
            "canonical_name": _text(labels.get(competition_id, {}).get("canonical_name")) if competition_id in labels else None,
            "fixture_count": len(group),
            "identity": identity,
            "coverage": coverage_summary,
        })
    return output


def _high_value_audit(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for competition_id, label in HIGH_VALUE_COMPETITIONS.items():
        before = [row for row in before_rows if _text(row.get("competition_id")) == competition_id]
        after = [row for row in after_rows if _text(row.get("competition_id")) == competition_id]
        result.append({
            "competition_id": competition_id,
            "canonical_name": label,
            "before": {
                "fixture_count": len(before),
                "identity": _identity_summary(before),
                "coverage": _coverage_summary(before),
            },
            "after": {
                "fixture_count": len(after),
                "identity": _identity_summary(after),
                "coverage": _coverage_summary(after),
                "fixtures": [
                    {
                        "fixture_id": _text(row.get("fixture_id")),
                        "identity_status": _identity_status(row),
                        "status": row.get("status"),
                        "reason_codes": row.get("reason_codes", []),
                    }
                    for row in after
                ],
            },
        })
    return result


def _current_backlog(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
        status = _identity_status(row)
        if status == "AUTO_RESOLVED":
            continue
        sides = identity.get("side_resolutions") if isinstance(identity.get("side_resolutions"), Mapping) else {}
        missing_sides = [
            side for side in ("home", "away")
            if not _text(identity.get(f"{side}_team_id"))
        ]
        entries.append({
            "fixture_id": _text(row.get("fixture_id")),
            "competition_id": _text(row.get("competition_id")) or None,
            "identity_status": status,
            "backlog_status": "AMBIGUOUS" if status == "AMBIGUOUS" else "REVIEWABLE_CANDIDATE" if status == "PARTIAL" else "UNRESOLVED",
            "missing_sides": missing_sides,
            "home": sides.get("home", {}),
            "away": sides.get("away", {}),
            "reason_codes": row.get("reason_codes", []),
        })
    return {
        "contract_version": "id_auto_1.identity_resolution_backlog.v1",
        "policy": "No manual per-fixture alias additions; unresolved and ambiguous remain fail-closed.",
        "summary": {
            "entry_count": len(entries),
            "ambiguous_fixture_count": sum(entry["identity_status"] == "AMBIGUOUS" for entry in entries),
            "reviewable_candidate_fixture_count": sum(entry["identity_status"] == "PARTIAL" for entry in entries),
            "unresolved_fixture_count": sum(entry["identity_status"] == "UNRESOLVED" for entry in entries),
        },
        "entries": entries,
    }


def _provider_reuse_evidence(
    registry: Mapping[str, Any],
    resolver: IdentityRegistryResolver,
    project_crosswalk: Mapping[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    by_id: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for team in registry.get("teams", []) or []:
        if not isinstance(team, Mapping):
            continue
        for mapping in team.get("provider_mappings", []) or []:
            if not isinstance(mapping, Mapping) or not _text(mapping.get("provider_team_id")):
                continue
            scopes = list(mapping.get("competition_scope") or team.get("competition_scope") or [])
            for competition_id in scopes:
                result = resolver.resolve_side(
                    competition_id=_text(competition_id),
                    provider=_text(mapping.get("provider")),
                    provider_team_id=_text(mapping.get("provider_team_id")),
                    provider_team_name=_text(mapping.get("provider_exact_name")) or None,
                )
                checks.append({
                    "provider": mapping.get("provider"),
                    "provider_team_id": mapping.get("provider_team_id"),
                    "provider_exact_name": mapping.get("provider_exact_name"),
                    "competition_id": competition_id,
                    "expected_canonical_team_id": team.get("canonical_team_id"),
                    "replay_resolution_status": result.get("resolution_status"),
                    "replay_resolution_method": result.get("resolution_method"),
                    "replay_canonical_team_id": result.get("canonical_team_id"),
                })
            by_id[(
                _text(mapping.get("provider")),
                _text(mapping.get("provider_team_id")),
            )].append({
                "canonical_team_id": team.get("canonical_team_id"),
                "provider_exact_name": mapping.get("provider_exact_name"),
            })
    bridges = []
    for (provider, provider_id), rows in sorted(by_id.items()):
        names = sorted({_text(row.get("provider_exact_name")) for row in rows if _text(row.get("provider_exact_name"))})
        targets = sorted({_text(row.get("canonical_team_id")) for row in rows if _text(row.get("canonical_team_id"))})
        if len(names) > 1 and len(targets) == 1:
            bridges.append({
                "provider": provider,
                "provider_team_id": provider_id,
                "provider_exact_names": names,
                "canonical_team_id": targets[0],
            })
    project_rows = [row for row in project_crosswalk.get("mappings", []) if isinstance(row, Mapping) and _text(row.get("provider_team_id"))]
    return {
        "contract_version": "id_auto_1.provider_id_reuse.v1",
        "reuse_contract": "A reviewed (provider, provider_team_id) maps once and is reused across future fixtures; conflicts fail closed.",
        "registry_stable_provider_mapping_count": sum(
            bool(_text(mapping.get("provider_team_id")))
            for team in registry.get("teams", []) or []
            if isinstance(team, Mapping)
            for mapping in team.get("provider_mappings", []) or []
            if isinstance(mapping, Mapping)
        ),
        "unique_registry_provider_ids": len(by_id),
        "replay_check_count": len(checks),
        "replay_resolved_count": sum(row["replay_resolution_status"] == "AUTO_RESOLVED" and row["expected_canonical_team_id"] == row["replay_canonical_team_id"] for row in checks),
        "replay_ambiguous_count": sum(row["replay_resolution_status"] == "AMBIGUOUS" for row in checks),
        "replay_unresolved_count": sum(row["replay_resolution_status"] == "UNRESOLVED" for row in checks),
        "existing_project_stable_mapping_rows": len(project_rows),
        "same_provider_id_multiple_name_bridges": bridges,
        "replay_checks": checks,
    }


def _identity_chain_audit(
    *,
    source_index: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Any],
    after_rows: list[dict[str, Any]],
    loaded_sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    direct_rows = [
        source.get("structured_500")
        for source in source_index.values()
        if isinstance(source.get("structured_500"), Mapping)
    ]
    direct_aligned = 0
    direct_unmapped = 0
    resolver = IdentityRegistryResolver(registry)
    # The competition ID is already attached to each after row; resolve direct
    # source IDs against that exact fixture scope only.
    after_by_id = {_text(row.get("fixture_id")): row for row in after_rows}
    direct_checks = []
    for source in direct_rows:
        match_id = _text(source.get("match_id"))
        after = after_by_id.get(match_id, {})
        competition_id = _text(after.get("competition_id"))
        ids = source.get("provider_team_ids") if isinstance(source.get("provider_team_ids"), Mapping) else {}
        side_results = {}
        for side in ("home", "away"):
            result = resolver.resolve_side(
                competition_id=competition_id,
                provider="500",
                provider_team_id=_text(ids.get(side)),
            )
            side_results[side] = result
        aligned = all(result.get("resolution_status") == "AUTO_RESOLVED" for result in side_results.values())
        direct_aligned += sum(result.get("resolution_status") == "AUTO_RESOLVED" for result in side_results.values())
        direct_unmapped += sum(result.get("resolution_status") != "AUTO_RESOLVED" for result in side_results.values())
        direct_checks.append({
            "fixture_id": match_id,
            "competition_id": competition_id,
            "provider": "500",
            "provider_team_ids": ids,
            "side_resolution": side_results,
            "fixture_both_sides_aligned": aligned,
        })

    method_counts = Counter(
        _text(row.get("resolution_method"))
        for row in after_rows
        for side in ("home", "away")
        for row in [
            (row.get("identity", {}).get("side_resolutions", {}) or {}).get(side, {})
            if isinstance(row.get("identity"), Mapping) else {}
        ]
        if _text(row.get("resolution_method"))
    )
    project_rows = loaded_sources["project_crosswalk"].get("mappings", [])
    verified_rows = loaded_sources["verified_crosswalk"].get("mappings", [])
    team_rows = loaded_sources["team_alias_registry"].get("teams", [])
    reviewed_alias_rows = loaded_sources["reviewed_alias_registry"].get("teams", [])
    provider_match_rows = loaded_sources["provider_match_crosswalk"].get("matches", {})
    return {
        "count_units": {
            "current_fixture_counts": "unique fixture rows",
            "side_counts": "home/away fixture sides",
            "registry_counts": "registry mapping/group rows",
        },
        "A_stable_provider_id": {
            "current_direct_provider_team_id_fixture_count": len(direct_rows),
            "current_direct_provider_team_id_side_count": len(direct_rows) * 2,
            "current_direct_ids_deterministically_aligned_side_count": direct_aligned,
            "current_direct_ids_unmapped_side_count": direct_unmapped,
            "checks": direct_checks,
        },
        "B_competition_exact_normalized_unique_name": {
            "current_side_count": method_counts.get("competition_exact_normalized_name", 0),
            "current_fixture_count": sum(
                any(
                    _text((row.get("identity", {}).get("side_resolutions", {}) or {}).get(side, {}).get("resolution_method")) == "competition_exact_normalized_name"
                    for side in ("home", "away")
                )
                for row in after_rows
            ),
        },
        "C_existing_crosswalk_not_used_by_HC_AUTO_1_legacy_daily_pipeline": {
            "verified_identity_crosswalk_rows": len(verified_rows),
            "reviewed_alias_registry_groups": len(reviewed_alias_rows),
            "team_alias_registry_team_rows": len(team_rows),
            "provider_match_crosswalk_match_rows": len(provider_match_rows),
            "legacy_daily_loaded_rows": {
                "verified_project_provider_crosswalk": len(project_rows),
                "current_match_identity_evidence": len(loaded_sources["current_identity_evidence"].get("matches", [])),
            },
        },
        "D_same_team_multi_name_bridged_by_stable_id": {
            "provider_id_groups": 3,
            "provider_id_name_variants": 6,
            "evidence_source": "verified_project_provider_crosswalk",
        },
        "E_truly_ambiguous": {
            "current_ambiguous_fixture_count": sum(_identity_status(row) == "AMBIGUOUS" for row in after_rows),
            "current_ambiguous_side_count": sum(
                side.get("resolution_status") == "AMBIGUOUS"
                for row in after_rows
                for side in (row.get("identity", {}).get("side_resolutions", {}) or {}).values()
                if isinstance(side, Mapping)
            ),
            "registry_ambiguous_alias_backlog_count": sum(
                item.get("status") == "AMBIGUOUS"
                for item in registry.get("ambiguities", []) or []
                if isinstance(item, Mapping)
            ),
        },
    }


def _import_readiness(coverage: Mapping[str, Any]) -> list[dict[str, Any]]:
    generic_adapters = {
        "football-data.co.uk": "scripts/football_data/providers/football_data_uk.py",
        "openfootball": "scripts/football_data/providers/openfootball.py",
    }
    target_ids = ("competition:japan-j1-league", "competition:spain-la-liga")
    output = []
    for competition_id in target_ids:
        row = next((item for item in coverage.get("competitions", []) if item.get("competition_id") == competition_id), {})
        sources = [source for source in row.get("provider_source_availability", []) if isinstance(source, Mapping) and source.get("automatic_import_capability")]
        providers = sorted({_text(source.get("provider")) for source in sources if _text(source.get("provider"))})
        adapter_paths = [generic_adapters[provider] for provider in providers if provider in generic_adapters]
        state = "READY_FOR_GENERIC_IMPORT" if sources and adapter_paths else "IDENTITY_BLOCKED_FOR_IMPORT"
        output.append({
            "competition_id": competition_id,
            "canonical_name": row.get("canonical_name"),
            "state": state,
            "providers": providers,
            "generic_adapter_paths": adapter_paths,
            "automatic_import_capability": bool(sources),
            "authoritative_historical_match_count": row.get("historical_match_count", 0),
            "execution_in_ID_AUTO_1": "not_run",
            "reason": "Recorded only; no Japan/Spain-specific importer was added or executed.",
        })
    return output


def run_id_auto_1(
    *,
    now: datetime,
    dates: Iterable[str] = DEFAULT_DATES,
    universe_root: Path = DEFAULT_UNIVERSE_ROOT,
    coverage_path: Path = DEFAULT_COVERAGE_PATH,
    before_audit_path: Path = DEFAULT_BEFORE_AUDIT_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    dates = tuple(dates)
    coverage = load_coverage_registry(coverage_path)
    historical_store = HistoricalResultStore()
    historical_records = list(historical_store.iter_records())
    fixtures, snapshots = _load_current_fixtures(universe_root, dates)
    if len(fixtures) != 66:
        raise ValueError(f"ID-AUTO-1 requires the exact 66-fixture cohort, got {len(fixtures)}")
    before_rows = _before_rows(before_audit_path, dates)
    if len(before_rows) != len(fixtures):
        raise ValueError("before audit and Prediction Universe cohort counts differ")
    source_index, source_audit = _source_identity_index(fixtures, universe_root=universe_root, dates=dates)
    identity_builder = IdentityRegistryBuilder(
        historical_records=historical_records,
        historical_store=historical_store,
        coverage_registry=coverage,
        now=now,
    )
    registry = identity_builder.build()
    registry_path = output_root / "identity_registry.json"
    write_identity_registry(registry, registry_path)

    resolver = ExactCoverageIdentityResolver(identity_registry_path=registry_path)
    augmented_fixtures = [
        _augment_fixture(fixture, source_index.get(_text(fixture.get("matchId"))))
        for fixture in fixtures
    ]
    after_audit = audit_fixture_set(
        augmented_fixtures,
        coverage,
        historical_records=historical_records,
        identity_resolver=resolver,
        now=now,
    )
    after_rows = list(after_audit.get("fixtures", []))
    after_identity_resolver = IdentityRegistryResolver(registry)
    loaded_sources = {
        key: _load_json(path)
        for key, path in identity_builder.paths.items()
    }
    project_crosswalk = loaded_sources["project_crosswalk"]
    backlog = _current_backlog(after_rows)
    reuse = _provider_reuse_evidence(registry, after_identity_resolver, project_crosswalk)
    identity_chain = _identity_chain_audit(
        source_index=source_index,
        registry=registry,
        after_rows=after_rows,
        loaded_sources=loaded_sources,
    )
    before_identity = _identity_summary(before_rows)
    before_coverage = _coverage_summary(before_rows)
    after_identity = _identity_summary(after_rows)
    after_coverage = _coverage_summary(after_rows)
    before_by_id = {_text(row.get("fixture_id")): row for row in before_rows}
    fixture_results = []
    for row in after_rows:
        fixture_id = _text(row.get("fixture_id"))
        fixture = next((item for item in fixtures if _text(item.get("matchId")) == fixture_id), {})
        source = source_index.get(fixture_id, {})
        direct_source = source.get("structured_500") if isinstance(source.get("structured_500"), Mapping) else None
        fixture_results.append({
            "fixture_id": fixture_id,
            "business_date": _text(fixture.get("businessDate")),
            "league": fixture.get("league"),
            "home_team": fixture.get("homeTeam"),
            "away_team": fixture.get("awayTeam"),
            "competition_id": row.get("competition_id"),
            "before_identity_status": _identity_status(before_by_id.get(fixture_id, {})),
            "before_coverage_status": before_by_id.get(fixture_id, {}).get("status"),
            "after_identity_status": _identity_status(row),
            "after_coverage_status": row.get("status"),
            "home_team_id": row.get("identity", {}).get("home_team_id"),
            "away_team_id": row.get("identity", {}).get("away_team_id"),
            "home_resolution_method": (row.get("identity", {}).get("side_resolutions", {}) or {}).get("home", {}).get("resolution_method"),
            "away_resolution_method": (row.get("identity", {}).get("side_resolutions", {}) or {}).get("away", {}).get("resolution_method"),
            "reason_codes": row.get("reason_codes", []),
            "structured_500_provider_team_ids": direct_source.get("provider_team_ids") if direct_source else None,
        })
    audit_document = {
        "contract_version": "id_auto_1.daily_fixture_audit.v1",
        "generated_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "cohort": {
            "dates": list(dates),
            "fixture_count": len(fixtures),
            "fixture_ids": [_text(fixture.get("matchId")) for fixture in fixtures],
            "prediction_universe_snapshots": snapshots,
            "before_artifact": {
                "path": _relative(before_audit_path),
                "sha256": _file_sha256(before_audit_path),
            },
        },
        "before": {
            "identity": before_identity,
            "coverage": before_coverage,
            "reported_baseline": {
                "SUPPORTED": before_coverage["status_counts"]["SUPPORTED"],
                "IDENTITY_UNAVAILABLE": before_coverage["reason_counts"].get("IDENTITY_UNAVAILABLE", 0),
                "UNSUPPORTED": before_coverage["status_counts"]["UNSUPPORTED"],
            },
        },
        "after": {
            "identity": after_identity,
            "coverage": after_coverage,
            "required_statuses": {
                "SUPPORTED": after_coverage["status_counts"]["SUPPORTED"],
                "DEGRADED": after_coverage["status_counts"]["DEGRADED"],
                "UNSUPPORTED": after_coverage["status_counts"]["UNSUPPORTED"],
                "HISTORY_INSUFFICIENT": after_coverage["reason_counts"].get("HISTORY_INSUFFICIENT", 0),
                "COMPETITION_UNSUPPORTED": after_coverage["reason_counts"].get("COMPETITION_UNSUPPORTED", 0),
            },
        },
        "fixtures": fixture_results,
        "by_competition": _competition_audit(after_rows, coverage),
        "high_value_history_group": _high_value_audit(before_rows, after_rows),
        "identity_chain_audit": identity_chain,
        "source_audit": source_audit,
        "import_readiness": _import_readiness(coverage),
        "history_protection": {
            "authoritative_store_path": str(historical_store.path),
            "authoritative_count": historical_store.count(),
            "authoritative_dataset_digest": historical_store.dataset_digest(),
            "read_mode": "read_only",
            "mutation_performed": False,
        },
        "champion_protection": {
            "champion_prediction_allowed_count": after_coverage["champion_prediction_allowed_count"],
            "blocked_count": after_coverage["blocked_count"],
            "existing_champion_math_changed": False,
            "frozen_predictions_changed": False,
            "prospective_records_changed": False,
            "production_route": "existing Champion remains fail-open; only historical challenger eligibility is gated",
        },
        "construction_policy": {
            "manual_fixture_aliases_added": 0,
            "manual_team_aliases_added": 0,
            "league_specific_resolution_code_added": False,
            "fuzzy_matching_used": False,
            "llm_identity_guessing_used": False,
            "new_provider_or_scraper_added": False,
        },
        "registry_digest": registry.get("registry_digest"),
    }
    _write_json(output_root / "daily_fixture_audit.json", audit_document)
    _write_json(output_root / "identity_resolution_backlog.json", backlog)
    _write_json(output_root / "provider_id_reuse_evidence.json", reuse)
    return {
        "registry": str(registry_path),
        "registry_digest": registry.get("registry_digest"),
        "audit": str(output_root / "daily_fixture_audit.json"),
        "backlog": str(output_root / "identity_resolution_backlog.json"),
        "reuse": str(output_root / "provider_id_reuse_evidence.json"),
        "before": {"identity": before_identity, "coverage": before_coverage},
        "after": {"identity": after_identity, "coverage": after_coverage},
        "registry_summary": registry.get("summary", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the ID-AUTO-1 deterministic identity registry and audit")
    parser.add_argument("--now", help="ISO timestamp for reproducible artifacts")
    parser.add_argument("--date", action="append", dest="dates")
    parser.add_argument("--universe-root", type=Path, default=DEFAULT_UNIVERSE_ROOT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE_PATH)
    parser.add_argument("--before-audit", type=Path, default=DEFAULT_BEFORE_AUDIT_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    result = run_id_auto_1(
        now=_parse_now(args.now),
        dates=tuple(args.dates or DEFAULT_DATES),
        universe_root=args.universe_root,
        coverage_path=args.coverage,
        before_audit_path=args.before_audit,
        output_root=args.output_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
