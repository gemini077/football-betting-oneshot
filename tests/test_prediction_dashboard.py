import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.prediction_dashboard import build_dashboard, render_dashboard  # noqa: E402
from test_formal_market_projection import formal_record  # noqa: E402


DATE = "2026-08-12"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fixture(index: int) -> dict:
    return {
        "matchId": str(1000 + index),
        "matchNum": f"T{index:03d}",
        "businessDate": DATE,
        "matchDate": DATE,
        "matchTime": f"{3 + index:02d}:00:00",
        "league": "测试联赛",
        "homeTeam": f"主队{index}",
        "awayTeam": f"客队{index}",
    }


def make_roots(tmp_path: Path, fixtures: list[dict], jobs: list[dict], predictions: list[dict] | None = None):
    universe_root = tmp_path / "universe"
    jobs_root = tmp_path / "jobs"
    prediction_root = tmp_path / "predictions"
    exclusion_root = tmp_path / "exclusions"
    result_root = tmp_path / "results"
    prospective_root = tmp_path / "prospective"
    runtime_path = tmp_path / "runtime" / "latest_cycle.json"
    write_json(universe_root / f"{DATE}.json", {
        "schema_version": "1.0",
        "business_date": DATE,
        "status": "READY",
        "source": "sporttery.cn",
        "fetched_at": "2026-08-12T12:00:00+08:00",
        "fixture_count": len(fixtures),
        "fixtures": fixtures,
    })
    write_json(jobs_root / f"{DATE}.json", {
        "schema_version": "1.0",
        "business_date": DATE,
        "status": "READY",
        "fixture_count": len(fixtures),
        "job_count": len(jobs),
        "jobs": jobs,
    })
    for prediction in predictions or []:
        write_json(prediction_root / f"{prediction['prediction_id']}.json", prediction)
    write_json(prospective_root / "summary.json", {
        "formal_sample_count_total": 1,
        "samples_added_this_run": 1,
        "excluded_prediction_count": 1,
        "pilot_excluded_settled": 1,
    })
    write_json(runtime_path, {
        "overall_status": "HEALTHY",
        "finished_at": "2026-08-12T12:05:00+08:00",
        "steps": {},
    })
    return {
        "universe_root": universe_root,
        "jobs_root": jobs_root,
        "prediction_root": prediction_root,
        "exclusion_root": exclusion_root,
        "result_root": result_root,
        "prospective_root": prospective_root,
        "runtime_path": runtime_path,
        "output_root": tmp_path / "dashboard",
    }


def frozen_job(match_id: str, prediction_id: str) -> dict:
    return {
        "job_id": f"BASE-{DATE}-{match_id}",
        "business_date": DATE,
        "match_id": match_id,
        "match_num": "T001",
        "league": "测试联赛",
        "home": "主队1",
        "away": "客队1",
        "kickoff": "2026-08-13T04:00:00+08:00",
        "status": "FROZEN",
        "prediction_id": prediction_id,
        "last_error": None,
    }


def frozen_prediction_legacy(prediction_id: str) -> dict:
    return {
        "prediction_id": prediction_id,
        "prediction_status": "formal",
        "product_role": "FUSION_BASELINE_V0",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "lambda_home": 1.4,
        "lambda_away": 0.8,
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "btts": {"yes": 0.45, "no": 0.55},
        "totals": [{"goals": "2", "probability": 0.3}],
        "unique_score": "1-0",
        "score_top3": ["1-0", "1-1", "2-0"],
        "market_intelligence_quality": "LIMITED",
        "data_grade": "C",
        "base_input_quality": "VERIFIED_MINIMUM",
        "minutes_to_kickoff_at_freeze": 120.0,
        "match_key": "FBOS-TEST-1",
        "match_identity": {"home": "主队1", "away": "客队1"},
    }


def frozen_prediction(
    prediction_id: str,
    *,
    home: str = "\u4e3b\u961f1",
    away: str = "\u5ba2\u961f1",
    match_id: str = "1001",
    job_id: str = f"BASE-{DATE}-1001",
    match_key: str = "FBOS-TEST-1",
    kickoff: str = "2026-08-13T04:00:00+08:00",
    source_cutoff: str = "2026-08-12T12:00:00+08:00",
    prediction_created: str = "2026-08-12T14:00:00+08:00",
    freeze_created: str = "2026-08-12T14:01:00+08:00",
    unique_score: str = "1-0",
) -> dict:
    return {
        "prediction_id": prediction_id,
        "job_id": job_id,
        "match_id": match_id,
        "home": home,
        "away": away,
        "kickoff_at": kickoff,
        "source_cutoff_at": source_cutoff,
        "market_snapshot_at": source_cutoff,
        "prediction_created_at": prediction_created,
        "freeze_created_at": freeze_created,
        "prediction_status": "formal",
        "model_role": "champion",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "prediction_variant": "model_only",
        "manual_override": False,
        "product_role": "FUSION_BASELINE_V0",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "lambda_home": 1.4,
        "lambda_away": 0.8,
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "btts": {"yes": 0.45, "no": 0.55},
        "totals": [{"goals": "2", "probability": 0.3}],
        "unique_score": unique_score,
        "score_top3": [unique_score, "1-1", "2-0"],
        "score_distribution": [
            {"score": unique_score, "probability": 0.155},
            {"score": "1-1", "probability": 0.125},
            {"score": "2-0", "probability": 0.100},
        ],
        "market_intelligence_quality": "LIMITED",
        "data_grade": "C",
        "base_input_quality": "VERIFIED_MINIMUM",
        "minutes_to_kickoff_at_freeze": 120.0,
        "match_key": match_key,
        "match_identity": {"home": home, "away": away, "kickoff_at": kickoff},
    }


