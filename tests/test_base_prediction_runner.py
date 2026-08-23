import json
import sys
import tempfile
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.base_prediction_runner as runner
from model_governance import PredictionConflictError, freeze_prediction, prediction_content_hash


TZ = timezone(timedelta(hours=8))
DATE = "2026-08-12"
NOW = datetime(2026, 8, 12, 14, 0, tzinfo=TZ)
KICKOFF = "2026-08-13T03:00:00+08:00"


def recent_form() -> dict:
    return {
        "home_overall": {"matches": 10, "wins": 4, "draws": 3, "losses": 3, "goals_for": 15, "goals_against": 10},
        "home_home": {"matches": 10, "wins": 5, "draws": 3, "losses": 2, "goals_for": 18, "goals_against": 8},
        "away_overall": {"matches": 10, "wins": 3, "draws": 2, "losses": 5, "goals_for": 11, "goals_against": 14},
        "away_away": {"matches": 10, "wins": 2, "draws": 3, "losses": 5, "goals_for": 9, "goals_against": 16},
    }


def fixture(index: int, *, spf: dict | None = None, kickoff: str = KICKOFF, nowscore: bool = False) -> dict:
    row = {
        "matchId": f"M{index:03d}",
        "matchNum": f"T{index:03d}",
        "businessDate": DATE,
        "matchDate": kickoff[:10],
        "matchTime": kickoff[11:19],
        "league": "Unpopular Test League",
        "homeTeam": f"Home {index}",
        "awayTeam": f"Away {index}",
    }
    if spf is not None:
        row["spf"] = spf
    if nowscore:
        row.update({"nowscoreId": 100000 + index, "nowscoreMatchStatus": "EXACT_MATCH"})
    return row


def parsed_source(index: int = 1, *, captured_at: str = "2026-08-12T12:30:00+08:00", full_market: bool = False, form: dict | None = None) -> dict:
    value = {
        "shuju_id": 1413000 + index,
        "fetched_at": captured_at,
        "shuju": {"recent_form": recent_form() if form is None else form},
    }
    if full_market:
        value["ouzhi"] = {
            "bookmakers": [
                {"name": "Book A", "spf_current": {"home": 1.8, "draw": 3.5, "away": 4.5}},
                {"name": "Book B", "spf_current": {"home": 1.9, "draw": 3.4, "away": 4.4}},
            ]
        }
        value["daxiao"] = {
            "companies": [{
                "name": "Book A",
                "current_line": 2.5,
                "current_over_water": 0.90,
                "current_under_water": 0.96,
            }]
        }
        value["yazhi"] = {
            "companies": [{
                "name": "Book A",
                "current_handicap": 0.0,
                "current_water_home": 0.91,
                "current_water_away": 0.93,
            }]
        }
    return value


def champion_result() -> dict:
    scores = [
        {"score": f"{index // 3}-{index % 3}", "probability": 0.10 - index * 0.005, "rank": index + 1}
        for index in range(10)
    ]
    return {
        "model": {
            "method": runner.MODEL_FAMILY,
            "lambda_home": 1.7,
            "lambda_away": 1.2,
            "rho": 0.0,
            "probabilities": {"home": 0.48, "draw": 0.27, "away": 0.25},
            "total_goals_buckets": [{"goals": "2", "probability": 0.22}],
            "btts": {"yes": 0.54, "no": 0.46},
            "score_probabilities": scores,
        },
        "decisions": {
            "unique_primary_dimension": "胜平负：主胜",
            "unique_score": "1-0",
            "score_selection_trace": {"confidence": "medium", "main_risk": "small sample"},
        },
        "data_quality": {"status": "MODEL_READY", "missing": []},
    }


