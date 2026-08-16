import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.prediction_dashboard import build_dashboard  # noqa: E402


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


def frozen_prediction(prediction_id: str) -> dict:
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
    assert "已预测" in html
    assert "预测已冻结" not in html
    assert "系统首推比分" in html
    assert "1X2 · 主胜倾向" in html
    assert "1–0" in html
    assert "1–1 · 2–0" in html
    assert "今日全部赛事" in html
    assert 'href="../matches/1001/"' in html
    assert "Prediction Universe" not in html
    assert "MISSING_RECENT_FORM" not in html
    assert "近期比赛数据不足" in html
    assert "2026-08-12 12:05" in html
    assert "Legacy 工作台" in html
    assert html.index('data-prediction-kind="formal"') < html.index("Legacy 工作台")
    for forbidden in (
        "今日新增正式样本",
        "试运行样本",
        "silent_missing_fixture = 0",
        "λ 主队",
        "λ 客队",
        "1X2 概率",
        "BTTS",
        "BASE 输入",
        "冻结时距开赛",
        "等待赛果",
        "模型偏大",
        "模型偏小",
        "集中",
        "中等",
        "分散",
    ):
        assert forbidden not in html


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

    assert payload["summary"]["completed_count"] == 1
    assert payload["summary"]["history_count"] == 1
    assert payload["completed"][0]["result_90m"] == "3-0"
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    assert "historical-results" in html
    assert "Lyon" in html
    assert "3-0" in html


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

    assert payload["summary"]["completed_count"] == 2
    assert 'data-filter="RESULT"' in html
    assert 'data-result-count="2"' in html
    assert "historicalResults" in html
    assert "filter !== 'ALL' && filter !== 'RESULT'" in html
    assert html.count('class="historical-result"') == 2


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
    assert "错过赛前窗口" in html


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
    assert cards[formal_id]["status_label"] == "已预测"

    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")
    pilot_match = re.search(r'<article[^>]*data-prediction-kind="pilot"[^>]*>.*?</article>', html, re.S)
    formal_match = re.search(r'<article[^>]*data-prediction-kind="formal"[^>]*>.*?</article>', html, re.S)
    assert pilot_match is not None
    assert formal_match is not None
    pilot_html = pilot_match.group(0)
    formal_html = formal_match.group(0)
    assert "试运行预测" in pilot_html
    assert "不纳入正式验证" in pilot_html
    assert "已预测" not in pilot_html
    assert "预测已冻结" not in pilot_html
    assert "已预测" in formal_html
    assert "预测已冻结" not in formal_html
    assert "1–0" in formal_html
    assert "1–1 · 2–0" in formal_html
    assert "1X2 · 主胜倾向" in formal_html


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
    assert "1–0" in html
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

    assert prediction["score_concentration"] == "集中度高"
    assert prediction["market_summary"]["asian_handicap"]["line"] == "-0.75"
    assert prediction["market_summary"]["total_line"]["line"] == "2.25"
    assert "AH · 主 -0.75" in html
    assert "O/U · 2.25" in html


def test_abnormal_runtime_shows_warning_without_normal_kpi_grid(tmp_path):
    roots = make_roots(tmp_path, [fixture(1)], [{"match_id": "1001", "status": "PENDING"}])
    write_json(roots["runtime_path"], {
        "overall_status": "FAILED",
        "finished_at": "2026-08-12T12:05:00+08:00",
        "steps": {"base_prediction": {"status": "FAILED"}},
    })

    build_dashboard(DATE, **roots)
    html = (roots["output_root"] / "latest.html").read_text(encoding="utf-8")

    assert "系统状态 · FAILED" in html
    assert "base_prediction" in html
    assert "预测已冻结" not in html