def test_universe_three_produces_three_accountable_cards_and_frozen_fields(tmp_path):
    fixtures = [fixture(index) for index in range(1, 4)]
    prediction_id = "FBOS-PRED-dashboard-1"
    roots = make_roots(tmp_path, fixtures, [
        frozen_job("1001", prediction_id),
        {"job_id": "BASE-2026-08-12-1002", "match_id": "1002", "status": "PENDING"},
        {"job_id": "BASE-2026-08-12-1003", "match_id": "1003", "status": "INSUFFICIENT_DATA", "last_error": "MISSING_RECENT_FORM"},
    ], [frozen_prediction(prediction_id)])

    payload = build_dashboard(DATE, **roots)

    assert payload["summary"]["fixture_count"] == 3
    assert payload["summary"]["card_count"] == 3
    assert payload["summary"]["frozen"] == 1
    assert payload["summary"]["pending"] == 1
    assert payload["summary"]["insufficient_data"] == 1
    assert payload["summary"]["silent_missing_fixture"] == 0
    card = payload["fixtures"][0]
    assert card["prediction"]["lambda_home"] == 1.4
    assert card["prediction"]["probabilities"]["home"] == 0.5
    assert card["prediction"]["btts"]["yes"] == 0.45
    assert card["prediction"]["score_top3"] == ["1-0", "1-1", "2-0"]
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "已形成预测" not in html
    assert "赛前预测已锁定" not in html
    assert "最高概率比分" in html
    assert "1-0 15.5%" in html
    assert "1X2 概率" in html
    assert "\u53cc\u65b9\u8fdb\u7403 \u662f 45.0%" in html
    assert "\u53cc\u65b9\u8fdb\u7403 \u5426 55.0%" in html
    assert "查看详情" in html
    assert 'href="../matches/1001/"' in html
    assert 'class="fixture-row-target"' in html
    assert '<a class="detail-link"' not in html
    assert "\u7ade\u5f69\u65e5" in html
    assert "\u4eca\u5929" not in html
    assert '\u6d4b\u8bd5\u9636\u6bb5 \u00b7 \u4ec5\u4f9b\u8d5b\u524d\u5206\u6790' in html
    assert "Prediction Universe" not in html
    assert "MISSING_RECENT_FORM" not in html
    assert "近期比赛数据不足" in html
    assert 'data-prediction-kind="formal"' in html
    assert 'class="status-badge"' not in html
    assert "HEALTHY" not in html
    assert 'class="dashboard-trust closed-beta-notice"' in html
    for copy in (
        "Closed Beta / \u6d4b\u8bd5\u9636\u6bb5",
        "\u9884\u6d4b\u4ec5\u4f9b\u6bd4\u8d5b\u5206\u6790\u4e0e\u7814\u7a76\u53c2\u8003\uff0c\u53ef\u80fd\u51fa\u9519\u3002",
        "\u672c\u4ea7\u54c1\u4e0d\u63d0\u4f9b\u8d2d\u5f69\u3001\u4ee3\u8d2d\u3001\u6536\u6b3e\u3001\u4e0b\u6ce8\u6216\u51fa\u7968\u670d\u52a1\u3002",
        "\u5982\u53c2\u4e0e\u5408\u6cd5\u5f69\u7968\u8d2d\u4e70\uff0c\u8bf7\u901a\u8fc7\u5408\u6cd5\u6b63\u89c4\u6e20\u9053\u5e76\u7406\u6027\u53c2\u4e0e\uff1b\u672a\u6210\u5e74\u4eba\u4e0d\u5f97\u8d2d\u4e70\u5f69\u7968\u3002",
    ):
        assert copy in html
    for forbidden in (
        "今日新增正式样本",
        "试运行样本",
        "silent_missing_fixture = 0",
        "λ 主队",
        "λ 客队",
        "冻结时距开赛",
        "等待赛果",
    ):
        assert forbidden not in html


