import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.legacy_analysis_mapper as legacy_mapper_module

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.match_analysis import (  # noqa: E402
    ANALYSIS_CONTRACT_VERSION,
    assemble_match_analysis,
    discover_legacy_analysis_material,
    match_url,
    select_best_real_match,
    write_analysis_contract,
)
from scripts.match_detail import render_match_detail, write_match_detail_page  # noqa: E402
from test_formal_market_projection import formal_record  # noqa: E402


DATE = "2026-08-12"


def _host_datetime(host_timezone):
    """Provide a datetime class whose local clock simulates a host timezone."""

    class HostDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 8, 13, 12, 0, tzinfo=host_timezone)
            return value.astimezone(tz) if tz else value

        def astimezone(self, tz=None):
            if tz is None:
                return self
            return super().astimezone(tz)

    return HostDateTime


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fixture(match_id: str, *, match_num: str = "周三003") -> dict:
    return {
        "matchId": match_id,
        "matchNum": match_num,
        "businessDate": DATE,
        "matchDate": "2026-08-13",
        "matchTime": "06:00:00",
        "league": "解放者杯",
        "homeTeam": "帕梅拉斯",
        "awayTeam": "波特诺",
        "nowscoreId": 2991818,
    }


def prediction(prediction_id: str, *, match_id: str = "2040820") -> dict:
    return {
        "prediction_id": prediction_id,
        "prediction_status": "formal",
        "product_role": "FUSION_BASELINE_V0",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "prediction_variant": "model_only",
        "model_role": "champion",
        "formal_eligibility_policy": "base_prediction_minimum.v1",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "data_grade": "B",
        "base_input_quality": "VERIFIED_MINIMUM",
        "market_intelligence_quality": "FULL",
        "match_id": match_id,
        "match_key": "FBOS-202608130600-test",
        "match_identity": {
            "match_key": "FBOS-202608130600-test",
            "home": "帕梅拉斯",
            "away": "波特诺",
            "kickoff_at": "2026-08-13T06:00:00+08:00",
        },
        "business_date": DATE,
        "kickoff_at": "2026-08-13T06:00:00+08:00",
        "prediction_created_at": "2026-08-12T15:39:49+08:00",
        "freeze_created_at": "2026-08-12T15:39:50+08:00",
        "source_cutoff_at": "2026-08-12T15:39:49+08:00",
        "input_snapshot_ref": "snapshots/snapshot.json",
        "input_sha256": "input-hash",
        "model_source_fingerprint": "model-fingerprint",
        "lambda_home": 1.4,
        "lambda_away": 0.8,
        "probabilities": {"home": 0.59, "draw": 0.245, "away": 0.165},
        "btts": {"yes": 0.414, "no": 0.586},
        "totals": [
            {"goals": "0", "probability": 0.095},
            {"goals": "2", "probability": 0.263},
        ],
        "unique_score": "1-0",
        "score_top1": {"score": "1-0", "probability": 0.155},
        "score_top3": ["1-0", "2-0", "1-1"],
        "score_top5": ["1-0", "2-0", "1-1", "0-0", "2-1"],
        "top_scores": [
            {"score": "1-0", "probability": 0.155, "rank": 1},
            {"score": "2-0", "probability": 0.126, "rank": 2},
            {"score": "1-1", "probability": 0.112, "rank": 3},
        ],
        "score_distribution": [
            {"score": "1-0", "probability": 0.155},
            {"score": "2-0", "probability": 0.126},
            {"score": "1-1", "probability": 0.112},
        ],
        "uncertainty": {"confidence_label": "中", "main_risk": "比分右尾风险"},
        "data_quality": {"status": "PREMATCH_INPUTS_VERIFIED", "missing": []},
        "source_references": [
            {"path": "data/prediction_universe/2026-08-12.json", "captured_at": "2026-08-12T14:03:06+08:00"}
        ],
    }


def job(match_id: str, prediction_id: str | None, *, status: str = "FROZEN") -> dict:
    return {
        "job_id": f"BASE-{DATE}-{match_id}",
        "business_date": DATE,
        "match_id": match_id,
        "match_num": "周三003",
        "status": status,
        "prediction_id": prediction_id,
        "last_error": None,
    }


def snapshot() -> dict:
    return {
        "snapshot_id": "FBOS-SNAPSHOT-test",
        "captured_at": "2026-08-12T15:39:49+08:00",
        "source_cutoff_at": "2026-08-12T15:39:49+08:00",
        "source_refs": ["data/source_cache/shared-football/parsed/test.json"],
        "input": {
            "selected_workspace_match": {"id": "2040820", "home": "帕梅拉斯", "away": "波特诺"},
            "prematch_fundamentals": {
                "captured_at": "2026-08-12T15:39:49+08:00",
                "form_source": "nowscore",
                "recent_form": {
                    "home_overall": {"matches": 10, "wins": 6, "draws": 1, "losses": 3, "goals_for": 21, "goals_against": 8},
                    "home_home": {"matches": 10, "wins": 5, "draws": 3, "losses": 2, "goals_for": 15, "goals_against": 6},
                    "away_overall": {"matches": 10, "wins": 5, "draws": 1, "losses": 4, "goals_for": 12, "goals_against": 8},
                    "away_away": {"matches": 10, "wins": 3, "draws": 1, "losses": 6, "goals_for": 8, "goals_against": 14},
                },
            },
            "official_market_baseline": {
                "source": "sporttery_spf",
                "captured_at": "2026-08-12T14:03:06+08:00",
                "fair_probabilities": {"home": 0.739, "draw": 0.181, "away": 0.081},
            },
            "source_snapshots": {
                "nowscore": {
                    "snapshots": [{
                        "fetched_at": "2026-08-12T15:39:49+08:00",
                        "ouzhi": {"bookmakers": [{"name": "澳门", "spf_current": {"home": 1.25, "draw": 4.7, "away": 9.0}}]},
                        "yazhi": {"companies": [{"name": "澳门", "current_handicap": -0.5, "current_water_home": 0.96, "current_water_away": 0.82}]},
                        "daxiao": {"companies": [{"name": "澳门", "current_line": 2.5, "current_over_water": 0.92, "current_under_water": 0.8}]},
                    }]
                }
            },
        },
    }


