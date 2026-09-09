from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.match_detail import render_match_detail  # noqa: E402
from scripts.prediction_dashboard import render_dashboard  # noqa: E402
from test_match_analysis import assemble, roots  # noqa: E402


def dashboard_payload() -> dict:
    return {
        "business_date": "2026-09-08",
        "generated_at": "2026-09-08T12:00:00+08:00",
        "summary": {"fixture_count": 1, "verified_results": 0},
        "system_runtime_health": {"status": "HEALTHY"},
        "prediction_quality_health": {
            "status": "HEALTHY",
            "scope": "current_serving",
            "available": True,
            "provenance_status": "MATCHED",
        },
        "fixtures": [
            {
                "match_id": "TARGET",
                "match_num": "周一001",
                "competition": "测试联赛",
                "kickoff": "2026-09-09T20:00:00+08:00",
                "kickoff_timestamp": "2026-09-09T12:00:00Z",
                "home": "主队",
                "away": "客队",
                "status": "FROZEN",
                "result": None,
                "prediction": {
                    "probabilities": {"home": 0.486, "draw": 0.276, "away": 0.238},
                    "totals": [
                        {"goals": "0", "probability": 0.08},
                        {"goals": "1", "probability": 0.19},
                        {"goals": "2", "probability": 0.29},
                        {"goals": "3", "probability": 0.22},
                        {"goals": "4+", "probability": 0.22},
                    ],
                    "score_distribution": [
                        {"score": "1-0", "probability": 0.147},
                        {"score": "1-1", "probability": 0.122},
                        {"score": "2-0", "probability": 0.101},
                    ],
                    "formal_markets": {
                        "markets": {
                            "exact_score": {"status": "AVAILABLE"},
                        },
                    },
                },
                "pilot_excluded": False,
            },
        ],
        "completed": [],
    }


def test_dashboard_uses_locked_probability_desk_surface():
    html = render_dashboard(dashboard_payload())

    assert 'class="app-shell"' in html
    assert 'class="side-rail"' in html
    assert 'class="league-group"' in html
    assert 'class="fixture-row match-card' in html
    assert 'data-matchup="true"' in html
    assert 'class="matchup-side matchup-home"' in html
    assert 'class="matchup-vs"' in html
    assert 'class="matchup-side matchup-away"' in html
    assert 'class="teams-status"' in html
    assert 'class="table-header"' not in html
    assert 'class="footer-principles"' in html
    assert "OneShot" in html
    assert "1X2 \u6982\u7387" in html
    assert html.count('class="probability-segment ') == 3
    assert 'data-score-serving-state="NORMAL"' not in html
    assert 'data-score-serving-state="DEGRADED"' in html
    assert html.count('data-score-rank=') == 3
    assert "Exact Top3" in html
    assert "\u603b\u8fdb\u7403\u5206\u5e03" not in html
    assert "\u5e02\u573a\u5bf9\u7167" not in html
    assert "\u51b3\u7b56\u8bed\u5883" not in html
    assert ".queue-score, .queue-context { display: none; }" not in html
    assert "JC" not in html
    assert "Top10" not in html
    assert "Top15" not in html
    assert "\u63a8\u8350" not in html
    assert 'href="./latest.html"' in html
    assert "source" not in html.lower()