def test_dashboard_keeps_formal_market_summary_compact_and_independent(tmp_path):
    prediction_id = "FBOS-PRED-formal-summary"
    record = frozen_prediction(prediction_id)
    record.update(formal_record(prediction_id=prediction_id, match_id="1001"))
    roots = make_roots(
        tmp_path,
        [fixture(1)],
        [frozen_job("1001", prediction_id)],
        [record],
    )

    payload = build_dashboard(DATE, **roots)
    prediction = payload["fixtures"][0]["prediction"]
    markets = prediction["formal_markets"]["markets"]
    assert markets["exact_score"]["status"] == "AVAILABLE"
    assert markets["exact_score"]["cell_count"] == 169
    assert markets["jc_total_goals"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["status"] == "AVAILABLE"
    assert "cells" not in markets["exact_score"]

    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert 'data-formal-market="exact_score"' in html
    assert 'data-formal-market="jc_total_goals"' in html
    assert 'data-formal-market="jc_handicap"' in html
    assert 'class="exact-grid"' not in html


def test_dashboard_publishes_workspace_completed_history_when_current_cards_have_no_results(tmp_path):
    roots = make_roots(tmp_path, [fixture(1)], [{"match_id": "1001", "status": "PENDING"}])
    workspace_path = tmp_path / "workspace" / "latest.json"
    write_json(workspace_path, {
        "completed": [],
        "history": [{
            "id": "FBOS-HISTORY-1",
            "home": "Lyon",
            "away": "Sparta Prague",
            "kickoff": "2026-08-12T03:00+08:00",
            "result_90m": "3-0",
            "prediction_frozen": True,
            "review_available": True,
            "historical_status": "FROZEN_PREMATCH_AND_REVIEW",
            "prematch_report_url": "../analysis_reports/prematch.html",
            "postmatch_report_url": "../postmatch_reports/review.html",
        }],
    })

    payload = build_dashboard(DATE, workspace_path=workspace_path, **roots)

    assert payload["summary"]["completed_count"] == 0
    assert payload["summary"]["historical_validation_count"] == 1
    assert payload["summary"]["history_count"] == 1
    assert payload["completed"][0]["result_90m"] == "3-0"
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "historical-results" in html
    assert "\u5386\u53f2\u9a8c\u8bc1" in html
    assert "Lyon" in html
    assert "3-0" in html


def test_upcoming_filter_requires_a_future_parseable_kickoff_not_result_absence(tmp_path):
    future = fixture(1)
    future.update({"matchDate": DATE, "matchTime": "23:00:00"})
    past_without_result = fixture(2)
    past_without_result.update({"matchDate": DATE, "matchTime": "01:00:00"})
    past_with_result = fixture(3)
    past_with_result["kickoff"] = "2026-08-11T23:00:00+08:00"
    invalid = fixture(4)
    invalid["kickoff"] = "not-a-kickoff"
    roots = make_roots(
        tmp_path,
        [future, past_without_result, past_with_result, invalid],
        [
            {"match_id": "1001", "status": "PENDING"},
            {"match_id": "1002", "status": "PENDING"},
            {"match_id": "1003", "status": "PENDING"},
            {"match_id": "1004", "status": "PENDING"},
        ],
    )
    write_json(roots["result_root"] / "past.json", {
        "match_id": "1003",
        "result_90m": "1-0",
        "verified_at": "2026-08-12T12:00:00+08:00",
    })

    payload = build_dashboard(
        DATE,
        now=datetime.fromisoformat("2026-08-12T12:00:00+08:00"),
        **roots,
    )
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    by_id = {card["match_id"]: card for card in payload["fixtures"]}

    assert by_id["1001"]["kickoff_timestamp"] == "2026-08-12T15:00:00Z"
    assert by_id["1002"]["kickoff_timestamp"] == "2026-08-11T17:00:00Z"
    assert by_id["1003"]["result"]["score_90m"] == "1-0"
    assert by_id["1004"]["kickoff_timestamp"] is None
    assert 'data-kickoff="2026-08-12T15:00:00Z"' in html
    assert 'data-kickoff="2026-08-11T17:00:00Z"' in html
    assert 'data-kickoff=""' in html
    assert "Number.isFinite(kickoffTimestamp) && Date.now() < kickoffTimestamp" in html
    assert "card.dataset.result !== 'yes'" not in html


def test_completed_filter_is_current_verified_only_and_history_is_independent(tmp_path):
    current = fixture(1)
    roots = make_roots(tmp_path, [current], [{"match_id": "1001", "status": "PENDING"}])
    write_json(roots["result_root"] / "current.json", {
        "match_id": "1001",
        "result_90m": "2-1",
        "verified_at": "2026-08-12T12:00:00+08:00",
    })
    workspace_path = tmp_path / "workspace" / "latest.json"
    write_json(workspace_path, {
        "completed": [{
            "id": "H-1",
            "home": "Historical FC",
            "away": "Archive FC",
            "kickoff": "2026-08-10T03:00+08:00",
            "result_90m": "0-0",
            "review_available": True,
        }],
        "history": [],
    })

    payload = build_dashboard(DATE, workspace_path=workspace_path, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert payload["summary"]["completed_count"] == 1
    assert payload["summary"]["historical_validation_count"] == 1
    assert 'data-result-count="1"' in html
    assert "2-1" in html
    assert "Historical FC" in html
    assert "\u5386\u53f2\u9a8c\u8bc1" in html
    assert "filter !== 'ALL'" in html
    assert "filter !== 'ALL' && filter !== 'RESULT'" not in html


def test_dashboard_filter_empty_states_use_current_verified_count_and_restore_all():
    payload = {
        "business_date": DATE,
        "summary": {
            "fixture_count": 1,
            "verified_results": 0,
            "completed_count": 99,
        },
        "prediction_quality_health": {
            "status": "HEALTHY",
            "scope": "current_serving",
            "available": True,
            "provenance_status": "MATCHED",
        },
        "system_runtime_health": {"overall_status": "HEALTHY"},
        "fixtures": [{
            "match_id": "1001",
            "match_num": "T001",
            "competition": "Fixture League",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff": "2099-08-12T20:00:00+08:00",
            "kickoff_timestamp": "2099-08-12T12:00:00Z",
            "status": "PENDING",
            "prediction": None,
            "result": None,
        }],
        "completed": [{"home": "Historical FC", "away": "Archive FC", "result_90m": "4-0"}],
        "history": [],
    }

    html = render_dashboard(payload)

    assert 'data-result-count="0"' in html
    assert 'data-filter-empty="UPCOMING"' in html
    assert 'data-filter-empty="RESULT"' in html
    assert "\u5f53\u524d\u7ade\u5f69\u65e5\u6682\u65e0\u672a\u5f00\u8d5b\u6bd4\u8d5b" in html
    assert "\u5f53\u524d\u7ade\u5f69\u65e5\u6682\u65e0\u5df2\u7ed3\u675f\u5e76\u6838\u9a8c\u7684\u6bd4\u8d5b" in html
    assert 'data-filter-empty="ALL"' not in html


def test_dashboard_overall_empty_state_requires_zero_current_fixture_count():
    payload = {
        "business_date": DATE,
        "summary": {"fixture_count": 0, "verified_results": 0, "completed_count": 12},
        "prediction_quality_health": {},
        "system_runtime_health": {"overall_status": "HEALTHY"},
        "fixtures": [],
        "completed": [{"home": "Historical FC", "away": "Archive FC", "result_90m": "1-0"}],
        "history": [],
    }

    html = render_dashboard(payload)

    assert 'data-filter-empty="ALL"' in html
    assert "\u4eca\u5929\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u6bd4\u8d5b\u3002" in html


def test_dashboard_selects_latest_legal_prematch_version_and_excludes_post_kickoff_record(tmp_path):
    current_fixture = fixture(1)
    current_fixture.update({"homeTeam": "\u65af\u6258\u514b\u57ce", "awayTeam": "\u8d6b\u5c14\u57ce"})
    job = frozen_job("1001", "FBOS-PRED-stale")
    job.update({
        "home": "\u65af\u6258\u514b\u57ce",
        "away": "\u8d6b\u5c14\u57ce",
        "prediction_ids": ["FBOS-PRED-early", "FBOS-PRED-latest", "FBOS-PRED-late"],
    })
    early = frozen_prediction(
        "FBOS-PRED-early",
        home="\u65af\u6258\u514b\u57ce",
        away="\u8d6b\u5c14\u57ce",
        source_cutoff="2026-08-12T22:00:00+08:00",
        prediction_created="2026-08-12T22:05:00+08:00",
        freeze_created="2026-08-12T22:06:00+08:00",
    )
    latest = frozen_prediction(
        "FBOS-PRED-latest",
        home="\u65af\u6258\u514b\u57ce",
        away="\u8d6b\u5c14\u57ce",
        source_cutoff="2026-08-13T03:10:00+08:00",
        prediction_created="2026-08-13T03:15:00+08:00",
        freeze_created="2026-08-13T03:16:00+08:00",
        unique_score="1-1",
    )
    late = frozen_prediction(
        "FBOS-PRED-late",
        home="\u65af\u6258\u514b\u57ce",
        away="\u8d6b\u5c14\u57ce",
        source_cutoff="2026-08-13T03:50:00+08:00",
        prediction_created="2026-08-13T04:05:00+08:00",
        freeze_created="2026-08-13T04:05:00+08:00",
    )
    roots = make_roots(tmp_path, [current_fixture], [job], [early, latest, late])

    payload = build_dashboard(
        DATE,
        now=datetime.fromisoformat("2026-08-13T03:30:00+08:00"),
        **roots,
    )

    card = payload["fixtures"][0]
    assert card["prediction_id"] == "FBOS-PRED-latest"
    assert card["selected_prediction_id"] == "FBOS-PRED-latest"
    assert card["current_prediction_id"] == "FBOS-PRED-latest"
    assert card["selected_source_cutoff_at"] == "2026-08-13T03:10:00+08:00"
    assert card["selected_freeze_created_at"] == "2026-08-13T03:16:00+08:00"
    assert card["superseded_count"] == 1
    assert card["prematch_selection"]["candidate_count"] == 2
    assert card["prematch_selection"]["status"] == "SELECTED"
    assert card["prediction"]["primary_score"] == "1-1"


def test_dashboard_fails_closed_on_same_job_identity_conflict(tmp_path):
    roots = make_roots(
        tmp_path,
        [fixture(1)],
        [frozen_job("1001", "FBOS-PRED-good")],
        [
            frozen_prediction("FBOS-PRED-good"),
            frozen_prediction("FBOS-PRED-conflict", home="\u53e6\u4e00\u4e3b\u961f"),
        ],
    )

    payload = build_dashboard(DATE, **roots)

    card = payload["fixtures"][0]
    assert card["prediction_id"] is None
    assert card["prematch_selection"]["status"] == "IDENTITY_CONFLICT"
    assert card["selected_prediction_id"] is None


def test_dashboard_current_job_conflict_is_order_invariant_and_abstains(tmp_path):
    retained = frozen_prediction("FBOS-PRED-retained")
    frozen = frozen_job("1001", retained["prediction_id"])
    insufficient = {
        **frozen,
        "job_id": "BASE-2026-08-12-1001-retry",
        "status": "INSUFFICIENT_DATA",
        "last_error": "SOURCE_FETCH_FAILED",
    }
    projections = []
    article_html = []
    for index, ordered_jobs in enumerate(([frozen, insufficient], [insufficient, frozen])):
        roots = make_roots(
            tmp_path / f"order-{index}",
            [fixture(1)],
            ordered_jobs,
            [retained],
        )
        payload = build_dashboard(DATE, **roots)
        card = payload["fixtures"][0]
        html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
        article = re.search(
            r'<article[^>]*data-status="CURRENT_JOB_STATE_CONFLICT"[^>]*>.*?</article>',
            html,
            re.S,
        ).group(0)
        projections.append({
            "status": card["status"],
            "reason_code": card["reason_code"],
            "prediction": card["prediction"],
            "prematch_selection": card["prematch_selection"],
            "current_job_resolution": card["current_job_resolution"],
        })
        article_html.append(article)

    assert projections[0] == projections[1]
    card = projections[0]
    assert card["status"] == "CURRENT_JOB_STATE_CONFLICT"
    assert card["reason_code"] == "DUPLICATE_CURRENT_JOB_STATE"
    assert card["prediction"] is None
    assert card["prematch_selection"]["status"] == "CONFLICT"
    assert card["current_job_resolution"]["status"] == "CONFLICT"
    assert card["current_job_resolution"]["row_count"] == 2
    for article in article_html:
        assert "prediction-panel" not in article
        assert "probability-grid" not in article
        assert "1X2" not in article
        assert "系统首推比分" not in article
        assert "本场状态待确认" in article
        assert "本场状态待确认，暂不形成预测" in article


def test_dashboard_duplicate_frozen_rows_fail_closed_without_double_serving(tmp_path):
    retained = frozen_prediction("FBOS-PRED-duplicate")
    frozen = frozen_job("1001", retained["prediction_id"])
    duplicate = {**frozen, "job_id": "BASE-2026-08-12-1001-duplicate"}
    roots = make_roots(tmp_path, [fixture(1)], [frozen, duplicate], [retained])

    payload = build_dashboard(DATE, **roots)

    card = payload["fixtures"][0]
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    article = re.search(
        r'<article[^>]*data-status="CURRENT_JOB_STATE_CONFLICT"[^>]*>.*?</article>',
        html,
        re.S,
    ).group(0)
    assert card["status"] == "CURRENT_JOB_STATE_CONFLICT"
    assert card["prediction"] is None
    assert card["current_job_resolution"]["row_count"] == 2
    assert "prediction-panel" not in article
    assert "系统首推比分" not in article
    assert "1X2" not in article


def test_completed_filter_controls_historical_rows_and_real_count(tmp_path):
    roots = make_roots(tmp_path, [fixture(1)], [{"match_id": "1001", "status": "PENDING"}])
    workspace_path = tmp_path / "workspace" / "latest.json"
    write_json(workspace_path, {
        "completed": [
            {"id": "H-1", "home": "Lyon", "away": "Sparta", "kickoff": "2026-08-12T03:00+08:00", "result_90m": "3-0", "review_available": True},
            {"id": "H-2", "home": "Graz", "away": "Fenerbahce", "kickoff": "2026-08-12T02:30+08:00", "result_90m": "0-1", "review_available": True},
        ],
        "history": [],
    })

    payload = build_dashboard(DATE, workspace_path=workspace_path, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert payload["summary"]["completed_count"] == 0
    assert payload["summary"]["historical_validation_count"] == 2
    assert 'data-filter="RESULT"' in html
    assert 'data-result-count="0"' in html
    assert "historicalResults" in html
    assert "\u5386\u53f2\u9a8c\u8bc1" in html
    assert "filter !== 'ALL' && filter !== 'RESULT'" not in html
    assert html.count('class="history-row"') == 2


def test_dashboard_counterexamples_cover_zero_one_and_twenty_five_fixtures(tmp_path):
    for count in (0, 1, 25):
        fixture_rows = [fixture(index) for index in range(1, count + 1)]
        if count == 1:
            fixture_rows[0]["homeTeam"] = "A team name that is intentionally long for reflow"
            fixture_rows[0]["awayTeam"] = "Another intentionally long away team name"
        roots = make_roots(tmp_path / f"count-{count}", fixture_rows, [])

        payload = build_dashboard(DATE, **roots)
        html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

        assert payload["summary"]["card_count"] == count
        assert html.count('<article class="fixture-row ') == count
        assert 'class="status-badge"' not in html
        if count == 0:
            assert "\u4eca\u5929\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u6bd4\u8d5b" in html
        if count == 1:
            assert "A team name that is intentionally long for reflow" in html
            assert "Another intentionally long away team name" in html


def test_universe_fourteen_keeps_every_fixture_without_prediction_artifact(tmp_path):
    fixtures = [fixture(index) for index in range(1, 15)]
    roots = make_roots(tmp_path, fixtures, [])

    payload = build_dashboard(DATE, **roots)

    assert payload["summary"]["fixture_count"] == 14
    assert payload["summary"]["card_count"] == 14
    assert payload["summary"]["silent_missing_fixture"] == 0
    assert all(card["status"] == "PENDING" for card in payload["fixtures"])


def test_dashboard_preserves_data_shortage_pending_and_missed_reasons(tmp_path):
    fixtures = [fixture(index) for index in range(1, 4)]
    roots = make_roots(tmp_path, fixtures, [
        {"job_id": "BASE-2026-08-12-1001", "match_id": "1001", "status": "INSUFFICIENT_DATA", "last_error": "MISSING_RECENT_FORM"},
        {"job_id": "BASE-2026-08-12-1002", "match_id": "1002", "status": "PENDING"},
        {"job_id": "BASE-2026-08-12-1003", "match_id": "1003", "status": "MISSED_PREMATCH_WINDOW", "last_error": "MISSED_PREMATCH_WINDOW"},
    ])

    payload = build_dashboard(DATE, **roots)

    by_id = {card["match_id"]: card for card in payload["fixtures"]}
    assert by_id["1001"]["reason_code"] == "MISSING_RECENT_FORM"
    assert by_id["1001"]["reason_text"] == "近期比赛数据不足"
    assert by_id["1002"]["status"] == "PENDING"
    assert by_id["1003"]["status"] == "MISSED_PREMATCH_WINDOW"
    assert payload["summary"]["missed"] == 1
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "近期比赛数据不足" in html
    assert "MISSING_RECENT_FORM" not in html
    assert "未形成合法赛前预测" in html


def test_dashboard_hides_retained_recommendation_for_insufficient_current_job(tmp_path):
    served_id = "FBOS-PRED-served"
    retained_id = "FBOS-PRED-retained"
    served = {**frozen_prediction(served_id), "business_date": DATE}
    retained = {
        **frozen_prediction(
            retained_id,
            home="主队2",
            away="客队2",
            match_id="1002",
            job_id=f"BASE-{DATE}-1002",
            match_key="FBOS-TEST-2",
            kickoff="2026-08-13T05:00:00+08:00",
            source_cutoff="2026-08-12T12:00:00+08:00",
            prediction_created="2026-08-12T14:00:00+08:00",
            freeze_created="2026-08-12T14:01:00+08:00",
            unique_score="2-2",
        ),
        "business_date": DATE,
    }
    for record in (served, retained):
        record.update({
            "model_input_snapshot_ref": "data/model_governance/input_snapshots/test.json",
            "input_sha256": "a" * 64,
            "model_source_fingerprint": "champion-fingerprint",
            "formal_eligibility_policy": "base_prediction_minimum.v1",
            "analysis_output": {"report_type": "base_prediction_minimal"},
        })
    roots = make_roots(
        tmp_path,
        [fixture(1), fixture(2)],
        [
            frozen_job("1001", served_id),
            {
                **frozen_job("1002", retained_id),
                "home": "主队2",
                "away": "客队2",
                "kickoff": "2026-08-13T05:00:00+08:00",
                "status": "INSUFFICIENT_DATA",
                "last_error": "SOURCE_FETCH_FAILED",
            },
        ],
        [served, retained],
    )
    runtime = json.loads(roots["runtime_path"].read_text(encoding="utf-8"))
    runtime["business_date"] = DATE
    write_json(roots["runtime_path"], runtime)

    payload = build_dashboard(DATE, **roots)
    by_id = {card["match_id"]: card for card in payload["fixtures"]}
    insufficient = by_id["1002"]
    frozen = by_id["1001"]
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    insufficient_html = re.search(
        r'<article[^>]*data-status="INSUFFICIENT_DATA"[^>]*>.*?</article>',
        html,
        re.S,
    ).group(0)

    assert insufficient["prediction_id"] == retained_id
    assert insufficient["status"] == "INSUFFICIENT_DATA"
    assert insufficient["reason_code"] == "SOURCE_FETCH_FAILED"
    assert insufficient["reason_text"]
    assert insufficient["prediction"] is None
    assert "prediction-panel" not in insufficient_html
    assert "probability-grid" not in insufficient_html
    assert "1X2" not in insufficient_html
    assert "最高概率比分" not in insufficient_html
    assert insufficient["reason_text"] in insufficient_html
    assert frozen["prediction"]["primary_score"] == "1-0"
    frozen_html = re.search(
        r'<article[^>]*data-status="FROZEN"[^>]*>.*?</article>',
        html,
        re.S,
    ).group(0)
    assert "probability-grid" in frozen_html
    assert "最高概率比分" in frozen_html
    assert payload["prediction_quality_health"]["current_job_count"] == 2
    assert payload["prediction_quality_health"]["current_frozen_job_count"] == 1
    assert payload["prediction_quality_health"]["selected_record_count"] == 1


def test_pilot_exclusion_and_formal_sample_are_distinguished(tmp_path):
    fixtures = [fixture(1), fixture(2)]
    excluded_id = "FBOS-PRED-pilot"
    formal_id = "FBOS-PRED-formal"
    roots = make_roots(tmp_path, fixtures, [
        frozen_job("1001", excluded_id),
        {**frozen_job("1002", formal_id), "match_num": "T002", "home": "主队2", "away": "客队2"},
    ], [
        {**frozen_prediction(excluded_id), "match_key": "FBOS-TEST-1"},
        {**frozen_prediction(formal_id), "match_key": "FBOS-TEST-2", "match_identity": {"home": "主队2", "away": "客队2"}},
    ])
    formal_path = roots["prediction_root"] / f"{formal_id}.json"
    formal_record = json.loads(formal_path.read_text(encoding="utf-8"))
    formal_record.update({
        "match_id": "1002",
        "job_id": "BASE-2026-08-12-1002",
        "home": "\u4e3b\u961f2",
        "away": "\u5ba2\u961f2",
        "match_identity": {
            "home": "\u4e3b\u961f2",
            "away": "\u5ba2\u961f2",
            "kickoff_at": "2026-08-13T04:00:00+08:00",
        },
    })
    write_json(formal_path, formal_record)
    write_json(roots["exclusion_root"] / "pilot.json", {
        "prediction_ids": [excluded_id],
        "reason_code": "BASE_QUALITY_GATE_BYPASS",
        "formal_prospective_eligible": False,
    })
    (roots["prospective_root"] / "ledger.jsonl").write_text(
        json.dumps({"prediction_id": formal_id, "metrics": {"1x2_brier": 0.2}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    payload = build_dashboard(DATE, **roots)

    cards = {card["prediction_id"]: card for card in payload["fixtures"]}
    assert cards[excluded_id]["pilot_excluded"] is True
    assert cards[excluded_id]["formal_prospective"] is False
    assert cards[formal_id]["formal_prospective"] is True
    assert cards[formal_id]["evaluation"]["metrics"]["1x2_brier"] == 0.2
    assert cards[excluded_id]["status_label"] == "试运行预测"
    assert cards[formal_id]["status_label"] == "已形成预测"

    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    pilot_match = re.search(r'<article[^>]*data-prediction-kind="pilot"[^>]*>.*?</article>', html, re.S)
    formal_match = re.search(r'<article[^>]*data-prediction-kind="formal"[^>]*>.*?</article>', html, re.S)
    assert pilot_match is not None
    assert formal_match is not None
    pilot_html = pilot_match.group(0)
    formal_html = formal_match.group(0)
    assert "试运行预测 · 仅供观察" in pilot_html
    assert "已形成预测" not in pilot_html
    assert "试运行预测" not in formal_html
    assert "最高概率比分" in formal_html
    assert "1-0 15.5%" in formal_html
    assert "probability-grid" in formal_html


def test_dashboard_is_read_only_projection_without_model_or_network_imports():
    source = (ROOT / "scripts" / "prediction_dashboard.py").read_text(encoding="utf-8")
    assert "automatic_model_core" not in source
    assert "urllib" not in source
    assert "requests" not in source


def test_noncanonical_snapshot_fields_do_not_become_market_lines(tmp_path):
    prediction_id = "FBOS-PRED-market-view"
    roots = make_roots(tmp_path, [fixture(1)], [frozen_job("1001", prediction_id)], [
        {**frozen_prediction(prediction_id),
         "input_snapshot": {
             "source_snapshots": {
                 "500_deep": {"snapshots": [{
                     "yazhi": {"companies": [{"current_handicap": -0.75}]},
                     "daxiao": {"companies": [{"current_line": 2.25}]},
                 }]}
             }
         },
         "score_top3": [],
         "score_distribution": [
             {"score": "1-0", "probability": 0.20},
             {"score": "1-1", "probability": 0.16},
             {"score": "2-0", "probability": 0.12},
             {"score": "0-0", "probability": 0.08},
         ]}
    ])
    payload = build_dashboard(DATE, **roots)
    prediction = payload["fixtures"][0]["prediction"]

    assert prediction["primary_score"] == "1-0"
    assert prediction["neighbor_scores"] == ["1-1", "2-0"]
    assert prediction["score_distribution"][0]["score"] == "1-0"
    assert prediction["score_concentration"] is None
    assert prediction["market_summary"] == {}
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "1-0 20.0%" in html
    assert "Top5" not in html
    assert "AH ·" not in html
    assert "O/U ·" not in html


def test_canonical_market_summary_and_score_concentration_are_display_only(tmp_path):
    prediction_id = "FBOS-PRED-canonical-view"
    record = {
        **frozen_prediction(prediction_id),
        "score_concentration": "集中度高",
        "market_summary": {
            "asian_handicap": {"line": "-0.75"},
            "total_line": {"line": "2.25"},
        },
    }
    roots = make_roots(tmp_path, [fixture(1)], [frozen_job("1001", prediction_id)], [record])

    payload = build_dashboard(DATE, **roots)
    prediction = payload["fixtures"][0]["prediction"]
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "AH · 主 -0.75" not in html
    assert "O/U · 2.25" not in html
    assert "1X2 概率" in html


def test_dashboard_goal_signals_keep_both_sides_visible(tmp_path):
    prediction_id = "FBOS-PRED-two-sided-goals"
    record = frozen_prediction(prediction_id)
    record["btts"] = {"yes": 0.537, "no": 0.463}
    record["totals"] = [
        {"goals": "0", "probability": 0.120},
        {"goals": "1", "probability": 0.180},
        {"goals": "2", "probability": 0.206},
        {"goals": "3", "probability": 0.180},
        {"goals": "4", "probability": 0.160},
        {"goals": "5", "probability": 0.154},
    ]
    roots = make_roots(tmp_path, [fixture(1)], [frozen_job("1001", prediction_id)], [record])

    build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert "\u53cc\u65b9\u8fdb\u7403 \u662f 53.7%" in html
    assert "\u53cc\u65b9\u8fdb\u7403 \u5426 46.3%" in html
    assert "\u5927\u5c0f2.5 \u5c0f 50.6%" in html
    assert "\u5927\u5c0f2.5 \u5927 49.4%" in html
    assert "BTTS \u5426 53.7%" not in html


def _serving_prediction(index: int, score: str) -> dict:
    match_id = str(2000 + index)
    home = f"Home {index}"
    away = f"Away {index}"
    prediction_id = f"FBOS-PRED-quality-{index}"
    record = frozen_prediction(
        prediction_id,
        home=home,
        away=away,
        match_id=match_id,
        job_id=f"BASE-{DATE}-{match_id}",
        match_key=f"FBOS-QUALITY-{index}",
        unique_score=score,
    )
    record["business_date"] = DATE
    record.update({
        "model_input_snapshot_ref": f"data/model_governance/input_snapshots/{prediction_id}.json",
        "input_sha256": f"input-{prediction_id}",
        "model_source_fingerprint": "champion-fingerprint",
        "critical_missing_fields": [],
        "missing_critical_fields": [],
        "formal_eligibility_policy": "base_prediction_minimum.v1",
        "analysis_output": {"report_type": "base_prediction_minimal"},
    })
    record["match_identity"] = {
        "match_id": match_id,
        "match_key": f"FBOS-QUALITY-{index}",
        "home": home,
        "away": away,
        "kickoff_at": record["kickoff_at"],
    }
    return record


def _quality_roots(tmp_path, scores: list[str]):
    fixtures = []
    jobs = []
    predictions = []
    for index, score in enumerate(scores, 1):
        match_id = str(2000 + index)
        home = f"Home {index}"
        away = f"Away {index}"
        fixture_row = fixture(index)
        fixture_row.update({"matchId": match_id, "homeTeam": home, "awayTeam": away})
        fixtures.append(fixture_row)
        prediction = _serving_prediction(index, score)
        predictions.append(prediction)
        jobs.append({
            **frozen_job(match_id, prediction["prediction_id"]),
            "match_num": f"T{index:03d}",
            "home": home,
            "away": away,
        })
    roots = make_roots(tmp_path, fixtures, jobs, predictions)
    runtime = json.loads(roots["runtime_path"].read_text(encoding="utf-8"))
    runtime["business_date"] = DATE
    write_json(roots["runtime_path"], runtime)
    roots["health_watch_path"] = tmp_path / "runtime" / "health_watch.json"
    return roots, runtime


def test_dashboard_normal_current_job_cohort_has_eight_serving_and_five_reason_only(tmp_path):
    fixtures = []
    jobs = []
    predictions = []
    for index in range(13):
        match_id = str(2001 + index)
        home = f"Home {index + 1}"
        away = f"Away {index + 1}"
        fixture_row = fixture(index + 1)
        fixture_row.update({"matchId": match_id, "homeTeam": home, "awayTeam": away})
        record = _serving_prediction(index + 1, "1-1" if index < 8 else f"{index % 3}-{(index + 1) % 4}")
        predictions.append(record)
        fixtures.append(fixture_row)
        jobs.append({
            **frozen_job(match_id, record["prediction_id"]),
            "match_num": f"T{index + 1:03d}",
            "home": home,
            "away": away,
            "status": "FROZEN" if index < 8 else "INSUFFICIENT_DATA",
            "last_error": None if index < 8 else "SOURCE_FETCH_FAILED",
        })

    roots = make_roots(tmp_path, fixtures, jobs, predictions)
    runtime = json.loads(roots["runtime_path"].read_text(encoding="utf-8"))
    runtime["business_date"] = DATE
    write_json(roots["runtime_path"], runtime)

    payload = build_dashboard(DATE, **roots)
    serving = [card for card in payload["fixtures"] if card["prediction"] is not None]
    insufficient = [card for card in payload["fixtures"] if card["status"] == "INSUFFICIENT_DATA"]

    assert payload["summary"]["card_count"] == 13
    assert len(serving) == 8
    assert len(insufficient) == 5
    assert all(card["prediction"] is None for card in insufficient)
    assert payload["prediction_quality_health"]["unique_current_match_count"] == 13
    assert payload["prediction_quality_health"]["duplicate_current_job_count"] == 0
    assert payload["prediction_quality_health"]["selected_record_count"] == 8


def test_dashboard_separates_system_runtime_and_current_prediction_quality_alert(tmp_path):
    roots, runtime = _quality_roots(tmp_path, ["1-1"] * 9 + ["2-1"])
    write_json(roots["health_watch_path"], {
        "schema_version": "1.0",
        "updated_at": "2026-08-12T12:06:00+08:00",
        "current_status": "ALERT",
        "business_date": DATE,
        "last_cycle_generated_at": runtime["finished_at"],
        "prediction_quality_health": {
            "status": "ALERT",
            "scope": "current_serving",
            "business_date": DATE,
            "runtime_cycle_finished_at": runtime["finished_at"],
            "reasons": ["SCORE_SELECTOR_COLLAPSE"],
        },
    })

    payload = build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert payload["system_runtime_health"]["status"] == "HEALTHY"
    assert payload["prediction_quality_health"]["status"] == "ALERT"
    assert payload["prediction_quality_health"]["scope"] == "current_serving"
    assert payload["prediction_quality_health"]["business_date"] == DATE
    assert "系统运行" not in html
    assert "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf" in html
    assert "\u5f53\u524d\u8d28\u91cf\u5f02\u5e38\uff0c\u6682\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u6bd4\u5206\u63a8\u8350\uff1b\u539f\u59cb\u6bd4\u5206\u6982\u7387\u7ee7\u7eed\u4fdd\u7559\u3002\u0031X2\u3001\u53cc\u65b9\u8fdb\u7403\u3001\u5927\u5c0f\u0032.5\u6309\u5404\u81ea\u6982\u7387\u5c55\u793a\u3002" in html
    assert "系统首推比分" not in html


def test_dashboard_keeps_exact_score_state_visible_inside_each_score_cell(tmp_path):
    roots, runtime = _quality_roots(tmp_path, ["1-1"] * 9 + ["2-1"])
    write_json(roots["health_watch_path"], {
        "business_date": DATE,
        "last_cycle_generated_at": runtime["finished_at"],
        "prediction_quality_health": {
            "status": "ALERT",
            "scope": "current_serving",
            "business_date": DATE,
            "runtime_cycle_finished_at": runtime["finished_at"],
            "reasons": ["SCORE_SELECTOR_COLLAPSE"],
        },
    })

    build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert 'data-score-serving-state="DEGRADED"' in html
    assert "\u6a21\u578b\u539f\u59cb\u6bd4\u5206" in html
    assert "\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf" in html


def test_dashboard_uses_normal_exact_score_copy_only_for_healthy_matched_current_serving(tmp_path):
    roots, runtime = _quality_roots(tmp_path, [f"{index}-{index + 1}" for index in range(1, 11)])
    write_json(roots["health_watch_path"], {
        "schema_version": "1.0",
        "updated_at": "2026-08-12T12:06:00+08:00",
        "current_status": "HEALTHY",
        "business_date": DATE,
        "last_cycle_generated_at": runtime["finished_at"],
        "prediction_quality_health": {
            "status": "HEALTHY",
            "scope": "current_serving",
            "business_date": DATE,
            "runtime_cycle_finished_at": runtime["finished_at"],
            "reasons": [],
        },
    })

    payload = build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert payload["prediction_quality_health"]["status"] == "HEALTHY"
    assert payload["prediction_quality_health"]["available"] is True
    assert payload["prediction_quality_health"]["provenance_status"] == "MATCHED"
    assert "预测质量降级" not in html
    assert 'class="quality-warning"' not in html
    assert "最高概率比分" in html


def test_dashboard_does_not_use_mismatched_health_watch_as_current_quality(tmp_path):
    roots, runtime = _quality_roots(tmp_path, [f"{index}-{index + 1}" for index in range(1, 11)])
    write_json(roots["health_watch_path"], {
        "schema_version": "1.0",
        "updated_at": "2026-08-12T12:06:00+08:00",
        "current_status": "ALERT",
        "business_date": "2026-08-11",
        "last_cycle_generated_at": "2026-08-11T12:05:00+08:00",
        "prediction_quality_health": {
            "status": "ALERT",
            "scope": "current_serving",
            "business_date": "2026-08-11",
            "runtime_cycle_finished_at": "2026-08-11T12:05:00+08:00",
            "reasons": ["SCORE_SELECTOR_COLLAPSE"],
        },
    })

    payload = build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert payload["system_runtime_health"]["status"] == "HEALTHY"
    assert payload["prediction_quality_health"]["status"] == "HEALTHY"
    assert payload["prediction_quality_health"]["provenance_status"] == "MISMATCHED"
    assert "预测质量降级" not in html
    assert "质量待确认，不作为正常推荐" in html


def test_dashboard_rejects_health_watch_from_previous_cycle_even_on_same_business_date(tmp_path):
    roots, runtime = _quality_roots(tmp_path, [f"{index}-{index + 1}" for index in range(1, 11)])
    previous_cycle = "2026-08-12T12:04:59+08:00"
    write_json(roots["health_watch_path"], {
        "schema_version": "1.0",
        "updated_at": "2026-08-12T12:05:00+08:00",
        "current_status": "ALERT",
        "business_date": DATE,
        "last_cycle_generated_at": previous_cycle,
        "prediction_quality_health": {
            "status": "ALERT",
            "scope": "current_serving",
            "business_date": DATE,
            "runtime_cycle_finished_at": previous_cycle,
            "reasons": ["SCORE_SELECTOR_COLLAPSE"],
        },
    })

    payload = build_dashboard(DATE, **roots)

    assert payload["prediction_quality_health"]["status"] == "HEALTHY"
    assert payload["prediction_quality_health"]["provenance_status"] == "MISMATCHED"
    assert payload["prediction_quality_health"]["runtime_cycle_finished_at"] == runtime["finished_at"]
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "质量待确认，不作为正常推荐" in html


def test_abnormal_runtime_shows_warning_without_normal_kpi_grid(tmp_path):
    roots = make_roots(tmp_path, [fixture(1)], [{"match_id": "1001", "status": "PENDING"}])
    write_json(roots["runtime_path"], {
        "overall_status": "FAILED",
        "finished_at": "2026-08-12T12:05:00+08:00",
        "steps": {"base_prediction": {"status": "FAILED"}},
    })

    build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert "当前数据更新异常" in html
    assert "base_prediction" not in html
    assert "预测已冻结" not in html
