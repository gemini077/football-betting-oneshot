from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.providers.openfootball import parse_football_txt_rows
from scripts.football_data.team_strength import TeamStrengthBuilder
from scripts.prediction_quality import recent_form_is_usable
from scripts.recent_form_cache import load_recent_form_cache


MADRID = "team:spain:real-madrid"
SOCIEDAD = "team:spain:real-sociedad"
CUTOFF = "2026-08-26T19:00:00Z"
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _result(index: int, kickoff: str, home: str, away: str, home_goals: int = 1, away_goals: int = 0, season: str = "2025") -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:spain:{index}",
        competition_id="competition:spain-la-liga",
        season_id=f"season:spain-la-liga:{season}",
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=home_goals,
        away_goals=away_goals,
        provider="openfootball",
        provider_match_id=f"openfootball:{index}",
        source_as_of_at=kickoff,
        captured_at="2026-08-26T10:00:00Z",
        source_record_ref=f"openfootball:fixture:{index}",
        source_reliable=True,
        resolution_method="manual_verified",
        raw_home_team=home,
        raw_away_team=away,
        raw_competition="Spain Primera División",
        raw_season=season,
        repository="openfootball/espana",
        commit_sha="fixture-commit",
        source_file="2025-26/1-liga-full.txt",
        match_type="league",
    )


def _team_history() -> list[dict]:
    return [
        _result(1, "2025-05-03T18:00:00Z", MADRID, "team:spain:opponent-a"),
        _result(2, "2025-05-10T18:00:00Z", "team:spain:opponent-b", MADRID),
        _result(3, "2025-05-17T18:00:00Z", MADRID, "team:spain:opponent-c"),
        _result(4, "2025-05-24T18:00:00Z", "team:spain:opponent-d", MADRID),
        _result(5, "2026-08-22T19:30:00Z", "team:spain:espanyol", MADRID, 1, 2, season="2026"),
        _result(6, "2025-05-03T16:00:00Z", SOCIEDAD, "team:spain:opponent-e"),
        _result(7, "2025-05-10T16:00:00Z", "team:spain:opponent-f", SOCIEDAD),
        _result(8, "2025-05-17T16:00:00Z", SOCIEDAD, "team:spain:opponent-g"),
        _result(9, "2025-05-24T16:00:00Z", "team:spain:opponent-h", SOCIEDAD),
        _result(10, "2026-08-21T19:00:00Z", "team:spain:betis", SOCIEDAD, 1, 0, season="2026"),
    ]


def test_openfootball_parser_supports_season_header_metadata_rollover_and_current_shape():
    old = """= Spain | Primera División 2025/26

Fri Aug 15 19:00 UTC+2 @ Estadi Municipal de Montilivi, Girona
  Girona FC v Rayo Vallecano 1-3 (0-3)
Wed Dec 31 18:00 UTC+1 @ venue
  Real Madrid C.F. v Real Sociedad 2-1 (1-0)
Sat Jan 3 18:00 UTC+1 @ venue
  Real Sociedad v Real Madrid C.F. 0-1 (0-0)
"""
    rows = parse_football_txt_rows(old)
    assert [row["kickoff_at"][:10] for row in rows] == ["2025-08-15", "2025-12-31", "2026-01-03"]
    assert rows[0]["kickoff_at"] == "2025-08-15T17:00:00Z"
    assert rows[1]["home_goals"] == 2

    current = """= Spain Primera División 2026/27
  Sat Aug 15 2026
    19:30 Deportivo Alavés v Getafe CF 3-0 (0-0)
  Sun Aug 16
    17:00 Real Sociedad de Fútbol v RCD Espanyol de Barcelona 2-0
"""
    current_rows = parse_football_txt_rows(current)
    assert [row["kickoff_at"][:10] for row in current_rows] == ["2026-08-15", "2026-08-16"]