def roots(
    tmp_path: Path,
    *,
    status: str = "FROZEN",
    with_prediction: bool = True,
    pilot: bool = False,
    legacy_root: Path | None = None,
    include_formal_markets: bool = False,
):
    universe_root = tmp_path / "universe"
    jobs_root = tmp_path / "jobs"
    prediction_root = tmp_path / "predictions"
    snapshot_root = tmp_path / "snapshots"
    exclusion_root = tmp_path / "exclusions"
    output_root = tmp_path / "analysis"
    match_id = "2040820"
    prediction_id = "FBOS-PRED-test" if with_prediction else None
    write_json(universe_root / f"{DATE}.json", {
        "business_date": DATE,
        "status": "READY",
        "fixture_count": 1,
        "fixtures": [fixture(match_id)],
    })
    write_json(jobs_root / f"{DATE}.json", {"business_date": DATE, "jobs": [job(match_id, prediction_id, status=status)]})
    if with_prediction:
        record = (
            formal_record(prediction_id=prediction_id, match_id=match_id)
            if include_formal_markets
            else prediction(prediction_id)
        )
        write_json(prediction_root / f"{prediction_id}.json", record)
        write_json(snapshot_root / "snapshots" / "snapshot.json", snapshot())
    if pilot:
        write_json(exclusion_root / "pilot.json", {"prediction_ids": [prediction_id], "reason_code": "BASE_QUALITY_GATE_BYPASS"})
    return {
        "universe_root": universe_root,
        "jobs_root": jobs_root,
        "prediction_root": prediction_root,
        "snapshot_root": snapshot_root,
        "exclusion_root": exclusion_root,
        "output_root": output_root,
        "analysis_reports_root": legacy_root or (tmp_path / "analysis_reports"),
        "workspace_root": tmp_path / "match_workspace",
        "postmatch_reports_root": tmp_path / "postmatch_reports",
    }


def assemble(roots_payload):
    return assemble_match_analysis(DATE, "2040820", **roots_payload)


def test_analysis_contract_has_stable_identity_and_version(tmp_path):
    contract = assemble(roots(tmp_path))

    assert contract["analysis_contract_version"] == ANALYSIS_CONTRACT_VERSION == "1.0"
    assert contract["identity"]["match_id"] == "2040820"
    assert contract["identity"]["business_date"] == DATE
    assert match_url("2040820") == "/matches/2040820/"
    assert contract["hero"]["primary_score"] == "1-0"
    assert [item["score"] for item in contract["candidate_scores"]] == ["1-0", "2-0", "1-1"]


