"""Populate P0/P1 shadow results and retrospective availability artifacts.

The command consumes a local capture directory. It never downloads a source
and never writes Champion or benchmark inputs. Raw captures remain outside Git;
only manifests, identity evidence, normalized eligible records, and diagnostics
are persisted.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .historical_results import HistoricalResultLedger
from .data_home import resolve_football_data_home
from .identity_artifacts import persist_identity_artifacts
from .p0_p1_coverage import (
    audit_retrospective_availability,
    verified_season_bridge_context,
    weighted_ready_coverage,
)
from .p0_p1_population import build_identity_candidates, build_normalized_records, expand_exact_provider_mappings
from .p0_p1_identity import normalize_source_team_name
from .team_strength import PreMatchSnapshotStore, TeamStrengthBuilder


ROOT = Path(__file__).resolve().parents[2]
USAGE_PATH = ROOT / "data" / "football_data" / "competition_usage_history.json"
CURRENT_IDENTITY_PATH = ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
REGISTRY_PATH = ROOT / "data" / "football_data" / "team_alias_registry.json"
OUTPUT_ROOT = ROOT / "data" / "football_data"
DOC_ROOT = ROOT / "docs" / "team-strength"
FOOTBALL_DATA_UK_MANIFEST_PATH = ROOT / "data" / "football_data" / "football_data_uk" / "demand_source_manifest.json"
BULK_DATA_ROOT = resolve_football_data_home()
LEDGER_ROOT = BULK_DATA_ROOT / "historical_results.duckdb"
SNAPSHOT_ROOT = BULK_DATA_ROOT / "team_strength_snapshots.duckdb"

P01_KEYS = (
    "portugal-primeira-liga",
    "norway-eliteserien",
    "finland-veikkausliiga",
    "brazil-serie-a",
    "usa-mls",
    "uefa-europa-league",
    "uefa-champions-league",
    "south-korea-k-league-1",
)


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _capture_file(capture_root: Path, name: str, *, encoding: str) -> tuple[str, str, int]:
    path = capture_root / name
    raw = path.read_bytes()
    return raw.decode(encoding), hashlib.sha256(raw).hexdigest(), len(raw)


def _source(
    capture_root: Path,
    *,
    filename: str,
    encoding: str,
    provider: str,
    competition_key: str,
    season: str,
    country: str,
    competition_name: str,
    provider_competition_id: str,
    provider_competition_name: str,
    provider_season_id: str,
    provider_season_name: str,
    source_url: str,
    source_file: str,
    season_filter: str | None = None,
    repository: str | None = None,
    commit_sha: str | None = None,
    competition_type: str = "league",
    match_type: str = "league",
) -> dict[str, Any]:
    raw_text, raw_sha256, raw_bytes = _capture_file(capture_root, filename, encoding=encoding)
    result = {
        "raw_text": raw_text,
        "raw_sha256": raw_sha256,
        "raw_bytes": raw_bytes,
        "provider": provider,
        "competition_key": competition_key,
        "competition_id": f"competition:{competition_key}",
        "season_id": f"season:{competition_key}:{season}",
        "country": country,
        "competition_name": competition_name,
        "provider_competition_id": provider_competition_id,
        "provider_competition_name": provider_competition_name,
        "provider_season_id": provider_season_id,
        "provider_season_name": provider_season_name,
        "source_url": source_url,
        "source_file": source_file,
        "season_filter": season_filter,
        "repository": repository,
        "commit_sha": commit_sha,
        "competition_type": competition_type,
        "match_type": match_type,
        "captured_at": "2026-08-11T00:00:00Z",
        "license": "CC0-1.0" if provider == "openfootball" else "football-data.co.uk terms review required",
        "commercial_use_review": "reviewed_cc0" if provider == "openfootball" else "required",
        "raw_redistribution": False if provider != "openfootball" else None,
        "internal_analysis_only": True if provider != "openfootball" else None,
    }
    if provider == "football-data.co.uk":
        manifest = _load(FOOTBALL_DATA_UK_MANIFEST_PATH, {})
        for evidence in manifest.get("sources", []):
            if (
                evidence.get("competition_key") == competition_key
                and str(evidence.get("provider_season_id")) == str(provider_season_id)
            ):
                result.update(
                    {
                        "listed_match_count": evidence.get("listed_match_count"),
                        "season_status": evidence.get("season_status"),
                        "current_season_coverage": evidence.get("current_season_coverage"),
                    }
                )
                break
    return result


def default_sources(capture_root: Path) -> list[dict[str, Any]]:
    """Describe the bounded captures used in this phase."""

    europe_repo = "openfootball/europe"
    europe_sha = "e27eb01726f394ddf9fa68b15d37b900487b5903"
    world_repo = "openfootball/world"
    world_sha = "3bf9667cb35b26c2dc17c51f0bda48e8e3eb2434"
    south_repo = "openfootball/south-america"
    south_sha = "40dd70ded402edb27b11972536c3534f6c5ff218"
    sources: list[dict[str, Any]] = []
    sources.extend(
        [
            _source(capture_root, filename="portugal-2025-26-openfootball.txt", encoding="utf-8", provider="openfootball", competition_key="portugal-primeira-liga", season="2025-26", country="Portugal", competition_name="Portuguese Primeira Liga", provider_competition_id="europe:portugal:pt1", provider_competition_name="Portuguese Primeira Liga", provider_season_id="2025-26", provider_season_name="2025/26", source_url=f"https://github.com/{europe_repo}/blob/{europe_sha}/portugal/2025-26_pt1.txt", source_file="portugal/2025-26_pt1.txt", repository=europe_repo, commit_sha=europe_sha),
            _source(capture_root, filename="portugal-2025-26-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key="portugal-primeira-liga", season="2025-26", country="Portugal", competition_name="Portuguese Primeira Liga", provider_competition_id="football-data.co.uk:portugal:primeira-liga", provider_competition_name="Portuguese Primeira Liga", provider_season_id="2025-26", provider_season_name="2025/26", source_url="https://www.football-data.co.uk/mmz4281/2526/PO1.csv", source_file="PO1.csv"),
        ]
    )
    for key, country, name, code, of_file in (
        ("norway-eliteserien", "Norway", "Norway Eliteserien", "NOR", "norway/2025_no1.txt"),
        ("finland-veikkausliiga", "Finland", "Finland Veikkausliiga", "FIN", "finland/2025_fi1.txt"),
    ):
        sources.extend(
            [
                _source(capture_root, filename=f"{key}-2025-openfootball.txt", encoding="utf-8", provider="openfootball", competition_key=key, season="2025", country=country, competition_name=name, provider_competition_id=f"europe:{key}", provider_competition_name=name, provider_season_id="2025", provider_season_name="2025", source_url=f"https://github.com/{europe_repo}/blob/{europe_sha}/{of_file}", source_file=of_file, repository=europe_repo, commit_sha=europe_sha),
                _source(capture_root, filename=f"{key}-2025-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key=key, season="2025", country=country, competition_name=name, provider_competition_id=f"football-data.co.uk:{key}", provider_competition_name=name, provider_season_id="2025", provider_season_name="2025", source_url=f"https://www.football-data.co.uk/new/{code}.csv", source_file=f"{code}.csv", season_filter="2025"),
                _source(capture_root, filename=f"{key}-2026-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key=key, season="2026", country=country, competition_name=name, provider_competition_id=f"football-data.co.uk:{key}", provider_competition_name=name, provider_season_id="2026", provider_season_name="2026", source_url=f"https://www.football-data.co.uk/new/{code}.csv", source_file=f"{code}.csv", season_filter="2026"),
            ]
        )
    sources.extend(
        [
            _source(capture_root, filename="brazil-serie-a-2026-openfootball.txt", encoding="utf-8", provider="openfootball", competition_key="brazil-serie-a", season="2026", country="Brazil", competition_name="Brazil Serie A", provider_competition_id="south-america:brazil:br1", provider_competition_name="Brazil Serie A", provider_season_id="2026", provider_season_name="2026", source_url=f"https://github.com/{south_repo}/blob/{south_sha}/brazil/2026_br1.txt", source_file="brazil/2026_br1.txt", repository=south_repo, commit_sha=south_sha),
            _source(capture_root, filename="brazil-serie-a-2025-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key="brazil-serie-a", season="2025", country="Brazil", competition_name="Brazil Serie A", provider_competition_id="football-data.co.uk:brazil:serie-a", provider_competition_name="Brazil Serie A", provider_season_id="2025", provider_season_name="2025", source_url="https://www.football-data.co.uk/new/BRA.csv", source_file="BRA.csv", season_filter="2025"),
            _source(capture_root, filename="brazil-serie-a-2026-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key="brazil-serie-a", season="2026", country="Brazil", competition_name="Brazil Serie A", provider_competition_id="football-data.co.uk:brazil:serie-a", provider_competition_name="Brazil Serie A", provider_season_id="2026", provider_season_name="2026", source_url="https://www.football-data.co.uk/new/BRA.csv", source_file="BRA.csv", season_filter="2026"),
            _source(capture_root, filename="usa-mls-2025-openfootball.txt", encoding="utf-8", provider="openfootball", competition_key="usa-mls", season="2025", country="United States", competition_name="USA MLS", provider_competition_id="world:mls", provider_competition_name="USA MLS", provider_season_id="2025", provider_season_name="2025", source_url=f"https://github.com/{world_repo}/blob/{world_sha}/north-america/major-league-soccer/2025_mls.txt", source_file="north-america/major-league-soccer/2025_mls.txt", repository=world_repo, commit_sha=world_sha),
            _source(capture_root, filename="usa-mls-2025-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key="usa-mls", season="2025", country="United States", competition_name="USA MLS", provider_competition_id="football-data.co.uk:usa:mls", provider_competition_name="USA MLS", provider_season_id="2025", provider_season_name="2025", source_url="https://www.football-data.co.uk/new/USA.csv", source_file="USA.csv", season_filter="2025"),
            _source(capture_root, filename="usa-mls-2026-football-data.csv", encoding="latin1", provider="football-data.co.uk", competition_key="usa-mls", season="2026", country="United States", competition_name="USA MLS", provider_competition_id="football-data.co.uk:usa:mls", provider_competition_name="USA MLS", provider_season_id="2026", provider_season_name="2026", source_url="https://www.football-data.co.uk/new/USA.csv", source_file="USA.csv", season_filter="2026"),
        ]
    )
    return sources


def _canonical_seeds() -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    registry = _load(REGISTRY_PATH, {})
    seeds.extend(registry.get("teams", []))
    current = _load(CURRENT_IDENTITY_PATH, {})
    for match in current.get("matches", []):
        for side in ("home", "away"):
            team_id = match.get(f"{side}_team_id")
            name = match.get(side)
            if team_id and name:
                seeds.append({"canonical_team_id": team_id, "canonical_name": name, "aliases": [name], "country": match.get("country")})
    return seeds


def _listed_match_count(raw_text: str) -> int | None:
    match = re.search(r"(?im)^\s*#\s*Matches\s+(\d+)\s*$", raw_text)
    return int(match.group(1)) if match else None


def _season_end_at(raw_text: str) -> date | None:
    match = re.search(
        r"(?im)^\s*#\s*Date.*?-\s*[A-Za-z]{3}\s+(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})",
        raw_text,
    )
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}",
            "%b %d %Y",
        ).date()
    except ValueError:
        return None


def _source_completeness(source: Mapping[str, Any], parsed: int, captured_at: str) -> dict[str, Any]:
    """Return auditable listed/parsed completeness without conflating providers."""

    raw_text = str(source.get("raw_text") or "")
    listed = source.get("listed_match_count")
    if listed is not None:
        listed = int(listed)
    else:
        listed = _listed_match_count(raw_text)
    if listed is None and source.get("provider") == "football-data.co.uk":
        # Football-Data CSVs expose completed result rows, not a fixture-list
        # total.  The parsed row count is therefore a completed-result count,
        # not evidence that an in-progress season is complete.
        listed = parsed
    ratio = (parsed / listed) if listed else None
    season_status = str(source.get("season_status") or "")
    if not parsed:
        status = "UNKNOWN"
    elif season_status == "in_progress":
        status = "IN_PROGRESS"
    elif listed is not None and parsed >= listed:
        status = "COMPLETE"
    else:
        end_at = _season_end_at(raw_text)
        captured_date = date.fromisoformat(str(captured_at)[:10])
        status = "PARTIAL" if end_at and end_at <= captured_date else "IN_PROGRESS"
    return {
        "listed_match_count": listed,
        "result_completion_ratio": ratio,
        "source_completeness_status": status,
        "result_coverage": "SUPPORTED" if status == "COMPLETE" else "PARTIAL" if status in {"PARTIAL", "IN_PROGRESS"} else "UNVERIFIED",
    }


def _source_manifest(sources: Iterable[Mapping[str, Any]], parse_counts: Iterable[Mapping[str, Any]], captured_at: str) -> dict[str, Any]:
    counts = {
        (
            str(row.get("provider")),
            str(row.get("competition_id")),
            str(row.get("season_id")),
        ): row
        for row in parse_counts
    }
    output: list[dict[str, Any]] = []
    for source in sources:
        count = counts.get(
            (
                str(source.get("provider")),
                str(source.get("competition_id")),
                str(source.get("season_id")),
            ),
            {},
        )
        parsed = int(count.get("parsed_records") or 0)
        completeness = _source_completeness(source, parsed, captured_at)
        output.append(
            {
                key: source.get(key)
                for key in (
                    "provider",
                    "competition_key",
                    "competition_id",
                    "season_id",
                    "country",
                    "competition_name",
                    "provider_competition_id",
                    "provider_competition_name",
                    "provider_season_id",
                    "provider_season_name",
                    "source_url",
                    "source_file",
                    "raw_sha256",
                    "raw_bytes",
                    "repository",
                    "commit_sha",
                    "license",
                    "commercial_use_review",
                    "raw_redistribution",
                    "internal_analysis_only",
                    "competition_type",
                    "match_type",
                    "season_status",
                    "current_season_coverage",
                )
            }
            | {
                "parsed_result_count": parsed,
                "eligible_result_count": int(count.get("eligible_records") or 0),
                "identity_coverage_status": "REVIEWED_PARTIAL" if count.get("mapped_team_names") else "UNVERIFIED",
                **completeness,
            }
        )
    return {
        "contract_version": "p0_p1_source_manifest.v1",
        "captured_at": captured_at,
        "capture_mode": "metadata_hash_and_normalized_records_only",
        "raw_redistribution": False,
        "internal_analysis_only": True,
        "sources": output,
        "notes": [
            "Raw third-party captures remain outside Git; source URL, source file, commit/raw SHA256 and parser evidence are retained.",
            "Source availability does not imply project demand coverage or current-strength readiness.",
        ],
    }


def _fetch_translation_index(provider_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Read only target-specific fetch metadata for reviewed English labels."""

    fetch_root = ROOT / "data" / "fetch_runs"
    output: dict[str, dict[str, Any]] = {}
    suffixes = {str(value).split("-")[-1] for value in provider_ids if value}
    for path in fetch_root.glob("*/*"):
        if path.suffix.lower() != ".json" or not any(suffix in path.name for suffix in suffixes):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        containers: list[Mapping[str, Any]] = []
        nowscore = data.get("nowscore")
        if isinstance(nowscore, Mapping):
            containers.extend([nowscore, nowscore.get("resolution") or {}])
        containers.extend([data.get("resolution") or {}, data.get("target") or {}])
        for container in containers:
            if not isinstance(container, Mapping):
                continue
            match_id = str(container.get("nowscore_id") or data.get("nowscore_id") or data.get("shuju_id") or "")
            home = container.get("home_team_en")
            away = container.get("away_team_en")
            if match_id and home and away and str(container.get("status") or "EXACT_MATCH") == "EXACT_MATCH":
                translation = {
                    "home_team_en": str(home),
                    "away_team_en": str(away),
                    "source_file": str(path.relative_to(ROOT)),
                    "resolution_status": str(container.get("status") or "EXACT_MATCH"),
                    "match_confidence": container.get("match_confidence"),
                }
                keys = {match_id}
                shuju_id = str(data.get("shuju_id") or "")
                if shuju_id:
                    keys.update({shuju_id, f"500-{shuju_id}"})
                for key in keys:
                    output[key] = translation
                break
    return output