def write_case(root: Path, fixtures: list[dict], *, universe_status: str = "READY", fetched_at: str = "2026-08-12T12:00:00+08:00") -> None:
    universe_root = root / "prediction_universe"
    jobs_root = root / "base_prediction_jobs"
    universe_root.mkdir(parents=True)
    jobs_root.mkdir(parents=True)
    universe = {
        "schema_version": "1.0",
        "business_date": DATE,
        "status": universe_status,
        "source": "sporttery.cn",
        "fetched_at": fetched_at,
        "fixture_count": len(fixtures),
        "fixtures": fixtures if universe_status == "READY" else [],
    }
    (universe_root / f"{DATE}.json").write_text(json.dumps(universe, ensure_ascii=False), encoding="utf-8")
    jobs = []
    for row in fixtures if universe_status == "READY" else []:
        jobs.append({
            "job_id": f"BASE-{DATE}-{row['matchId']}",
            "business_date": DATE,
            "match_id": row["matchId"],
            "match_num": row["matchNum"],
            "league": row["league"],
            "home": row["homeTeam"],
            "away": row["awayTeam"],
            "kickoff": f"{row['matchDate']}T{row['matchTime']}+08:00",
            "status": "PENDING",
            "created_at": "2026-08-12T12:00:00+08:00",
            "updated_at": "2026-08-12T12:00:00+08:00",
            "source_universe": f"data/prediction_universe/{DATE}.json",
            "prediction_id": None,
            "last_error": None,
        })
    ledger = {
        "schema_version": "1.0",
        "business_date": DATE,
        "status": universe_status,
        "generated_at": "2026-08-12T12:00:00+08:00",
        "fixture_count": len(jobs),
        "job_count": len(jobs),
        "pending_count": len(jobs),
        "frozen_count": 0,
        "predicted_count": 0,
        "insufficient_data_count": 0,
        "prediction_failed_count": 0,
        "missed_prematch_count": 0,
        "jobs": jobs,
    }
    (jobs_root / f"{DATE}.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")


def trade_payload(count: int = 20) -> dict:
    return {
        "success": True,
        "fetch_time": "2026-08-12T12:15:00+08:00",
        "matches": [
            {
                "match_num": f"T{index:03d}",
                "shuju_id": 1413000 + index,
                "home_team": f"Home {index}",
                "away_team": f"Away {index}",
                "kickoff_local": "2026-08-13 03:00",
            }
            for index in range(1, count + 1)
        ],
    }


def run_case(
    root: Path,
    *,
    parsed: dict | None = None,
    model: dict | None = None,
    model_side_effect=None,
    now: datetime = NOW,
    nowscore_result: dict | None = None,
    competition_registry_path: Path | None = None,
) -> tuple[dict, Mock]:
    parsed = parsed if parsed is not None else parsed_source()
    with ExitStack() as stack:
        stack.enter_context(patch.object(runner, "ANALYSIS_INPUT_ROOT", root / "analysis_inputs"))
        stack.enter_context(patch.object(runner, "fetch_trade_matches", return_value=trade_payload()))
        stack.enter_context(patch.object(runner, "fetch_and_parse", return_value=parsed))
        stack.enter_context(patch.object(runner, "fetch_match_markets", return_value=nowscore_result))
        build = stack.enter_context(
            patch.object(runner, "build_automatic_model", return_value=model if model is not None else champion_result(), side_effect=model_side_effect)
        )
        summary = runner.run_base_prediction_jobs(
            DATE,
            universe_root=root / "prediction_universe",
            jobs_root=root / "base_prediction_jobs",
            now=now,
            record_root=root / "model_governance" / "predictions",
            input_snapshot_root=root / "model_governance" / "input_snapshots",
            competition_registry_path=competition_registry_path,
        )
    return summary, build


def read_ledger(root: Path) -> dict:
    return json.loads((root / "base_prediction_jobs" / f"{DATE}.json").read_text(encoding="utf-8"))


def records(root: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in (root / "model_governance" / "predictions").glob("*.json")]


def limited_spf() -> dict:
    return {"home": 1.8, "draw": 3.5, "away": 4.5}


