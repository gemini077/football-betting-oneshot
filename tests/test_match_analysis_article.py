from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.match_analysis import assemble_match_analysis  # noqa: E402
from scripts.match_analysis_article import build_match_analysis_article  # noqa: E402
from scripts.match_analysis_evidence_binding import (  # noqa: E402
    article_base_hash,
    base_article_evidence,
    bind_article_plan,
    build_evidence_envelope,
    build_late_briefing,
)
from scripts.match_detail import _render_match_analysis_article, render_match_detail  # noqa: E402


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


def _o2_prediction(cutoff: str = "2026-09-18T10:00:00+00:00") -> dict:
    return {
        "prediction_id": "FBOS-PRED-O2-TEST",
        "source_cutoff_at": cutoff,
        "kickoff_at": "2026-09-18T12:00:00+00:00",
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "top_scores": [{"score": "1-0", "probability": 0.1}],
        "totals": [{"goals": 2, "probability": 0.4}, {"goals": 3, "probability": 0.6}],
        "btts": {"yes": 0.45, "no": 0.55},
    }


def _o2_evidence(fields: dict) -> dict:
    return {
        "source_provider": "fixture-test",
        "prematch_evidence": {
            "source": {
                "provider": "fixture-test",
                "source_references": ["fixture://o2"],
            },
            "target_fixture": {
                "provider_match_id": "fixture-301",
                "home_team_id": 10,
                "away_team_id": 20,
                "kickoff_at": "2026-09-18T12:00:00+00:00",
            },
            "fields": fields,
        },
    }

def _o2_field(
    value,
    *,
    state: str = "PRESENT",
    observed_at: str = "2026-09-18T10:00:00+00:00",
    semantic_state: str | None = None,
) -> dict:
    return {
        "state": state,
        "value": value,
        "reason_code": "TEST",
        "semantic_state": semantic_state,
        "surface": "fixture",
        "source_surfaces": ["fixture"],
        "observed_at": observed_at,
        "source_update_at": observed_at,
        "prematch_eligible": True,
    }


def _confirmed_side(team_id: int, prefix: str) -> dict:
    return {
        "team_id": team_id,
        "starting_xi": [
            {"player_id": f"{prefix}-{index}", "name": f"{prefix}{index}"}
            for index in range(1, 12)
        ],
    }


def test_o2_exact_cutoff_is_admissible_but_future_evidence_is_not():
    prediction = _o2_prediction()
    exact = build_evidence_envelope(
        prediction,
        _o2_evidence({"recent_form": _o2_field({"summary": {}})}),
        {},
    )    exact_item = next(
        item for item in exact["items"]
        if item["evidence_id"] == "football_evidence.recent_form"
    )
    assert exact_item["status"] == "VERIFIED"
    assert exact_item["freshness"] == "AT_OR_BEFORE_CUTOFF"
    assert exact_item["admissible"] is True

    future = build_evidence_envelope(
        prediction,
        _o2_evidence({
            "recent_form": _o2_field(
                {"summary": {}},
                observed_at="2026-09-18T10:00:01+00:00",
            )
        }),
        {},
    )
    future_item = next(
        item for item in future["items"]
        if item["evidence_id"] == "football_evidence.recent_form"
    )
    assert future_item["status"] == "VERIFIED"
    assert future_item["freshness"] == "AFTER_CUTOFF"
    assert future_item["admissible"] is False

    plan = [{
        "role": "recent_process",
        "subject": "主队",
        "direction": "home",
        "strength": "moderate",
        "evidence_refs": ["football_evidence.recent_form"],
        "order": 1,
        "text": "主队近期表现占优。",
    }]
    assert bind_article_plan(plan, exact) == plan
    assert bind_article_plan(plan, future) == []


def test_o2_unresolved_evidence_id_fails_closed():
    envelope = build_evidence_envelope(
        _o2_prediction(),
        _o2_evidence({}),
        {},
    )
    plan = [{
        "role": "forecast",
        "subject": "prediction",
        "direction": "home",
        "strength": "moderate",
        "evidence_refs": ["football_evidence.does_not_exist"],
        "order": 1,
        "text": "不应进入文章。",
    }]
    assert bind_article_plan(plan, envelope) == []


