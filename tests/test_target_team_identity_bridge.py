import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from target_team_identity_bridge import resolve_target_team_identity  # noqa: E402


CUTOFF = "2026-08-12T12:30:00+08:00"


def _source(*, team_ids=None, panlu_ids=(999, 998), provider_context=False):
    source = {
        "status": "OK",
        "fetched_at": CUTOFF,
        "nowscore_id": 123456,
        "target": {
            "home": "博德闪耀",
            "away": "腓特烈斯塔",
            "kickoff": "2026-08-13T18:00:00+08:00",
        },
        "identity": {
            "nowscore_id": 123456,
            "home_team": "博德闪耀(主)",
            "away_team": "腓特烈斯塔",
            "kickoff_local": "2026/08/13 18:00",
        },
        "analysis_source_url": "https://live.nowscore.com/analysis/123456.js",
        "shuju": {
            "recent_form": {"home_overall": {"matches": 10}},
            **({"team_ids": team_ids} if team_ids is not None else {}),
        },
        "context": {
            "panlu": {
                "matches": [{"home_team_id": panlu_ids[0], "away_team_id": panlu_ids[1]}],
            },
        },
    }
    if provider_context:
        source.update({
            "provider_competition_id": "nowscore:norway-eliteserien",
            "provider_season_id": "2026",
            "provider_identity_evidence": {
                "status": "OK",
                "provider_match_id": "123456",
                "schedule": {
                    "status": "OK",
                    "provider_match_id": "123456",
                    "provider_competition_id": "nowscore:norway-eliteserien",
                    "fetched_at": CUTOFF,
                    "source_ref": "https://example.test/bf1.js",
                    "raw_sha256": "a" * 64,
                },
                "season": {
                    "status": "OK",
                    "provider_competition_id": "nowscore:norway-eliteserien",
                    "provider_season_id": "2026",
                    "fetched_at": CUTOFF,
                    "source_ref": "https://example.test/league.html",
                    "raw_sha256": "b" * 64,
                    "season_list_source_ref": "https://example.test/season.js",
                    "season_list_raw_sha256": "c" * 64,
                },
            },
        })
    return source


def _request(source):
    return {
        "job": {
            "match_id": "500-TEST-123456",
            "home": "博德闪耀",
            "away": "腓特烈斯塔",
            "kickoff": "2026-08-13T18:00:00+08:00",
            "league": "挪威超级联赛",
        },
        "fixture": {
            "matchId": "500-TEST-123456",
            "homeTeam": "博德闪耀",
            "awayTeam": "腓特烈斯塔",
            "nowscoreId": source["nowscore_id"],
            "canonical_competition_id": "competition:norway-eliteserien",
            "canonical_season_context": {
                "canonical_season_id": "season:norway-eliteserien:2026",
                "source": "phase2c_research_readiness",
                "source_ref": "data/football_data/phase2c_research_readiness.json",
                "reviewed": True,
            },
        },
        "context": {"source_snapshots": {"nowscore": {"snapshots": [source]}}},
        "input_snapshot": {"source_cutoff_at": CUTOFF},
    }


def _reviewed_registry(tmp_path):
    path = tmp_path / "competition_registry.json"
    path.write_text(
        json.dumps({
            "contract_version": "competition_registry.v1",
            "competitions": [{
                "canonical_competition_id": "competition:norway-eliteserien",
                "seasons": [{
                    "canonical_season_id": "season:norway-eliteserien:2026",
                    "provider": "nowscore",
                    "provider_competition_id": "nowscore:norway-eliteserien",
                    "provider_competition_name": "Norway Eliteserien",
                    "provider_season_id": "2026",
                    "provider_season_name": "2026",
                    "verified": True,
                    "resolution_method": "manual_verified",
                    "confidence": 1.0,
                }],
            }],
        }),
        encoding="utf-8",
    )
    return path


def test_analysis_team_ids_are_used_and_panlu_ids_are_ignored(tmp_path):
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))

    result = resolve_target_team_identity(
        repository_root=ROOT,
        competition_registry_path=_reviewed_registry(tmp_path),
        **args,
    )

    assert result["canonical_team_identity"]["home_team_id"] == "team:norway:bod-glimt"
    assert result["canonical_team_identity"]["away_team_id"] == "team:norway:fredrikstad"
    assert result["evidence"]["home"]["provider_team_id"] == "472"
    assert result["evidence"]["away"]["provider_team_id"] == "478"
    assert result["evidence"]["source"]["parser"] == "parse_analysis_data"
    assert result["evidence"]["source"]["field"] == "shuju.team_ids"
    assert result["evidence"]["source"]["panlu_used"] is False


