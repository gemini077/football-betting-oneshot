import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nowscore_markets import (  # noqa: E402
    fetch_nowscore_season_context,
    parse_league_season_response,
    parse_schedule_js,
    schedule_identity_for_match,
)
import nowscore_markets  # noqa: E402
from target_team_identity_bridge import resolve_target_team_identity  # noqa: E402


SCHEDULE = """
var B=Array(1);
B[0]=[36,'Premier League','Premier League','ENG PR','#FF3333',1,1,'League.aspx?SclassID=36',0,1,0,0];
var A=Array(1);
A[0]=[12345,0,101,202,'Home',0,'Home EN','Away',0,'Away EN','12:00','2026,7,23,12,00,00'];
"""

LEAGUE_PAGE = """
<script>
var selectSeason = '2026-2027';
var SclassID = 36;
</script>
"""

SEASON_JS = "var arrSeason = ['2026-2027','2025-2026'];"


def _registry(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "contract_version": "competition_registry.v1",
                "competitions": [
                    {
                        "canonical_competition_id": "competition:norway-eliteserien",
                        "seasons": [
                            {
                                "canonical_season_id": "season:norway-eliteserien:2026-2027",
                                "provider": "nowscore",
                                "provider_competition_id": "fixture:sclass-36",
                                "provider_competition_name": "Synthetic Competition",
                                "provider_season_id": "fixture:2026-2027",
                                "provider_season_name": "Synthetic Season",
                                "verified": True,
                                "resolution_method": "manual_verified",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _identity_source(evidence: dict | None = None) -> dict:
    return {
        "status": "OK",
        "fetched_at": "2026-08-12T12:00:00+08:00",
        "nowscore_id": 123456,
        "target": {
            "home": "Bodo Glimt",
            "away": "Fredrikstad",
            "kickoff": "2026-08-13T18:00:00+08:00",
        },
        "identity": {
            "nowscore_id": 123456,
            "home_team": "Bodo Glimt",
            "away_team": "Fredrikstad",
        },
        "shuju": {"team_ids": {"home": 472, "away": 478}},
        "provider_competition_id": "fixture:sclass-36",
        "provider_season_id": "fixture:2026-2027",
        "provider_identity_evidence": evidence
        or {
            "status": "OK",
            "provider_match_id": "123456",
            "schedule": {
                "status": "OK",
                "provider_match_id": "123456",
                "provider_competition_id": "fixture:sclass-36",
                "fetched_at": "2026-08-12T12:00:00+08:00",
                "source_ref": "https://live.nowscore.com/data/bf1.js",
                "raw_sha256": "a" * 64,
            },
            "season": {
                "status": "OK",
                "provider_competition_id": "fixture:sclass-36",
                "provider_season_id": "fixture:2026-2027",
                "returned_sclass_id": "36",
                "fetched_at": "2026-08-12T12:00:00+08:00",
                "source_ref": "https://info.nowscore.com/cn/League/36.html",
                "raw_sha256": "b" * 64,
                "season_list_source_ref": "https://info.nowscore.com/jsData/LeagueSeason/sea36.js",
                "season_list_raw_sha256": "c" * 64,
            },
        },
    }


def _identity_request(source: dict, registry: Path) -> dict:
    return {
        "job": {
            "match_id": "500-TEST-123456",
            "home": "Bodo Glimt",
            "away": "Fredrikstad",
            "kickoff": "2026-08-13T18:00:00+08:00",
        },
        "fixture": {"matchId": "500-TEST-123456", "nowscoreId": 123456},
        "context": {"source_snapshots": {"nowscore": {"snapshots": [source]}}},
        "input_snapshot": {"source_cutoff_at": "2026-08-12T12:30:00+08:00"},
        "repository_root": ROOT,
        "competition_registry_path": registry,
    }


def test_bf1_a_row_uses_b_record_zero_as_sclass_id_not_b_index():
    row = parse_schedule_js(SCHEDULE)[0]

    assert row["provider_match_id"] == "12345"
    assert row["provider_competition_id"] == "36"
    assert row["provider_competition_id"] != str(row["provider_competition_evidence"]["sclass_record_index"])
    assert row["provider_competition_evidence"]["field"] == "B[A[i][1]][0]"


def test_schedule_identity_requires_exact_target_match_id():
    schedule = parse_schedule_js(SCHEDULE)

    assert schedule_identity_for_match(schedule, 12345)["status"] == "OK"
    assert schedule_identity_for_match(schedule, 99999)["status"] == "TARGET_PROVIDER_MATCH_NOT_IN_SCHEDULE"
    assert schedule_identity_for_match(schedule, None)["status"] == "TARGET_PROVIDER_MATCH_ID_INVALID"


def test_league_season_response_requires_matching_sclass_and_listed_season():
    result = parse_league_season_response(LEAGUE_PAGE, 36, SEASON_JS)

    assert result["status"] == "OK"
    assert result["provider_competition_id"] == "36"
    assert result["provider_season_id"] == "2026-2027"

    mismatch = parse_league_season_response(LEAGUE_PAGE.replace("SclassID = 36", "SclassID = 31"), 36, SEASON_JS)
    assert mismatch["status"] == "TARGET_PROVIDER_SCLASS_ID_MISMATCH"

    missing = parse_league_season_response(LEAGUE_PAGE, 36, "var arrSeason = ['2025-2026'];")
    assert missing["status"] == "TARGET_PROVIDER_SEASON_KEY_NOT_LISTED"


def test_season_fetch_keeps_raw_hash_provenance_and_timezone_aware_capture(tmp_path):
    page_raw = LEAGUE_PAGE.encode()
    season_raw = SEASON_JS.encode()

    with patch("nowscore_markets.CACHE_ROOT", tmp_path), patch(
        "nowscore_markets._fetch_bytes", side_effect=[page_raw, season_raw]
    ):
        result = fetch_nowscore_season_context(36, no_cache=True)

    assert result["status"] == "OK"
    assert result["raw_sha256"] == hashlib.sha256(page_raw).hexdigest()
    assert result["season_list_raw_sha256"] == hashlib.sha256(season_raw).hexdigest()
    assert result["source_ref"].endswith("/League/36.html")
    assert result["season_list_source_ref"].endswith("/sea36.js")
    assert datetime.fromisoformat(result["fetched_at"]).tzinfo is not None


def test_market_acquisition_persists_target_competition_and_season_evidence(tmp_path):
    season = {
        "status": "OK",
        "provider_competition_id": "36",
        "provider_season_id": "2026-2027",
        "source_ref": "https://info.nowscore.com/cn/League/36.html",
        "season_list_source_ref": "https://info.nowscore.com/jsData/LeagueSeason/sea36.js",
        "raw_sha256": "b" * 64,
        "season_list_raw_sha256": "c" * 64,
        "fetched_at": "2026-08-12T12:00:00+08:00",
    }
    parsed_market = {
        "identity": {"home_team": "Home", "away_team": "Away", "kickoff_local": "2026/08/23 12:00"},
        "ouzhi": {"bookmakers": [], "total": 0},
        "yazhi": {"companies": [], "total": 0},
        "daxiao": {"companies": [], "total": 0},
    }

    with patch.object(nowscore_markets, "CACHE_ROOT", tmp_path), patch.object(
        nowscore_markets, "_fetch_bytes", side_effect=[SCHEDULE.encode(), b"market", b"analysis"]
    ), patch.object(nowscore_markets, "parse_three_in_one", return_value=parsed_market), patch.object(
        nowscore_markets, "fetch_nowscore_season_context", return_value=season
    ), patch.object(nowscore_markets, "fetch_context_bundle", return_value={}), patch.object(
        nowscore_markets, "record_binding"
    ):
        result = nowscore_markets.fetch_match_markets(
            "Home", "Away", "2026-08-23T12:00:00+08:00", explicit_id=12345, no_cache=True
        )

    assert result["status"] == "OK"
    assert result["provider_match_id"] == "12345"
    assert result["provider_competition_id"] == "36"
    assert result["provider_season_id"] == "2026-2027"
    assert result["provider_identity_evidence"]["status"] == "OK"
    assert result["provider_identity_evidence"]["schedule"]["raw_sha256"] == hashlib.sha256(SCHEDULE.encode()).hexdigest()


def test_reviewed_string_season_key_resolves_before_freeze(tmp_path):
    registry = _registry(tmp_path / "competition_registry.json")
    result = resolve_target_team_identity(**_identity_request(_identity_source(), registry))

    assert result["evidence"]["status"] == "RESOLVED"
    assert result["canonical_team_identity"]["competition_id"] == "competition:norway-eliteserien"
    assert result["canonical_team_identity"]["season_id"] == "season:norway-eliteserien:2026-2027"


def test_provider_ids_without_verified_identity_evidence_fail_closed(tmp_path):
    registry = _registry(tmp_path / "competition_registry.json")
    source = _identity_source()
    source.pop("provider_identity_evidence")

    result = resolve_target_team_identity(**_identity_request(source, registry))

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"


def test_identity_evidence_must_be_aware_and_before_cutoff(tmp_path):
    registry = _registry(tmp_path / "competition_registry.json")
    future = _identity_source()
    future["provider_identity_evidence"]["season"]["fetched_at"] = "2026-08-12T12:30:01+08:00"
    assert resolve_target_team_identity(**_identity_request(future, registry))["evidence"]["status"] == (
        "TARGET_IDENTITY_PROVIDER_EVIDENCE_AFTER_CUTOFF"
    )

    naive = _identity_source()
    naive["provider_identity_evidence"]["schedule"]["fetched_at"] = "2026-08-12T12:00:00"
    assert resolve_target_team_identity(**_identity_request(naive, registry))["evidence"]["status"] == (
        "TARGET_IDENTITY_PROVIDER_EVIDENCE_TIME_INVALID"
    )


def test_identity_evidence_requires_raw_hash_and_source_reference(tmp_path):
    registry = _registry(tmp_path / "competition_registry.json")
    source = _identity_source()
    source["provider_identity_evidence"]["season"].pop("raw_sha256")

    result = resolve_target_team_identity(**_identity_request(source, registry))

    assert result["canonical_team_identity"] is None
    assert result["evidence"]["status"] == "TARGET_PROVIDER_IDENTITY_EVIDENCE_NOT_VERIFIED"