def test_three_jobs_call_champion_and_create_three_governance_freezes():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(index, spf=limited_spf()) for index in range(1, 4)])
        summary, build = run_case(root)
        ledger = read_ledger(root)
        frozen = records(root)

        assert summary["attempted"] == 3
        assert summary["frozen"] == 3
        assert build.call_count == 3
        assert len(frozen) == 3
        assert {job["status"] for job in ledger["jobs"]} == {"FROZEN"}
        assert all(record["product_role"] == "FUSION_BASELINE_V0" for record in frozen)


def test_fourteen_jobs_are_all_attempted_without_selection_or_popularity_filter():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(index, spf=limited_spf()) for index in range(1, 15)])
        summary, build = run_case(root)

    assert summary["attempted"] == 14
    assert summary["frozen"] == 14
    assert build.call_count == 14


def test_tier_a_market_snapshot_is_full():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, _ = run_case(root, parsed=parsed_source(full_market=True))
        record = records(root)[0]

    assert summary["frozen"] == 1
    assert record["market_intelligence_quality"] == "FULL"
    assert record["market_sources"] == ["500.com"]
    assert record["market_data_providers"] == ["500.com"]
    assert record["market_bookmakers"] == ["Book A", "Book B"]
    assert record["market_families"] == ["1x2", "asian_handicap", "totals"]


def test_two_bookmakers_without_handicap_or_totals_are_limited():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        parsed = parsed_source(full_market=True)
        parsed.pop("yazhi")
        parsed.pop("daxiao")
        summary, _ = run_case(root, parsed=parsed)
        record = records(root)[0]

    assert summary["frozen"] == 1
    assert record["market_intelligence_quality"] == "LIMITED"
    assert record["market_families"] == ["1x2"]


def test_tier_b_sporttery_spf_is_limited_and_saved_as_market_baseline():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, _ = run_case(root)
        record = records(root)[0]

    baseline = record["market_only_baseline"]
    assert summary["frozen"] == 1
    assert record["market_intelligence_quality"] == "LIMITED"
    assert record["market_data_providers"] == ["sporttery"]
    assert record["market_bookmakers"] == []
    assert record["market_families"] == ["1x2"]
    assert baseline["method"] == "sporttery_spf_devig"
    assert sum(baseline[key] for key in ("home", "draw", "away")) == pytest.approx(1.0, abs=1e-8)


def test_missing_market_intelligence_is_insufficient_data():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1)])
        summary, build = run_case(root)
        ledger = read_ledger(root)

    assert summary["frozen"] == 0
    assert summary["insufficient_data"] == 1
    assert summary["failure_reasons"] == {"MISSING_MARKET_INTELLIGENCE": 1}
    assert build.call_count == 0
    assert ledger["jobs"][0]["status"] == "INSUFFICIENT_DATA"


def test_missing_recent_form_is_insufficient_data():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, build = run_case(root, parsed=parsed_source(form={}))

    assert summary["insufficient_data"] == 1
    assert summary["failure_reasons"] == {"MISSING_RECENT_FORM": 1}
    assert build.call_count == 0


def test_unverifiable_source_timestamp_is_rejected_before_model_call():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, build = run_case(
            root,
            parsed=parsed_source(captured_at=KICKOFF),
        )

    assert summary["failure_reasons"] == {"INPUT_TIMESTAMP_UNVERIFIED": 1}
    assert build.call_count == 0


def test_model_none_is_insufficient_data():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, build = run_case(root, model={"model": None})

    assert summary["failure_reasons"] == {"MODEL_RETURNED_NO_PREDICTION": 1}
    assert summary["insufficient_data"] == 1
    assert build.call_count == 1


def test_champion_exception_is_prediction_failed():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, build = run_case(root, model_side_effect=RuntimeError("boom"))

    assert summary["prediction_failed"] == 1
    assert summary["failure_reasons"] == {"MODEL_EXCEPTION_RuntimeError": 1}
    assert build.call_count == 1


