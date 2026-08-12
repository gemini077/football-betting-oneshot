import json
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
    return {
        "universe_root": universe_root,
        "jobs_root": jobs_root,
        "prediction_root": prediction_root,
        "exclusion_root": exclusion_root,
        "result_root": result_root,
        "prospective_root": prospective_root,
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
    assert "预测已冻结" in html
    assert "本日新增正式样本" in html
    assert "Pilot excluded" in html


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


def test_dashboard_is_read_only_projection_without_model_or_network_imports():
    source = (ROOT / "scripts" / "prediction_dashboard.py").read_text(encoding="utf-8")
    assert "automatic_model_core" not in source
    assert "urllib" not in source
    assert "requests" not in source
