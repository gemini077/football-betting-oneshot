import hashlib
import json
import sys
from pathlib import Path

import pytest

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


DATE = "2026-08-12"


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
        record = prediction(prediction_id)
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


def test_legacy_material_is_really_discovered_and_consistency_checked(tmp_path):
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
    assert contract["candidate_scores"][0]["script_label"] == "主队优势兑现，客队得分路径受限"
    assert "主队优势兑现，客队得分路径受限" in render_match_detail(contract)


def test_legacy_conflict_is_excluded_from_analysis(tmp_path):
    legacy_root = tmp_path / "analysis_reports"
    write_json(legacy_root / "conflict.json", legacy_report(score="2-1"))
    payload = roots(tmp_path / "assembled", legacy_root=legacy_root)

    contract = assemble(payload)

    assert contract["evidence"]["legacy_report_material"]["status"] == "CONFLICTED"
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


def test_selector_rewards_usable_legacy_material(tmp_path):
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
    assert "试运行预测" in html
    assert "1–0" in html
    assert "1–0 · 15.5%" in html
    assert "强弱与主动权" in html
    assert "节奏与进球环境" in html
    assert "得分路径" in html
    assert "关键分叉" in html
    assert "最终收敛" in html
    assert "当前没有可追溯的正式比赛剧本字段" in html

    pending = assemble(roots(tmp_path / "pending", status="PENDING", with_prediction=False))
    pending_html = render_match_detail(pending)
    assert "预测尚未冻结" in pending_html
    assert "1–0" not in pending_html

    insufficient = assemble(roots(tmp_path / "insufficient", status="INSUFFICIENT_DATA", with_prediction=False))
    insufficient_html = render_match_detail(insufficient)
    assert "当前数据不足" in insufficient_html
    assert "当前证据不足，暂不扩展判断" in insufficient_html


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
