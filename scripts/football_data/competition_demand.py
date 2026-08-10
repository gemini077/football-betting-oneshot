"""Recover project competition demand from bounded metadata indexes.

This module deliberately counts project fixtures, not imported historical
source rows.  It accepts only exact reviewed competition aliases and keeps
unresolved demand visible instead of guessing from team names or prestige.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


PROJECT_TIMEZONE = timezone(timedelta(hours=8))


COMPETITION_CATALOG: dict[str, dict[str, str]] = {
    "england-premier-league": {"name": "Premier League", "country": "England", "entity_type": "club", "competition_type": "league"},
    "spain-la-liga": {"name": "La Liga", "country": "Spain", "entity_type": "club", "competition_type": "league"},
    "italy-serie-a": {"name": "Serie A", "country": "Italy", "entity_type": "club", "competition_type": "league"},
    "germany-bundesliga": {"name": "Bundesliga", "country": "Germany", "entity_type": "club", "competition_type": "league"},
    "france-ligue-1": {"name": "Ligue 1", "country": "France", "entity_type": "club", "competition_type": "league"},
    "france-ligue-2": {"name": "Ligue 2", "country": "France", "entity_type": "club", "competition_type": "league"},
    "portugal-primeira-liga": {"name": "Portuguese Primeira Liga", "country": "Portugal", "entity_type": "club", "competition_type": "league"},
    "netherlands-eredivisie": {"name": "Eredivisie", "country": "Netherlands", "entity_type": "club", "competition_type": "league"},
    "netherlands-eerste-divisie": {"name": "Eerste Divisie", "country": "Netherlands", "entity_type": "club", "competition_type": "league"},
    "belgium-pro-league": {"name": "Belgian Pro League", "country": "Belgium", "entity_type": "club", "competition_type": "league"},
    "sweden-allsvenskan": {"name": "Sweden Allsvenskan", "country": "Sweden", "entity_type": "club", "competition_type": "league"},
    "sweden-superettan": {"name": "Sweden Superettan", "country": "Sweden", "entity_type": "club", "competition_type": "league"},
    "norway-eliteserien": {"name": "Eliteserien", "country": "Norway", "entity_type": "club", "competition_type": "league"},
    "finland-veikkausliiga": {"name": "Veikkausliiga", "country": "Finland", "entity_type": "club", "competition_type": "league"},
    "denmark-superliga": {"name": "Danish Superliga", "country": "Denmark", "entity_type": "club", "competition_type": "league"},
    "japan-j1-league": {"name": "J1 League", "country": "Japan", "entity_type": "club", "competition_type": "league"},
    "japan-j2-league": {"name": "J2 League", "country": "Japan", "entity_type": "club", "competition_type": "league"},
    "south-korea-k-league-1": {"name": "K League 1", "country": "South Korea", "entity_type": "club", "competition_type": "league"},
    "china-super-league": {"name": "Chinese Super League", "country": "China", "entity_type": "club", "competition_type": "league"},
    "australia-a-league-men": {"name": "A-League", "country": "Australia", "entity_type": "club", "competition_type": "league"},
    "usa-mls": {"name": "MLS", "country": "United States", "entity_type": "club", "competition_type": "league"},
    "mexico-liga-mx": {"name": "Liga MX", "country": "Mexico", "entity_type": "club", "competition_type": "league"},
    "brazil-serie-a": {"name": "Brazil Serie A", "country": "Brazil", "entity_type": "club", "competition_type": "league"},
    "brazil-copa-do-brasil": {"name": "Copa do Brasil", "country": "Brazil", "entity_type": "club", "competition_type": "domestic_cup"},
    "argentina-primera-division": {"name": "Argentine Primera", "country": "Argentina", "entity_type": "club", "competition_type": "league"},
    "uefa-champions-league": {"name": "Champions League", "country": "Europe", "entity_type": "club", "competition_type": "international_club"},
    "uefa-europa-league": {"name": "Europa League", "country": "Europe", "entity_type": "club", "competition_type": "international_club"},
    "uefa-conference-league": {"name": "Conference League", "country": "Europe", "entity_type": "club", "competition_type": "international_club"},
    "fifa-world-cup": {"name": "World Cup", "country": "International", "entity_type": "national_team", "competition_type": "national_team"},
}


# Exact strings observed in the project's metadata indexes.  This is a
# reviewed demand vocabulary, not a fuzzy identity resolver.
COMPETITION_ALIASES: dict[str, str] = {
    "世界杯": "fifa-world-cup",
    "world cup": "fifa-world-cup",
    "欧洲冠军联赛": "uefa-champions-league",
    "欧冠": "uefa-champions-league",
    "champions league": "uefa-champions-league",
    "欧罗巴联赛": "uefa-europa-league",
    "欧罗巴": "uefa-europa-league",
    "europa league": "uefa-europa-league",
    "瑞典超级联赛": "sweden-allsvenskan",
    "sweden allsvenskan": "sweden-allsvenskan",
    "挪威超级联赛": "norway-eliteserien",
    "挪超": "norway-eliteserien",
    "norway eliteserien": "norway-eliteserien",
    "芬兰超级联赛": "finland-veikkausliiga",
    "芬兰超级联赛": "finland-veikkausliiga",
    "finland veikkausliiga": "finland-veikkausliiga",
    "韩国职业联赛": "south-korea-k-league-1",
    "k league 1": "south-korea-k-league-1",
    "巴西甲级联赛": "brazil-serie-a",
    "brazil serie a": "brazil-serie-a",
    "巴西杯": "brazil-copa-do-brasil",
    "copa do brasil": "brazil-copa-do-brasil",
    "美国职业大联盟": "usa-mls",
    "mls": "usa-mls",
    "日本职业联赛": "japan-j1-league",
    "j1 league": "japan-j1-league",
    "日本乙级联赛": "japan-j2-league",
    "j2 league": "japan-j2-league",
    "荷兰甲级联赛": "netherlands-eredivisie",
    "eredivisie": "netherlands-eredivisie",
    "荷兰乙级联赛": "netherlands-eerste-divisie",
    "eerste divisie": "netherlands-eerste-divisie",
    "德国乙级联赛": "germany-2-bundesliga",
    "2. bundesliga": "germany-2-bundesliga",
    "英格兰联赛杯": "england-league-cup",
    "efl cup": "england-league-cup",
    "葡萄牙超级联赛": "portugal-primeira-liga",
    "葡萄牙超级联赛": "portugal-primeira-liga",
    "portuguese primeira liga": "portugal-primeira-liga",
    "法国乙级联赛": "france-ligue-2",
    "ligue 2": "france-ligue-2",
}

COMPETITION_CATALOG.update({
    "germany-2-bundesliga": {"name": "2. Bundesliga", "country": "Germany", "entity_type": "club", "competition_type": "league"},
    "england-league-cup": {"name": "EFL Cup", "country": "England", "entity_type": "club", "competition_type": "domestic_cup"},
})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(value.strip(), fmt)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PROJECT_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normal_text(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def resolve_project_competition(raw_name: Any) -> dict[str, Any]:
    """Resolve an observed competition only through an exact reviewed alias."""

    raw = _text(raw_name)
    key = COMPETITION_ALIASES.get(raw.casefold())
    if not key:
        return {
            "competition_key": None,
            "canonical_competition_id": None,
            "resolution_status": "unresolved",
            "resolution_method": "unresolved",
            "confidence": None,
            "reason": "no exact reviewed competition alias",
            "raw_name": raw or None,
        }
    catalog = dict(COMPETITION_CATALOG.get(key) or {})
    return {
        "competition_key": key,
        "canonical_competition_id": f"competition:{key}",
        "resolution_status": "resolved",
        "resolution_method": "exact_reviewed_alias",
        "confidence": 1.0,
        "reason": "exact project competition vocabulary match",
        "raw_name": raw or None,
        **catalog,
    }


def _match_text(value: Any) -> tuple[str, str] | None:
    text = _text(value)
    if " vs " not in text.casefold():
        return None
    home, away = text.split(" vs ", 1)
    home = home.strip()
    away = away.strip()
    return (home, away) if home and away else None


class _DemandCollector:
    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.fixture_index: dict[str, str] = {}
        self.base_fixture_index: dict[str, str] = {}
        self.id_index: dict[str, str] = {}
        self.counter = 0

    def _fixture_key(self, row: Mapping[str, Any], kickoff: datetime | None) -> str | None:
        home = _normal_text(row.get("home") or row.get("home_team"))
        away = _normal_text(row.get("away") or row.get("away_team"))
        if not home or not away or kickoff is None:
            return None
        competition = _normal_text(row.get("competition") or row.get("league"))
        return f"fixture:{home}|{away}|{_iso(kickoff)}|{competition}"

    def _base_fixture_key(self, row: Mapping[str, Any], kickoff: datetime | None) -> str | None:
        home = _normal_text(row.get("home") or row.get("home_team"))
        away = _normal_text(row.get("away") or row.get("away_team"))
        if not home or not away or kickoff is None:
            return None
        return f"fixture:{home}|{away}|{_iso(kickoff)}"

    def add(
        self,
        row: Mapping[str, Any],
        *,
        source: str,
        evidence: Mapping[str, Any] | None = None,
        current_match: bool = False,
    ) -> str:
        kickoff = _parse_time(row.get("kickoff_at") or row.get("kickoff_local") or row.get("kickoff") or row.get("date"))
        provider_id = _text(row.get("provider_match_id") or row.get("nowscore_id")) or None
        canonical_id = _text(row.get("canonical_match_id") or row.get("id")) or None
        candidates = []
        for value in (canonical_id, provider_id):
            if value:
                key = self.id_index.get(value)
                if key:
                    candidates.append(key)
        fixture = self._fixture_key(row, kickoff)
        if fixture and fixture in self.fixture_index:
            candidates.append(self.fixture_index[fixture])
        base_fixture = self._base_fixture_key(row, kickoff)
        if base_fixture and base_fixture in self.base_fixture_index:
            candidates.append(self.base_fixture_index[base_fixture])
        key = candidates[0] if candidates else None
        new_competition = resolve_project_competition(row.get("competition") or row.get("league"))
        if key is None:
            self.counter += 1
            key = f"demand:{self.counter}"
            self.events[key] = {
                "demand_id": key,
                "canonical_match_id": canonical_id,
                "provider_match_ids": [provider_id] if provider_id else [],
                "home": _text(row.get("home") or row.get("home_team")) or None,
                "away": _text(row.get("away") or row.get("away_team")) or None,
                "kickoff_at": _iso(kickoff),
                "competition": new_competition,
                "sources": [],
                "evidence": [],
                "current_match": bool(current_match),
                "deduplication_method": "canonical_or_provider_id" if canonical_id or provider_id else "fixture_fingerprint",
            }
        event = self.events[key]
        existing_competition = event.get("competition") or {}
        existing_key = existing_competition.get("competition_key")
        new_key = new_competition.get("competition_key")
        if existing_key and new_key and existing_key != new_key:
            event["competition"] = {
                "competition_key": None,
                "canonical_competition_id": None,
                "resolution_status": "unresolved",
                "resolution_method": "unresolved",
                "confidence": None,
                "reason": "exact fixture has conflicting competition metadata",
                "raw_name": existing_competition.get("raw_name") or new_competition.get("raw_name"),
            }
            event["source_conflict"] = True
        elif not existing_key and new_key:
            event["competition"] = new_competition
            if base_fixture:
                event["deduplication_method"] = "exact_home_away_kickoff_enriched_competition"
        if canonical_id:
            event["canonical_match_id"] = event.get("canonical_match_id") or canonical_id
            self.id_index[canonical_id] = key
        if provider_id:
            if provider_id not in event["provider_match_ids"]:
                event["provider_match_ids"].append(provider_id)
            self.id_index[provider_id] = key
        if fixture:
            self.fixture_index[fixture] = key
        if base_fixture:
            self.base_fixture_index[base_fixture] = key
        if source not in event["sources"]:
            event["sources"].append(source)
        if evidence:
            event["evidence"].append(dict(evidence))
        event["current_match"] = bool(event.get("current_match") or current_match)
        return key


def _task_values(tasks: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    if isinstance(tasks, Mapping):
        return [(str(key), value) for key, value in tasks.items() if isinstance(value, Mapping)]
    return [(str(index), value) for index, value in enumerate(tasks) if isinstance(value, Mapping)]


def _job_task(job_id: str, job: Mapping[str, Any], task_items: list[tuple[str, Mapping[str, Any]]]) -> tuple[str, Mapping[str, Any]] | None:
    provider_id = job_id.split(":", 1)[-1]
    exact = [(key, task) for key, task in task_items if _text(task.get("provider_match_id")) == provider_id]
    if len(exact) == 1:
        return exact[0]
    match = _match_text(job.get("match"))
    if match is None:
        return None
    home, away = map(_normal_text, match)
    candidates = [
        (key, task)
        for key, task in task_items
        if _normal_text(task.get("home")) == home and _normal_text(task.get("away")) == away
    ]
    return candidates[0] if len(candidates) == 1 else None


def _row_from_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider_match_id": task.get("provider_match_id"),
        "home": task.get("home"),
        "away": task.get("away"),
        "league": task.get("league"),
        "kickoff": task.get("kickoff"),
    }


def _row_from_job(job_id: str, job: Mapping[str, Any]) -> dict[str, Any]:
    match = _match_text(job.get("match"))
    date_text, provider_id = (job_id.split(":", 1) + [""])[:2]
    row: dict[str, Any] = {"kickoff": f"{date_text} 00:00", "provider_match_id": provider_id or None}
    if match:
        row.update({"home": match[0], "away": match[1]})
    return row


def _bucket(events: Iterable[Mapping[str, Any]], *, reference: datetime, days: int | None) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "project_analysis_count": 0,
        "current_match_count": 0,
        "resolved_match_count": 0,
        "unresolved_match_count": 0,
        "evidence_source_count": 0,
        "first_seen_at": None,
        "last_seen_at": None,
        "raw_names": [],
    })
    start = reference - timedelta(days=days) if days is not None else None
    for event in events:
        kickoff = _parse_time(event.get("kickoff_at"))
        if days is not None and (kickoff is None or kickoff < start):
            continue
        resolution = event.get("competition") or {}
        key = resolution.get("competition_key")
        if not key:
            continue
        row = grouped[key]
        row["project_analysis_count"] += 1
        row["resolved_match_count"] += 1
        row["current_match_count"] += int(bool(event.get("current_match")))
        row["evidence_source_count"] += len(event.get("sources") or [])
        raw = resolution.get("raw_name")
        if raw and raw not in row["raw_names"]:
            row["raw_names"].append(raw)
        if kickoff is not None:
            iso = _iso(kickoff)
            row["first_seen_at"] = min(value for value in (row["first_seen_at"], iso) if value) if row["first_seen_at"] else iso
            row["last_seen_at"] = max(value for value in (row["last_seen_at"], iso) if value) if row["last_seen_at"] else iso
    for row in grouped.values():
        row["raw_names"] = sorted(row["raw_names"])
    return dict(sorted(grouped.items()))


def recover_competition_usage(
    *,
    schedule_rows: Iterable[Mapping[str, Any]],
    prematch_tasks: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    analysis_jobs: Mapping[str, Any],
    selected_matches: Iterable[Mapping[str, Any]],
    current_matches: Iterable[Mapping[str, Any]],
    generated_at: str,
    previous_usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recover and deduplicate project demand from lightweight metadata only."""

    reference = _parse_time(generated_at) or datetime.now(timezone.utc)
    collector = _DemandCollector()
    schedule_rows = list(schedule_rows)
    task_items = _task_values(prematch_tasks)
    for row in schedule_rows:
        collector.add(row, source="postmatch_schedule_index", evidence={"file": row.get("metadata_file"), "status": row.get("status")})
    for task_id, task in task_items:
        collector.add(_row_from_task(task), source="prematch_task_index", evidence={"task_id": task_id})
    job_recovery: list[dict[str, Any]] = []
    for job_id, job in (analysis_jobs or {}).items():
        job = job if isinstance(job, Mapping) else {}
        linked = _job_task(str(job_id), job, task_items)
        if linked:
            task_id, task = linked
            event_key = collector.add(
                _row_from_task(task),
                source="analysis_job_index",
                evidence={"job_id": job_id, "linked_task_id": task_id, "resolution_method": "exact_provider_or_home_away_metadata"},
            )
            job_recovery.append({"job_id": job_id, "status": "recovered", "event_id": event_key, "evidence": "prematch_tasks.json"})
        else:
            event_key = collector.add(
                _row_from_job(str(job_id), job),
                source="analysis_job_index",
                evidence={"job_id": job_id, "resolution_method": "unresolved_job_metadata"},
            )
            job_recovery.append({"job_id": job_id, "status": "unresolved", "event_id": event_key, "evidence": "core_auto_state.json"})
    for row in selected_matches:
        collector.add(row, source="selected_match_metadata", evidence={"file": "data/match_workspace/selected_matches.json"})
    for row in current_matches:
        collector.add(row, source="current_match_metadata", evidence={"file": "data/match_workspace/latest.json"}, current_match=True)

    events = list(collector.events.values())
    unresolved = [
        {
            "demand_id": event["demand_id"],
            "provider_match_ids": event["provider_match_ids"],
            "home": event.get("home"),
            "away": event.get("away"),
            "kickoff_at": event.get("kickoff_at"),
            "raw_competition": (event.get("competition") or {}).get("raw_name"),
            "resolution_status": "unresolved",
            "reason": (event.get("competition") or {}).get("reason", "no exact reviewed competition alias"),
            "sources": event.get("sources", []),
            "evidence": event.get("evidence", []),
        }
        for event in events
        if not (event.get("competition") or {}).get("competition_key")
    ]
    resolved = [event for event in events if (event.get("competition") or {}).get("competition_key")]
    windows = {
        "last_30d": {"competitions": _bucket(resolved, reference=reference, days=30)},
        "last_90d": {"competitions": _bucket(resolved, reference=reference, days=90)},
        "all_indexed_recent_production_period": {
            "competitions": _bucket(resolved, reference=reference, days=None),
            "project_match_count": len(resolved),
            "unresolved_match_count": len(unresolved),
        },
    }
    for window in windows.values():
        for row in window.get("competitions", {}).values():
            row["analysis_count_30d"] = row["project_analysis_count"] if window is windows["last_30d"] else 0
            row["analysis_count_90d"] = row["project_analysis_count"] if window is windows["last_90d"] else 0
            row["analysis_count_all_recoverable"] = row["project_analysis_count"] if window is windows["all_indexed_recent_production_period"] else 0
    recovered_jobs = sum(item["status"] == "recovered" for item in job_recovery)
    source_counts = defaultdict(int)
    for event in events:
        for source in event.get("sources", []):
            source_counts[source] += 1
    output = {
        "contract_version": "competition_usage_history.v2",
        "registry_started_at": (previous_usage or {}).get("registry_started_at") or generated_at,
        "generated_at": generated_at,
        "historical_usage_before_registry_start": "recovered_partial",
        "evidence_scope": [
            "data/postmatch_automation/schedules/*.json metadata",
            "data/market_history/prematch_tasks.json metadata",
            "data/analysis_jobs/core_auto_state.json metadata",
            "data/match_workspace/selected_matches.json",
            "data/match_workspace/latest.json match metadata",
            "data/football_data/current_match_identity_evidence.json",
        ],
        "windows": windows,
        "resolved_match_count": len(resolved),
        "unresolved_match_count": len(unresolved),
        "unresolved_usage": unresolved,
        "job_recovery": {
            "analysis_job_count": len(job_recovery),
            "recovered_count": recovered_jobs,
            "still_unresolved_count": len(job_recovery) - recovered_jobs,
            "jobs": job_recovery,
        },
        "source_event_counts": dict(sorted(source_counts.items())),
        "deduplicated_event_count": len(events),
        "notes": [
            "Project demand is deduplicated by canonical/provider match ID or an exact home-away-kickoff-competition fingerprint.",
            "Source record counts from historical providers are excluded from project usage and priority.",
            "The bounded indexes do not prove complete historical demand; usage before the registry start is recovered_partial.",
        ],
        "recovered_events": events,
    }
    # Keep the all-period bucket convenient for callers while retaining the
    # versioned windows structure used by the persisted registry.
    output["last_30d"] = windows["last_30d"]
    output["last_90d"] = windows["last_90d"]
    output["all_indexed_recent_production_period"] = windows["all_indexed_recent_production_period"]
    return output