def test_last_n_crosses_season_and_recency_uses_latest_selected_result():
    builder = TeamStrengthBuilder(_team_history(), captured_at="2026-08-26T12:00:00Z")
    madrid = builder.build(MADRID, target_kickoff=CUTOFF, window_type="last_5", competition_id="competition:spain-la-liga", season_id="season:spain-la-liga:2026")
    sociedad = builder.build(SOCIEDAD, target_kickoff=CUTOFF, window_type="last_5", competition_id="competition:spain-la-liga", season_id="season:spain-la-liga:2026")

    assert madrid["matches"] == sociedad["matches"] == 5
    assert madrid["metrics"]["home"]["matches"] > 0
    assert sociedad["metrics"]["away"]["matches"] > 0
    assert madrid["latest_historical_match_at"] == "2026-08-22T19:30:00Z"
    assert sociedad["latest_historical_match_at"] == "2026-08-21T19:00:00Z"
    assert madrid["history_recency_status"] == sociedad["history_recency_status"] == "current"
    assert madrid["current_strength_ready"] is sociedad["current_strength_ready"] is True


def _cache_records(*, stale: bool = False, missing_home_venue: bool = False) -> list[dict]:
    dates = ["2025-05-03", "2025-05-10", "2025-05-17", "2025-05-24"]
    records = []
    for index, day in enumerate(dates, 1):
        kickoff = f"{day}T18:00:00Z"
        records.append({"team_id": MADRID, "kickoff_at": kickoff, "venue": "away" if index % 2 == 0 else "home", "goals_for": 1, "goals_against": 0, "source_file": "2025-26/1-liga-full.txt", "source_line": index, "raw_home": "Real Madrid C.F.", "raw_away": "Opponent"})
        records.append({"team_id": SOCIEDAD, "kickoff_at": kickoff, "venue": "away" if index % 2 == 0 else "home", "goals_for": 1, "goals_against": 0, "source_file": "2025-26/1-liga-full.txt", "source_line": index + 10, "raw_home": "Opponent", "raw_away": "Real Sociedad"})
    madrid_latest = "2026-06-20T18:00:00Z" if stale else "2026-08-22T19:30:00Z"
    sociedad_latest = "2026-06-21T18:00:00Z" if stale else "2026-08-21T19:00:00Z"
    records.extend([
        {"team_id": MADRID, "kickoff_at": madrid_latest, "venue": "away", "goals_for": 2, "goals_against": 1, "source_file": "2026-27/1-liga.txt", "source_line": 30, "raw_home": "RCD Espanyol de Barcelona", "raw_away": "Real Madrid CF"},
        {"team_id": SOCIEDAD, "kickoff_at": sociedad_latest, "venue": "away", "goals_for": 0, "goals_against": 1, "source_file": "2026-27/1-liga.txt", "source_line": 26, "raw_home": "Real Betis Balompié", "raw_away": "Real Sociedad de Fútbol"},
        {"team_id": MADRID, "kickoff_at": "2026-08-27T00:00:00Z", "venue": "home", "goals_for": 9, "goals_against": 9, "source_file": "2026-27/1-liga.txt", "source_line": 999, "raw_home": "Real Madrid CF", "raw_away": "Future"},
    ])
    if missing_home_venue:
        for row in records:
            if row["team_id"] == MADRID and row["venue"] == "home":
                row["venue"] = "away"
    return records


