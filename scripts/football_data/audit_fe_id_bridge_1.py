"""Read-only, target-only audit for FE-ID-BRIDGE-1."""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

try:
    from .data_home import historical_results_path
    from .storage import HistoricalResultStore
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.football_data.data_home import historical_results_path
    from scripts.football_data.storage import HistoricalResultStore


ROOT = Path(__file__).resolve().parents[2]
MATCH_ID = "500-1362754"
PREDICTION_ID = "FBOS-PRED-a4787da3359e9462042cb287"
MATCH_KEY = "FBOS-202608292100-21c3ea757c"
NOWSCORE_MATCH_ID = "2912253"
HOME_PROVIDER_ID = "417"
AWAY_PROVIDER_ID = "2088"
HOME_ID = "team:sweden:if-elfsborg"
AWAY_ID = "team:sweden:degerfors-if"
COMPETITION_ID = "competition:sweden-allsvenskan"
ANALYSIS_JS_SHA256 = "370f1bfc3d1a8c61566f7c8e740515fb7806eb6a58c11c23d1f1220a2ee33b19"

UNIVERSE = "data/prediction_universe/2026-08-29.json"
SCHEDULE = "data/schedule_updates/20260829_032017/20260829_032017_sporttery_2026-08-29.json"
PROSPECTIVE = f"data/prospective/football_evidence/{PREDICTION_ID}.json"
FROZEN = f"data/model_governance/predictions/{PREDICTION_ID}.json"
SNAPSHOT = "data/model_governance/input_snapshots/d1e88cba5ba1918235e2b2a2c90c3c6ecdc2335af791240efa3f8d80d49155ce.json"
CURRENT_IDENTITY = "data/football_data/current_match_identity_evidence.json"
PROJECT_CROSSWALK = "data/football_data/verified_project_provider_crosswalk.json"
OPENFOOTBALL_IDENTITY = "data/football_data/openfootball/identity_evidence.json"
FOOTBALL_DATA_IDENTITY = "data/football_data/football_data_uk/identity_evidence.json"
HISTORICAL_SAMPLE = "data/football_data/historical_result_samples/football_data_uk_sweden_2026.json"


def _read(root: Path, relative_path: str) -> dict[str, Any]:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def _sha256(root: Path, relative_path: str) -> str:
    return hashlib.sha256((root / relative_path).read_bytes()).hexdigest()