def _demand_targets(canonical_by_name: Mapping[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    usage = _load(USAGE_PATH, {})
    current = _load(CURRENT_IDENTITY_PATH, {})
    current_by_provider_id: dict[str, Mapping[str, Any]] = {}
    for match in current.get("matches", []):
        for value in (match.get("provider_match_id"), match.get("id"), match.get("nowscore_match_id")):
            if value:
                current_by_provider_id[str(value)] = match
    p01 = [event for event in usage.get("recovered_events", []) if (event.get("competition") or {}).get("competition_key") in P01_KEYS]
    provider_ids = {str(value) for event in p01 for value in event.get("provider_match_ids", []) if value}
    translations = _fetch_translation_index(provider_ids)
    targets: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    for event in p01:
        competition = event.get("competition") or {}
        key = str(competition.get("competition_key"))
        provider_id = str((event.get("provider_match_ids") or [""])[0])
        current_match = current_by_provider_id.get(provider_id)
        home_id = current_match.get("home_team_id") if current_match else None
        away_id = current_match.get("away_team_id") if current_match else None
        identity_method = "current_match_identity_evidence" if current_match else None
        identity_evidence: list[Any] = []
        if current_match:
            identity_evidence.extend(current_match.get("verification_evidence") or [])
        translation = translations.get(provider_id.split("-")[-1]) or translations.get(provider_id)
        if not home_id and translation:
            home_id = canonical_by_name.get(normalize_source_team_name(translation["home_team_en"]))
            away_id = canonical_by_name.get(normalize_source_team_name(translation["away_team_en"]))
            if home_id and away_id:
                identity_method = "project_exact_match_to_cross_source_identity"
                identity_evidence.append(translation)
        season = "2026-27" if key == "portugal-primeira-liga" else "2026"
        competition_type = str(competition.get("competition_type") or "league")
        if key in {"uefa-champions-league", "uefa-europa-league"}:
            season = "2026-27"
            competition_type = "international_club"
        bridge_context = None
        if key == "portugal-primeira-liga" and current_match:
            bridge_context = verified_season_bridge_context(
                bridge_from_season="season:portugal-primeira-liga:2025-26",
                bridge_to_season="season:portugal-primeira-liga:2026-27",
                season_stage="opening",
                evidence=[
                    "openfootball/europe@e27eb01726f394ddf9fa68b15d37b900487b5903:portugal/2026-27_pt1.txt",
                    "official 2026/27 Primeira Liga Matchday 1 fixture context",
                    "data/football_data/current_match_identity_evidence.json",
                ],
                bridge_reason="official current-season fixture is in Matchday 1; previous-season result history is retained as an explicit bridge",
            )
        target = {
            "canonical_match_id": event.get("canonical_match_id"),
            "provider_match_id": provider_id or None,
            "competition_key": key,
            "competition_id": competition.get("canonical_competition_id"),
            "season_id": f"season:{key}:{season}",
            "competition_type": competition_type,
            "kickoff_at": event.get("kickoff_at"),
            "home": event.get("home"),
            "away": event.get("away"),
            "home_team_id": home_id,
            "away_team_id": away_id,
            "entity_type": str(competition.get("entity_type") or "club"),
            "weight": 1,
            "bridge_context": bridge_context,
            "intended_match_types": ["league"] if competition_type == "league" else ["league", "domestic_cup", "continental_club"],
            "source_available": key in {"portugal-primeira-liga", "norway-eliteserien", "finland-veikkausliiga", "brazil-serie-a", "usa-mls"},
        }
        targets.append(target)
        identity_rows.append(
            {
                "canonical_match_id": event.get("canonical_match_id"),
                "competition_key": key,
                "provider_match_id": provider_id or None,
                "project_home": event.get("home"),
                "project_away": event.get("away"),
                "resolved_home_team_id": home_id,
                "resolved_away_team_id": away_id,
                "resolution_status": "resolved" if home_id and away_id else "unresolved",
                "resolution_method": identity_method or "unresolved",
                "evidence": identity_evidence,
                "translation": translation,
            }
        )
    return targets, {
        "target_count": len(targets),
        "resolved_target_count": sum(bool(row.get("home_team_id") and row.get("away_team_id")) for row in targets),
        "unresolved_target_count": sum(not bool(row.get("home_team_id") and row.get("away_team_id")) for row in targets),
        "fetch_translation_count": len(translations),
        "identity_rows": identity_rows,
    }


def _write_docs(
    *,
    candidates: Mapping[str, Any],
    population: Mapping[str, Any],
    weighted: Mapping[str, Any],
    audits: list[Mapping[str, Any]],
    k_league: Mapping[str, Any],
    captured_at: str,
) -> None:
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    by_comp: dict[str, list[Mapping[str, Any]]] = {}
    for row in audits:
        by_comp.setdefault(str(row.get("competition_key")), []).append(row)
    lines = [
        "# Phase 2B.3 P0/P1 team strength coverage",
        "",
        f"Generated at `{captured_at}` from the recovered project-demand fixtures. This is a retrospective data-layer audit; it does not create predictions or benchmark records.",
        "",
        f"Demand weight: `{weighted.get('demand_weight', 0)}`; strict ready `{weighted.get('strict_ready_weight', 0)}`; verified bridge `{weighted.get('verified_bridge_weight', 0)}`; strict rate `{weighted.get('strict_ready_rate', 0)}`; ready+bridge rate `{weighted.get('ready_plus_bridge_rate', 0)}`.",
        "",
        "Source rows are not demand rows. Only eligible normalized results strictly before each target kickoff are used.",
        "",
        "| Competition | Demand | Strict ready | Verified bridge | Stale | Identity missing | Source missing | Scope partial |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in P01_KEYS:
        rows = by_comp.get(key, [])
        total = len(rows)
        count = {status: sum(row.get("status") == status for row in rows) for status in ("STRICT_READY", "VERIFIED_BRIDGE", "STALE", "IDENTITY_MISSING", "SOURCE_MISSING", "SCOPE_PARTIAL")}
        lines.append(f"| {key} | {total} | {count['STRICT_READY']} | {count['VERIFIED_BRIDGE']} | {count['STALE']} | {count['IDENTITY_MISSING']} | {count['SOURCE_MISSING']} | {count['SCOPE_PARTIAL']} |")
    lines.extend(
        [
            "",
            "## Identity population",
            "",
            f"AUTO_VERIFIED `{candidates.get('summary', {}).get('AUTO_VERIFIED', 0)}`; REVIEW_REQUIRED `{candidates.get('summary', {}).get('REVIEW_REQUIRED', 0)}`; UNRESOLVED `{candidates.get('summary', {}).get('UNRESOLVED', 0)}`; CONFLICT `{candidates.get('summary', {}).get('CONFLICT', 0)}`.",
            "",
            "AUTO_VERIFIED here means a shadow candidate backed by repeated cross-source fixture context. Deterministic candidate IDs may be generated for previously unseen clubs, but the production team registry is not mutated automatically. Compact verified truth is retained in `data/football_data/verified_identity_crosswalk.json`; detailed candidate evidence is local-only at `${FOOTBALL_DATA_HOME}/identity/p0_p1_identity_candidates.json`.",
            "",
            f"Eligible normalized records available after this capture's deduplication: `{population.get('eligible_records_available', 0)}`; newly persisted immutable records: `{population.get('eligible_records_persisted', 0)}`. Cross-source duplicate collapse: `{population.get('duplicates_collapsed', 0)}`; conflicts: `{population.get('conflicts', 0)}`.",
            "",
            "## Scope rule",
            "",
            "Domestic league demand uses league history as its explicitly observed scope. UEFA demand requires league, domestic-cup and continental history for COMPLETE all-competition recent form; UEFA-only history is therefore PARTIAL.",
            "",
            "## K League",
            "",
            f"`K_LEAGUE_SOURCE_GAP={k_league.get('K_LEAGUE_SOURCE_GAP')}`. No compliant free historical result source was adopted in this phase; the 27-match demand weight remains in the denominator.",
            "",
            "## Source boundaries",
            "",
            "OpenFootball is used as pinned offline Football.TXT historical research data; Football-Data.co.uk is used as captured historical result CSV only. Neither source supplies xG, lineup, injury, or authoritative global identity data here.",
            "",
            "No new feature is validated for the Champion.",
        ]
    )
    (DOC_ROOT / "P0_P1_COVERAGE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    source_lines = [
        "# P0/P1 source decisions",
        "",
        "## UEFA OpenFootball",
        "",
        "Adopted as an offline historical/schema source through the existing OpenFootball adapter. The pinned repository exposes UCL/Europa/Conference Football.TXT files and CC0/public-domain terms. The captured 2025/26 files do not prove 2026/27 current-season coverage; therefore current UEFA demand remains source/current-season missing until the next season files are available.",
        "",
        "See [openfootball/champions-league](https://github.com/openfootball/champions-league) and its [CC0 license](https://github.com/openfootball/champions-league/blob/master/LICENSE.md).",
        "",
        "## World Cup",
        "",
        "Registered as `SOURCE_AVAILABLE` for future research only via [openfootball/worldcup](https://github.com/openfootball/worldcup). It is outside the P0/P1 club-strength gate and no national-team model is started.",
        "",
        "## K League",
        "",
        "`K_LEAGUE_SOURCE_GAP=true`. The official K League terms restrict copying/publishing/providing data without prior permission and prohibit commercial use in the relevant clause; no compliant free source was adopted. See [K League terms](https://portal.kleague.com/user/service/userTermsNice.do).",
        "",
        "## API-Football",
        "",
        "`DEFER`: future candidate only. No API key, paid plan, runtime network call, or fake response is enabled in Phase 2B.3. Coverage and pricing must be re-reviewed before adoption.",
        "",
        "The requested Agent-Reach CLI was not available in this Codex environment; bounded official-source discovery used direct source pages as a fallback.",
    ]
    (DOC_ROOT / "P0_P1_SOURCE_DECISIONS.md").write_text("\n".join(source_lines) + "\n", encoding="utf-8")


def run(capture_root: Path, *, captured_at: str = "2026-08-11T00:00:00Z") -> dict[str, Any]:
    sources = default_sources(capture_root)
    for source in sources:
        source["captured_at"] = captured_at
    result, observations = build_identity_candidates(sources, canonical_seeds=_canonical_seeds())
    mappings = expand_exact_provider_mappings(result, sources)
    records, parse_summary = build_normalized_records(sources, mappings)
    ledger = HistoricalResultLedger(LEDGER_ROOT)
    persisted = 0
    existing_record_keys = {
        (
            str(row.get("provider") or ""),
            str(row.get("provider_match_id") or ""),
            str(row.get("kickoff_at") or ""),
            row.get("home_goals"),
            row.get("away_goals"),
        )
        for row in ledger.records()
    }
    for record in records:
        if record.get("eligible_for_team_strength") is not True:
            continue
        record_key = (
            str(record.get("provider") or ""),
            str(record.get("provider_match_id") or ""),
            str(record.get("kickoff_at") or ""),
            record.get("home_goals"),
            record.get("away_goals"),
        )
        if record_key in existing_record_keys:
            continue
        ledger.append(record)
        existing_record_keys.add(record_key)
        persisted += 1
    all_records = ledger.records()
    canonical_by_name: dict[str, str] = {}
    ambiguous_names: set[str] = set()
    for mapping in mappings.values():
        if mapping.get("verified") is not True:
            continue
        team_id = str(mapping.get("canonical_team_id") or "")
        for name in (mapping.get("provider_team_name"), mapping.get("canonical_name")):
            key = normalize_source_team_name(str(name or ""))
            if not key or not team_id:
                continue
            if key in canonical_by_name and canonical_by_name[key] != team_id:
                ambiguous_names.add(key)
            else:
                canonical_by_name[key] = team_id
    for key in ambiguous_names:
        canonical_by_name.pop(key, None)
    targets, target_summary = _demand_targets(canonical_by_name)
    for target in targets:
        if target.get("source_available") is False and target.get("home_team_id") and target.get("away_team_id"):
            target["source_available"] = False
    audits = audit_retrospective_availability(targets, all_records, captured_at=captured_at)
    for target, audit in zip(targets, audits):
        if target.get("source_available") is False:
            # Source absence is the primary bucket for a competition-level
            # gap. Identity absence is retained as an additional reason, but
            # the demand weight must not disappear into an identity bucket.
            audit["status"] = "SOURCE_MISSING"
            audit["strict_ready"] = False
            audit["strength_ready"] = False
            reasons = list(audit.get("reason") or [])
            if "source_missing_for_competition" not in reasons:
                reasons.append("source_missing_for_competition")
            if not target.get("home_team_id") or not target.get("away_team_id"):
                if "identity_missing" not in reasons:
                    reasons.append("identity_missing")
            audit["reason"] = reasons
    weighted = weighted_ready_coverage(audits)
    snapshots = TeamStrengthBuilder(ledger, captured_at=captured_at, snapshot_revision="p0-p1-v3")
    snapshot_store = PreMatchSnapshotStore(SNAPSHOT_ROOT)
    snapshot_count = 0
    for target, audit in zip(targets, audits):
        if not target.get("home_team_id") or not target.get("away_team_id"):
            continue
        for team_id in (target["home_team_id"], target["away_team_id"]):
            for window in ("last_5", "last_10", "last_20", "season_to_date"):
                try:
                    snapshot = snapshots.build(
                        str(team_id),
                        target_kickoff=str(target["kickoff_at"]),
                        window_type=window,
                        competition_id=target.get("competition_id"),
                        season_id=target.get("season_id"),
                        target_match_id=str(target.get("canonical_match_id") or target.get("provider_match_id") or "target"),
                        entity_type=str(target.get("entity_type") or "club"),
                        bridge_context=target.get("bridge_context"),
                    )
                    snapshot["recent_form_scope"] = audit.get("home_details", {}).get("recent_form_scope") if team_id == target.get("home_team_id") else audit.get("away_details", {}).get("recent_form_scope")
                    snapshot["league_form_ready"] = audit.get("league_form_ready")
                    snapshot["all_competition_form_ready"] = audit.get("all_competition_form_ready")
                    snapshot["history_scope_incomplete"] = snapshot["recent_form_scope"] != "COMPLETE"
                    snapshot_store.put(snapshot)
                    snapshot_count += 1
                except (TypeError, ValueError):
                    continue
    k_league = {"K_LEAGUE_SOURCE_GAP": True, "status": "SOURCE_MISSING", "demand_remains_in_denominator": True}
    manifest = _source_manifest(sources, parse_summary["parse_counts"], captured_at)
    population = {
        **parse_summary,
        "observation_count": len(observations),
        "candidate_count": len(result.get("candidates", [])),
        "reviewed_mapping_count": len(mappings),
        "canonical_team_identity_count": len({
            str(mapping.get("canonical_team_id"))
            for mapping in mappings.values()
            if mapping.get("verified") is True and mapping.get("canonical_team_id")
        }),
        "eligible_records_available": sum(
            bool(row.get("eligible_for_team_strength")) for row in records
        ),
        "eligible_records_persisted": persisted,
        "ledger_record_count_after": len(all_records),
        "snapshot_count": snapshot_count,
        "target_summary": target_summary,
    }
    identity_output = {**result, "reviewed_mapping_count": len(mappings), "provider_mappings": [dict(row) for row in mappings.values()]}
    persist_identity_artifacts(identity_output, generated_at=captured_at)
    _json(OUTPUT_ROOT / "p0_p1_identity_evidence.json", target_summary)
    _json(OUTPUT_ROOT / "p0_p1_source_manifest.json", manifest)
    _json(OUTPUT_ROOT / "p0_p1_population_summary.json", population)
    _json(OUTPUT_ROOT / "p0_p1_demand_availability.json", {"contract_version": "p0_p1_demand_availability.v1", "generated_at": captured_at, "audits": audits})
    _json(OUTPUT_ROOT / "p0_p1_weighted_coverage.json", {"contract_version": "p0_p1_weighted_coverage.v1", "generated_at": captured_at, **weighted})
    _json(OUTPUT_ROOT / "p0_p1_source_registry.json", {
        "contract_version": "p0_p1_source_registry.v1",
        "generated_at": captured_at,
        "sources": [
            {"source": "openfootball/champions-league", "status": "SOURCE_AVAILABLE", "coverage": ["Champions League", "Europa League", "Conference League"], "current_2026_27_files_verified": False, "license": "CC0-1.0", "commit_sha": "abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef"},
            {"source": "openfootball/worldcup", "status": "SOURCE_AVAILABLE", "coverage": ["World Cup", "qualifiers"], "in_p0_p1_gate": False, "license": "CC0-1.0"},
            {"source": "K League official/public discovery", "status": "SOURCE_MISSING", "K_LEAGUE_SOURCE_GAP": True, "demand_remains_in_denominator": True},
            {"source": "API-Football", "status": "DEFER", "runtime_enabled": False, "api_key_required": True},
        ],
    })
    health_path = OUTPUT_ROOT / "team_strength_health.json"
    health = _load(health_path, {})
    health["p0_p1_retrospective"] = {"demand_weight": weighted["demand_weight"], **weighted, "audited_matches": len(audits), "last_updated_at": captured_at, "validated_for_model": False}
    _json(health_path, health)
    _write_docs(candidates=result, population=population, weighted=weighted, audits=audits, k_league=k_league, captured_at=captured_at)
    return {"manifest": manifest, "population": population, "weighted": weighted, "audits": audits, "candidates": result, "k_league": k_league}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--captured-at", default="2026-08-11T00:00:00Z")
    args = parser.parse_args()
    result = run(args.capture_dir, captured_at=args.captured_at)
    print(json.dumps({"population": result["population"], "weighted": result["weighted"], "k_league": result["k_league"]}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