def _write_cache(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps({
        "contract_version": "recent_form_cache.v1",
        "generated_at": "2026-08-26T12:00:00Z",
        "fixtures": [{
            "match_id": "500-1427944",
            "home": "皇家马德里",
            "away": "皇家社会",
            "home_team_id": MADRID,
            "away_team_id": SOCIEDAD,
            "cutoff_at": CUTOFF,
            "records": records,
            "provenance": {
                "provider": "openfootball",
                "repository": "openfootball/espana",
                "commit_sha": "fixture-commit",
                "source_files": ["2025-26/1-liga-full.txt", "2026-27/1-liga.txt"],
                "raw_sha256": {"2025-26/1-liga-full.txt": "a" * 64, "2026-27/1-liga.txt": "b" * 64},
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")


def _job():
    return {"match_id": "500-1427944", "home": "皇家马德里", "away": "皇家社会", "kickoff": "2026-08-27T03:00:00+08:00"}


def test_compact_cache_builds_four_blocks_from_exact_project_names_and_rejects_future_stale_or_missing_venue(tmp_path):
    cache = tmp_path / "cache.json"
    _write_cache(cache, _cache_records())
    selected = load_recent_form_cache(_job(), _job()["kickoff"], NOW, cache_path=cache)
    assert selected is not None
    assert recent_form_is_usable(selected["recent_form"])
    assert selected["recent_form"]["home_home"]["matches"] > 0
    assert selected["recent_form"]["away_away"]["matches"] > 0
    assert all(row["kickoff_at"] < CUTOFF for row in selected["records"])

    _write_cache(cache, _cache_records(stale=True))
    diagnostics = []
    assert load_recent_form_cache(_job(), _job()["kickoff"], NOW, cache_path=cache, diagnostics=diagnostics) is None
    assert diagnostics[0]["stage"] == "CACHE_PROVENANCE_INVALID"
    _write_cache(cache, _cache_records(missing_home_venue=True))
    assert load_recent_form_cache(_job(), _job()["kickoff"], NOW, cache_path=cache) is None


def test_refresh_failure_keeps_existing_fresh_cache_usable(tmp_path):
    import scripts.recent_form_cache as cache_module

    cache = tmp_path / "cache.json"
    _write_cache(cache, _cache_records())
    with patch.object(cache_module, "_github_request", side_effect=OSError("offline")):
        assert cache_module.refresh_recent_form_cache(
            "2026-08-26",
            jobs=[_job()],
            now=NOW,
            cache_path=cache,
        ) is False
    assert load_recent_form_cache(_job(), _job()["kickoff"], NOW, cache_path=cache) is not None


def _refresh_raw() -> bytes:
    raw = """= Spain Primera División 2026/27
Sat Aug 15 2026
  Real Madrid CF v Rayo Vallecano 2-0
Sun Aug 16 2026
  Rayo Vallecano v Real Madrid C.F. 1-1
Mon Aug 17 2026
  Real Sociedad de Fútbol v Sevilla FC 1-0
Tue Aug 18 2026
  Valencia CF v Real Sociedad 0-1
"""
    return raw.encode("utf-8")


def _refresh_manifest(path: Path, raw_sha256: str, commit_sha: str = "locked-commit") -> None:
    path.write_text(json.dumps({
        "contract_version": "historical_source_manifest.v1",
        "repository": "openfootball/espana",
        "commit_sha": commit_sha,
        "sources": [{"source_file": "2026-27/1-liga.txt", "provider_season_id": "2026-27", "raw_sha256": raw_sha256}],
        "targets": [
            {"canonical_team_id": MADRID, "project_names": ["皇家马德里"], "provider_team_names": ["Real Madrid CF", "Real Madrid C.F."]},
            {"canonical_team_id": SOCIEDAD, "project_names": ["皇家社会"], "provider_team_names": ["Real Sociedad de Fútbol", "Real Sociedad"]},
        ],
    }, ensure_ascii=False), encoding="utf-8")


def test_locked_manifest_skips_github_api_and_uses_pinned_raw_commit(tmp_path):
    import scripts.recent_form_cache as cache_module

    raw = _refresh_raw()
    manifest = tmp_path / "manifest.json"
    cache = tmp_path / "cache.json"
    _refresh_manifest(manifest, hashlib.sha256(raw).hexdigest())
    with patch.object(cache_module, "_github_json", side_effect=AssertionError("pinned manifest must skip API")) as api, \
         patch.object(cache_module, "_github_request", return_value=raw) as request:
        assert cache_module.refresh_recent_form_cache(
            "2026-08-26",
            jobs=[_job()],
            now=NOW,
            manifest_path=manifest,
            cache_path=cache,
        )
    api.assert_not_called()
    assert "openfootball/espana/locked-commit/2026-27/1-liga.txt" in request.call_args.args[0]
    entry = json.loads(cache.read_text(encoding="utf-8"))["fixtures"][0]
    assert entry["provenance"]["commit_sha"] == "locked-commit"
    assert entry["recent_form"]["home_home"]["matches"] == 1
    assert entry["recent_form"]["away_away"]["matches"] == 1


def test_manifest_hash_mismatch_does_not_overwrite_existing_cache(tmp_path):
    import scripts.recent_form_cache as cache_module

    raw = _refresh_raw()
    manifest = tmp_path / "manifest.json"
    cache = tmp_path / "cache.json"
    _refresh_manifest(manifest, "0" * 64)
    existing = b'{"contract_version":"existing","fixtures":[]}'
    cache.write_bytes(existing)
    with patch.object(cache_module, "_github_json", side_effect=AssertionError("pinned manifest must skip API")), \
         patch.object(cache_module, "_github_request", return_value=raw):
        assert cache_module.refresh_recent_form_cache(
            "2026-08-26",
            jobs=[_job()],
            now=NOW,
            manifest_path=manifest,
            cache_path=cache,
        ) is False
    assert cache.read_bytes() == existing


def _runner_fixture():
    return {"matchId": "500-1427944", "homeTeam": "皇家马德里", "awayTeam": "皇家社会", "spf": {"home": 2.0, "draw": 3.0, "away": 4.0}}


def test_runner_uses_fresh_cache_only_when_live_form_is_missing():
    import scripts.base_prediction_runner as runner

    form = {
        "home_overall": {"matches": 5, "wins": 3, "draws": 1, "losses": 1, "goals_for": 8, "goals_against": 4},
        "home_home": {"matches": 2, "wins": 1, "draws": 1, "losses": 0, "goals_for": 4, "goals_against": 1},
        "away_overall": {"matches": 5, "wins": 2, "draws": 1, "losses": 2, "goals_for": 6, "goals_against": 6},
        "away_away": {"matches": 3, "wins": 1, "draws": 1, "losses": 1, "goals_for": 3, "goals_against": 4},
    }
    job = {"match_id": "500-1427944", "home": "皇家马德里", "away": "皇家社会", "kickoff": "2026-08-27T03:00:00+08:00"}
    official = {"captured_at": "2026-08-26T10:00:00+08:00", "fair_probabilities": {"home": .5, "draw": .25, "away": .25}}
    universe = {"fetched_at": "2026-08-26T10:00:00+08:00"}
    snapshot = {"source_cutoff_at": "2026-08-26T11:00:00+08:00", "market_snapshot_at": "2026-08-26T10:00:00+08:00"}
    with patch.object(runner, "_official_market_baseline", return_value=(official, None)), \
         patch.object(runner, "_find_existing_form", return_value=(None, False, [])), \
         patch.object(runner, "_nowscore_source", return_value=(None, False, [])), \
         patch.object(runner, "_five_hundred_source", return_value=(None, False, [])), \
         patch.object(runner, "load_recent_form_cache", return_value={"recent_form": form, "source": "openfootball_recent_form_cache", "captured_at": "2026-08-26T12:00:00+00:00", "references": [{"url": "https://raw.example"}], "source_refs": ["https://raw.example"]}), \
         patch.object(runner, "build_deterministic_model_input_snapshot", return_value=snapshot):
        context, metadata, error = runner._assemble_context("2026-08-26", job, _runner_fixture(), universe, NOW, None)
    assert error is None
    assert context["prematch_fundamentals"]["recent_form"] == form
    assert metadata["form_source"] == "openfootball_recent_form_cache"

    live = {"recent_form": form, "source": "existing_prematch_snapshot", "captured_at": "2026-08-26T11:00:00+00:00", "references": []}
    with patch.object(runner, "_official_market_baseline", return_value=(official, None)), \
         patch.object(runner, "_find_existing_form", return_value=(live, False, [])), \
         patch.object(runner, "_nowscore_source", return_value=(None, False, [])), \
         patch.object(runner, "_five_hundred_source", return_value=(None, False, [])), \
         patch.object(runner, "load_recent_form_cache") as cache_loader, \
         patch.object(runner, "build_deterministic_model_input_snapshot", return_value=snapshot):
        context, metadata, error = runner._assemble_context("2026-08-26", job, _runner_fixture(), universe, NOW, None)
    assert error is None
    assert context["prematch_fundamentals"]["recent_form"] == form
    assert metadata["form_source"] == "existing_prematch_snapshot"
    cache_loader.assert_not_called()
