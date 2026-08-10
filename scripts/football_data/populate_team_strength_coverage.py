"""Generate bounded Phase 2B coverage artifacts from normalized pilot evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .coverage import build_coverage_registry, rank_coverage_gaps
from .health import build_team_strength_health
from .historical_results import HistoricalResultLedger
from .team_strength import PreMatchSnapshotStore, TeamStrengthBuilder


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "football_data" / "openfootball" / "source_manifest.json"
CURRENT_PATH = ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
PILOT_PATH = ROOT / "data" / "football_data" / "historical_result_samples" / "openfootball_pilot.json"
LEDGER_ROOT = ROOT / "data" / "football_data" / "historical_result_ledger"
COVERAGE_PATH = ROOT / "data" / "football_data" / "competition_coverage_registry.json"
GAP_PATH = ROOT / "data" / "football_data" / "coverage_gap_ranking.json"
HEALTH_PATH = ROOT / "data" / "football_data" / "team_strength_health.json"
PILOT_SUMMARY_PATH = ROOT / "data" / "football_data" / "team_strength_pilot_summary.json"
SNAPSHOT_ROOT = ROOT / "data" / "football_data" / "team_strength_snapshots"
DOCS_ROOT = ROOT / "docs" / "team-strength"


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
    ("brazil-serie-a", "Brasileirão", "Brazil", "club", "league"),
    ("argentina-primera-division", "Argentine Primera", "Argentina", "club", "league"),
    ("uefa-champions-league", "Champions League", "Europe", "club", "international_club"),
    ("uefa-europa-league", "Europa League", "Europe", "club", "international_club"),
    ("uefa-conference-league", "Conference League", "Europe", "club", "international_club"),
    ("conmebol-copa-libertadores", "Copa Libertadores", "South America", "club", "international_club"),
    ("conmebol-copa-sudamericana", "Copa Sudamericana", "South America", "club", "international_club"),
    ("fifa-world-cup", "World Cup", "International", "national_team", "national_team"),
    ("uefa-european-championship", "UEFA Euro", "Europe", "national_team", "national_team"),
    ("conmebol-copa-america", "Copa América", "South America", "national_team", "national_team"),
    ("fifa-world-cup-qualifiers", "World Cup Qualifiers", "International", "national_team", "national_team"),
]


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _base_entries(captured_at: str) -> list[dict[str, Any]]:
    entries = []
    for key, name, country, entity_type, competition_type in KNOWN_COMPETITIONS:
        entries.append(
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
                "notes": ["No reviewed historical result adapter/source in this phase."],
            }
        )
    reviewed = {
        "sweden-allsvenskan": {
            "canonical_competition_id": "competition:sweden-allsvenskan",
            "historical_result_sources": ["openfootball"],
            "current_match_sources": ["sporttery"],
            "result_coverage": "SUPPORTED",
            "current_season_coverage": "PARTIAL",
            "team_identity_coverage": 1.0,
            "last_verified_at": captured_at,
            "notes": ["2025 source results are available; current 2026 schedule coverage is separate and not a live OpenFootball feed."],
        },
        "sweden-superettan": {
            "canonical_competition_id": "competition:sweden-superettan",
            "historical_result_sources": ["openfootball"],
            "current_match_sources": [],
            "result_coverage": "SUPPORTED",
            "current_season_coverage": "MISSING",
            "team_identity_coverage": 1.0,
            "last_verified_at": captured_at,
            "notes": ["2025 source results are available; no current scheduled match was observed in the bounded audit."],
        },
        "portugal-primeira-liga": {
            "canonical_competition_id": "competition:portugal-primeira-liga",
            "historical_result_sources": ["openfootball"],
            "current_match_sources": ["sporttery"],
            "result_coverage": "SUPPORTED",
            "current_season_coverage": "PARTIAL",
            "team_identity_coverage": 1.0,
            "last_verified_at": captured_at,
            "notes": ["2025/26 source results are available; current 2026/27 schedule coverage is separate and not a live OpenFootball feed."],
        },
    }
    for entry in entries:
        entry.update(reviewed.get(entry["competition_key"], {}))
    return entries


def _render_coverage_doc(registry: dict[str, Any], ranked: list[dict[str, Any]], health: dict[str, Any]) -> str:
    counts = {status: sum(row.get("coverage_status") == status for row in registry["competitions"]) for status in ("SUPPORTED", "PARTIAL", "MISSING", "UNVERIFIED")}
    lines = [
        "# Competition coverage",
        "",
        f"Generated from bounded current workspace evidence and the OpenFootball pilot manifest at `{registry['generated_at']}`.",
        "This is a data-layer coverage report, not a prediction-quality report. A status is never promoted by a raw league name.",
        "",
        "## Status counts",
        "",
        f"`SUPPORTED` {counts['SUPPORTED']} · `PARTIAL` {counts['PARTIAL']} · `MISSING` {counts['MISSING']} · `UNVERIFIED` {counts['UNVERIFIED']}",
        "",
        "## Registry",
        "",
        "| Competition | Entity | Overall | Historical result | Current-season | Team identity | Sources | Priority |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    rank_by_key = {row.get("competition_key"): row for row in ranked}
    for row in registry["competitions"]:
        ranked_row = rank_by_key.get(row["competition_key"], {})
        sources = ", ".join(row.get("historical_result_sources") or []) or "—"
        lines.append(f"| {row['name']} | {row['entity_type']} | {row.get('coverage_status', 'UNVERIFIED')} | {row['result_coverage']} | {row['current_season_coverage']} | {row.get('team_identity_coverage') if row.get('team_identity_coverage') is not None else '—'} | {sources} | {ranked_row.get('coverage_priority', 'P3')} |")
    lines.extend([
        "",
        "## Observed competitions",
        "",
        "| Key | Raw names | Observed records/matches | Current matches |",
        "| --- | --- | ---: | ---: |",
    ])
    for row in registry["observed_competitions"]:
        lines.append(f"| {row['competition_key']} | {' / '.join(row['raw_names']) or '—'} | {row['observed_count']} | {row['current_match_count']} |")
    lines.extend([
        "",
        "## Current bounded health",
        "",
        f"Current matches: `{health['current_matches']}`; both sides evaluable: `{health['both_teams_evaluable']}`; one side: `{health['one_team_evaluable']}`; neither: `{health['neither_evaluable']}`.",
        "",
        "Only the three observed current schedule rows are used for this health calculation. No unsupported competition is presented as covered.",
    ])
    return "\n".join(lines) + "\n"


def _render_source_gap_plan(registry: dict[str, Any]) -> str:
    supported = [row["name"] for row in registry["competitions"] if row.get("result_coverage") == "SUPPORTED"]
    return "\n".join([
        "# Phase 2B source gap plan",
        "",
        "## Adopted source",
        "",
        f"OpenFootball is adopted as an offline historical result adapter for the explicitly captured files. Current supported historical competition contexts are: {', '.join(supported)}.",
        "Official references: [openfootball/europe](https://github.com/openfootball/europe), [football.json schema/examples](https://github.com/openfootball/football.json), and [OpenFootball CC0 license](https://github.com/openfootball/europe/blob/master/LICENSE.md).",
        "The upstream `openfootball/europe` repository uses native Football.TXT files in this capture. The adapter records repository, commit SHA, source file, raw SHA256, capture time, license, parser version, and team verification evidence.",
        "",
        "OpenFootball does not solve current all-competition coverage, stable provider team IDs, xG, lineups, injuries, or live schedules. Its public-domain/CC0 data is useful for reproducible result history only.",
        "",
        "## Next source candidate",
        "",
        "`NEXT_SOURCE_CANDIDATE = football-data.org API` — DEFER.",
        "Reference: [football-data.org quickstart](https://www.football-data.org/documentation/quickstart), [API reference](https://www.football-data.org/documentation/api), and [API policies](https://docs.football-data.org/general/v4/policies.html).",
        "It exposes structured competition, season, team, match, UTC date, status, and score resources, but the project has no approved token/plan or completed terms/commercial-use review in this phase. CI must remain offline.",
        "",
        "`football-data.co.uk` was also reviewed as a candidate. Its [downloadable historical results](https://www.football-data.co.uk/data) are simple and broad, but [terms/help](https://www.football-data.co.uk/help_footballdata.php), lack of stable provider IDs, and name-only identity make it a later review candidate rather than an automatic second adapter.",
        "",
        "## Gap policy",
        "",
        "No scraper fleet is enabled. Unknown competitions and names remain unresolved; source conflicts remain ineligible; result history is not synthesized from recent-form aggregates, odds, Champion lambda, or LLM text.",
        "",
        "Discovery note: `grill-me unavailable in current Codex environment` and `agent-reach unavailable in current Codex environment`; official source pages were checked directly as a fallback and the adapter remains offline in CI.",
    ]) + "\n"


def _render_audit(manifest: dict[str, Any], health: dict[str, Any], pilot: dict[str, Any], registry: dict[str, Any]) -> str:
    parsed = sum(int(source.get("parsed_result_count") or 0) for source in manifest.get("sources", []))
    return "\n".join([
        "# Real historical data audit",
        "",
        f"Audit/capture time: `{manifest['captured_at']}`. Scope is limited to the current match workspace, latest schedule metadata, existing provider capability audit, the OpenFootball manifest, and the bounded normalized pilot sample.",
        "",
        "## Existing Nowscore / 500 capability",
        "",
        "The existing scoped provider audit found 2,652 JSON snapshots: 366 Nowscore-named, 231 500 deep, 442 500 trade, 396 aggregate recent-form, and 393 with provider team IDs. It found 0 explicit match-level result records. These are snapshot-file observations, not distinct-match counts.",
        "",
        "The available `recent_form` shape is aggregate overall/home/away data with matches, wins, draws, losses, goals for and goals against. It lacks individual match dates, opponents, opponent IDs, and scores, so it cannot be expanded into a result ledger without inventing history.",
        "",
        "## OpenFootball pilot",
        "",
        f"The pinned `{manifest['repository']}@{manifest['commit_sha']}` capture contains {parsed} parsed result rows across three source files. The bounded pilot stores {pilot['record_count']} normalized records involving the six current pilot teams; {pilot['eligible_record_count']} are eligible for Team Strength.",
        "",
        "Every eligible record has canonical home/away IDs from explicit source-context identity evidence, a date/time, score, competition, season, source fact time, reliable provenance, and no source conflict. OpenFootball source files do not provide provider team IDs; that absence is recorded rather than fabricated.",
        "",
        "## Current buildability",
        "",
        f"Current bounded schedule: {health['current_matches']} matches; both teams evaluable: {health['both_teams_evaluable']}; one side: {health['one_team_evaluable']}; neither: {health['neither_evaluable']}. Source conflicts: {health['source_conflict']}; unresolved identity: {health['identity_unresolved']}.",
        f"Immutable pre-match Team Strength snapshots persisted: {health.get('pre_match_snapshot_count', 0)}; they remain data-layer-only.",
        "",
        "Team Strength uses result history only. xG, lineups, injuries, Elo, odds, and Champion expected goals are not used as substitutes.",
        "",
        "The normalized sample is a shadow data layer and remains `validated_for_model=false`; the Champion does not read it.",
    ]) + "\n"


def generate() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))["matches"]
    pilot = json.loads(PILOT_PATH.read_text(encoding="utf-8"))
    ledger_records = HistoricalResultLedger(LEDGER_ROOT).records()
    health = build_team_strength_health(current, ledger_records, captured_at=manifest["captured_at"])
    snapshot_builder = TeamStrengthBuilder(ledger_records, captured_at=manifest["captured_at"])
    snapshot_store = PreMatchSnapshotStore(SNAPSHOT_ROOT)
    snapshot_count = 0
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
                    )
                except (TypeError, ValueError):
                    continue
                snapshot_store.put(snapshot)
                snapshot_count += 1
    health["pre_match_snapshot_count"] = snapshot_count
    health["pre_match_snapshot_root"] = "data/football_data/team_strength_snapshots"
    observed = []
    current_key_by_competition = {}
    for row in current:
        key = str(row.get("competition_id") or "").removeprefix("competition:") or str(row.get("league") or "unresolved")
        current_key_by_competition[str(row.get("competition_id"))] = key
        observed.append({"competition_key": key, "raw_name": row.get("league"), "current_match_count": 1, "observed_count": 1, "provider_competition_id": None})
    for source in manifest.get("sources", []):
        observed.append({"competition_key": source["competition_key"], "raw_name": source["provider_competition_name"], "observed_count": source.get("parsed_result_count", 0), "current_match_count": 0, "provider_competition_id": source["provider_competition_id"]})
    registry = build_coverage_registry(observed=observed, entries=_base_entries(manifest["captured_at"]), generated_at=manifest["captured_at"])
    for row in registry["competitions"]:
        competition_id = row.get("canonical_competition_id")
        current_row = health["coverage_by_competition"].get(competition_id, {})
        current_count = int(current_row.get("current_matches") or 0)
        row["current_strength_coverage"] = round(int(current_row.get("both_teams_evaluable") or 0) / current_count, 6) if current_count else None
        row["coverage_status"] = "PARTIAL" if row.get("result_coverage") == "SUPPORTED" and row.get("current_season_coverage") == "PARTIAL" else row.get("result_coverage", "UNVERIFIED")
    ranked = rank_coverage_gaps(registry["competitions"])
    registry["coverage_priority"] = ranked
    _json(COVERAGE_PATH, registry)
    _json(GAP_PATH, {"generated_at": manifest["captured_at"], "gaps": ranked})
    _json(HEALTH_PATH, health)
    pilot_summary = {
        "generated_at": manifest["captured_at"],
        "teams": {},
    }
    for coverage in health["coverage_by_match"]:
        for side in ("home", "away"):
            detail = coverage.get("team_details", {}).get(side, {})
            team_id = detail.get("canonical_team_id")
            if team_id:
                pilot_summary["teams"][team_id] = detail
    _json(PILOT_SUMMARY_PATH, pilot_summary)
    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    (DOCS_ROOT / "REAL_DATA_AUDIT.md").write_text(_render_audit(manifest, health, pilot, registry), encoding="utf-8")
    (DOCS_ROOT / "COMPETITION_COVERAGE.md").write_text(_render_coverage_doc(registry, ranked, health), encoding="utf-8")
    (DOCS_ROOT / "SOURCE_GAP_PLAN.md").write_text(_render_source_gap_plan(registry), encoding="utf-8")
    (DOCS_ROOT / "COVERAGE_REPORT.md").write_text(
        "\n".join([
            "# Team Strength coverage report",
            "",
            f"Current bounded matches: `{health['current_matches']}`.",
            f"Both teams evaluable: `{health['both_teams_evaluable']}`; one side: `{health['one_team_evaluable']}`; neither: `{health['neither_evaluable']}`.",
            f"Overall bounded coverage: `{round(health['both_teams_evaluable'] / health['current_matches'], 6) if health['current_matches'] else 0}`.",
            "",
            "The report is generated from the normalized historical ledger and current-match identity evidence. It is shadow data only and does not alter the Champion.",
            "",
            "See [COMPETITION_COVERAGE.md](COMPETITION_COVERAGE.md) for the competition-by-competition registry.",
        ]) + "\n",
        encoding="utf-8",
    )
    return {"registry": registry, "health": health, "ranked": ranked}


if __name__ == "__main__":
    result = generate()
    print(json.dumps({
        "observed_competitions": len(result["registry"]["observed_competitions"]),
        "current_matches": result["health"]["current_matches"],
        "both_teams_evaluable": result["health"]["both_teams_evaluable"],
        "p0": sum(row.get("coverage_priority") == "P0" for row in result["ranked"]),
    }))