def test_o2_stale_absence_is_not_current_and_recovery_cancels_prior_absence():
    stale_evidence = _o2_evidence({
        "injuries": _o2_field({
            "records": [{
                "player_id": "p7",
                "team_id": 10,
                "status": "OUT",
                "as_of": "2026-09-18T08:00:00+00:00",
                "valid_until": "2026-09-18T09:00:00+00:00",
            }]
        })
    })
    stale = build_evidence_envelope(_o2_prediction(), stale_evidence, {})
    stale_item = next(
        item for item in stale["items"]
        if item["evidence_id"] == "football_evidence.injuries"
    )
    assert stale_item["status"] == "STALE"
    assert stale_item["value"]["current_absences"] == []

    recovered_evidence = _o2_evidence({
        "injuries": _o2_field({
            "records": [
                {
                    "player_id": "p7",
                    "team_id": 10,
                    "status": "OUT",
                    "as_of": "2026-09-18T08:00:00+00:00",
                },
                {
                    "player_id": "p7",
                    "team_id": 10,
                    "status": "RECOVERED",
                    "as_of": "2026-09-18T09:30:00+00:00",
                },
            ]
        })
    })
    recovered = build_evidence_envelope(_o2_prediction(), recovered_evidence, {})
    recovered_item = next(
        item for item in recovered["items"]
        if item["evidence_id"] == "football_evidence.injuries"
    )
    assert recovered_item["status"] == "VERIFIED"
    assert recovered_item["value"]["current_absences"] == []
    assert recovered_item["value"]["resolved_records"][0]["status"] == "RECOVERED"


def test_o2_wrong_team_availability_binding_degrades_instead_of_guessing():
    evidence = _o2_evidence({
        "injuries": _o2_field({
            "records": [{
                "player_id": "p7",
                "team_id": 999,
                "status": "OUT",
                "as_of": "2026-09-18T09:00:00+00:00",
            }]
        })
    })
    envelope = build_evidence_envelope(_o2_prediction(), evidence, {})
    item = next(
        item for item in envelope["items"]
        if item["evidence_id"] == "football_evidence.injuries"
    )
    assert item["status"] == "DEGRADED"
    assert item["admissible"] is False
    assert "TEAM_ID_MISMATCH" in item["availability_resolution"]["binding_errors"]


def test_o2_expected_lineup_never_becomes_confirmed_late_briefing():
    prediction = _o2_prediction()
    evidence = _o2_evidence({
        "lineup_state": _o2_field(
            {
                "confirmation_status": "EXPECTED",
                "home": _confirmed_side(10, "h"),
                "away": _confirmed_side(20, "a"),
            },
            observed_at="2026-09-18T11:30:00+00:00",
            semantic_state="EXPECTED",
        )
    })
    envelope = build_evidence_envelope(prediction, evidence, {})
    base = {"contract_version": "match_analysis_article.v2", "status": "AVAILABLE", "article_plan": []}    late = build_late_briefing(base, prediction, evidence, envelope)
    assert late["status"] == "OMITTED"
    assert late["reason_code"] == "LINEUP_NOT_CONFIRMED"


def test_o2_confirmed_lineup_is_independent_and_identity_bound():
    prediction = _o2_prediction()
    evidence = _o2_evidence({
        "lineup_state": _o2_field(
            {
                "confirmation_status": "CONFIRMED",
                "home": _confirmed_side(10, "h"),
                "away": _confirmed_side(20, "a"),
            },
            observed_at="2026-09-18T11:30:00+00:00",
            semantic_state="CONFIRMED",
        )
    })
    envelope = build_evidence_envelope(prediction, evidence, {})
    base = {
        "contract_version": "match_analysis_article.v2",
        "status": "AVAILABLE",
        "article_plan": [{"role": "thesis", "text": "冻结基础文章"}],
    }
    base_before = copy.deepcopy(base)
    prediction_before = copy.deepcopy(prediction)
    late = build_late_briefing(base, prediction, evidence, envelope)
    assert late["status"] == "AVAILABLE"
    assert late["evidence_refs"] == ["football_evidence.lineup_state"]
    assert len(late["confirmed_xi"]["home"]["players"]) == 11
    assert len(late["confirmed_xi"]["away"]["players"]) == 11
    assert late["base_article_hash"] == article_base_hash(base)
    assert base == base_before
    assert prediction == prediction_before
    assert "probability" not in json.dumps(late, ensure_ascii=False).casefold()

    wrong = copy.deepcopy(evidence)
    wrong["prematch_evidence"]["fields"]["lineup_state"]["value"]["away"]["team_id"] = 999
    wrong_envelope = build_evidence_envelope(prediction, wrong, {})
    wrong_late = build_late_briefing(base, prediction, wrong, wrong_envelope)
    assert wrong_late["status"] == "OMITTED"
    assert wrong_late["reason_code"] == "LINEUP_IDENTITY_MISMATCH"


