from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.match_analysis import assemble_match_analysis  # noqa: E402
from scripts.match_analysis_article import build_evidence_envelope, build_late_briefing, render_article_plan  # noqa: E402
from scripts.match_detail import _render_late_briefing, _render_match_analysis_article, render_match_detail  # noqa: E402


DATE = "2026-09-11"
BENCHMARK_IDS = ("2996143", "2995342", "3019134", "2993794", "3018812")


def _contract(match_id: str) -> dict:
    return assemble_match_analysis(DATE, match_id)


def test_five_benchmark_articles_are_connected_and_public_safe():
    plan_lengths = []
    for match_id in BENCHMARK_IDS:
        article = _contract(match_id)["match_analysis_article"]

        assert article["contract_version"] == "match_analysis_article.v2"
        assert article["status"] == "AVAILABLE"
        plan = article["article_plan"]
        plan_lengths.append(len(plan))
        assert plan == article["paragraphs"]
        assert plan[0]["role"] == "thesis"
        assert plan[-1]["role"] == "forecast"
        assert [item["order"] for item in plan] == list(range(1, len(plan) + 1))
        for item in plan:
            assert set(item) == {"role", "subject", "direction", "strength", "evidence_refs", "order", "text"}
            assert item["evidence_refs"]
        serialized = json.dumps(article, ensure_ascii=False).casefold()
        for forbidden in (
            "parse_uncertain",
            "model_family",
            "release_version",
            "data_grade",
            "truth gate",
            "xg",
            "sharp",
            "trap",
        ):
            assert forbidden not in serialized
    assert set(plan_lengths) == {4, 5}


def test_benchmark_primitives_keep_alignment_outlier_and_conflict_visible():
    az = _contract("2996143")["match_analysis_article"]
    assert az["result_process_alignment"] == "supportive"
    assert az["market_relationship"] == "aligned"
    assert az["identifiability"] == "HIGH"

    nurnberg = _contract("3019134")["match_analysis_article"]
    assert nurnberg["result_process_alignment"] == "contradictory"
    assert nurnberg["market_relationship"] == "conflicting"
    assert nurnberg["outlier_concentration"] == {
        "status": "PRESENT",
        "side": "away",
        "dimension": "goals_for",
        "value": 9,
        "share": 0.692308,
        "window_total": 13,
        "match_date": "2026-08-22",
        "discount_raw_totals": True,
    }
    assert nurnberg["identifiability"] == "LOW"
    assert nurnberg["paragraphs"][1]["role"] == "evidence_conflict"
    assert "9" in nurnberg["paragraphs"][1]["text"]

    venezia = _contract("2993794")["match_analysis_article"]
    union = _contract("3018812")["match_analysis_article"]
    assert venezia["market_relationship"] == "conflicting"
    assert venezia["identifiability"] == "LOW"
    assert union["market_relationship"] == "conflicting"
    assert union["identifiability"] in {"MEDIUM", "LOW"}
    assert union["process_signals"]["result_direction"] == "home"
    assert union["process_signals"]["process_direction"] == "home"
    assert any("柏林联合" in item["text"] for item in union["article_plan"] if item["role"] == "recent_process")
    assert all("沙尔克04的结果方向与过程方向一致" not in item["text"] for item in union["article_plan"])


def test_plan_surface_fidelity_is_validated_and_emitted():
    contract = _contract("2993794")
    article = contract["match_analysis_article"]
    rendered = _render_match_analysis_article(contract)
    serialized = json.dumps(article, ensure_ascii=False)
    assert "\u8fc7\u7a0b\u65b9\u5411\u504f\u5411\u4e24\u961f" not in serialized
    assert "\u6ca1\u6709\u5f62\u6210\u5355\u8fb9\u65b9\u5411" in serialized
    for item in article["article_plan"]:
        assert f'data-article-role="{item["role"]}"' in rendered
        assert f'data-article-subject="{item["subject"]}"' in rendered
        assert f'data-article-direction="{item["direction"]}"' in rendered
        assert f'data-article-strength="{item["strength"]}"' in rendered
    invalid = copy.deepcopy(contract)
    invalid["match_analysis_article"]["article_plan"][0]["strength"] = "invalid"
    assert _render_match_analysis_article(invalid) == ""


def test_public_ui_workflow_runs_article_validation():
    workflow = (ROOT / ".github/workflows/public-ui-visual-evidence.yml").read_text(encoding="utf-8")
    assert workflow.count("scripts/match_analysis_article.py") >= 2
    assert workflow.count("tests/test_match_analysis_article.py") >= 2


def test_low_identifiability_weakens_exact_score_language_and_article_is_first():
    contract = _contract("2993794")
    article = contract["match_analysis_article"]
    assert article["forecast"]["exact_score_cluster"]["primary_score"] is None
    assert article["forecast"]["exact_score_cluster"]["unique_score_allowed"] is False

    html = render_match_detail(contract)
    rendered_article = _render_match_analysis_article(contract)
    article_start = html.index('id="analysis-article"')
    primary_start = html.index('class="grid3 primary-grid"')
    assert article_start < primary_start
    assert 'data-article-version="match_analysis_article.v2"' in rendered_article
    assert 'data-identifiability="LOW"' in rendered_article
    assert "不设唯一首选" in rendered_article


