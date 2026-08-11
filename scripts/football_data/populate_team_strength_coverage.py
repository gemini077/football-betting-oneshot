"""Generate bounded Phase 2B coverage artifacts from normalized evidence.

This command is intentionally a shadow-data job.  It consumes captured source
manifests, the current workspace identity evidence, a project-usage registry,
and the immutable result ledger.  Source volume is kept separate from project
usage so imported rows cannot manufacture demand or coverage priority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .competition_demand import COMPETITION_CATALOG, usage_observations
from .coverage import analysis_weighted_coverage, build_coverage_registry, rank_coverage_gaps
from .health import build_team_strength_health
from .historical_results import HistoricalResultLedger
from .team_strength import PreMatchSnapshotStore, TeamStrengthBuilder


ROOT = Path(__file__).resolve().parents[2]
OPENFOOTBALL_MANIFEST_PATH = ROOT / "data" / "football_data" / "openfootball" / "source_manifest.json"
FOOTBALL_DATA_MANIFEST_PATH = ROOT / "data" / "football_data" / "football_data_uk" / "source_manifest.json"
FOOTBALL_DATA_DEMAND_MANIFEST_PATH = ROOT / "data" / "football_data" / "football_data_uk" / "demand_source_manifest.json"
CURRENT_PATH = ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
OPENFOOTBALL_PILOT_PATH = ROOT / "data" / "football_data" / "historical_result_samples" / "openfootball_pilot.json"
FOOTBALL_DATA_SAMPLE_PATH = ROOT / "data" / "football_data" / "historical_result_samples" / "football_data_uk_sweden_2026.json"
USAGE_PATH = ROOT / "data" / "football_data" / "competition_usage_history.json"
BULK_DATA_ROOT = ROOT / ".cache" / "football_data"
LEDGER_ROOT = BULK_DATA_ROOT / "historical_results.duckdb"
COVERAGE_PATH = ROOT / "data" / "football_data" / "competition_coverage_registry.json"
GAP_PATH = ROOT / "data" / "football_data" / "coverage_gap_ranking.json"
HEALTH_PATH = ROOT / "data" / "football_data" / "team_strength_health.json"
PILOT_SUMMARY_PATH = ROOT / "data" / "football_data" / "team_strength_pilot_summary.json"
SNAPSHOT_ROOT = BULK_DATA_ROOT / "team_strength_snapshots.duckdb"
DOCS_ROOT = ROOT / "docs" / "team-strength"
SNAPSHOT_REVISION = "recency-v3"


KNOWN_COMPETITIONS = [
    ("england-premier-league", "Premier League", "England", "club", "league"),
    ("spain-la-liga", "La Liga", "Spain", "club", "league"),
    ("italy-serie-a", "Serie A", "Italy", "club", "league"),
    ("germany-bundesliga", "Bundesliga", "Germany", "club", "league"),
    ("france-ligue-1", "Ligue 1", "France", "club", "league"),
    ("portugal-primeira-liga", "Portuguese Primeira Liga", "Portugal", "club", "league"),
    ("netherlands-eredivisie", "Eredivisie", "Netherlands", "club", "league"),
    ("belgium-pro-league", "Belgian Pro League", "Belgium", "club", "league"),
    ("sweden-allsvenskan", "Sweden Allsvenskan", "Sweden", "club", "league"),
    ("sweden-superettan", "Sweden Superettan", "Sweden", "club", "league"),
    ("norway-eliteserien", "Eliteserien", "Norway", "club", "league"),
    ("denmark-superliga", "Danish Superliga", "Denmark", "club", "league"),
    ("japan-j1-league", "J1 League", "Japan", "club", "league"),
    ("south-korea-k-league-1", "K League 1", "South Korea", "club", "league"),
    ("china-super-league", "Chinese Super League", "China", "club", "league"),
    ("australia-a-league-men", "A-League", "Australia", "club", "league"),
    ("usa-mls", "MLS", "United States", "club", "league"),
    ("mexico-liga-mx", "Liga MX", "Mexico", "club", "league"),
    ("brazil-serie-a", "Brasileirao", "Brazil", "club", "league"),
    ("argentina-primera-division", "Argentine Primera", "Argentina", "club", "league"),
    ("uefa-champions-league", "Champions League", "Europe", "club", "international_club"),
    ("uefa-europa-league", "Europa League", "Europe", "club", "international_club"),
    ("uefa-conference-league", "Conference League", "Europe", "club", "international_club"),
    ("conmebol-copa-libertadores", "Copa Libertadores", "South America", "club", "international_club"),
    ("conmebol-copa-sudamericana", "Copa Sudamericana", "South America", "club", "international_club"),
    ("fifa-world-cup", "World Cup", "International", "national_team", "national_team"),
    ("uefa-european-championship", "UEFA Euro", "Europe", "national_team", "national_team"),
    ("conmebol-copa-america", "Copa America", "South America", "national_team", "national_team"),
    ("fifa-world-cup-qualifiers", "World Cup Qualifiers", "International", "national_team", "national_team"),
]


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _put_snapshot_without_rewriting(store: PreMatchSnapshotStore, snapshot: Mapping[str, Any]) -> str:
    """Accept an existing semantically identical snapshot without rewriting it.

    Some inherited snapshots use CRLF while the current canonical serializer
    uses LF.  Formatting is not a data change; a real content conflict still
    raises from the immutable store.
    """

    try:
        return store.put(snapshot)
    except ValueError:
        identity = str(snapshot.get("snapshot_id") or "")
        existing = store.get(identity)
        if dict(existing) != dict(snapshot):
            raise
        return identity


def _competition_key(value: Any) -> str:
    text = str(value or "").strip()
    return text.removeprefix("competition:") or "unresolved"


def _base_entries(captured_at: str) -> list[dict[str, Any]]:
    known = list(KNOWN_COMPETITIONS)
    known_keys = {item[0] for item in known}
    known.extend(
        (key, meta["name"], meta["country"], meta["entity_type"], meta["competition_type"])
        for key, meta in COMPETITION_CATALOG.items()
        if key not in known_keys
    )
    entries = [
        {
            "competition_key": key,
            "canonical_competition_id": None,
            "name": name,
            "country": country,
            "entity_type": entity_type,
            "competition_type": competition_type,
            "historical_result_sources": [],
            "current_match_sources": [],
            "result_coverage": "MISSING",
            "current_season_coverage": "MISSING",
            "team_identity_coverage": None,
            "last_verified_at": None,
            "notes": ["No reviewed historical result adapter/source in this bounded phase."],
        }
        for key, name, country, entity_type, competition_type in known
    ]
    reviewed = {
        "sweden-allsvenskan": {
            "canonical_competition_id": "competition:sweden-allsvenskan",
            "historical_result_sources": ["openfootball", "football-data.co.uk"],
            "current_match_sources": ["sporttery"],
            "result_coverage": "SUPPORTED",
            "current_season_coverage": "PARTIAL",
            "team_identity_coverage": 1.0,
            "last_verified_at": captured_at,
            "notes": [
                "OpenFootball 2025 is PARTIAL; football-data.co.uk provides a complete 2025 file and 119/240 in-progress 2026 results.",
                "Current Swedish target matches use the reviewed 2026 football-data.co.uk identity evidence.",
            ],
        },
        "sweden-superettan": {
            "canonical_competition_id": "competition:sweden-superettan",
            "historical_result_sources": ["openfootball"],
            "current_match_sources": [],
            "result_coverage": "PARTIAL",
            "current_season_coverage": "MISSING",
            "team_identity_coverage": 1.0,
            "last_verified_at": captured_at,
            "notes": ["OpenFootball 2025 is 45/240 and therefore PARTIAL; no current target was observed."],
        },
        "portugal-primeira-liga": {
            "canonical_competition_id": "competition:portugal-primeira-liga",
            "historical_result_sources": ["openfootball"],
            "current_match_sources": ["sporttery"],
            "result_coverage": "SUPPORTED",
            "current_season_coverage": "MISSING",
            "team_identity_coverage": 1.0,
            "last_verified_at": captured_at,
            "notes": ["OpenFootball 2025/26 is complete; no reviewed 2026/27 current-season result source is present."],
        },
    }
    for entry in entries:
        entry.update(reviewed.get(entry["competition_key"], {}))
    return entries


def _source_observations(manifests: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest in manifests:
        for source in manifest.get("sources", []):
            rows.append({
                "competition_key": source.get("competition_key"),
                "raw_name": source.get("provider_competition_name"),
                "source_record_count": int(source.get("parsed_result_count") or 0),
                "current_match_count": 0,
                "provider_competition_id": source.get("provider_competition_id"),
                "provider_season_id": source.get("provider_season_id"),
                "provider_season_name": source.get("provider_season_name"),
                "source": manifest.get("provider"),
                "source_completeness_status": source.get("source_completeness_status"),
                "result_completion_ratio": source.get("result_completion_ratio"),
                "result_coverage": source.get("result_coverage"),
                "current_season_coverage": source.get("current_season_coverage"),
                "identity_coverage_status": source.get("identity_coverage_status"),
                "country": source.get("country"),
                "competition_type": source.get("competition_type"),
            })
    return rows


def _apply_source_metadata(registry: dict[str, Any], source_observations: Iterable[Mapping[str, Any]]) -> None:
    """Attach source completeness without turning source volume into demand."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for source in source_observations:
        key = str(source.get("competition_key") or "unresolved")
        grouped.setdefault(key, []).append(source)
    for row in registry["competitions"]:
        sources = grouped.get(str(row.get("competition_key"))) or []
        if not sources:
            continue
        provider_names = set(row.get("historical_result_sources") or [])
        provider_names.update(str(source.get("source")) for source in sources if source.get("source"))
        row["historical_result_sources"] = sorted(provider_names)
        result_statuses = {str(source.get("result_coverage") or "UNVERIFIED").upper() for source in sources}
        current_statuses = {str(source.get("current_season_coverage") or "UNVERIFIED").upper() for source in sources}
        def combine(statuses: set[str]) -> str:
            for value in ("SUPPORTED", "PARTIAL", "MISSING", "UNVERIFIED"):
                if value in statuses:
                    return value
            return "UNVERIFIED"

        if row.get("result_coverage") in {None, "MISSING", "UNVERIFIED"}:
            row["result_coverage"] = combine(result_statuses)
        if row.get("current_season_coverage") in {None, "MISSING", "UNVERIFIED"}:
            row["current_season_coverage"] = combine(current_statuses)
        if row.get("team_identity_coverage") is None and any(source.get("identity_coverage_status") == "UNVERIFIED" for source in sources):
            row["team_identity_coverage"] = 0.0
            row.setdefault("notes", []).append("Historical source is available, but no reviewed project team identity mappings were imported in this bounded phase.")


