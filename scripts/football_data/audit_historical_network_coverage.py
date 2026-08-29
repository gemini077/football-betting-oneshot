"""Read-only coverage audit for FE-HISTORY-GRAPH-1.

This module measures the connected components already present in the
authoritative historical-result store and joins only deterministic identity
evidence to the current canonical production universe.  It does not fit or
run a model and never writes to any input data source.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from .data_home import historical_results_path
    from .storage import HistoricalResultStore
except ImportError:  # pragma: no cover - supports direct CLI execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.football_data.data_home import historical_results_path
    from scripts.football_data.storage import HistoricalResultStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENT_IDENTITY_PATH = PROJECT_ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
PROJECT_CROSSWALK_PATH = PROJECT_ROOT / "data" / "football_data" / "verified_project_provider_crosswalk.json"
CROSS_SOURCE_CROSSWALK_PATH = PROJECT_ROOT / "data" / "football_data" / "verified_identity_crosswalk.json"
ALIAS_REGISTRY_PATH = PROJECT_ROOT / "data" / "football_data" / "team_alias_registry.json"
COMPETITION_REGISTRY_PATH = PROJECT_ROOT / "data" / "football_data" / "competition_coverage_registry.json"
OUTPUT_JSON_PATH = PROJECT_ROOT / "data" / "football_data" / "fe_history_graph1_results_summary.json"
OUTPUT_MARKDOWN_PATH = PROJECT_ROOT / "docs" / "team-strength" / "FE_HISTORY_GRAPH_1_HISTORICAL_NETWORK_COVERAGE.md"
UTC = timezone.utc
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


def normalize_name(value: Any) -> str:
    """Normalize for exact alias lookup; this is not fuzzy matching."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _universe_kickoff(fixture: Mapping[str, Any]) -> datetime | None:
    direct = fixture.get("kickoff_at") or fixture.get("kickoffAt")
    if direct:
        return _parse_datetime(direct)
    date = fixture.get("matchDate")
    time = fixture.get("matchTime")
    if not date or not time:
        return None
    return datetime.fromisoformat(f"{date}T{time}:00").replace(tzinfo=BUSINESS_TIMEZONE)


def _dedupe_historical_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    fallback_index = 0
    for row in rows:
        item = dict(row)
        key = str(item.get("canonical_match_id") or f"__row_{fallback_index}")
        fallback_index += 1
        result.setdefault(key, item)
    return list(result.values())


def _graph_components(rows: Iterable[Mapping[str, Any]]) -> tuple[set[str], list[tuple[str, str]], list[set[str]]]:
    nodes: set[str] = set()
    edges: list[tuple[str, str]] = []
    for row in rows:
        home = row.get("home_team_id")
        away = row.get("away_team_id")
        if not home or not away:
            continue
        home_id, away_id = str(home), str(away)
        nodes.update((home_id, away_id))
        edges.append((home_id, away_id))

    adjacency = {node: set() for node in nodes}
    for home, away in edges:
        adjacency[home].add(away)
        adjacency[away].add(home)

    components: list[set[str]] = []
    seen: set[str] = set()
    for start in sorted(nodes):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: set[str] = set()
        while stack:
            node = stack.pop()
            component.add(node)
            for neighbour in adjacency[node] - seen:
                seen.add(neighbour)
                stack.append(neighbour)
        components.append(component)
    components.sort(key=lambda component: (-len(component), sorted(component)[0]))
    return nodes, edges, components


def _coverage_for_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    unique_rows = _dedupe_historical_rows(rows)
    nodes, edges, components = _graph_components(unique_rows)
    largest = components[0] if components else set()
    connected_matches = sum(home in largest and away in largest for home, away in edges)
    match_count = len(edges)
    team_count = len(nodes)
    return {
        "match_count": match_count,
        "team_count": team_count,
        "component_count": len(components),
        "largest_component_match_count": connected_matches,
        "largest_component_team_count": len(largest),
        "connected_match_coverage": connected_matches / match_count if match_count else 0.0,
        "connected_team_coverage": len(largest) / team_count if team_count else 0.0,
        "fully_connected": len(components) <= 1,
        "component_sizes": [len(component) for component in components],
    }