def usage_observations(usage: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert recovered all-period demand into coverage observations."""

    rows: list[dict[str, Any]] = []
    all_period = usage.get("windows", {}).get("all_indexed_recent_production_period", {})
    all_rows = all_period.get("competitions", {})
    last_30 = usage.get("windows", {}).get("last_30d", {}).get("competitions", {})
    last_90 = usage.get("windows", {}).get("last_90d", {}).get("competitions", {})
    for key, value in sorted(all_rows.items()):
        row30 = last_30.get(key, {})
        row90 = last_90.get(key, {})
        rows.append({
            "competition_key": key,
            "raw_name": (value.get("raw_names") or [key])[0],
            "project_analysis_count": int(value.get("project_analysis_count") or 0),
            "analysis_count_30d": int(row30.get("project_analysis_count") or 0),
            "analysis_count_90d": int(row90.get("project_analysis_count") or 0),
            "analysis_count_all_recoverable": int(value.get("project_analysis_count") or 0),
            "current_match_count": int(value.get("current_match_count") or 0),
            "resolved_match_count": int(value.get("resolved_match_count") or 0),
            "unresolved_match_count": int(value.get("unresolved_match_count") or 0),
            "first_seen_at": value.get("first_seen_at"),
            "last_seen_at": value.get("last_seen_at"),
        })
    return rows


__all__ = [
    "COMPETITION_ALIASES",
    "COMPETITION_CATALOG",
    "recover_competition_usage",
    "resolve_project_competition",
    "usage_observations",
]