def test_o2_evidence_hash_changes_when_relevant_freshness_changes():
    prediction = _o2_prediction()
    first = build_evidence_envelope(
        prediction,
        _o2_evidence({
            "recent_form": _o2_field(
                {"summary": {}},
                observed_at="2026-09-18T09:59:58+00:00",
            )
        }),
        {},
    )
    second = build_evidence_envelope(
        prediction,
        _o2_evidence({
            "recent_form": _o2_field(
                {"summary": {}},
                observed_at="2026-09-18T09:59:59+00:00",
            )
        }),
        {},
    )
    assert first["content_hash"] != second["content_hash"]


def test_o2_real_article_refs_resolve_and_late_briefing_fails_closed_without_confirmed_xi():
    article = _contract("2996143")["match_analysis_article"]
    assert article["evidence_envelope"]["contract_version"] == "match_analysis_evidence_envelope.v1"
    lookup = {
        item["evidence_id"]: item
        for item in article["evidence_envelope"]["items"]
    }
    for item in article["article_plan"]:
        for ref in item["evidence_refs"]:
            assert ref in lookup
            assert lookup[ref]["admissible"] is True    assert article["base_article_hash"] == article_base_hash(article)
    assert article["late_briefing"]["status"] == "OMITTED"

def test_o2_base_article_calculation_cannot_use_post_cutoff_field_updates():
    prediction_path = ROOT / "data/model_governance/predictions/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    sidecar_path = ROOT / "data/prospective/football_evidence/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    snapshot_ref = prediction["model_input_snapshot_ref"]
    snapshot = json.loads((ROOT / snapshot_ref).read_text(encoding="utf-8"))
    identity = {
        "match_id": "3019134",
        "home": "纽伦堡",
        "away": "汉诺威96",
        "kickoff_at": prediction["kickoff_at"],
    }

    future = copy.deepcopy(sidecar)
    future_field = future["prematch_evidence"]["fields"]["future_schedule_rest"]
    future_field["observed_at"] = "2026-09-11T13:52:27+00:00"
    future_field["source_update_at"] = "2026-09-11T13:52:27+00:00"
    for fixture in future_field["value"]["fixtures"]:
        fixture["interval_days"] = 1

    absent = copy.deepcopy(sidecar)
    absent_field = absent["prematch_evidence"]["fields"]["future_schedule_rest"]
    absent_field["state"] = "ABSENT"
    absent_field["value"] = None

    future_article = build_match_analysis_article(
        prediction, snapshot, future, identity, identity
    )
    absent_article = build_match_analysis_article(
        prediction, snapshot, absent, identity, identity
    )
    assert future_article["article_plan"] == absent_article["article_plan"]
    assert future_article["forecast"] == absent_article["forecast"]
    assert future_article["future_schedule_rest"] == absent_article["future_schedule_rest"]

    envelope = build_evidence_envelope(prediction, future, identity)
    frozen = base_article_evidence(future, envelope)
    assert frozen["prematch_evidence"]["fields"]["future_schedule_rest"]["state"] == "ABSENT"
    assert frozen["prematch_evidence"]["fields"]["future_schedule_rest"]["value"] is None


