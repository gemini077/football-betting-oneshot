from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from automatic_model_core import build_automatic_model


def test_deterministic_model_generates_complete_probability_matrix():
    deep = {"shuju": {"recent_form": {
        "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
        "away_overall": {"matches": 10, "goals_for": 22, "goals_against": 9},
        "home_home": {"matches": 10, "goals_for": 19, "goals_against": 11},
        "away_away": {"matches": 10, "goals_for": 16, "goals_against": 13},
    }}, "ouzhi": {"bookmakers": [
        {"spf_current": {"home": 4.5, "draw": 4.0, "away": 1.7}},
        {"spf_current": {"home": 4.2, "draw": 3.8, "away": 1.72}},
    ]}, "daxiao": {"companies": [{"current_line": 2.75}, {"current_line": 2.5}]}}
    context = {"request": {"match_id": "2040514"}, "selected_workspace_match": {"id": "2040514", "home": "主队", "away": "客队"}, "source_snapshots": {"500_deep": {"snapshots": [deep]}}}
    result = build_automatic_model(context)
    model = result["model"]
    assert model["lambda_home"] > 0 and model["lambda_away"] > 0
    assert abs(sum(model["probabilities"].values()) - 1) < 1e-5
    assert len(model["score_probabilities"]) == 10
    assert model["score_probabilities"][0]["fair_odds"] > 1
    assert any(row["market"] == "SPF主胜" for row in result["price_audit"])
    assert result["decisions"]["unique_score"] == model["score_probabilities"][0]["score"]
    assert result["live_ev_profiles"]["active"] is True
    assert result["live_ev_profiles"]["contract"]["market_name"] == "全场独赢"
    assert result["decisions"]["match_story"]
    assert "单个比分格" in result["decisions"]["score_vs_outcome_explanation"]
    assert result["decisions"]["market_conflict"]


def test_deterministic_model_refuses_to_invent_missing_form():
    context = {"source_snapshots": {"500_deep": {"snapshots": [{"shuju": {}, "ouzhi": {}}]}}}
    assert build_automatic_model(context)["model"] is None


def test_deterministic_model_uses_checked_espn_form_when_deep_page_is_missing():
    form = {
        "home_overall": {"matches": 5, "wins": 2, "draws": 1, "losses": 2, "goals_for": 7, "goals_against": 6},
        "home_home": {"matches": 2, "wins": 1, "draws": 1, "losses": 0, "goals_for": 4, "goals_against": 2},
        "away_overall": {"matches": 5, "wins": 3, "draws": 1, "losses": 1, "goals_for": 9, "goals_against": 4},
        "away_away": {"matches": 2, "wins": 1, "draws": 0, "losses": 1, "goals_for": 3, "goals_against": 2},
    }
    context = {
        "request": {"match_id": "2040518"},
        "selected_workspace_match": {"id": "2040518", "home": "日利纳", "away": "斯海杜克"},
        "source_snapshots": {"500_deep": {"snapshots": []}},
        "prematch_fundamentals": {"recent_form": form, "form_source": "ESPN近5场赛事样本"},
        "official_market_baseline": {"fair_probabilities": {"home": 0.30, "draw": 0.27, "away": 0.43}},
    }

    result = build_automatic_model(context)

    assert result["model"] is not None
    assert result["model"]["method"] == "recent_form_market_calibrated_poisson_v2"
    assert result["model"]["calibration"]["form_source"] == "ESPN近5场赛事样本"
    assert any("ESPN" in item for item in result["model"]["limitations"])