def test_detail_keeps_exact_score_as_separate_truthful_lane(tmp_path):
    contract = assemble(roots(tmp_path, include_formal_markets=True))
    contract["model"]["probabilities"] = {"home": 0.486, "draw": 0.276, "away": 0.238}
    contract["model"]["totals"] = [
        {"goals": "0", "probability": 0.08},
        {"goals": "1", "probability": 0.19},
        {"goals": "2", "probability": 0.29},
        {"goals": "3", "probability": 0.22},
        {"goals": "4+", "probability": 0.22},
    ]
    contract["evidence"]["fundamentals"] = {
        "captured_at": "2026-09-08T12:00:00+08:00",
        "recent_form": {"home_overall": {"matches": 5, "wins": 3, "draws": 1, "losses": 1}},
    }
    html = render_match_detail(contract)

    assert html.count('data-exact-cell-home=') == 169
    assert html.count('data-exact-compact-score=') == 6
    assert 'data-exact-compact-source-cell-count="169"' in html
    assert 'data-exact-compact-remainder-count="163"' in html
    assert 'data-exact-disclosure' in html
    assert 'class="hero"' in html
    assert 'data-matchup="true"' in html
    assert 'class="matchup-vs hero-vs"' in html
    assert '.detail-page .hero .team h1 { font-size: 13px;' in html
    assert '.detail-page .kick strong { font-size: 14px;' in html
    assert '.detail-page .supporting-grid { display: flex;' in html
    assert '.detail-page .supporting-panel { min-height: 0;' in html
    assert 'class="tabs"' in html
    assert html.count('class="grid3') >= 2
    assert 'score-grid signature-grid' in html
    assert 'class="trust-strip detail-trust"' in html
    assert '<details open class="exact-full-disclosure"' not in html
    assert html.count('class="probability-segment') == 3
    assert "JC" not in html
    assert "BTTS" not in html
    assert "Top10" not in html
    assert "Top15" not in html
    assert "\u63a8\u8350" not in html
    assert "\u7531\u5f53\u524d\u6bd4\u5206\u5206\u5e03\u6c47\u603b" in html
    assert "\u603b\u8fdb\u7403\u5206\u5e03\u6700\u9ad8\u6bb5" not in html
    assert 'data-evidence-role="MODEL_INPUT"' in html

    unavailable = copy.deepcopy(contract)
    unavailable["formal_markets"]["markets"]["exact_score"] = {
        "status": "NOT_RECORDED",
        "reason_code": "FORMAL_CONTRACT_NOT_RECORDED",
    }
    unavailable_html = render_match_detail(unavailable)
    assert 'data-exact-state="UNAVAILABLE"' in unavailable_html
    assert 'data-exact-cell-home=' not in unavailable_html
    assert 'data-exact-compact-score=' not in unavailable_html
    assert "\u6bd4\u5206\u6982\u7387\u6682\u4e0d\u53ef\u7528" in unavailable_html


def test_completed_detail_prioritizes_90_minute_result(tmp_path):
    contract = assemble(roots(tmp_path, include_formal_markets=True))
    contract["model"]["probabilities"] = {"home": 0.486, "draw": 0.276, "away": 0.238}
    contract["model"]["totals"] = [{"goals": "2", "probability": 0.29}]
    contract["result"] = {
        "score_90m": "0-2",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-09-08T23:00:00+08:00",
        "source": "TEST FIXTURE",
    }
    html = render_match_detail(contract)

    assert html.index('id="result"') < html.index('id="verification"') < html.index('id="analysis"')
    assert "0-2" in html
    assert "90\u5206\u949f\u8d5b\u679c" in html
    assert "\u9884\u6d4b vs \u5b9e\u9645" in html
    assert "actual_probability" not in html


def test_understand_match_separates_only_explicit_evidence_roles(tmp_path):
    contract = assemble(roots(tmp_path, include_formal_markets=True))
    contract["evidence"] = {
        "fundamentals": {
            "recent_form": {"home_overall": {"matches": 5, "wins": 3}},
        },
        "market_reaction": [{"text": "同一场赛前快照记录了主胜变化。"}],
        "context_only": [{"text": "赛事背景仅供阅读。"}],
        "missing_or_unverified": [{"text": "伤停信息未确认。"}],
    }
    contract["change_awareness"] = {
        "status": "AVAILABLE",
        "current_snapshot": {"prediction_id": "CURRENT"},
        "previous_snapshot": {"prediction_id": "PREVIOUS"},
        "markets": {},
    }

    html = render_match_detail(contract)

    assert 'data-evidence-role="MODEL_INPUT"' in html
    assert 'data-evidence-role="MARKET_REACTION"' in html
    assert 'data-evidence-role="CONTEXT_ONLY"' in html
    assert 'data-evidence-role="MISSING_OR_UNVERIFIED"' in html
    assert "模型输入" in html
    assert "市场变化" in html
    assert "背景信息" in html
    assert "缺失或未确认" in html