def test_past_kickoff_is_missed_and_no_prediction_is_written():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf(), kickoff="2026-08-12T13:59:00+08:00")])
        summary, build = run_case(root)
        ledger = read_ledger(root)
        frozen_files = list((root / "model_governance" / "predictions").glob("*.json"))

    assert summary["missed_prematch"] == 1
    assert summary["frozen"] == 0
    assert build.call_count == 0
    assert ledger["jobs"][0]["status"] == "MISSED_PREMATCH_WINDOW"
    assert frozen_files == []


def test_frozen_job_is_idempotent_and_does_not_call_champion_again():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        first, first_build = run_case(root)
        first_record = records(root)[0]
        second, second_build = run_case(root, model_side_effect=AssertionError("rerun"))
        final_record = records(root)[0]

    assert first["frozen"] == second["frozen"] == 1
    assert first_build.call_count == 1
    assert second_build.call_count == 0
    assert final_record["prediction_id"] == first_record["prediction_id"]
    assert final_record["probabilities"] == first_record["probabilities"]


def test_governance_record_contains_minimum_prediction_contract():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        summary, _ = run_case(root)
        record = records(root)[0]

    assert summary["frozen"] == 1
    assert record["model_family"] == runner.MODEL_FAMILY
    assert record["release_version"] == "v0.19.0"
    assert record["lambda_home"] is not None
    assert record["lambda_away"] is not None
    assert set(record["probabilities"]) == {"home", "draw", "away"}
    assert record["prediction_output"]["btts"]
    assert record["score_top1"]
    assert len(record["score_top3"]) == 3
    assert len(record["score_top5"]) == 5
    assert record["model_input_snapshot_ref"].endswith(".json")
    assert record["minutes_to_kickoff_at_freeze"] > 0
    assert record["freeze_created_at"]
    assert record["data_grade"] == "C"
    assert record["generic_data_grade"] == "C"
    assert record["base_input_quality"] == "VERIFIED_MINIMUM"
    assert record["formal_eligibility_policy"] == "base_prediction_minimum.v1"
    assert record["formal_eligible"] is True