def _time(value: Any) -> datetime:
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _unique(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        result.setdefault(str(row.get("canonical_match_id") or f"row-{index}"), dict(row))
    return list(result.values())


def _component(rows: Iterable[Mapping[str, Any]], start: str) -> set[str]:
    graph: dict[str, set[str]] = {}
    for row in rows:
        home, away = str(row.get("home_team_id") or ""), str(row.get("away_team_id") or "")
        if home and away:
            graph.setdefault(home, set()).add(away)
            graph.setdefault(away, set()).add(home)
    if start not in graph:
        return set()
    seen, pending = {start}, deque([start])
    while pending:
        node = pending.popleft()
        for neighbour in sorted(graph[node] - seen):
            seen.add(neighbour)
            pending.append(neighbour)
    return seen


def _history_summary(team_id: str, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    team_rows = [row for row in rows if team_id in (row.get("home_team_id"), row.get("away_team_id"))]
    kickoffs = sorted(_time(row["kickoff_at"]) for row in team_rows)
    return {
        "canonical_team_id": team_id,
        "usable_match_count": len(team_rows),
        "kickoff_min": kickoffs[0].isoformat().replace("+00:00", "Z") if kickoffs else None,
        "kickoff_max": kickoffs[-1].isoformat().replace("+00:00", "Z") if kickoffs else None,
        "providers": dict(sorted(Counter(str(row.get("provider") or "") for row in team_rows).items())),
    }


def _verify_historical_identity_sources(root: Path) -> None:
    expected = {HOME_ID: {"IF Elfsborg", "Elfsborg"}, AWAY_ID: {"Degerfors IF", "Degerfors"}}
    openfootball = _read(root, OPENFOOTBALL_IDENTITY).get("teams", [])
    football_data = _read(root, FOOTBALL_DATA_IDENTITY).get("mappings", [])
    for canonical_id, names in expected.items():
        _require(
            sum(row.get("canonical_team_id") == canonical_id and row.get("provider_team_name") in names and row.get("verified") is True for row in openfootball) == 1,
            f"OpenFootball identity evidence missing for {canonical_id}",
        )
        _require(
            sum(row.get("canonical_team_id") == canonical_id and row.get("provider_team_name") in names and row.get("verified") is True for row in football_data) == 1,
            f"football-data.co.uk identity evidence missing for {canonical_id}",
        )


def build_target_evidence(*, root: Path = ROOT, historical_path: Path | None = None) -> dict[str, Any]:
    root = Path(root)
    universe = _read(root, UNIVERSE)
    fixtures = [row for row in universe.get("fixtures", []) if row.get("matchId") == MATCH_ID]
    _require(len(fixtures) == 1, "target fixture must occur exactly once")
    fixture = fixtures[0]
    _require(
        fixture.get("nowscoreId") == int(NOWSCORE_MATCH_ID)
        and fixture.get("nowscoreMatchStatus") == "EXACT_MATCH"
        and fixture.get("nowscoreMatchConfidence") == 1.0,
        "target fixture lacks exact Nowscore binding",
    )
    target_kickoff = _time(f"{fixture['matchDate']}T{fixture['matchTime']}:00+08:00").astimezone(timezone.utc)
    cutoff_text = target_kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    schedule = _read(root, SCHEDULE)
    schedule_rows = [row for row in schedule.get("matches", []) if row.get("matchId") == MATCH_ID]
    _require(len(schedule_rows) == 1, "target schedule source must contain exactly one match")
    schedule_row = schedule_rows[0]
    _require(
        all(schedule_row.get(field) == fixture.get(field) for field in ("matchId", "businessDate", "matchDate", "matchTime", "league", "homeTeam", "awayTeam", "nowscoreId")),
        "schedule source does not match the exact target fixture",
    )

    identity = _read(root, CURRENT_IDENTITY)
    identity_rows = [row for row in identity.get("matches", []) if row.get("id") == MATCH_ID]
    _require(len(identity_rows) == 1 and identity_rows[0].get("verified") is True, "target identity is not uniquely verified")
    target_identity = identity_rows[0]
    _require(
        target_identity.get("provider") == "sporttery"
        and target_identity.get("provider_match_id") == MATCH_ID
        and target_identity.get("nowscore_match_id") == NOWSCORE_MATCH_ID
        and target_identity.get("home") == fixture.get("homeTeam")
        and target_identity.get("away") == fixture.get("awayTeam")
        and target_identity.get("competition_id") == COMPETITION_ID
        and target_identity.get("provider_team_ids") == {"home": HOME_PROVIDER_ID, "away": AWAY_PROVIDER_ID}
        and target_identity.get("home_team_id") == HOME_ID
        and target_identity.get("away_team_id") == AWAY_ID
        and any(ANALYSIS_JS_SHA256 in str(item) for item in target_identity.get("verification_evidence", [])),
        "target identity does not retain the exact provider-ID/source chain",
    )

    crosswalk = _read(root, PROJECT_CROSSWALK)
    mapping_by_id = {
        str(row.get("provider_team_id")): row
        for row in crosswalk.get("mappings", [])
        if row.get("provider") == "nowscore" and str(row.get("provider_team_id")) in {HOME_PROVIDER_ID, AWAY_PROVIDER_ID}
    }
    _require(set(mapping_by_id) == {HOME_PROVIDER_ID, AWAY_PROVIDER_ID}, "target provider IDs lack two unique crosswalk rows")
    for provider_id, canonical_id, side in ((HOME_PROVIDER_ID, HOME_ID, "home"), (AWAY_PROVIDER_ID, AWAY_ID, "away")):
        row = mapping_by_id[provider_id]
        _require(
            row.get("verified") is True
            and row.get("canonical_team_id") == canonical_id
            and row.get("competition") == COMPETITION_ID
            and row.get("provider_team_name") == fixture.get(f"{side}Team")
            and row.get("source_ref_count") == len(row.get("source_refs", [])),
            f"crosswalk row {provider_id} is not exact and competition-scoped",
        )

    prospective = _read(root, PROSPECTIVE)
    _require(
        all(prospective.get(key) == value for key, value in (("prediction_id", PREDICTION_ID), ("match_id", MATCH_ID), ("match_key", MATCH_KEY), ("nowscore_id", int(NOWSCORE_MATCH_ID)), ("home", fixture.get("homeTeam")), ("away", fixture.get("awayTeam")))),
        "prospective evidence does not match the target fixture",
    )
    home_recent, away_recent = prospective["recent_matches"]["home_team"], prospective["recent_matches"]["away_team"]
    home_id_hits = sum(HOME_PROVIDER_ID in {str(row.get("home_team_id")), str(row.get("away_team_id"))} for row in home_recent)
    away_id_hits = sum(AWAY_PROVIDER_ID in {str(row.get("home_team_id")), str(row.get("away_team_id"))} for row in away_recent)
    source_cutoff = _time(prospective["source_cutoff_at"])

    frozen = _read(root, FROZEN)
    frozen_refs = {str(item.get("url") or item.get("path")) for item in frozen.get("source_references", []) if isinstance(item, Mapping)}
    snapshot = _read(root, SNAPSHOT)
    _require(
        snapshot.get("source_hashes", {}).get("data/source_cache/nowscore/raw/2912253_analysis.js") == ANALYSIS_JS_SHA256
        and "https://live.nowscore.com/analysisJs/data2912253.js" in frozen_refs,
        "frozen provider source hash/reference is missing",
    )
    _verify_historical_identity_sources(root)

    store = HistoricalResultStore(historical_path or historical_results_path())
    home_rows = _unique(
        row for row in store.query_before_kickoff(HOME_ID, cutoff_text, competition_id=COMPETITION_ID, eligible_only=True)
        if row.get("source_conflict") is False and row.get("duplicate_status") == "unique" and _time(row["kickoff_at"]) < target_kickoff
    )
    away_rows = _unique(
        row for row in store.query_before_kickoff(AWAY_ID, cutoff_text, competition_id=COMPETITION_ID, eligible_only=True)
        if row.get("source_conflict") is False and row.get("duplicate_status") == "unique" and _time(row["kickoff_at"]) < target_kickoff
    )
    history_rows = _unique([*home_rows, *away_rows])
    component = _component(history_rows, HOME_ID)
    shared_matches = sorted(
        str(row["canonical_match_id"])
        for row in history_rows
        if {row.get("home_team_id"), row.get("away_team_id")} == {HOME_ID, AWAY_ID}
    )
    checks = {
        "current_fixture_exact_nowscore_binding": True,
        "home_provider_id_exactly_verified": len(home_recent) == home_id_hits == 30,
        "away_provider_id_exactly_verified": len(away_recent) == away_id_hits == 30,
        "frozen_nowscore_analysis_source_hash_present": True,
        "source_cutoff_before_target_kickoff": source_cutoff < target_kickoff,
        "home_canonical_id_present": target_identity["home_team_id"] == HOME_ID,
        "away_canonical_id_present": target_identity["away_team_id"] == AWAY_ID,
        "home_pre_kickoff_history_present": bool(home_rows),
        "away_pre_kickoff_history_present": bool(away_rows),
        "same_allsvenskan_historical_network": AWAY_ID in component,
        "no_post_kickoff_history_used": all(_time(row["kickoff_at"]) < target_kickoff for row in history_rows),
    }
    source_paths = [UNIVERSE, SCHEDULE, PROSPECTIVE, FROZEN, SNAPSHOT, CURRENT_IDENTITY, PROJECT_CROSSWALK, OPENFOOTBALL_IDENTITY, FOOTBALL_DATA_IDENTITY, HISTORICAL_SAMPLE]
    return {
        "contract_version": "fe_id_bridge_audit.v1",
        "task": "FE-ID-BRIDGE-1",
        "status": "READY_FOR_ACCEPTANCE" if all(checks.values()) else "BLOCKED",
        "scope": {"fixture_count": 1, "fixture_id": MATCH_ID, "competition_id": COMPETITION_ID, "historical_query_scope": "target canonical teams only; no other fixtures processed"},
        "fixture": {"match_id": MATCH_ID, "match_key": MATCH_KEY, "home": fixture.get("homeTeam"), "away": fixture.get("awayTeam"), "kickoff_at": f"{fixture['matchDate']}T{fixture['matchTime']}:00+08:00", "target_kickoff_utc": cutoff_text, "nowscore_match_id": NOWSCORE_MATCH_ID},
        "provider_identity": {
            "provider": "nowscore",
            "exact_fixture_source": "sporttery fixture + Nowscore match binding",
            "home": {"provider_team_id": HOME_PROVIDER_ID, "provider_team_name": fixture.get("homeTeam"), "canonical_team_id": HOME_ID, "crosswalk_method": mapping_by_id[HOME_PROVIDER_ID]["resolution_method"]},
            "away": {"provider_team_id": AWAY_PROVIDER_ID, "provider_team_name": fixture.get("awayTeam"), "canonical_team_id": AWAY_ID, "crosswalk_method": mapping_by_id[AWAY_PROVIDER_ID]["resolution_method"]},
            "crosswalk_mapping_count": 2,
            "current_identity_resolution_method": target_identity["resolution_method"],
            "current_identity_source_references": target_identity.get("source_references", []),
        },
        "provider_evidence": {
            "prediction_id": PREDICTION_ID, "captured_at": prospective.get("evidence_captured_at"), "source_cutoff_at": prospective.get("source_cutoff_at"),
            "home_recent_rows": len(home_recent), "home_provider_id_occurrences": home_id_hits, "away_recent_rows": len(away_recent), "away_provider_id_occurrences": away_id_hits,
            "analysis_js_sha256": ANALYSIS_JS_SHA256, "analysis_js_selectors": ["teamNames[TeamId=417]", "teamNames[TeamId=2088]"],
            "frozen_match_identity": frozen.get("match_identity"),
            "retained_source_hashes": {path: snapshot.get("source_hashes", {}).get(path) for path in ("data/source_cache/nowscore/raw/2912253_3in1.html", "data/source_cache/nowscore/raw/2912253_analysis.js")},
        },
        "historical_validation": {
            "store": "FOOTBALL_DATA_HOME/historical_results.duckdb", "dataset_digest": store.dataset_digest(), "target_kickoff_exclusive_cutoff": cutoff_text,
            "home": _history_summary(HOME_ID, home_rows), "away": _history_summary(AWAY_ID, away_rows), "unique_target_team_history_rows": len(history_rows),
            "network_component_team_count": len(component), "same_network": AWAY_ID in component, "shared_historical_match_ids": shared_matches, "post_kickoff_rows_used": 0,
        },
        "source_hashes": {path: _sha256(root, path) for path in source_paths},
        "checks": checks,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _render_markdown(report: Mapping[str, Any]) -> str:
    fixture, provider, evidence, history = report["fixture"], report["provider_identity"], report["provider_evidence"], report["historical_validation"]
    lines = [
        "# FE-ID-BRIDGE-1 — Swedish Current-to-History Identity Bridge", "", f"**Status:** `{report['status']}`", "",
        "## Scope", "", f"Only fixture `{fixture['match_id']}` (`{fixture['match_key']}`) was audited.", f"Target kickoff: `{fixture['kickoff_at']}`; exclusive UTC cutoff: `{fixture['target_kickoff_utc']}`.", "No provider, historical import, model, Champion, production, or frozen prediction was changed.", "",
        "## Exact provider identity evidence", "", f"Nowscore match `{fixture['nowscore_match_id']}` is bound by the exact Sporttery/Prediction Universe fixture.", f"Prospective evidence records home ID `{provider['home']['provider_team_id']}` in {evidence['home_provider_id_occurrences']}/{evidence['home_recent_rows']} home-side rows and away ID `{provider['away']['provider_team_id']}` in {evidence['away_provider_id_occurrences']}/{evidence['away_recent_rows']} away-side rows.", f"Frozen Nowscore analysis source SHA-256: `{evidence['analysis_js_sha256']}`; selectors: `teamNames[TeamId=417]`, `teamNames[TeamId=2088]`.", "",
        "| side | provider ID | canonical team ID | mapping |", "|---|---:|---|---|", f"| home | `{provider['home']['provider_team_id']}` | `{provider['home']['canonical_team_id']}` | `{provider['home']['crosswalk_method']}` |", f"| away | `{provider['away']['provider_team_id']}` | `{provider['away']['canonical_team_id']}` | `{provider['away']['crosswalk_method']}` |", "", "Canonical candidates are corroborated by checked-in OpenFootball and football-data.co.uk identity evidence plus the authoritative direct historical meeting; no fuzzy or name-distance resolution is used.", "",
        "## Authoritative historical validation", "", f"- Home usable history: **{history['home']['usable_match_count']}** matches (`{history['home']['kickoff_min']}` — `{history['home']['kickoff_max']}`).", f"- Away usable history: **{history['away']['usable_match_count']}** matches (`{history['away']['kickoff_min']}` — `{history['away']['kickoff_max']}`).", f"- Same `Sweden Allsvenskan` network: **{history['same_network']}**; component size: `{history['network_component_team_count']}` teams.", f"- Direct historical edge: `{history['shared_historical_match_ids'][0]}`." if history["shared_historical_match_ids"] else "- Direct historical edge: none.", "- All selected rows satisfy `kickoff_at < target_kickoff`, are team-strength eligible, unique, and conflict-free; post-kickoff rows used: **0**.", "",
        "## Checks", "", *[f"- `{name}`: `{value}`" for name, value in report["checks"].items()], "", "## Evidence files", "", *[f"- `{path}`" for path in (UNIVERSE, SCHEDULE, PROSPECTIVE, FROZEN, OPENFOOTBALL_IDENTITY, FOOTBALL_DATA_IDENTITY, HISTORICAL_SAMPLE)], "", "The retained Nowscore raw-source hashes are recorded in the frozen input snapshot; raw source-cache files are not copied into this evidence package.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=ROOT / "data/football_data/fe_id_bridge1_evidence.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "docs/team-strength/FE_ID_BRIDGE_1_SWEDISH_IDENTITY_BRIDGE.md")
    args = parser.parse_args(argv)
    report = build_target_evidence()
    _write_json(args.output_json, report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output_json": str(args.output_json), "output_md": str(args.output_md)}, ensure_ascii=False))
    return 0 if report["status"] == "READY_FOR_ACCEPTANCE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