def test_panlu_only_ids_do_not_create_target_identity():
    args = _request(_source(team_ids=None, panlu_ids=(472, 478)))

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_PROVIDER_TEAM_IDS_MISSING"
    assert result["evidence"]["source"]["panlu_used"] is False


def test_unreviewed_provider_ids_fail_closed_without_name_fallback(tmp_path):
    args = _request(_source(team_ids={"home": 2091, "away": 1525}, provider_context=True))

    result = resolve_target_team_identity(
        repository_root=ROOT,
        competition_registry_path=_reviewed_registry(tmp_path),
        **args,
    )

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_UNRESOLVED"
    assert result["evidence"]["home"]["resolution_status"] == "unresolved"
    assert result["evidence"]["away"]["resolution_status"] == "unresolved"


def test_non_ok_provider_snapshot_cannot_supply_hand_shaped_ids():
    args = _request(_source(team_ids={"home": 472, "away": 478}))
    args["context"]["source_snapshots"]["nowscore"]["snapshots"][0]["status"] = "FETCH_ERROR"

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_PROVIDER_SOURCE_NOT_VERIFIED"


def test_source_after_cutoff_is_rejected_with_explicit_evidence_status():
    args = _request(_source(team_ids={"home": 472, "away": 478}))
    args["context"]["source_snapshots"]["nowscore"]["snapshots"][0]["fetched_at"] = "2026-08-12T12:30:01+08:00"
    args["input_snapshot"]["source_cutoff_at"] = CUTOFF

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_SOURCE_AFTER_CUTOFF"


def test_provider_match_id_mismatch_is_rejected():
    args = _request(_source(team_ids={"home": 472, "away": 478}))
    args["context"]["source_snapshots"]["nowscore"]["snapshots"][0]["nowscore_id"] = 654321

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_PROVIDER_MATCH_ID_MISMATCH"


def test_reviewed_competition_conflict_fails_closed(tmp_path):
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))
    args["fixture"]["canonical_competition_id"] = "competition:finland-veikkausliiga"

    result = resolve_target_team_identity(
        repository_root=ROOT,
        competition_registry_path=_reviewed_registry(tmp_path),
        **args,
    )

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_CONTEXT_AMBIGUOUS"


def test_unique_reviewed_ids_supply_competition_context_without_name_guessing(tmp_path):
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))
    args["fixture"].pop("canonical_competition_id")

    result = resolve_target_team_identity(
        repository_root=ROOT,
        competition_registry_path=_reviewed_registry(tmp_path),
        **args,
    )

    assert result["canonical_team_identity"]["competition_id"] == "competition:norway-eliteserien"
    assert result["evidence"]["source"]["competition_context"] == "reviewed_crosswalk"


def test_caller_supplied_season_context_cannot_replace_provider_ids():
    args = _request(_source(team_ids={"home": 472, "away": 478}))

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_SEASON_CONTEXT_MISSING"


def test_missing_source_timestamp_fails_closed():
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))
    args["context"]["source_snapshots"]["nowscore"]["snapshots"][0].pop("fetched_at")

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_SOURCE_TIME_INVALID"


def test_naive_source_timestamp_fails_closed():
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))
    args["context"]["source_snapshots"]["nowscore"]["snapshots"][0]["fetched_at"] = "2026-08-12T12:30:00"

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_SOURCE_TIME_INVALID"


def test_missing_input_cutoff_fails_closed():
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))
    args["input_snapshot"].pop("source_cutoff_at")

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_CUTOFF_TIME_INVALID"


def test_naive_input_cutoff_fails_closed():
    args = _request(_source(team_ids={"home": 472, "away": 478}, provider_context=True))
    args["input_snapshot"]["source_cutoff_at"] = "2026-08-12T12:30:00"

    result = resolve_target_team_identity(repository_root=ROOT, **args)

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_IDENTITY_CUTOFF_TIME_INVALID"