def test_renderer_reads_article_plan_not_legacy_paragraphs():
    contract = _contract("2996143")
    article = contract["match_analysis_article"]
    article["paragraphs"] = [{"role": "legacy", "text": "不应渲染"}]
    rendered = _render_match_analysis_article(contract)
    assert "不应渲染" not in rendered
    assert "data-article-role=\"thesis\"" in rendered


def test_article_is_deterministic_without_mutating_prediction_record():
    prediction_path = ROOT / "data/model_governance/predictions/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    before = prediction_path.read_bytes()
    first = copy.deepcopy(_contract("3019134")["match_analysis_article"])
    second = _contract("3019134")["match_analysis_article"]
    assert first == second
    assert prediction_path.read_bytes() == before


def _issue301_inputs(*, lineup_state="CONFIRMED", lineup_value=None):
    prediction = {
        "prediction_id": "P-301",
        "prediction_sha256": "prediction-301-sha",
        "match_id": "301",
        "kickoff_at": "2026-09-10T18:00:00+08:00",
        "freeze_created_at": "2026-09-10T12:00:00+08:00",
        "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
    }
    fields = {
        "market_context": {
            "state": "PRESENT",
            "value": {"bookmakers": []},
            "observed_at": "2026-09-10T11:00:00+08:00",
            "prematch_eligible": True,
        },
        "lineup_state": {
            "state": "PRESENT",
            "semantic_state": lineup_state,
            "value": lineup_value if lineup_value is not None else {
                "home": {"team_id": 10, "team_name": "Team A", "players": [{"player_id": 101, "player_name": "A One"}]},
                "away": {"team_id": 20, "team_name": "Team B", "players": [{"player_id": 201, "player_name": "B One"}]},
            },
            "observed_at": "2026-09-10T11:30:00+08:00",
            "prematch_eligible": True,
        },
    }
    evidence = {
        "source": {"provider": "fixture", "source_cutoff_at": "2026-09-10T12:00:00+08:00"},
        "prematch_evidence": {"fields": fields},
    }
    fixture = {"matchId": "301", "home_team_id": 10, "away_team_id": 20, "kickoff_at": prediction["kickoff_at"]}
    identity = {"home_team_id": 10, "away_team_id": 20, "home_team_name": "Team A", "away_team_name": "Team B"}
    return prediction, {}, evidence, fixture, identity


def test_issue301_envelope_fails_closed_on_future_and_unresolved_refs():
    prediction, snapshot, evidence, fixture, _ = _issue301_inputs()
    evidence["prematch_evidence"]["fields"]["market_context"]["observed_at"] = "2026-09-10T19:00:00+08:00"
    envelope = build_evidence_envelope(prediction, snapshot, evidence, fixture)
    items = {item["evidence_id"]: item for item in envelope["items"]}
    assert items["football_evidence.market_context"]["status"] == "STALE"
    assert items["football_evidence.market_context"]["admissible"] is False
    plan = [{
        "role": "market", "subject": "market", "direction": "neutral", "strength": "weak",
        "evidence_refs": ["football_evidence.market_context"], "order": 1, "text": "market",
    }]
    assert render_article_plan(plan, envelope) == []


def test_issue301_availability_latest_recovery_cancels_prior_absence():
    prediction, snapshot, evidence, fixture, _ = _issue301_inputs()
    evidence["prematch_evidence"]["fields"]["injuries"] = {
        "state": "PRESENT",
        "value": {"records": [
            {"player_id": 7, "status": "OUT", "observed_at": "2026-09-09T10:00:00+08:00"},
            {"player_id": 7, "status": "AVAILABLE", "observed_at": "2026-09-10T11:00:00+08:00"},
        ]},
        "observed_at": "2026-09-10T11:00:00+08:00",
        "prematch_eligible": True,
    }
    envelope = build_evidence_envelope(prediction, snapshot, evidence, fixture)
    item = next(item for item in envelope["items"] if item["evidence_id"] == "football_evidence.injuries")
    assert item["status"] == "VERIFIED"
    assert item["value"]["records"] == [{"player_id": 7, "status": "AVAILABLE", "observed_at": "2026-09-10T11:00:00+08:00"}]


def test_issue301_late_briefing_requires_confirmed_identity_and_preserves_base():
    prediction, snapshot, evidence, fixture, identity = _issue301_inputs()
    base = {"contract_version": "match_analysis_article.v2", "status": "AVAILABLE", "article_plan": [{"text": "frozen"}]}
    base_before = copy.deepcopy(base)
    prediction_before = copy.deepcopy(prediction)
    briefing = build_late_briefing(base, prediction, snapshot, evidence, fixture, identity)
    assert briefing["status"] == "AVAILABLE"
    assert briefing["lineup_status"] == "CONFIRMED"
    assert briefing["base_article_sha256"]
    assert "probabilities" not in briefing
    assert 'id="late-briefing"' in _render_late_briefing({"late_briefing": briefing})
    assert base == base_before
    assert prediction == prediction_before

    expected = copy.deepcopy(evidence)
    expected["prematch_evidence"]["fields"]["lineup_state"]["semantic_state"] = "PREDICTED"
    assert build_late_briefing(base, prediction, snapshot, expected, fixture, identity)["status"] == "OMITTED"

    wrong_team = copy.deepcopy(evidence)
    wrong_team["prematch_evidence"]["fields"]["lineup_state"]["value"]["home"]["players"][0]["team_id"] = 20
    assert build_late_briefing(base, prediction, snapshot, wrong_team, fixture, identity)["reason"] == "LINEUP_IDENTITY_AMBIGUOUS"