def test_o2_late_briefing_rejects_post_kickoff_source_update_and_semantic_conflict():
    prediction = _o2_prediction()
    evidence = _o2_evidence({
        "lineup_state": _o2_field(
            {
                "confirmation_status": "CONFIRMED",
                "home": _confirmed_side(10, "h"),
                "away": _confirmed_side(20, "a"),
            },
            observed_at="2026-09-18T11:30:00+00:00",
            semantic_state="CONFIRMED",
        )
    })
    evidence["prematch_evidence"]["fields"]["lineup_state"]["source_update_at"] = "2026-09-18T12:00:01+00:00"
    envelope = build_evidence_envelope(prediction, evidence, {})
    base = {"contract_version": "match_analysis_article.v2", "status": "AVAILABLE", "article_plan": []}
    late = build_late_briefing(base, prediction, evidence, envelope)
    assert late["status"] == "OMITTED"
    assert late["reason_code"] == "LINEUP_AFTER_KICKOFF_OR_TIME_UNKNOWN"

    conflict = copy.deepcopy(evidence)
    conflict_field = conflict["prematch_evidence"]["fields"]["lineup_state"]
    conflict_field["source_update_at"] = "2026-09-18T11:30:00+00:00"
    conflict_field["value"]["confirmation_status"] = "EXPECTED"
    conflict_envelope = build_evidence_envelope(prediction, conflict, {})
    conflict_late = build_late_briefing(base, prediction, conflict, conflict_envelope)
    assert conflict_late["status"] == "OMITTED"
    assert conflict_late["reason_code"] == "LINEUP_NOT_CONFIRMED"

def _real_3019134_late_evidence(provider_match_id: str = "3019134") -> dict:
    return {
        "source_provider": "fixture-test",
        "prematch_evidence": {
            "source": {"provider": "fixture-test", "source_references": ["fixture://late"]},
            "target_fixture": {
                "provider_match_id": provider_match_id,
                "home_team_id": 136,
                "away_team_id": 169,
                "kickoff_at": "2026-09-12T00:30:00+08:00",
            },
            "fields": {
                "lineup_state": _o2_field(
                    {
                        "confirmation_status": "CONFIRMED",
                        "home": _confirmed_side(136, "h"),
                        "away": _confirmed_side(169, "a"),
                    },
                    observed_at="2026-09-11T16:00:00+00:00",
                    semantic_state="CONFIRMED",
                )
            },
        },
    }


def test_o2_late_evidence_cannot_change_frozen_base_article_hash_or_plan():
    prediction_path = ROOT / "data/model_governance/predictions/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    sidecar_path = ROOT / "data/prospective/football_evidence/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    snapshot = json.loads((ROOT / prediction["model_input_snapshot_ref"]).read_text(encoding="utf-8"))
    identity = {
        "match_id": "3019134",
        "home": "纽伦堡",
        "away": "汉诺威96",
        "kickoff_at": prediction["kickoff_at"],
    }

    base_only = build_match_analysis_article(
        prediction, snapshot, sidecar, identity, identity
    )
    with_late = build_match_analysis_article(
        prediction,
        snapshot,
        sidecar,
        identity,
        identity,
        _real_3019134_late_evidence(),
    )

    assert base_only["base_article_hash"] == with_late["base_article_hash"]
    assert base_only["article_plan"] == with_late["article_plan"]
    assert base_only["forecast"] == with_late["forecast"]
    assert base_only["evidence_envelope"] == with_late["evidence_envelope"]
    assert base_only["late_briefing"]["status"] == "OMITTED"
    assert with_late["late_briefing"]["status"] == "AVAILABLE"
    assert with_late["late_briefing"]["base_article_hash"] == base_only["base_article_hash"]


def test_o2_late_briefing_rejects_wrong_fixture_even_with_valid_team_and_player_ids():
    prediction_path = ROOT / "data/model_governance/predictions/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    sidecar_path = ROOT / "data/prospective/football_evidence/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    snapshot = json.loads((ROOT / prediction["model_input_snapshot_ref"]).read_text(encoding="utf-8"))
    identity = {
        "match_id": "3019134",
        "home": "纽伦堡",
        "away": "汉诺威96",
        "kickoff_at": prediction["kickoff_at"],
    }

    article = build_match_analysis_article(
        prediction,
        snapshot,
        sidecar,
        identity,
        identity,
        _real_3019134_late_evidence("9999999"),
    )
    assert article["late_briefing"]["status"] == "OMITTED"
    assert article["late_briefing"]["reason_code"] == "LINEUP_FIXTURE_IDENTITY_MISMATCH"