def test_formal_markets_are_wired_to_detail_and_completed_verification(tmp_path):
    contract = assemble(roots(tmp_path, include_formal_markets=True))

    markets = contract["formal_markets"]["markets"]
    assert markets["exact_score"]["status"] == "AVAILABLE"
    assert len(markets["exact_score"]["contract"]["cells"]) == 169
    assert markets["jc_total_goals"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["contract"]["official_integer_line"] == 1

    contract["result"] = {
        "score_90m": "1-0",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-08-13T08:10:00+08:00",
        "source": "TEST FIXTURE",
    }
    html = render_match_detail(contract)

    assert 'id="formal-markets"' in html
    assert html.count('data-formal-cell-home=') == 169
    assert "JC\u603b\u8fdb\u7403" in html
    assert "JC\u8ba9\u7403 H/D/A" in html
    assert 'data-formal-cell-home="13"' not in html
    assert ">13+<" not in html
    assert 'data-formal-verification-status="VERIFIED"' in html
    assert 'data-formal-verification-market="jc_handicap"' in html


def test_formal_market_unavailability_is_scoped_to_one_market(tmp_path):
    payload = roots(tmp_path, include_formal_markets=True)
    record = formal_record(prediction_id="FBOS-PRED-test", match_id="2040820")
    record.pop("jc_handicap")
    write_json(payload["prediction_root"] / "FBOS-PRED-test.json", record)

    contract = assemble(payload)
    markets = contract["formal_markets"]["markets"]
    assert markets["exact_score"]["status"] == "AVAILABLE"
    assert markets["jc_total_goals"]["status"] == "AVAILABLE"
    assert markets["jc_handicap"]["status"] == "NOT_RECORDED"
    html = render_match_detail(contract)
    assert html.count('data-formal-cell-home=') == 169
    assert 'data-formal-market="jc_total_goals"' in html
    assert 'data-formal-market="jc_handicap"' in html
    assert "\u65e7\u8bb0\u5f55\u6ca1\u6709\u8be5\u6b63\u5f0f\u73a9\u6cd5" in html


def test_pilot_contract_is_explicit_and_uses_real_frozen_outputs(tmp_path):
    contract = assemble(roots(tmp_path, pilot=True))

    assert contract["governance"]["pilot_excluded"] is True
    assert contract["governance"]["formal_prospective_eligible"] is False
    assert contract["status"]["label"] == "试运行预测"
    assert contract["hero"]["primary_score"] == "1-0"
    assert contract["model"]["probabilities"] == {"home": 0.59, "draw": 0.245, "away": 0.165}


@pytest.mark.parametrize("status", ["INSUFFICIENT_DATA", "PENDING", "PREDICTION_FAILED", "MISSED_PREMATCH_WINDOW"])
def test_non_prediction_statuses_have_safe_detail_contracts(tmp_path, status):
    contract = assemble(roots(tmp_path, status=status, with_prediction=False))

    assert contract["status"]["code"] == status
    assert contract["hero"]["primary_score"] is None
    assert "当前证据不足" in contract["hero"]["summary"] or status == "PENDING"
    assert all(section["conclusion"] == "当前证据不足，暂不扩展判断。" for section in contract["analysis_sections"])


def test_insufficient_status_with_retained_prediction_keeps_hero_fail_closed(tmp_path):
    contract = assemble(roots(tmp_path, status="INSUFFICIENT_DATA", with_prediction=True))
    html = render_match_detail(contract)

    assert contract["status"]["code"] == "INSUFFICIENT_DATA"
    assert contract["governance"]["prediction_id"] == "FBOS-PRED-test"
    assert contract["hero"]["primary_score"] is None
    assert contract["hero"]["probabilities"] == {}
    assert contract["model"]["probabilities"] == {}
    assert '<div class="hero-probabilities">' not in html
    assert "1-0" not in html


def test_missing_current_job_with_retained_prediction_stays_pending_and_fail_closed(tmp_path):
    payload = roots(tmp_path)
    write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": []})

    contract = assemble(payload)

    assert contract["status"]["code"] == "PENDING"
    assert contract["status"]["reason_code"] == "BASE_JOB_MISSING"
    assert contract["current_job_resolution"]["status"] == "MISSING"
    assert contract["governance"]["prediction_id"] == "FBOS-PRED-test"
    assert contract["hero"]["primary_score"] is None
    assert contract["hero"]["probabilities"] == {}
    assert contract["model"]["probabilities"] == {}


def test_conflicting_current_jobs_are_order_invariant_and_detail_fails_closed(tmp_path):
    for index, ordered_jobs in enumerate((
        [job("2040820", "FBOS-PRED-test"), {**job("2040820", "FBOS-PRED-test"), "job_id": "BASE-CONFLICT-2", "status": "INSUFFICIENT_DATA", "last_error": "SOURCE_FETCH_FAILED"}],
        [{**job("2040820", "FBOS-PRED-test"), "job_id": "BASE-CONFLICT-2", "status": "INSUFFICIENT_DATA", "last_error": "SOURCE_FETCH_FAILED"}, job("2040820", "FBOS-PRED-test")],
    )):
        payload = roots(tmp_path / f"order-{index}")
        write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": ordered_jobs})

        contract = assemble(payload)
        detail_html = render_match_detail(contract)

        assert contract["status"]["code"] == "CURRENT_JOB_STATE_CONFLICT"
        assert contract["status"]["reason_code"] == "DUPLICATE_CURRENT_JOB_STATE"
        assert contract["current_job_resolution"]["status"] == "CONFLICT"
        assert contract["current_job_resolution"]["row_count"] == 2
        assert contract["governance"]["prediction_id"] == "FBOS-PRED-test"
        assert contract["hero"]["primary_score"] is None
        assert contract["hero"]["probabilities"] == {}
        assert contract["model"]["probabilities"] == {}
        assert contract["candidate_scores"] == []
        assert '<div class="hero-probabilities">' not in detail_html
        assert "1-0" not in detail_html
        assert "当前比赛状态冲突" in detail_html
        assert "当前比赛状态冲突，暂不形成预测" in detail_html
        if index == 0:
            first_projection = (contract["status"], contract["hero"], contract["model"], contract["governance"]["prediction_id"])
        else:
            second_projection = (contract["status"], contract["hero"], contract["model"], contract["governance"]["prediction_id"])

    assert first_projection == second_projection


def test_duplicate_frozen_jobs_keep_detail_fail_closed(tmp_path):
    payload = roots(tmp_path)
    first = job("2040820", "FBOS-PRED-test")
    second = {**first, "job_id": "BASE-DUPLICATE-2"}
    write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": [first, second]})

    contract = assemble(payload)
    detail_html = render_match_detail(contract)

    assert contract["status"]["code"] == "CURRENT_JOB_STATE_CONFLICT"
    assert contract["hero"]["primary_score"] is None
    assert contract["hero"]["probabilities"] == {}
    assert contract["model"]["probabilities"] == {}
    assert "1-0" not in detail_html


def test_assembler_does_not_fabricate_market_direction_or_script(tmp_path):
    contract = assemble(roots(tmp_path))

    assert contract["hero"]["script"] is None
    assert contract["hero"]["attention_tag"] is None
    assert contract["market"]["interpretation"] is None
    assert contract["market"]["observed_totals_lines"] == [2.5]
    assert contract["market"]["model_comparison"]["classification"] is None
    assert "score_concentration" not in contract["model"]


def test_raw_evidence_does_not_become_hero_support_or_conflict(tmp_path):
    contract = assemble(roots(tmp_path))

    assert contract["evidence"]["legacy_report_material"]["status"] == "NOT_FOUND"
    assert contract["evidence"]["legacy_report_material"]["consistency_checked"] is True
    assert contract["hero"]["supports"] == []
    assert contract["hero"]["conflicts"] == []
    assert all(section["supports"] == [] for section in contract["analysis_sections"])
    assert all(section["conflicts"] == [] for section in contract["analysis_sections"])


def legacy_report(*, score: str = "1-0", sections: list[dict] | None = None) -> dict:
    return {
        "report": {
            "report_type": "完整分析版",
            "analysis_timestamp": "2026-08-12T15:00:00+08:00",
            "snapshot_timestamp": "2026-08-12T14:59:00+08:00",
        },
        "match": {
            "match_id": "2040820",
            "match_key": "FBOS-202608130600-test",
            "business_date": DATE,
            "competition": "解放者杯",
            "home": "帕梅拉斯",
            "away": "波特诺",
            "kickoff_local": "2026-08-13 06:00",
        },
        "decisions": {"unique_score": score},
        "analysis_material": {
            "sections": sections or [
                {
                    "id": "strength",
                    "conclusion": "已有分析判断认为主队更可能掌握主动权。",
                    "supports": [{"type": "基本面", "text": "主队的主动权判断来自旧报告明确结论。", "source_ref": "legacy-report"}],
                    "conflicts": [],
                    "explanation": "该结论来自可追溯的赛前分析素材。",
                    "score_impact": "更支持1-0而不是1-1。",
                },
                {
                    "id": "tempo",
                    "conclusion": "旧报告把比赛节奏判断为相对受控。",
                    "supports": [{"type": "市场", "text": "旧报告明确写出总进球环境偏受控。", "source_ref": "legacy-report"}],
                    "conflicts": [],
                    "explanation": "这是旧报告的解释性结论，不是盘口数值复述。",
                    "score_impact": "降低高比分邻近候选。",
                },
                {
                    "id": "scoring",
                    "conclusion": "旧报告保留主队一球领先的得分路径。",
                    "supports": [{"type": "模型", "text": "旧报告将主队一球领先列为主要得分路径。", "source_ref": "legacy-report"}],
                    "conflicts": [],
                    "explanation": "结论与冻结候选池能够直接对应。",
                    "score_impact": "支持1-0而不是2-0。",
                },
                {
                    "id": "fork",
                    "conclusion": "客队反击效率是旧报告指出的关键分叉。",
                    "supports": [],
                    "conflicts": [{"type": "基本面", "text": "客队仍有明确进球路径。", "source_ref": "legacy-report"}],
                    "explanation": "该风险来自旧报告，而非自动阈值。",
                    "score_impact": "保留1-1作为邻近迁移路径。",
                },
                {
                    "id": "convergence",
                    "conclusion": "旧报告比较了1-0、2-0与1-1，最终认为1-0最符合证据组合。",
                    "supports": [{"type": "分析", "text": "1-0同时保留主队优势与受控节奏。", "source_ref": "legacy-report"}],
                    "conflicts": [],
                    "explanation": "首推与两个邻近候选均有明确条件比较。",
                    "score_impact": "1-0胜过2-0与1-1。",
                },
            ],
            "candidate_scores": {
                "1-0": {"script_label": "主队优势兑现，客队得分路径受限"},
                "2-0": {"script_label": "需要主队控制并完成零封"},
            },
        },
        "source_references": [{"path": "data/analysis_reports/legacy.json"}],
    }


R4_LEAK_SENTINELS = (
    "SHOULD_NOT_LEAK_SCRIPT",
    "SHOULD_NOT_LEAK_ATTENTION",
    "SHOULD_NOT_LEAK_SUPPORT",
    "SHOULD_NOT_LEAK_CONFLICT",
    "SHOULD_NOT_LEAK_RISK",
    "SHOULD_NOT_LEAK_MARKET",
)


def r4_rich_retained_payload(tmp_path: Path, *, status: str) -> dict:
    legacy_root = tmp_path / "analysis_reports"
    payload = roots(tmp_path, status=status, with_prediction=True, legacy_root=legacy_root)
    retained = prediction("FBOS-PRED-test")
    retained.update({
        "short_match_script": "SHOULD_NOT_LEAK_SCRIPT",
        "attention_tag": "SHOULD_NOT_LEAK_ATTENTION",
    })
    retained["uncertainty"] = {"confidence_label": "HIGH", "main_risk": "SHOULD_NOT_LEAK_RISK"}
    write_json(payload["prediction_root"] / "FBOS-PRED-test.json", retained)

    legacy = legacy_report()
    legacy["decisions"].update({
        "match_story": "SHOULD_NOT_LEAK_SCRIPT",
        "maximum_error_points": ["SHOULD_NOT_LEAK_RISK"],
        "market_conflict": "SHOULD_NOT_LEAK_MARKET",
    })
    legacy["market"] = {
        "interpretation": {
            "impact_code": "confirm",
            "direction": "home",
            "model_impact": "SHOULD_NOT_LEAK_MARKET",
        }
    }
    legacy_sections = legacy["analysis_material"]["sections"]
    legacy_sections[0]["supports"][0]["text"] = "SHOULD_NOT_LEAK_SUPPORT"
    legacy_sections[3]["conflicts"][0]["text"] = "SHOULD_NOT_LEAK_CONFLICT"
    write_json(legacy_root / "legacy.json", legacy)
    return payload


@pytest.mark.parametrize("status", ["INSUFFICIENT_DATA", "PREDICTION_FAILED", "MISSED_PREMATCH_WINDOW", "PENDING"])
def test_non_serving_retained_prediction_narrative_is_not_projected(tmp_path, status):
    contract = assemble(r4_rich_retained_payload(tmp_path, status=status))
    html = render_match_detail(contract)
    serialized = json.dumps(contract, ensure_ascii=False)

    assert contract["status"]["code"] == status
    assert contract["governance"]["prediction_id"] == "FBOS-PRED-test"
    assert contract["hero"]["primary_score"] is None
    assert contract["hero"]["probabilities"] == {}
    assert contract["hero"]["script"] is None
    assert contract["hero"]["attention_tag"] is None
    assert contract["hero"]["supports"] == []
    assert contract["hero"]["conflicts"] == []
    assert contract["hero"]["biggest_failure_point"] is None
    assert contract["candidate_scores"] == []
    assert contract["model"]["probabilities"] == {}
    assert contract["model"]["top_scores"] == []
    assert contract["market"]["model_comparison"]["model_home_probability"] is None
    assert contract["market"]["model_comparison"]["source_refs"] == []
    assert contract["market"]["source_refs"] == []
    assert contract["source_quality"]["source_references"] == []
    assert contract["source_quality"]["recent_form_source"] is None
    assert all(sentinel not in serialized for sentinel in R4_LEAK_SENTINELS)
    assert all(sentinel not in html for sentinel in R4_LEAK_SENTINELS)
    assert "\u9884\u6d4b\u6982\u7387" not in html
    assert "\u6a21\u578b\u539f\u59cb\u6bd4\u5206\u7ee7\u7eed\u4fdd\u7559" not in html


def test_conflict_retained_prediction_narrative_is_not_projected_in_either_order(tmp_path):
    projections = []
    for index, ordered_jobs in enumerate((
        [job("2040820", "FBOS-PRED-test"), {**job("2040820", "FBOS-PRED-test"), "job_id": "BASE-CONFLICT-2", "status": "INSUFFICIENT_DATA", "last_error": "SOURCE_FETCH_FAILED"}],
        [{**job("2040820", "FBOS-PRED-test"), "job_id": "BASE-CONFLICT-2", "status": "INSUFFICIENT_DATA", "last_error": "SOURCE_FETCH_FAILED"}, job("2040820", "FBOS-PRED-test")],
    )):
        payload = r4_rich_retained_payload(tmp_path / f"order-{index}", status="FROZEN")
        write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": ordered_jobs})
        contract = assemble(payload)
        html = render_match_detail(contract)
        serialized = json.dumps(contract, ensure_ascii=False)

        assert contract["status"]["code"] == "CURRENT_JOB_STATE_CONFLICT"
        assert contract["governance"]["prediction_id"] == "FBOS-PRED-test"
        assert contract["hero"]["script"] is None
        assert contract["hero"]["attention_tag"] is None
        assert contract["hero"]["supports"] == []
        assert contract["hero"]["conflicts"] == []
        assert contract["hero"]["biggest_failure_point"] is None
        assert contract["candidate_scores"] == []
        assert all(sentinel not in serialized for sentinel in R4_LEAK_SENTINELS)
        assert all(sentinel not in html for sentinel in R4_LEAK_SENTINELS)
        assert "\u6a21\u578b\u539f\u59cb\u6bd4\u5206\u7ee7\u7eed\u4fdd\u7559" not in html
        projections.append((contract["status"], contract["hero"], contract["model"], contract["market"], html))

    assert projections[0] == projections[1]


def test_duplicate_frozen_retained_prediction_narrative_is_not_projected(tmp_path):
    payload = r4_rich_retained_payload(tmp_path, status="FROZEN")
    first = job("2040820", "FBOS-PRED-test")
    second = {**first, "job_id": "BASE-DUPLICATE-2"}
    write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": [first, second]})

    contract = assemble(payload)
    html = render_match_detail(contract)
    serialized = json.dumps(contract, ensure_ascii=False)

    assert contract["status"]["code"] == "CURRENT_JOB_STATE_CONFLICT"
    assert contract["current_job_resolution"]["status"] == "CONFLICT"
    assert contract["hero"]["script"] is None
    assert contract["hero"]["supports"] == []
    assert contract["hero"]["conflicts"] == []
    assert contract["hero"]["biggest_failure_point"] is None
    assert all(sentinel not in serialized for sentinel in R4_LEAK_SENTINELS)
    assert all(sentinel not in html for sentinel in R4_LEAK_SENTINELS)


def test_non_frozen_quality_warning_is_not_rendered(tmp_path):
    contract = assemble(roots(tmp_path, status="INSUFFICIENT_DATA", with_prediction=True))
    contract["prediction_quality_health"] = {"status": "UNVERIFIED", "scope": "current_serving"}

    html = render_match_detail(contract)

    assert "\u6a21\u578b\u539f\u59cb\u6bd4\u5206\u7ee7\u7eed\u4fdd\u7559" not in html


@pytest.mark.parametrize("host_timezone", [timezone.utc, timezone(timedelta(hours=8))])
def test_legacy_material_is_really_discovered_and_consistency_checked(tmp_path, monkeypatch, host_timezone):
    monkeypatch.setattr(legacy_mapper_module, "datetime", _host_datetime(host_timezone))
    legacy_root = tmp_path / "analysis_reports"
    write_json(legacy_root / "legacy.json", legacy_report())

    material = discover_legacy_analysis_material(
        DATE,
        fixture("2040820"),
        frozen_prediction=prediction("FBOS-PRED-test"),
        analysis_reports_root=legacy_root,
        workspace_root=tmp_path / "missing-workspace",
        postmatch_reports_root=tmp_path / "missing-postmatch",
    )

    assert material["status"] == "USABLE"
    assert material["consistency_checked"] is True
    assert material["items"][0]["status"] == "USABLE"
    assert material["interpretations"]
    assert material["interpretations"][0]["section_id"] == "strength"

    payload = roots(tmp_path / "assembled", legacy_root=legacy_root)
    contract = assemble(payload)
    assert contract["evidence"]["legacy_report_material"]["status"] == "USABLE"
    assert contract["hero"]["supports"]
    assert contract["analysis_material"]["status"] == "USABLE"
    assert contract["analysis_material"]["analysis_origin"]["type"] == "LEGACY_STRUCTURED_ANALYSIS"
    assert contract["analysis_material"]["lineage"]
    assert contract["candidate_scores"][0]["script_label"] == "主队优势兑现，客队得分路径受限"
    html = render_match_detail(contract)
    assert "最高概率比分" in html
    assert "1-0</strong>" in html
    assert "15.5%" in html
    assert "主队优势兑现，客队得分路径受限" not in html


@pytest.mark.parametrize("host_timezone", [timezone.utc, timezone(timedelta(hours=8))])
def test_legacy_conflict_is_excluded_from_analysis(tmp_path, monkeypatch, host_timezone):
    monkeypatch.setattr(legacy_mapper_module, "datetime", _host_datetime(host_timezone))
    legacy_root = tmp_path / "analysis_reports"
    write_json(legacy_root / "conflict.json", legacy_report(score="2-1"))
    payload = roots(tmp_path / "assembled", legacy_root=legacy_root)

    contract = assemble(payload)

    assert contract["evidence"]["legacy_report_material"]["status"] == "PREDICTION_MISMATCH"
    assert contract["analysis_material"]["interpretations"] == []
    assert contract["hero"]["supports"] == []


def test_missing_legacy_material_is_not_reported_as_not_available(tmp_path):
    material = discover_legacy_analysis_material(
        DATE,
        fixture("2040820"),
        frozen_prediction=prediction("FBOS-PRED-test"),
        analysis_reports_root=tmp_path / "missing-analysis",
        workspace_root=tmp_path / "missing-workspace",
        postmatch_reports_root=tmp_path / "missing-postmatch",
    )

    assert material["status"] == "NOT_FOUND"
    assert material["consistency_checked"] is True
    assert "NOT_AVAILABLE" not in json.dumps(material, ensure_ascii=False)


def test_convergence_does_not_use_rank_as_fake_analysis(tmp_path):
    contract = assemble(roots(tmp_path))
    convergence = next(item for item in contract["analysis_sections"] if item["id"] == "convergence")

    assert "没有足够可追溯的分析素材" in convergence["conclusion"]
    assert convergence["supports"] == []
    assert convergence["score_impact"] is None
    assert "候选顺序沿用冻结记录的rank" not in json.dumps(convergence, ensure_ascii=False)


@pytest.mark.parametrize("host_timezone", [timezone.utc, timezone(timedelta(hours=8))])
def test_selector_rewards_usable_legacy_material(tmp_path, monkeypatch, host_timezone):
    monkeypatch.setattr(legacy_mapper_module, "datetime", _host_datetime(host_timezone))
    legacy_root = tmp_path / "analysis_reports"
    write_json(legacy_root / "legacy.json", legacy_report())
    payload = roots(tmp_path, legacy_root=legacy_root)

    second = fixture("2040821", match_num="周三004")
    universe = json.loads((payload["universe_root"] / f"{DATE}.json").read_text(encoding="utf-8"))
    universe["fixtures"].append(second)
    universe["fixture_count"] = 2
    write_json(payload["universe_root"] / f"{DATE}.json", universe)
    write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": [job("2040820", "FBOS-PRED-test"), job("2040821", "FBOS-PRED-incomplete")]})
    richer = prediction("FBOS-PRED-incomplete", match_id="2040821")
    richer["match_key"] = "FBOS-202608130600-second"
    richer["match_identity"]["match_key"] = richer["match_key"]
    richer["top_scores"] = [{"score": f"{i}-0", "probability": 0.1, "rank": i + 1} for i in range(10)]
    write_json(payload["prediction_root"] / "FBOS-PRED-incomplete.json", richer)

    selected = select_best_real_match(**payload)

    assert selected["match_id"] == "2040820"
    assert selected["legacy_report_material_status"] == "USABLE"


def test_frozen_prediction_file_is_not_modified_by_assembly(tmp_path):
    payload = roots(tmp_path)
    prediction_path = payload["prediction_root"] / "FBOS-PRED-test.json"
    before = hashlib.sha256(prediction_path.read_bytes()).hexdigest()

    assemble(payload)

    assert hashlib.sha256(prediction_path.read_bytes()).hexdigest() == before


def test_post_freeze_evidence_has_separate_channel(tmp_path):
    contract = assemble(roots(tmp_path))

    assert contract["timestamps"]["prediction_frozen_at"] == "2026-08-12T15:39:50+08:00"
    assert contract["timestamps"]["evidence_updated_at"] == "2026-08-12T15:39:49+08:00"
    assert "prediction_frozen_at" not in contract["post_freeze_updates"]
    assert contract["post_freeze_updates"]["items"] == []


def test_revision_changes_only_when_substantive_content_changes(tmp_path):
    payload = roots(tmp_path)
    contract = assemble(payload)
    write_analysis_contract(contract, output_root=payload["output_root"], generated_at="2026-08-13T10:00:00+08:00")
    write_analysis_contract(contract, output_root=payload["output_root"], generated_at="2026-08-13T11:00:00+08:00")
    report_dir = payload["output_root"] / DATE / "2040820"
    assert len(list(report_dir.glob("revision-*.json"))) == 1

    changed = json.loads(json.dumps(contract, ensure_ascii=False))
    changed["source_quality"]["note"] = "substantive evidence note"
    write_analysis_contract(changed, output_root=payload["output_root"], generated_at="2026-08-13T12:00:00+08:00")
    assert len(list(report_dir.glob("revision-*.json"))) == 2


def test_selector_prefers_evidence_complete_real_frozen_sample(tmp_path):
    payload = roots(tmp_path)
    second = fixture("2040821", match_num="周三004")
    universe = json.loads((payload["universe_root"] / f"{DATE}.json").read_text(encoding="utf-8"))
    universe["fixtures"].append(second)
    universe["fixture_count"] = 2
    write_json(payload["universe_root"] / f"{DATE}.json", universe)
    write_json(payload["jobs_root"] / f"{DATE}.json", {"business_date": DATE, "jobs": [job("2040820", "FBOS-PRED-test"), job("2040821", "FBOS-PRED-incomplete")]})
    write_json(payload["prediction_root"] / "FBOS-PRED-incomplete.json", {"prediction_id": "FBOS-PRED-incomplete", "match_id": "2040821", "prediction_status": "formal", "unique_score": "1-0"})

    selected = select_best_real_match(**payload)

    assert selected["match_id"] == "2040820"
    assert selected["prediction_id"] == "FBOS-PRED-test"


def test_detail_renderer_has_three_layers_and_uses_same_contract_for_statuses(tmp_path):
    contract = assemble(roots(tmp_path, pilot=True))
    html = render_match_detail(contract)

    assert 'id="conclusion"' in html
    assert 'id="analysis"' in html
    assert 'id="evidence"' in html
    assert "试运行预测 · 仅供观察" in html
    assert "1-0" in html
    assert "1-0</strong>" in html
    assert "15.5%" in html
    assert "胜平负概率" in html
    assert "比分概率 · 不是确定答案" in html
    assert "进球信号" in html
    assert "关键依据" in html
    assert "赛前预测已锁定于" in html
    assert "首推" not in html
    assert 'class="status-badge"' not in html

    pending = assemble(roots(tmp_path / "pending", status="PENDING", with_prediction=False))
    pending_html = render_match_detail(pending)
    assert "预测尚未形成" in pending_html
    assert "胜平负概率" not in pending_html
    assert "1-0" not in pending_html

    insufficient = assemble(roots(tmp_path / "insufficient", status="INSUFFICIENT_DATA", with_prediction=False))
    insufficient_html = render_match_detail(insufficient)
    assert "数据不足，暂不预测" in insufficient_html
    assert "胜平负概率" not in insufficient_html
    assert "score-distribution" not in insufficient_html


def test_serving_detail_with_null_market_renders_safely(tmp_path):
    contract = assemble(roots(tmp_path))
    contract["market"] = None
    contract["evidence"]["market"] = {}

    html = render_match_detail(contract)

    assert "<html" in html
    assert 'class="hero-probabilities"' in html
    assert "比分概率 · 不是确定答案" in html
    assert 'id="market"' not in html
    assert "模型与市场" not in html


def test_completed_detail_leads_with_verified_90m_result_and_compares_frozen_forecast(tmp_path):
    contract = assemble(roots(tmp_path))
    contract["result"] = {
        "score_90m": "0-2",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-08-13T08:10:00+08:00",
        "source": "TEST FIXTURE",
    }

    html = render_match_detail(contract)

    assert html.index("\u5b9e\u9645\u8d5b\u679c") < html.index("\u8d5b\u524d\u9884\u6d4b")
    assert "0-2" in html
    assert "90\u5206\u949f\u8d5b\u679c" in html
    assert "\u6bd4\u5206" in html and "\u672a\u547d\u4e2d" in html
    assert "1X2\u65b9\u5411" in html and "\u547d\u4e2d" in html
    assert "\u8d5b\u524d\u9884\u6d4b\u5df2\u9501\u5b9a" in html
    assert html.index("\u5b9e\u9645\u8d5b\u679c") < html.index("\u80dc\u5e73\u8d1f\u6982\u7387")
    assert html.count("\u9884\u6d4b vs \u5b9e\u9645") == 0
    assert 'id="verification"' not in html
    result_start = html.index('id="result"')
    deeper_start = html.index('id="evidence"')
    result_panel = html[result_start:deeper_start]
    assert result_panel.index("\u5b9e\u9645\u6bd4\u5206") < result_panel.index("\u6bd4\u5206")
    assert result_panel.index("\u65b9\u5411") < result_panel.index("\u5b9e\u9645\u65b9\u5411")
    assert 'data-probability="0.155000"' in html
    assert 'style="width:15.5%"' in html
    assert 'style="width:100.0%"' not in html
    for label in ("\u5f53\u65f6\u6700\u9ad8\u6982\u7387\u6bd4\u5206", "\u5f53\u65f6\u0031X2\u65b9\u5411", "\u5b9e\u9645\u65b9\u5411"):
        assert label in html


def test_degraded_detail_keeps_exact_score_scope_and_local_context(tmp_path):
    contract = assemble(roots(tmp_path))
    contract["prediction_quality_health"] = {
        "status": "ALERT",
        "scope": "current_serving",
        "available": True,
        "provenance_status": "MATCHED",
    }

    html = render_match_detail(contract)

    assert "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf" in html
    assert "\u5f53\u524d\u8d28\u91cf\u5f02\u5e38\uff0c\u6682\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u6bd4\u5206\u63a8\u8350" in html
    assert "\u6a21\u578b\u539f\u59cb\u6bd4\u5206" in html
    assert 'data-score-serving-state="DEGRADED"' in html
    assert 'style="width:15.5%"' in html


@pytest.mark.parametrize(
    "status, provenance, label, local_label",
    [
        (
            "INSUFFICIENT_SAMPLE",
            "MATCHED",
            "\u6bd4\u5206\u9884\u6d4b\u5f53\u524d\u6837\u672c\u4e0d\u8db3\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
            "\u5f53\u524d\u6837\u672c\u4e0d\u8db3\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
        ),
        (
            "ALERT",
            "MATCHED",
            "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
            "\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
        ),
        (
            "HEALTHY",
            "MISMATCHED",
            "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f85\u786e\u8ba4\uff0c\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u63a8\u8350",
            "\u8d28\u91cf\u5f85\u786e\u8ba4\uff0c\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u63a8\u8350",
        ),
    ],
)
def test_detail_quality_copy_matches_raw_health_status(tmp_path, status, provenance, label, local_label):
    contract = assemble(roots(tmp_path))
    contract["prediction_quality_health"] = {
        "status": status,
        "scope": "current_serving",
        "available": True,
        "provenance_status": provenance,
    }

    html = render_match_detail(contract)

    assert label in html
    assert f"模型原始比分 · {local_label}" in html


def test_trust_title_changes_when_only_freeze_and_cutoff_are_visible(tmp_path):
    contract = assemble(roots(tmp_path))
    contract["source_quality"]["source_references"] = []
    contract["evidence"]["source_quality"]["source_references"] = []
    contract["model"]["source_references"] = []
    contract["market"] = {}
    contract["evidence"]["market"] = {}

    html = render_match_detail(contract)

    assert "\u8d5b\u524d\u8bb0\u5f55" in html
    assert "\u53ef\u4fe1\u5ea6\u4e0e\u6765\u6e90" not in html


def test_detail_renderer_uses_user_facing_terms_and_hides_internal_metadata(tmp_path):
    html = render_match_detail(assemble(roots(tmp_path, pilot=True)))

    technical_start = html.index('<details class="technical-details">')
    primary_html = html[:technical_start]
    technical_html = html[technical_start:]
    for forbidden in (
        "Analysis Contract",
        "analysis_contract_version",
        "governance",
        "Frozen Top-K",
        "Frozen Prediction",
        "pilot_excluded",
        "BASE_QUALITY_GATE_BYPASS",
        "lineage",
        "Legacy Structured Analysis",
        "Layer 1",
        "Layer 2",
        "Layer 3",
    ):
        assert forbidden not in primary_html
    for technical_value in (
        "recent_form_market_calibrated_poisson_v2",
        "prediction_id",
        "status_code",
    ):
        assert technical_value in technical_html

    for required in (
        "胜平负概率",
        "比分概率 · 不是确定答案",
        "最高概率",
        "进球信号",
        "关键依据",
        "可信度与来源",
        "技术详情",
        "赛前预测已锁定",
        "试运行预测 · 仅供观察",
    ):
        assert required in html


def test_technical_details_are_closed_and_user_safe_when_legacy_source_exists(tmp_path):
    legacy_root = tmp_path / "analysis_reports"
    write_json(legacy_root / "legacy.json", legacy_report())
    html = render_match_detail(assemble(roots(tmp_path, legacy_root=legacy_root)))

    assert '<details class="technical-details"><summary>技术详情</summary>' in html
    assert '<details open class="technical-details">' not in html
    for forbidden in ("legacy_mapper.v1", "LEGACY_STRUCTURED_ANALYSIS", "mapping_status", "source_artifact"):
        assert forbidden not in html


def test_detail_writer_uses_stable_static_match_route(tmp_path):
    contract = assemble(roots(tmp_path))
    page = write_match_detail_page(contract, tmp_path / "site" / "matches")

    assert page == tmp_path / "site" / "matches" / "2040820" / "index.html"
    assert page.exists()
    assert 'name="viewport"' in page.read_text(encoding="utf-8")


def test_assembler_and_renderer_have_no_runtime_model_or_network_path():
    for name in ("match_analysis.py", "match_detail.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "automatic_model_core" not in source
        assert "urllib" not in source
        assert "requests" not in source
        assert "openai" not in source.lower()