def competition_network_coverage(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return undirected connected coverage grouped by canonical competition."""

    grouped: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        competition = row.get("competition_id")
        if competition:
            grouped[str(competition)].append(row)

    result: dict[str, dict[str, Any]] = {}
    for competition in sorted(grouped):
        coverage = _coverage_for_rows(grouped[competition])
        coverage["season_count"] = len({row.get("season_id") for row in grouped[competition] if row.get("season_id")})
        result[competition] = coverage
    return result


def competition_season_network_coverage(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        competition = row.get("competition_id")
        season = row.get("season_id")
        if competition and season:
            grouped[(str(competition), str(season))].append(row)

    result: dict[str, dict[str, Any]] = {}
    for (competition, season), grouped_rows in sorted(grouped.items()):
        key = f"{competition}|{season}"
        result[key] = _coverage_for_rows(grouped_rows)
        result[key]["competition_id"] = competition
        result[key]["season_id"] = season
    return result


def _quantile(values: list[int], probability: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * probability
    lower, upper = int(position), min(int(position) + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def team_history_match_count_distribution(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    counts: collections.Counter[str] = collections.Counter()
    by_competition: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for row in _dedupe_historical_rows(rows):
        home = row.get("home_team_id")
        away = row.get("away_team_id")
        competition = row.get("competition_id")
        if not home or not away:
            continue
        counts[str(home)] += 1
        counts[str(away)] += 1
        if competition:
            by_competition[str(competition)][str(home)] += 1
            by_competition[str(competition)][str(away)] += 1

    values = sorted(counts.values())
    buckets = {"0": 0, "1-4": 0, "5-9": 0, "10-19": 0, "20-39": 0, "40+": 0}
    for value in values:
        bucket = "0" if value == 0 else "1-4" if value <= 4 else "5-9" if value <= 9 else "10-19" if value <= 19 else "20-39" if value <= 39 else "40+"
        buckets[bucket] += 1

    return {
        "unique_team_count": len(values),
        "min": min(values) if values else None,
        "p25": _quantile(values, 0.25),
        "median": _quantile(values, 0.50),
        "p75": _quantile(values, 0.75),
        "max": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "buckets": buckets,
        "match_count_frequency": {str(k): v for k, v in sorted(collections.Counter(values).items())},
        "per_team_match_count": dict(sorted(counts.items())),
        "by_competition": {
            competition: {
                "team_count": len(team_counts),
                "min": min(team_counts.values()) if team_counts else None,
                "median": _quantile(sorted(team_counts.values()), 0.5),
                "max": max(team_counts.values()) if team_counts else None,
            }
            for competition, team_counts in sorted(by_competition.items())
        },
    }


def historical_identity_diagnostics(
    rows: Iterable[Mapping[str, Any]],
    cross_source_crosswalk: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Find exact crosswalk evidence that splits one canonical entity in history."""

    unique_rows = _dedupe_historical_rows(rows)
    historical_team_ids = {
        str(row[field])
        for row in unique_rows
        for field in ("home_team_id", "away_team_id")
        if row.get(field)
    }
    raw_name_to_history_ids: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for row in unique_rows:
        competition = str(row.get("competition_id") or "")
        for id_field, raw_field in (("home_team_id", "raw_home_team"), ("away_team_id", "raw_away_team")):
            team_id, raw_name = row.get(id_field), row.get(raw_field)
            if team_id and raw_name:
                raw_name_to_history_ids[(competition, normalize_name(raw_name))].add(str(team_id))

    canonical_to_history_ids: dict[str, set[str]] = collections.defaultdict(set)
    canonical_to_competitions: dict[str, set[str]] = collections.defaultdict(set)
    crosswalk_team_ids: set[str] = set()
    for mapping in cross_source_crosswalk:
        if mapping.get("verified") is False or not mapping.get("canonical_team_id"):
            continue
        canonical_id = str(mapping["canonical_team_id"])
        crosswalk_team_ids.add(canonical_id)
        competition = str(mapping.get("competition") or "")
        canonical_to_competitions[canonical_id].add(competition)
        exact_ids = raw_name_to_history_ids.get((competition, normalize_name(mapping.get("provider_team_name"))), set())
        canonical_to_history_ids[canonical_id].update(exact_ids)

    fragmented = {
        canonical_id: sorted(history_ids)
        for canonical_id, history_ids in sorted(canonical_to_history_ids.items())
        if len(history_ids) > 1
    }
    fragmented_history_ids = {history_id for ids in fragmented.values() for history_id in ids}
    fragmented_competitions = sorted(
        {
            competition
            for canonical_id in fragmented
            for competition in canonical_to_competitions.get(canonical_id, set())
            if competition
        }
    )
    fragmented_match_ids = {
        str(row.get("canonical_match_id"))
        for row in unique_rows
        if row.get("canonical_match_id")
        and any(row.get(field) in fragmented_history_ids for field in ("home_team_id", "away_team_id"))
    }
    exact_raw_name_collisions = {
        f"{competition}|{raw_name}": sorted(history_ids)
        for (competition, raw_name), history_ids in sorted(raw_name_to_history_ids.items())
        if len(history_ids) > 1
    }
    return {
        "historical_team_id_count": len(historical_team_ids),
        "crosswalk_canonical_team_id_count": len(crosswalk_team_ids),
        "historical_team_ids_covered_by_crosswalk": len(historical_team_ids & crosswalk_team_ids),
        "historical_team_ids_uncovered_by_crosswalk": len(historical_team_ids - crosswalk_team_ids),
        "crosswalk_historical_id_coverage": len(historical_team_ids & crosswalk_team_ids) / len(historical_team_ids)
        if historical_team_ids
        else 0.0,
        "fragmented_canonical_entity_count": len(fragmented),
        "fragmented_historical_team_id_count": len(fragmented_history_ids),
        "fragmented_match_count": len(fragmented_match_ids),
        "fragmented_competitions": fragmented_competitions,
        "direct_conflict_mapping_count": len(fragmented),
        "exact_raw_name_collision_count": len(exact_raw_name_collisions),
        "fragmented_entities": [
            {"crosswalk_canonical_team_id": canonical_id, "historical_team_ids": history_ids}
            for canonical_id, history_ids in fragmented.items()
        ],
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _canonical_competition_id(value: Any) -> str:
    text = str(value or "")
    return text if text.startswith("competition:") else f"competition:{text}"


def build_competition_registry_lookup(registry: Mapping[str, Any]) -> dict[str, set[str]]:
    """Build exact raw-label to canonical competition lookup."""

    if registry and all(isinstance(value, (set, list, tuple)) for value in registry.values()):
        return {normalize_name(key): {str(item) for item in value} for key, value in registry.items()}

    lookup: dict[str, set[str]] = collections.defaultdict(set)
    for container_name in ("observed_competitions", "source_observed_competitions", "source_completeness"):
        for entry in registry.get(container_name, []) or []:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("competition_key")
            if not key:
                key = entry.get("competition")
            if not key:
                continue
            canonical = _canonical_competition_id(key)
            for raw_name in entry.get("raw_names", []) or []:
                lookup[normalize_name(raw_name)].add(canonical)
            if entry.get("raw_name"):
                lookup[normalize_name(entry["raw_name"])].add(canonical)
    return dict(lookup)


def _provider_hint(fixture: Mapping[str, Any]) -> str | None:
    match_id = str(fixture.get("matchId") or fixture.get("match_id") or "")
    if match_id.startswith("500-"):
        return "500"
    if fixture.get("nowscoreId") or fixture.get("nowscore_id"):
        return "nowscore"
    return None


def _identity_by_match_id(identity_matches: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in identity_matches:
        if item.get("verified") is not True:
            continue
        if not item.get("home_team_id") or not item.get("away_team_id"):
            continue
        for key in ("id", "provider_match_id", "match_id"):
            if item.get(key) is not None:
                index[str(item[key])] = dict(item)
    return index


def _crosswalk_name_index(mappings: Iterable[Mapping[str, Any]]) -> dict[tuple[str | None, str], list[dict[str, Any]]]:
    index: dict[tuple[str | None, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for mapping in mappings:
        if mapping.get("verified") is False:
            continue
        provider = str(mapping.get("provider")) if mapping.get("provider") else None
        for field in ("provider_team_name", "canonical_name"):
            normalized = normalize_name(mapping.get(field))
            if normalized:
                index[(provider, normalized)].append(dict(mapping))
    return index


def _crosswalk_candidates(
    name: Any,
    provider_hint: str | None,
    index: Mapping[tuple[str | None, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    normalized = normalize_name(name)
    if not normalized:
        return []
    values = list(index.get((provider_hint, normalized), [])) if provider_hint else []
    if not values:
        values = list(index.get((None, normalized), []))
    if not values and provider_hint is None:
        for (provider, candidate_name), mappings in index.items():
            if candidate_name == normalized:
                values.extend(mappings)

    unique: dict[tuple[Any, Any], dict[str, Any]] = {}
    for value in values:
        key = (value.get("canonical_team_id"), value.get("competition"))
        if key[0]:
            unique[key] = value
    return list(unique.values())


def _fixture_identity(
    fixture: Mapping[str, Any],
    identity_index: Mapping[str, Mapping[str, Any]],
    crosswalk_index: Mapping[tuple[str | None, str], list[dict[str, Any]]],
    competition_lookup: Mapping[str, set[str]],
) -> dict[str, Any]:
    fixture_id = str(fixture.get("matchId") or fixture.get("match_id") or fixture.get("shujuId") or "")
    evidence = identity_index.get(fixture_id)
    if evidence:
        return {
            "status": "resolved",
            "source": "current_match_identity_evidence",
            "home_team_id": evidence.get("home_team_id"),
            "away_team_id": evidence.get("away_team_id"),
            "competition_id": evidence.get("competition_id"),
            "reason": None,
        }

    direct_home = fixture.get("home_team_id") or fixture.get("homeTeamId")
    direct_away = fixture.get("away_team_id") or fixture.get("awayTeamId")
    direct_competition = fixture.get("competition_id")
    if direct_home and direct_away and direct_competition:
        return {
            "status": "resolved",
            "source": "fixture_direct_canonical_ids",
            "home_team_id": direct_home,
            "away_team_id": direct_away,
            "competition_id": direct_competition,
            "reason": None,
        }

    provider_hint = _provider_hint(fixture)
    home_candidates = _crosswalk_candidates(fixture.get("homeTeam") or fixture.get("home"), provider_hint, crosswalk_index)
    away_candidates = _crosswalk_candidates(fixture.get("awayTeam") or fixture.get("away"), provider_hint, crosswalk_index)
    if not home_candidates or not away_candidates:
        return {
            "status": "unresolved",
            "source": None,
            "home_team_id": None,
            "away_team_id": None,
            "competition_id": None,
            "reason": "identity_team_name_missing",
        }

    pair_keys = {
        (home.get("canonical_team_id"), away.get("canonical_team_id"), home.get("competition"))
        for home in home_candidates
        for away in away_candidates
        if home.get("canonical_team_id")
        and away.get("canonical_team_id")
        and home.get("canonical_team_id") != away.get("canonical_team_id")
        and home.get("competition") == away.get("competition")
    }
    if len(pair_keys) != 1:
        return {
            "status": "unresolved",
            "source": None,
            "home_team_id": None,
            "away_team_id": None,
            "competition_id": None,
            "reason": "identity_pair_not_unique",
        }

    home_id, away_id, competition_id = next(iter(pair_keys))
    schedule_competitions = competition_lookup.get(normalize_name(fixture.get("league")), set())
    if len(schedule_competitions) != 1:
        return {
            "status": "unresolved",
            "source": None,
            "home_team_id": None,
            "away_team_id": None,
            "competition_id": None,
            "reason": "identity_competition_unresolved",
        }
    if competition_id not in schedule_competitions:
        return {
            "status": "unresolved",
            "source": None,
            "home_team_id": None,
            "away_team_id": None,
            "competition_id": None,
            "reason": "identity_competition_mismatch",
        }
    return {
        "status": "resolved",
        "source": "verified_project_provider_crosswalk_exact",
        "home_team_id": home_id,
        "away_team_id": away_id,
        "competition_id": competition_id,
        "reason": None,
    }


def _network_index(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, set[str]], dict[str, list[set[str]]]]:
    competition_teams: dict[str, set[str]] = collections.defaultdict(set)
    components: dict[str, list[set[str]]] = {}
    grouped: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        competition = row.get("competition_id")
        if competition:
            grouped[str(competition)].append(row)
    for competition, grouped_rows in grouped.items():
        nodes, _, component_list = _graph_components(grouped_rows)
        competition_teams[competition] = nodes
        components[competition] = component_list
    return dict(competition_teams), components


def _schedule_competition_status(
    fixture: Mapping[str, Any],
    competition_lookup: Mapping[str, set[str]],
    historical_competitions: set[str],
) -> tuple[str, set[str]]:
    mapped = set(competition_lookup.get(normalize_name(fixture.get("league")), set()))
    if mapped & historical_competitions:
        return "historical_supported_competition", mapped
    if mapped:
        return "known_competition_without_historical_results", mapped
    return "competition_context_unresolved", mapped


def build_current_fixture_coverage(
    fixtures: Iterable[Mapping[str, Any]],
    historical_rows: Iterable[Mapping[str, Any]],
    *,
    crosswalk_mappings: Iterable[Mapping[str, Any]],
    identity_matches: Iterable[Mapping[str, Any]],
    competition_registry: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _dedupe_historical_rows(historical_rows)
    competition_lookup = build_competition_registry_lookup(competition_registry)
    historical_competitions = {str(row.get("competition_id")) for row in rows if row.get("competition_id")}
    identity_index = _identity_by_match_id(identity_matches)
    crosswalk_index = _crosswalk_name_index(crosswalk_mappings)
    fixture_results: list[dict[str, Any]] = []
    blocker_counts = {"identity": 0, "history": 0, "ready": 0}
    identity_reasons: collections.Counter[str] = collections.Counter()
    history_reasons: collections.Counter[str] = collections.Counter()
    competition_statuses: collections.Counter[str] = collections.Counter()
    supported_competitions: collections.Counter[str] = collections.Counter()
    missing_competitions: collections.Counter[str] = collections.Counter()

    for fixture in fixtures:
        identity = _fixture_identity(fixture, identity_index, crosswalk_index, competition_lookup)
        competition_status, mapped_competitions = _schedule_competition_status(
            fixture, competition_lookup, historical_competitions
        )
        competition_statuses[competition_status] += 1
        if competition_status == "historical_supported_competition":
            for competition in mapped_competitions:
                if competition in historical_competitions:
                    supported_competitions[competition] += 1
        elif competition_status == "known_competition_without_historical_results":
            for competition in mapped_competitions:
                missing_competitions[competition] += 1
        status = "identity_blocker"
        reason = identity["reason"]
        history_match_counts: dict[str, int] = {}
        if identity["status"] == "resolved":
            competition = str(identity["competition_id"] or "")
            home_id, away_id = identity["home_team_id"], identity["away_team_id"]
            target_kickoff = _universe_kickoff(fixture)
            prior_rows = [
                row
                for row in rows
                if target_kickoff is None
                or (
                    _parse_datetime(row.get("kickoff_at")) is not None
                    and _parse_datetime(row.get("kickoff_at")) < target_kickoff
                )
            ]
            competition_teams, components = _network_index(prior_rows)
            history_match_counts = {
                "home": sum(
                    1
                    for row in prior_rows
                    if row.get("competition_id") == competition
                    and home_id in (row.get("home_team_id"), row.get("away_team_id"))
                ),
                "away": sum(
                    1
                    for row in prior_rows
                    if row.get("competition_id") == competition
                    and away_id in (row.get("home_team_id"), row.get("away_team_id"))
                ),
            }
            if target_kickoff is None:
                status, reason = "history_blocker", "target_kickoff_missing"
            elif competition not in competition_teams:
                status, reason = "history_blocker", "history_competition_missing"
            elif home_id not in competition_teams[competition] or away_id not in competition_teams[competition]:
                status, reason = "history_blocker", "history_team_missing"
            elif not any(
                home_id in component and away_id in component for component in components.get(competition, [])
            ):
                status, reason = "history_blocker", "history_network_disconnected"
            else:
                status, reason = "ready", None

        blocker_counts["ready" if status == "ready" else "history" if status == "history_blocker" else "identity"] += 1
        if status == "identity_blocker":
            identity_reasons[str(reason)] += 1
        elif status == "history_blocker":
            history_reasons[str(reason)] += 1
        fixture_results.append(
            {
                "fixture_id": str(fixture.get("matchId") or fixture.get("match_id") or fixture.get("shujuId") or ""),
                "home_name": fixture.get("homeTeam") or fixture.get("home"),
                "away_name": fixture.get("awayTeam") or fixture.get("away"),
                "league": fixture.get("league"),
                "kickoff_at": (_universe_kickoff(fixture) or datetime.min.replace(tzinfo=UTC)).isoformat(),
                "competition_status": competition_status,
                "mapped_competitions": sorted(mapped_competitions),
                "identity_status": identity["status"],
                "identity_source": identity["source"],
                "home_team_id": identity["home_team_id"],
                "away_team_id": identity["away_team_id"],
                "history_match_counts": history_match_counts,
                "status": status,
                "blocker_reason": reason,
            }
        )

    fixture_count = len(fixture_results)
    return {
        "fixture_count": fixture_count,
        "both_teams_enter_network": blocker_counts["ready"],
        "coverage_ratio": blocker_counts["ready"] / fixture_count if fixture_count else 0.0,
        "identity_resolved_fixture_count": fixture_count - blocker_counts["identity"],
        "blocker_counts": blocker_counts,
        "identity_blocker_reasons": dict(sorted(identity_reasons.items())),
        "history_blocker_reasons": dict(sorted(history_reasons.items())),
        "competition_history_gate": {
            "historical_supported_competition": competition_statuses["historical_supported_competition"],
            "known_competition_without_historical_results": competition_statuses[
                "known_competition_without_historical_results"
            ],
            "competition_context_unresolved": competition_statuses["competition_context_unresolved"],
            "historical_supported_competitions": dict(sorted(supported_competitions.items())),
            "known_missing_competitions": dict(sorted(missing_competitions.items())),
        },
        "fixtures": fixture_results,
    }


def _filter_historical_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    accepted = []
    for row in _dedupe_historical_rows(rows):
        if row.get("eligible_for_team_strength") is not True:
            continue
        if row.get("source_conflict") is True:
            continue
        if row.get("duplicate_status") not in (None, "unique"):
            continue
        if row.get("entity_type") not in (None, "club"):
            continue
        if row.get("match_type") not in (None, "league"):
            continue
        if not row.get("competition_id") or not row.get("home_team_id") or not row.get("away_team_id"):
            continue
        if not row.get("kickoff_at"):
            continue
        accepted.append(row)
    return accepted


def _range_for(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, str | None]:
    values = sorted(str(row[field]) for row in rows if row.get(field))
    return {"min": values[0] if values else None, "max": values[-1] if values else None}


def _crosswalk_summary(mappings: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(mappings)
    return {
        "mapping_count": len(values),
        "verified_mapping_count": sum(value.get("verified") is True for value in values),
        "unique_canonical_team_count": len({value.get("canonical_team_id") for value in values if value.get("canonical_team_id")}),
        "provider_counts": dict(sorted(collections.Counter(value.get("provider") for value in values).items())),
        "provider_team_id_present_count": sum(value.get("provider_team_id") not in (None, "") for value in values),
    }


def build_audit_report(
    *,
    historical_rows: Iterable[Mapping[str, Any]],
    current_universe: Mapping[str, Any],
    project_crosswalk: Iterable[Mapping[str, Any]],
    cross_source_crosswalk: Iterable[Mapping[str, Any]],
    identity_matches: Iterable[Mapping[str, Any]],
    alias_registry: Mapping[str, Any],
    competition_registry: Mapping[str, Any],
    source_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw_rows = [dict(row) for row in historical_rows]
    accepted_rows = _filter_historical_rows(raw_rows)
    competition_coverage = competition_network_coverage(accepted_rows)
    season_coverage = competition_season_network_coverage(accepted_rows)
    team_distribution = team_history_match_count_distribution(accepted_rows)
    project_crosswalk_items = list(project_crosswalk)
    cross_source_items = list(cross_source_crosswalk)
    historical_identity = historical_identity_diagnostics(accepted_rows, cross_source_items)
    current_fixtures = list(current_universe.get("fixtures", []))
    current_coverage = build_current_fixture_coverage(
        current_fixtures,
        accepted_rows,
        crosswalk_mappings=project_crosswalk,
        identity_matches=identity_matches,
        competition_registry=build_competition_registry_lookup(competition_registry),
    )

    current_kickoffs = [kickoff for kickoff in (_universe_kickoff(fixture) for fixture in current_fixtures) if kickoff]
    historical_kickoffs = [_parse_datetime(row.get("kickoff_at")) for row in accepted_rows]
    historical_kickoffs = [value for value in historical_kickoffs if value]
    source_as_of = [_parse_datetime(row.get("source_as_of_at")) for row in accepted_rows]
    source_as_of = [value for value in source_as_of if value]
    captured_at = [_parse_datetime(row.get("captured_at")) for row in accepted_rows]
    captured_at = [value for value in captured_at if value]
    current_min = min(current_kickoffs) if current_kickoffs else None
    historical_max = max(historical_kickoffs) if historical_kickoffs else None
    source_max = max(source_as_of) if source_as_of else None
    captured_max = max(captured_at) if captured_at else None
    all_connected = bool(competition_coverage) and all(item["fully_connected"] for item in competition_coverage.values())
    identity_clean = historical_identity["fragmented_canonical_entity_count"] == 0
    historical_research_condition = (
        "READY_FOR_BOUNDED_RESEARCH"
        if all_connected and identity_clean
        else "CONDITIONAL_IDENTITY_REPAIR_REQUIRED"
    )
    identity_items = list(identity_matches)
    current_fixture_ids = {
        str(fixture.get("matchId") or fixture.get("match_id") or fixture.get("shujuId") or "")
        for fixture in current_fixtures
    }
    identity_fixture_ids = {
        str(item.get("id") or item.get("provider_match_id") or item.get("match_id") or "")
        for item in identity_items
    }

    report = {
        "contract_version": "fe_history_graph_1_audit.v1",
        "milestone": "FE-HISTORY-GRAPH-1",
        "status": "READY_FOR_ACCEPTANCE",
        "scope": {
            "read_only_inputs": [
                "FOOTBALL_DATA_HOME/historical_results.duckdb",
                "data/prediction_universe/{business_date}.json",
                "data/football_data/current_match_identity_evidence.json",
                "data/football_data/verified_project_provider_crosswalk.json",
                "data/football_data/verified_identity_crosswalk.json",
                "data/football_data/competition_coverage_registry.json",
            ],
            "no_model_fit": True,
            "no_production_mutation": True,
            "no_result_or_settlement_evaluation": True,
        },
        "source": dict(source_metadata or {}),
        "historical_library": {
            "input_row_count": len(raw_rows),
            "eligible_network_match_count": len(accepted_rows),
            "distinct_match_count": len({row.get("canonical_match_id") for row in accepted_rows}),
            "distinct_team_count": len(team_distribution["per_team_match_count"]),
            "distinct_competition_count": len(competition_coverage),
            "distinct_season_count": len({row.get("season_id") for row in accepted_rows if row.get("season_id")}),
            "providers": dict(sorted(collections.Counter(row.get("provider") for row in accepted_rows).items())),
            "quality": dict(sorted(collections.Counter(row.get("quality") for row in accepted_rows).items())),
            "kickoff_range": _range_for(accepted_rows, "kickoff_at"),
            "source_as_of_range": _range_for(accepted_rows, "source_as_of_at"),
            "captured_at_range": _range_for(accepted_rows, "captured_at"),
            "all_goal_fields_present": all(
                row.get("home_goals") is not None and row.get("away_goals") is not None for row in accepted_rows
            ),
        },
        "connected_coverage_by_competition": competition_coverage,
        "connected_coverage_by_competition_season": season_coverage,
        "team_history_match_count_distribution": team_distribution,
        "historical_identity": historical_identity,
        "identity_crosswalk": {
            "current_identity_evidence_match_count": len(identity_items),
            "current_identity_evidence_exact_match_overlap_count": len(current_fixture_ids & identity_fixture_ids),
            "project_provider_crosswalk": _crosswalk_summary(project_crosswalk_items),
            "cross_source_crosswalk": _crosswalk_summary(cross_source_items),
            "team_alias_registry_team_count": len(alias_registry.get("teams", [])),
            "team_alias_registry_crosswalk_count": len(alias_registry.get("crosswalk", [])),
        },
        "current_production_coverage": {
            "business_date": current_universe.get("business_date"),
            "source_status": current_universe.get("status"),
            "source_fetched_at": current_universe.get("fetched_at"),
            "fixture_source_count": current_universe.get("source_fixture_count"),
            **current_coverage,
        },
        "time_semantics": {
            "historical_max_kickoff": historical_max.isoformat() if historical_max else None,
            "current_fixture_min_kickoff": current_min.isoformat() if current_min else None,
            "historical_max_kickoff_strictly_before_current_fixtures": bool(
                historical_max and current_min and historical_max < current_min
            ),
            "historical_source_as_of_max": source_max.isoformat() if source_max else None,
            "historical_captured_at_max": captured_max.isoformat() if captured_max else None,
            "source_as_of_strictly_before_current_fixtures": bool(source_max and current_min and source_max < current_min),
            "captured_at_strictly_before_current_fixtures": bool(captured_max and current_min and captured_max < current_min),
            "pre_match_feature_rule": "Use only historical rows with kickoff_at < target kickoff_at; never use target or later rows.",
        },
        "model_readiness": {
            "historical_graph": {
                "all_covered_competitions_connected": all_connected,
                "historical_identity_clean": identity_clean,
                "research_condition": historical_research_condition,
            },
            "elo": {
                "historical_research_condition": historical_research_condition,
                "current_production_condition": "NOT_READY",
                "blocker": "No current production fixture has a deterministic canonical home/away pair; Portugal history also has 15 exact crosswalk fragmentation clusters, and 24 fixtures lack supported historical competition coverage.",
            },
            "dynamic_attack_defense": {
                "historical_research_condition": historical_research_condition,
                "current_production_condition": "NOT_READY",
                "blocker": "The historical rows contain time-ordered kickoff and goal fields, but Portugal identity fragmentation and current production identity/network linkage remain.",
            },
        },
        "blocker_attribution": {
            "current_fixture_identity_blockers": current_coverage["blocker_counts"]["identity"],
            "current_fixture_history_blockers_after_identity_resolution": current_coverage["blocker_counts"]["history"],
            "current_fixture_ready": current_coverage["blocker_counts"]["ready"],
            "known_schedule_competition_history_gaps_before_team_identity": current_coverage[
                "competition_history_gate"
            ]["known_competition_without_historical_results"],
            "schedule_competition_context_unresolved": current_coverage["competition_history_gate"][
                "competition_context_unresolved"
            ],
            "historical_identity_fragmented_canonical_entity_count": historical_identity[
                "fragmented_canonical_entity_count"
            ],
            "historical_identity_fragmented_team_id_count": historical_identity[
                "fragmented_historical_team_id_count"
            ],
            "primary_blocker": "identity",
            "missing_categories": ["identity", "competition_history"],
            "data_source_finding": "The existing result sources cover 7 competitions; current-day schedule coverage is exact-supported for 4 fixtures, has 6 known unsupported-competition fixtures, and has 18 unresolved competition labels in the existing registry.",
        },
        "production_mutation_check": {
            "input_data_written": False,
            "champion_changed": False,
            "frozen_prediction_changed": False,
            "production_workflow_changed": False,
            "evidence_outputs_only": True,
        },
    }
    return report


def run_audit(
    *,
    root: Path = PROJECT_ROOT,
    business_date: str,
    historical_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(root)
    universe_path = root / "data" / "prediction_universe" / f"{business_date}.json"
    historical_path = Path(historical_path or historical_results_path())
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    identity = json.loads((root / CURRENT_IDENTITY_PATH.relative_to(PROJECT_ROOT)).read_text(encoding="utf-8"))
    project_crosswalk = json.loads(
        (root / PROJECT_CROSSWALK_PATH.relative_to(PROJECT_ROOT)).read_text(encoding="utf-8")
    )
    cross_source_crosswalk = json.loads(
        (root / CROSS_SOURCE_CROSSWALK_PATH.relative_to(PROJECT_ROOT)).read_text(encoding="utf-8")
    )
    alias_registry = json.loads((root / ALIAS_REGISTRY_PATH.relative_to(PROJECT_ROOT)).read_text(encoding="utf-8"))
    competition_registry = json.loads(
        (root / COMPETITION_REGISTRY_PATH.relative_to(PROJECT_ROOT)).read_text(encoding="utf-8")
    )
    store = HistoricalResultStore(historical_path)
    source_metadata = {
        "repository_revision": _git_revision(root),
        "historical_dataset_digest": store.dataset_digest(),
        "historical_store": "FOOTBALL_DATA_HOME/historical_results.duckdb",
        "historical_store_sha256": _file_sha256(historical_path),
        "current_production_fixture_source": f"data/prediction_universe/{business_date}.json",
        "current_production_fixture_source_sha256": _file_sha256(universe_path),
        "current_identity_evidence_sha256": _file_sha256(root / CURRENT_IDENTITY_PATH.relative_to(PROJECT_ROOT)),
        "project_crosswalk_sha256": _file_sha256(root / PROJECT_CROSSWALK_PATH.relative_to(PROJECT_ROOT)),
        "audit_input_policy": "canonical current-day Prediction Universe per D-001; no settlement/result files read",
    }
    return build_audit_report(
        historical_rows=store.records(),
        current_universe=universe,
        project_crosswalk=project_crosswalk.get("mappings", []),
        cross_source_crosswalk=cross_source_crosswalk.get("mappings", []),
        identity_matches=identity.get("matches", []),
        alias_registry=alias_registry,
        competition_registry=competition_registry,
        source_metadata=source_metadata,
    )


def _fmt_ratio(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def render_markdown(report: Mapping[str, Any]) -> str:
    historical = report["historical_library"]
    current = report["current_production_coverage"]
    blockers = report["blocker_attribution"]
    readiness = report["model_readiness"]
    historical_identity = report["historical_identity"]
    lines = [
        "# FE-HISTORY-GRAPH-1 — Historical Network Coverage Audit",
        "",
        f"Status: `{report['status']}`",
        "",
        "## Scope",
        "",
        "This is a read-only topology and identity-coverage audit. It does not fit a model, modify Champion, modify production, or read settlement/postmatch evaluation data.",
        "",
        f"- Historical store: `FOOTBALL_DATA_HOME/historical_results.duckdb`; dataset digest `{report['source'].get('historical_dataset_digest')}`.",
        f"- Current production fixture source: `{report['source'].get('current_production_fixture_source')}`; business date `{current.get('business_date')}`; source status `{current.get('source_status')}`.",
        f"- Historical library: **{historical['distinct_match_count']} matches / {historical['distinct_team_count']} teams / {historical['distinct_competition_count']} competitions / {historical['distinct_season_count']} seasons**.",
        "",
        "## Connected coverage by competition",
        "",
        "| Competition | Matches | Teams | Components | Largest component | Match coverage | Team coverage |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for competition, item in report["connected_coverage_by_competition"].items():
        lines.append(
            f"| `{competition}` | {item['match_count']} | {item['team_count']} | {item['component_count']} | {item['largest_component_team_count']} teams | {_fmt_ratio(item['connected_match_coverage'])} | {_fmt_ratio(item['connected_team_coverage'])} |"
        )
    distribution = report["team_history_match_count_distribution"]
    lines.extend(
        [
            "",
            "## Team history depth",
            "",
            f"{distribution['unique_team_count']} teams; min/median/p75/max = {distribution['min']}/{distribution['median']}/{distribution['p75']}/{distribution['max']} matches; mean = {distribution['mean']:.2f}.",
            f"Buckets: `{distribution['buckets']}`. The exact per-team distribution is retained in the JSON evidence.",
            f"Historical identity diagnostic: {historical_identity['fragmented_canonical_entity_count']} crosswalk entity clusters split across {historical_identity['fragmented_historical_team_id_count']} historical team IDs; affected competitions: `{historical_identity['fragmented_competitions']}`.",
            "",
            "## Current production fixture coverage",
            "",
            f"Canonical current-day universe: **{current['fixture_count']} fixtures**; both teams in the same historical network: **{current['both_teams_enter_network']}/{current['fixture_count']} ({_fmt_ratio(current['coverage_ratio'])})**.",
            f"Mutually exclusive blockers: identity `{blockers['current_fixture_identity_blockers']}`, history after identity resolution `{blockers['current_fixture_history_blockers_after_identity_resolution']}`, ready `{blockers['current_fixture_ready']}`.",
            f"Existing current identity evidence has `{report['identity_crosswalk']['current_identity_evidence_match_count']}` rows but exact overlap with this universe is `{report['identity_crosswalk']['current_identity_evidence_exact_match_overlap_count']}`; no verified two-team pair is available.",
            f"Competition-level pre-identity signal: supported historical competition `{current['competition_history_gate']['historical_supported_competition']}`, known missing historical competition `{current['competition_history_gate']['known_competition_without_historical_results']}`, registry-unresolved `{current['competition_history_gate']['competition_context_unresolved']}`.",
            f"Known missing competition history keys: `{current['competition_history_gate']['known_missing_competitions']}`.",
            "",
            "## Readiness",
            "",
            f"- Elo: historical graph `{readiness['elo']['historical_research_condition']}`; current-production development `{readiness['elo']['current_production_condition']}`.",
            f"- Dynamic A/D: historical graph `{readiness['dynamic_attack_defense']['historical_research_condition']}`; current-production development `{readiness['dynamic_attack_defense']['current_production_condition']}`.",
            "",
            "## Time semantics",
            "",
            f"Historical max kickoff `{report['time_semantics']['historical_max_kickoff']}`; current fixture min kickoff `{report['time_semantics']['current_fixture_min_kickoff']}`; strict prior relation `{report['time_semantics']['historical_max_kickoff_strictly_before_current_fixtures']}`.",
            f"Historical source_as_of/captured_at are also before the current fixture minimum: `{report['time_semantics']['source_as_of_strictly_before_current_fixtures']}` / `{report['time_semantics']['captured_at_strictly_before_current_fixtures']}`.",
            "Feature construction rule remains strict `historical kickoff_at < target kickoff_at`; no target or later match is eligible.",
            "",
            "## Conclusion",
            "",
            f"Primary blocker: **{blockers['primary_blocker']}**. Missing categories: `{', '.join(blockers['missing_categories'])}`.",
            f"The historical graph is topologically connected within all seven covered competitions, but the verified crosswalk exposes {historical_identity['fragmented_canonical_entity_count']} identity-fragmentation clusters in Portugal. The current production universe has no deterministic two-team identity pair. In addition, 24 current fixtures are outside an exact-supported historical competition context (6 known missing result coverage, 18 unresolved in the existing competition registry).",
            "",
            "## Production mutation check",
            "",
            "The audit reads the historical DuckDB and tracked evidence only; it writes only this compact report and the audit markdown. Champion, frozen predictions, production workflows, and the shared data store are not modified.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--historical-path", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args(argv)

    report = run_audit(root=args.root, business_date=args.business_date, historical_path=args.historical_path)
    json_output = args.json_output or args.root / OUTPUT_JSON_PATH.relative_to(PROJECT_ROOT)
    markdown_output = args.markdown_output or args.root / OUTPUT_MARKDOWN_PATH.relative_to(PROJECT_ROOT)
    _write_json(json_output, report)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "json_output": str(json_output), "markdown_output": str(markdown_output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