def test_reviewed_target_ids_flow_through_champion_challenger_pair_freeze():
    from model_governance import load_input_snapshot
    from prospective_challenger_runner import build_challenger_record
    from prospective_pair_capture import capture_forward_pairs

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        row = fixture(1, spf=limited_spf(), nowscore=True)
        row.update({
            "homeTeam": "博德闪耀",
            "awayTeam": "腓特烈斯塔",
            "league": "挪威超级联赛",
            "canonical_competition_id": "competition:norway-eliteserien",
        })
        nowscore = {
            "status": "OK",
            "fetched_at": "2026-08-12T12:30:00+08:00",
            "nowscore_id": row["nowscoreId"],
            "target": {"home": row["homeTeam"], "away": row["awayTeam"], "kickoff": KICKOFF},
            "identity": {"home_team": "博德闪耀(主)", "away_team": "腓特烈斯塔"},
            "analysis_source_url": "https://live.nowscore.com/analysis/test.js",
            "provider_competition_id": "fixture:sclass-36",
            "provider_season_id": "fixture:2026-2027",
            "provider_identity_evidence": {
                "contract_version": "nowscore_target_identity_evidence.v1",
                "status": "OK",
                "provider": "nowscore",
                "provider_match_id": str(row["nowscoreId"]),
                "schedule": {
                    "status": "OK",
                    "provider_match_id": str(row["nowscoreId"]),
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
            "shuju": {"recent_form": recent_form(), "team_ids": {"home": 472, "away": 478}},
            "context": {"panlu": {"matches": [{"home_team_id": 999, "away_team_id": 998}]}},
            "ouzhi": {"bookmakers": []},
            "yazhi": {"companies": []},
            "daxiao": {"companies": []},
        }
        registry_path = root / "competition_registry.json"
        registry_path.write_text(json.dumps({
            "contract_version": "competition_registry.v1",
            "competitions": [{
                "canonical_competition_id": "competition:norway-eliteserien",
                "seasons": [{
                    "canonical_season_id": "season:norway-eliteserien:2026-2027",
                    "provider": "nowscore",
                    "provider_competition_id": "fixture:sclass-36",
                    "provider_season_id": "fixture:2026-2027",
                    "verified": True,
                    "resolution_method": "manual_verified",
                }],
            }],
        }), encoding="utf-8")
        write_case(root, [row])
        summary, _ = run_case(
            root,
            nowscore_result=nowscore,
            competition_registry_path=registry_path,
        )
        champion = records(root)[0]

        assert summary["frozen"] == 1
        assert champion["canonical_team_identity"]["home_team_id"] == "team:norway:bod-glimt"
        assert champion["canonical_team_identity"]["away_team_id"] == "team:norway:fredrikstad"
        assert champion["canonical_team_identity"]["season_id"] == "season:norway-eliteserien:2026-2027"
        assert champion["target_team_identity_evidence"]["source"]["panlu_used"] is False
        assert champion["target_team_identity_evidence"]["source"]["provider_identity_evidence"]["season"]["raw_sha256"] == "b" * 64

        snapshot = load_input_snapshot(champion, root / "model_governance" / "input_snapshots")
        history = [
            {
                "canonical_match_id": f"history:{index}",
                "competition_id": "competition:norway-eliteserien",
                "season_id": "2026",
                "home_team_id": "team:norway:bod-glimt" if index % 2 == 0 else f"team:norway:other-{index}",
                "away_team_id": "team:norway:fredrikstad" if index % 2 else f"team:norway:other-{index}",
                "kickoff_at": f"2026-08-{index:02d}T10:00:00+08:00",
                "home_goals": index % 3,
                "away_goals": (index + 1) % 2,
                "eligible_for_team_strength": True,
                "duplicate_status": "unique",
                "source_conflict": False,
                "entity_type": "club",
                "source_as_of_at": "2026-08-12T10:00:00+08:00",
                "captured_at": "2026-08-12T10:00:00+08:00",
            }
            for index in range(1, 11)
        ]
        challenger = build_challenger_record(
            champion,
            history_records=history,
            input_snapshot_document=snapshot,
            now=datetime(2026, 8, 12, 15, 0, tzinfo=TZ),
            historical_dataset_digest="synthetic-history",
            historical_dataset_path="synthetic.duckdb",
        )
        challenger_result = freeze_prediction(
            challenger,
            root / "model_governance" / "challenger_predictions",
            input_snapshot_root=root / "model_governance" / "challenger_input_snapshots",
        )
        challenger = json.loads(challenger_result["path"].read_text(encoding="utf-8"))
        assert challenger["canonical_team_identity"] == champion["canonical_team_identity"]
        captured = capture_forward_pairs(
            [champion],
            [challenger],
            now=datetime(2026, 8, 12, 16, 0, tzinfo=TZ),
            business_date=DATE,
            pair_root=root / "prospective" / "pairs",
            raw_frozen_path=root / "paper_ledger" / "frozen.json",
        )

    assert captured["pairs_captured_this_run"] == 1
    assert captured["TRUE_PAIRED"] == 0


def test_repeat_freeze_with_same_prediction_id_different_content_keeps_conflict_guard():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        run_case(root)
        record_path = next((root / "model_governance" / "predictions").glob("*.json"))
        changed = json.loads(record_path.read_text(encoding="utf-8"))
        changed["probabilities"]["home"] = 0.99
        changed["prediction_sha256"] = prediction_content_hash(changed)
        with pytest.raises(PredictionConflictError):
            freeze_prediction(
                changed,
                root / "model_governance" / "predictions",
                input_snapshot_root=root / "model_governance" / "input_snapshots",
            )


def test_runner_does_not_create_deep_report_or_parallel_prediction_store():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_case(root, [fixture(1, spf=limited_spf())])
        run_case(root)

        assert not (root / "base_prediction_inputs").exists()
        assert not (root / "base_predictions").exists()
        assert list(root.rglob("*.html")) == []