def _usage_observations(usage: Mapping[str, Any], current: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    del current  # Demand recovery already incorporates current match metadata.
    return usage_observations(usage)


def _business_status(row: Mapping[str, Any], health_row: Mapping[str, Any] | None) -> str:
    current = int(row.get("current_match_count") or 0)
    if not current:
        if float(row.get("team_identity_coverage") or 0) < 1.0:
            return "PARTIAL" if row.get("result_coverage") not in {None, "MISSING"} else "MISSING"
        return "PARTIAL" if row.get("result_coverage") == "PARTIAL" else "MISSING" if row.get("result_coverage") == "MISSING" else "READY"
    health_row = health_row or {}
    ready = int(health_row.get("both_current_strength_ready") or 0)
    bridge = int(health_row.get("bridge_only") or 0)
    stale = int(health_row.get("stale_history") or 0)
    if ready == current:
        return "READY"
    if bridge == current:
        return "BRIDGE_ONLY"
    if stale:
        return "STALE"
    return "PARTIAL"


def _render_coverage_doc(registry: Mapping[str, Any], ranked: list[Mapping[str, Any]], health: Mapping[str, Any]) -> str:
    historical_counts = {status: sum(row.get("result_coverage") == status for row in registry["competitions"]) for status in ("SUPPORTED", "PARTIAL", "MISSING", "UNVERIFIED")}
    overall_counts = {status: sum(row.get("coverage_status") == status for row in registry["competitions"]) for status in ("SUPPORTED", "PARTIAL", "MISSING", "UNVERIFIED")}
    rank_by_key = {row.get("competition_key"): row for row in ranked}
    lines = [
        "# Competition coverage",
        "",
        f"Generated from bounded project usage and source manifests at `{registry['generated_at']}`.",
        "Source record volume is separate from project analysis usage. It cannot raise P0/P1 priority.",
        "",
        f"Historical-result status counts: SUPPORTED `{historical_counts['SUPPORTED']}`, PARTIAL `{historical_counts['PARTIAL']}`, MISSING `{historical_counts['MISSING']}`, UNVERIFIED `{historical_counts['UNVERIFIED']}`.",
        f"Overall current/data-layer status counts: SUPPORTED `{overall_counts['SUPPORTED']}`, PARTIAL `{overall_counts['PARTIAL']}`, MISSING `{overall_counts['MISSING']}`, UNVERIFIED `{overall_counts['UNVERIFIED']}`.",
        f"Analysis-weighted STRICT READY `{registry.get('analysis_weighted_coverage', {}).get('analysis_weighted_strict_ready', 0)}`; READY+verified BRIDGE `{registry.get('analysis_weighted_coverage', {}).get('analysis_weighted_ready_plus_bridge', 0)}`; demand weight `{registry.get('analysis_weighted_coverage', {}).get('analysis_weight', 0)}`.",
        "",
        "| Competition | Historical | Current season | Recency/health | Project 30d | All recoverable | Source records | Priority | Business status |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in registry["competitions"]:
        key = row["competition_key"]
        ranked_row = rank_by_key.get(key, {})
        health_row = health.get("coverage_by_competition", {}).get(row.get("canonical_competition_id") or key, {})
        if not health_row.get("current_matches"):
            recency = "unknown"
        elif health_row.get("both_current_strength_ready") == health_row.get("current_matches"):
            recency = "current-ready"
        elif health_row.get("bridge_only"):
            recency = "bridge-only"
        elif health_row.get("stale_history"):
            recency = "stale"
        else:
            recency = "missing/partial"
        lines.append(
            f"| {row['name']} | {row.get('result_coverage')} | {row.get('current_season_coverage')} | {recency} | {row.get('analysis_count_30d', 0)} | {row.get('analysis_count_all_recoverable', 0)} | {row.get('source_record_count', 0)} | {ranked_row.get('coverage_priority', 'P3')} | {row.get('business_status', 'MISSING')} |"
        )
    lines.extend([
        "",
        "## Source completeness evidence",
        "",
        "| Source | Competition | Season | Completion ratio | Completeness |",
        "| --- | --- | --- | ---: | --- |",
    ])
    for source in registry.get("source_completeness", []):
        lines.append(
            f"| {source.get('source')} | {source.get('competition_key')} | {source.get('provider_season_id')} | {source.get('result_completion_ratio')} | {source.get('source_completeness_status')} |"
        )
    lines.extend([
        "",
        "## Current health",
        "",
        f"Current matches `{health.get('current_matches', 0)}`; both history available `{health.get('both_history_available', 0)}`; both current-strength ready `{health.get('both_current_strength_ready', 0)}`; bridge-only `{health.get('bridge_only', 0)}`; stale `{health.get('stale_history', 0)}`.",
        f"P0/P1 ready coverage `{health.get('p0_p1_ready_coverage', 0)}`; P0/P1 ready+bridge coverage `{health.get('p0_p1_ready_plus_bridge_coverage', 0)}`.",
        f"Analysis-weighted strict coverage `{health.get('analysis_weighted_strict_ready', 0)}`; analysis-weighted ready+verified-bridge `{health.get('analysis_weighted_ready_plus_bridge', 0)}`.",
        "",
        "Only bounded schedule metadata is used for project demand. Historical usage before the usage registry start is incomplete.",
    ])
    return "\n".join(lines) + "\n"


def _render_source_gap_plan(registry: Mapping[str, Any]) -> str:
    p01 = [row for row in registry.get("coverage_priority", []) if row.get("coverage_priority") in {"P0", "P1"}]
    source_backed = [row.get("name") for row in p01 if row.get("historical_result_sources")]
    source_missing = [row.get("name") for row in p01 if not row.get("historical_result_sources")]
    return "\n".join([
        "# Phase 2B source gap plan",
        "",
        "## Current source boundary",
        "",
        "OpenFootball remains an offline historical result adapter for pinned native Football.TXT files. The Swedish 2025 Allsvenskan and Superettan captures are PARTIAL (53/240 and 45/240), so their source manifests do not claim complete coverage. The Portuguese 2025/26 capture is COMPLETE.",
        "",
        "Football-Data.co.uk is now an offline historical-result adapter for captured CSV. The Sweden 2026 file has 119/240 completed rows and is IN_PROGRESS; it supplies current Swedish history but not a complete-season claim. The bounded demand expansion also captured BRA, NOR, FIN, JPN and USA source hashes; these source rows do not automatically create reviewed team identities. The project stores source URL, capture time, raw SHA256, parser version and identity status. Raw redistribution is false and internal analysis only is true.",
        "",
        "References: [OpenFootball Europe](https://github.com/openfootball/europe), [Football-Data downloads](https://www.football-data.co.uk/data), [Football-Data Sweden page](https://www.football-data.co.uk/sweden.php), and [Football-Data help/terms](https://www.football-data.co.uk/help_footballdata.php).",
        "",
        "## Next source",
        "",
        "`NEXT_SOURCE_CANDIDATE = API-Football` is planning-only. No API key, network adapter or fake response is enabled in this phase. See [API_FOOTBALL_ADOPTION_PLAN.md](API_FOOTBALL_ADOPTION_PLAN.md).",
        "",
        "No source fleet is enabled. Unknown names remain unresolved, conflicts remain ineligible, and result history is never synthesized from recent-form aggregates, odds, Champion lambda or LLM text.",
        f"Current P0/P1 source-backed demand: `{', '.join(source_backed) or 'none'}`.",
        f"Current P0/P1 demand without a source: `{', '.join(source_missing) or 'none'}`. European cups and national-team gaps remain separate from domestic-league CSV coverage.",
        "",
        "Discovery note: `agent-reach unavailable in current Codex environment`; official source pages were checked directly as the fallback. `grill-me unavailable in current Codex environment` was also recorded by the earlier Phase 2A review.",
    ]) + "\n"


def _render_audit(
    openfootball_manifest: Mapping[str, Any],
    football_data_manifest: Mapping[str, Any],
    health: Mapping[str, Any],
    pilot: Mapping[str, Any],
    football_data_sample: Mapping[str, Any],
    demand_manifest: Mapping[str, Any],
) -> str:
    openfootball_parsed = sum(int(source.get("parsed_result_count") or 0) for source in openfootball_manifest.get("sources", []))
    return "\n".join([
        "# Real historical data audit",
        "",
        f"Bounded audit capture: `{openfootball_manifest.get('captured_at')}`. Scope is current workspace metadata, provider snapshots, pinned source manifests and normalized samples; the full report history was not scanned.",
        "",
        "## Existing current providers",
        "",
        "The existing bounded provider audit found aggregate recent_form snapshots but zero explicit match-level result records. recent_form has aggregate overall/home/away matches, wins, draws, losses, goals for and goals against; it has no reliable per-match date, opponent ID or score. It cannot be expanded into a historical ledger without inventing history.",
        "",
        "## Historical result sources",
        "",
        f"OpenFootball pinned capture: `{openfootball_manifest.get('repository')}@{openfootball_manifest.get('commit_sha')}`; listed/parsed source totals are `240/53`, `240/45`, and `306/306`, for `{openfootball_parsed}` parsed rows. The two completed Swedish files are PARTIAL; Portugal is COMPLETE.",
        f"Football-Data.co.uk capture: `{football_data_manifest.get('source_url')}`; raw SHA256 `{football_data_manifest.get('raw_sha256')}`; the normalized Sweden 2026 sample has `{football_data_sample.get('record_count')}` records and `{football_data_sample.get('eligible_record_count')}` eligible records. The expanded demand manifest contains `{len(demand_manifest.get('sources', []))}` season/file observations for Brazil, Norway, Finland, Japan and USA; the raw CSVs are not committed and their team identity status remains UNVERIFIED.",
        "",
        "## Current buildability",
        "",
        f"Current bounded schedule: `{health.get('current_matches')}` matches; both history available `{health.get('both_history_available')}`; both current-strength ready `{health.get('both_current_strength_ready')}`; bridge-only `{health.get('bridge_only')}`; stale `{health.get('stale_history')}`; source conflicts `{health.get('source_conflict')}`; identity unresolved `{health.get('identity_unresolved')}`.",
        "",
        "The ledger preserves old results as valid historical evidence. Team-strength recency is calculated from the latest match kickoff, not source capture time. The data layer remains shadow-only and `validated_for_model=false`.",
        "Project demand recovery used schedule/task/job metadata only. It recovered the 25 historical analysis jobs without guessing; unresolved schedule rows remain explicitly unresolved. Source record volume is not project usage.",
    ]) + "\n"


def _render_usage_recovery_doc(usage: Mapping[str, Any], ranked: Iterable[Mapping[str, Any]]) -> str:
    job = usage.get("job_recovery", {})
    unresolved = usage.get("unresolved_usage", [])
    lines = [
        "# Competition usage recovery",
        "",
        "This artifact recovers project demand from lightweight metadata indexes. It does not read report bodies or count historical source rows as user demand.",
        "",
        f"Analysis jobs: `{job.get('analysis_job_count', 0)}`; recovered `{job.get('recovered_count', 0)}`; still unresolved `{job.get('still_unresolved_count', 0)}`.",
        f"Deduplicated indexed demand fixtures: `{usage.get('deduplicated_event_count', 0)}`; resolved competition fixtures `{usage.get('resolved_match_count', 0)}`; unresolved competition fixtures `{usage.get('unresolved_match_count', 0)}`.",
        f"Historical usage before registry start: `{usage.get('historical_usage_before_registry_start')}`.",
        "",
        "## Demand windows",
        "",
        "| Window | Resolved competitions | Project fixtures |",
        "| --- | ---: | ---: |",
    ]
    for name in ("last_30d", "last_90d", "all_indexed_recent_production_period"):
        bucket = usage.get("windows", {}).get(name, {})
        lines.append(f"| {name} | {len(bucket.get('competitions', {}))} | {sum(int(row.get('project_analysis_count') or 0) for row in bucket.get('competitions', {}).values())} |")
    lines.extend(["", "## Priority", "", "| Competition | Project demand | Priority | Source records |", "| --- | ---: | --- | ---: |"])
    for row in ranked:
        if row.get("project_usage_count"):
            lines.append(f"| {row.get('name')} | {row.get('project_usage_count')} | {row.get('coverage_priority')} | {row.get('source_record_count', 0)} |")
    lines.extend(["", "## Unresolved evidence", ""])
    for row in unresolved:
        lines.append(f"- `{row.get('home')} vs {row.get('away')}`; raw competition `{row.get('raw_competition')}`; reason `{row.get('reason')}`; sources `{', '.join(row.get('sources') or [])}`.")
    lines.extend(["", "Unresolved demand is not assigned to P0/P1 by name guessing. It remains available for a later reviewed metadata repair.", ""])
    return "\n".join(lines)


def _render_coverage_report(health: Mapping[str, Any], registry: Mapping[str, Any]) -> str:
    lines = [
        "# Team Strength coverage report",
        "",
        f"Current matches: `{health.get('current_matches', 0)}`.",
        f"Both history available: `{health.get('both_history_available', 0)}`; both current-strength ready: `{health.get('both_current_strength_ready', 0)}`; bridge-only: `{health.get('bridge_only', 0)}`; stale: `{health.get('stale_history', 0)}`.",
        f"Ready rate: `{round(health.get('both_current_strength_ready', 0) / health.get('current_matches', 1), 6) if health.get('current_matches') else 0}`; ready+bridge rate: `{round((health.get('both_current_strength_ready', 0) + health.get('bridge_only', 0)) / health.get('current_matches', 1), 6) if health.get('current_matches') else 0}`.",
        f"Analysis-weighted STRICT READY: `{health.get('analysis_weighted_strict_ready', 0)}`; READY+verified BRIDGE: `{health.get('analysis_weighted_ready_plus_bridge', 0)}`.",
        "",
        "## Current matches",
        "",
        "| Match | History available | Current strength ready | Status | Latest history | Age days |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for row in health.get("coverage_by_match", []):
        home = row.get("team_details", {}).get("home", {})
        away = row.get("team_details", {}).get("away", {})
        lines.append(
            f"| {row.get('home')} vs {row.get('away')} | {home.get('history_available')} / {away.get('history_available')} | {home.get('current_strength_ready')} / {away.get('current_strength_ready')} | {row.get('status')} | {home.get('latest_historical_match_date')} / {away.get('latest_historical_match_date')} | {home.get('history_age_days')} / {away.get('history_age_days')} |"
        )
    lines.extend([
        "",
        "This is a shadow data-layer report. It does not create benchmark records and does not alter the Champion.",
        "",
        f"Observed project competitions: `{len(registry.get('observed_competitions', []))}`; source volume is not usage volume.",
    ])
    return "\n".join(lines) + "\n"


def generate() -> dict[str, Any]:
    openfootball_manifest = json.loads(OPENFOOTBALL_MANIFEST_PATH.read_text(encoding="utf-8"))
    football_data_manifest = json.loads(FOOTBALL_DATA_MANIFEST_PATH.read_text(encoding="utf-8"))
    demand_manifest = json.loads(FOOTBALL_DATA_DEMAND_MANIFEST_PATH.read_text(encoding="utf-8")) if FOOTBALL_DATA_DEMAND_MANIFEST_PATH.exists() else {"sources": []}
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))["matches"]
    usage = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    pilot = json.loads(OPENFOOTBALL_PILOT_PATH.read_text(encoding="utf-8"))
    football_data_sample = json.loads(FOOTBALL_DATA_SAMPLE_PATH.read_text(encoding="utf-8"))
    ledger = HistoricalResultLedger(LEDGER_ROOT)
    ledger_records = ledger.records()
    # Existing pre-match snapshots are immutable.  New source capture time is
    # provenance for the source manifest only; it must not rewrite snapshot
    # identity/content for the same target match.
    captured_at = str(football_data_manifest.get("captured_at") or openfootball_manifest["captured_at"])

    health = build_team_strength_health(
        current,
        ledger_records,
        captured_at=captured_at,
        snapshot_revision=SNAPSHOT_REVISION,
    )
    snapshot_builder = TeamStrengthBuilder(
        ledger,
        captured_at=captured_at,
        snapshot_revision=SNAPSHOT_REVISION,
    )
    snapshot_store = PreMatchSnapshotStore(SNAPSHOT_ROOT)
    snapshot_ids: set[str] = set()
    for match in current:
        for team_id in (match.get("home_team_id"), match.get("away_team_id")):
            if not team_id:
                continue
            for window in ("last_5", "last_10", "last_20", "season_to_date"):
                try:
                    snapshot = snapshot_builder.build(
                        str(team_id),
                        target_kickoff=str(match["kickoff_at"]),
                        window_type=window,
                        competition_id=match.get("competition_id"),
                        season_id=match.get("season_id"),
                        target_match_id=str(match.get("id")),
                        entity_type=str(match.get("entity_type") or "club"),
                        bridge_context=match.get("bridge_context"),
                    )
                except (TypeError, ValueError):
                    continue
                snapshot_ids.add(_put_snapshot_without_rewriting(snapshot_store, snapshot))
    health["pre_match_snapshot_count"] = len(snapshot_ids)
    health["pre_match_snapshot_root"] = ".cache/football_data/team_strength_snapshots.duckdb"
    health["snapshot_revision"] = SNAPSHOT_REVISION

    source_observations = _source_observations([openfootball_manifest, football_data_manifest, demand_manifest])
    observed = _usage_observations(usage, current)
    observed.extend(source_observations)
    registry = build_coverage_registry(
        observed=observed,
        entries=_base_entries(captured_at),
        generated_at=captured_at,
    )
    _apply_source_metadata(registry, source_observations)
    for row in registry["competitions"]:
        competition_id = row.get("canonical_competition_id")
        current_row = health["coverage_by_competition"].get(competition_id, {})
        current_count = int(current_row.get("current_matches") or 0)
        row["history_available_coverage"] = round(int(current_row.get("both_history_available") or 0) / current_count, 6) if current_count else None
        row["current_strength_coverage"] = round(int(current_row.get("both_current_strength_ready") or 0) / current_count, 6) if current_count else None
        if row.get("result_coverage") == "MISSING":
            row["coverage_status"] = "MISSING"
        elif row.get("result_coverage") == "PARTIAL" or row.get("current_season_coverage") in {"PARTIAL", "MISSING"}:
            row["coverage_status"] = "PARTIAL"
        else:
            row["coverage_status"] = row.get("result_coverage", "UNVERIFIED")
        row["business_status"] = _business_status(row, current_row)
        row["history_recency_status"] = (
            "CURRENT" if current_row.get("both_current_strength_ready") == current_count and current_count else
            "BRIDGE_ONLY" if current_row.get("bridge_only") == current_count and current_count else
            "STALE" if current_row.get("stale_history") else
            "UNKNOWN"
        )
    ranked = rank_coverage_gaps(registry["competitions"])
    weighted = analysis_weighted_coverage(ranked)
    ranked_by_key = {row.get("competition_key"): row for row in ranked}
    for row in registry["competitions"]:
        row["coverage_priority"] = ranked_by_key.get(row.get("competition_key"), {}).get("coverage_priority", "P3")
    registry["analysis_weighted_coverage"] = weighted
    registry["coverage_priority"] = ranked
    registry["source_completeness"] = source_observations
    registry["usage_registry_start"] = usage.get("registry_started_at")
    registry["historical_usage_before_registry_start"] = usage.get("historical_usage_before_registry_start")
    p01 = [row for row in ranked if row.get("coverage_priority") in {"P0", "P1"}]
    p01_current = sum(int(row.get("current_match_count") or 0) for row in p01)
    p01_ready = 0
    p01_bridge = 0
    for row in p01:
        health_row = health["coverage_by_competition"].get(row.get("canonical_competition_id") or row.get("competition_key"), {})
        p01_ready += int(health_row.get("both_current_strength_ready") or 0)
        p01_bridge += int(health_row.get("bridge_only") or 0)
    health["p0_p1_current_matches"] = p01_current
    health["p0_p1_both_current_strength_ready"] = p01_ready
    health["p0_p1_bridge_only"] = p01_bridge
    health["p0_p1_ready_coverage"] = round(p01_ready / p01_current, 6) if p01_current else 0
    health["p0_p1_ready_plus_bridge_coverage"] = round((p01_ready + p01_bridge) / p01_current, 6) if p01_current else 0
    health["analysis_weighted_strict_ready"] = weighted["analysis_weighted_strict_ready"]
    health["analysis_weighted_ready_plus_bridge"] = weighted["analysis_weighted_ready_plus_bridge"]
    health["analysis_weight"] = weighted["analysis_weight"]
    health["strict_ready_coverage"] = weighted["analysis_weighted_strict_ready"]
    health["ready_plus_verified_bridge_coverage"] = weighted["analysis_weighted_ready_plus_bridge"]
    _json(COVERAGE_PATH, registry)
    _json(GAP_PATH, {"generated_at": captured_at, "gaps": ranked})
    _json(HEALTH_PATH, health)

    pilot_summary = {"generated_at": captured_at, "teams": {}}
    for coverage in health["coverage_by_match"]:
        for side in ("home", "away"):
            detail = coverage.get("team_details", {}).get(side, {})
            team_id = detail.get("canonical_team_id")
            if team_id:
                pilot_summary["teams"][team_id] = detail
    _json(PILOT_SUMMARY_PATH, pilot_summary)

    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    (DOCS_ROOT / "REAL_DATA_AUDIT.md").write_text(_render_audit(openfootball_manifest, football_data_manifest, health, pilot, football_data_sample, demand_manifest), encoding="utf-8")
    (DOCS_ROOT / "COMPETITION_COVERAGE.md").write_text(_render_coverage_doc(registry, ranked, health), encoding="utf-8")
    (DOCS_ROOT / "SOURCE_GAP_PLAN.md").write_text(_render_source_gap_plan(registry), encoding="utf-8")
    (DOCS_ROOT / "COMPETITION_USAGE_RECOVERY.md").write_text(_render_usage_recovery_doc(usage, ranked), encoding="utf-8")
    (DOCS_ROOT / "COVERAGE_REPORT.md").write_text(_render_coverage_report(health, registry), encoding="utf-8")
    return {"registry": registry, "health": health, "ranked": ranked}


if __name__ == "__main__":
    result = generate()
    print(json.dumps({
        "observed_competitions": len(result["registry"]["observed_competitions"]),
        "current_matches": result["health"]["current_matches"],
        "both_history_available": result["health"]["both_history_available"],
        "both_current_strength_ready": result["health"]["both_current_strength_ready"],
        "p0": sum(row.get("coverage_priority") == "P0" for row in result["ranked"]),
    }))
