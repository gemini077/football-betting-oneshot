from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from automatic_model_core import _scenario_score_pick, build_automatic_model


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
    trace = result["decisions"]["score_selection_trace"]
    assert trace["selected_score"] == result["decisions"]["unique_score"]
    assert trace["method"] == "matrix_map_with_scenario_challenger_v1"
    assert trace["candidates"]
    assert result["live_ev_profiles"]["active"] is True
    assert result["live_ev_profiles"]["contract"]["market_name"] == "全场独赢"
    assert result["decisions"]["match_story"]
    assert "单个比分格" in result["decisions"]["score_vs_outcome_explanation"]
    assert result["decisions"]["market_conflict"]
    lines = {row["line"]: row for row in model["total_line_analysis"]}
    assert set(lines) == {2.5, 2.75, 3.0, 3.25, 3.5}
    assert abs(
        lines[3.5]["over"]["win_equivalent_probability"]
        + lines[3.5]["under"]["win_equivalent_probability"]
        - 1
    ) < 1e-5
    assert lines[3.0]["over"]["push_equivalent_probability"] > 0


def test_deterministic_model_refuses_to_invent_missing_form():
    context = {"source_snapshots": {"500_deep": {"snapshots": [{"shuju": {}, "ouzhi": {}}]}}}
    assert build_automatic_model(context)["model"] is None


def test_deterministic_model_labels_nowscore_form_as_primary():
    deep = {
        "source_provenance": {"form_primary": "nowscore_analysis"},
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 15, "goals_against": 10},
            "away_overall": {"matches": 10, "goals_for": 10, "goals_against": 15},
            "home_home": {"matches": 10, "goals_for": 17, "goals_against": 8},
            "away_away": {"matches": 10, "goals_for": 8, "goals_against": 17},
        }},
        "ouzhi": {"bookmakers": [{"spf_current": {"home": 1.8, "draw": 3.5, "away": 4.2}}]},
        "daxiao": {"companies": [{"current_line": 2.5}]},
    }
    result = build_automatic_model({"source_snapshots": {"500_deep": {"snapshots": [deep]}}})
    assert result["model"]["calibration"]["form_source"] == "Nowscore近期赛事数据"


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


def test_coach_and_referee_shape_match_script_without_overriding_probability():
    deep = {
        "source_provenance": {"form_primary": "nowscore_analysis"},
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 18, "goals_against": 9},
            "away_overall": {"matches": 10, "goals_for": 10, "goals_against": 16},
            "home_home": {"matches": 10, "goals_for": 20, "goals_against": 8},
            "away_away": {"matches": 10, "goals_for": 8, "goals_against": 18},
        }},
        "ouzhi": {"bookmakers": [{"spf_current": {"home": 1.70, "draw": 3.8, "away": 5.0}}]},
        "daxiao": {"companies": [{"current_line": 2.75}]},
        "nowscore_context": {
            "coach": {
                "home": {"name": "主帅甲", "team_records": [{"matches": 20, "points_per_match": 2.1, "venue_flag": "1"}]},
                "away": {"name": "客帅乙", "team_records": [{"matches": 18, "points_per_match": 1.1, "venue_flag": "0"}]},
            },
            "referee": {"name": "裁判甲", "summaries": [{
                "matches": 50,
                "home": {"avg_yellow": 2.5, "avg_red": 0.10, "win_rate": "46%"},
                "away": {"avg_yellow": 2.3, "avg_red": 0.08, "win_rate": "32%"},
            }]},
        },
    }
    result = build_automatic_model({
        "selected_workspace_match": {"home": "主队", "away": "客队"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
    })
    story = result["decisions"]["match_story"]
    assert "教练剧本" in story
    assert "裁判剧本" in story
    assert result["fundamentals"]["nowscore_context"]["script_context"]["model_usage"].endswith("not_probability_override")
    assert any("红牌" in item for item in result["decisions"]["maximum_error_points"])


def test_unique_score_uses_matrix_map_and_keeps_scenario_as_challenger():
    matrix = {
        (1, 1): 0.12,
        (2, 1): 0.11,
        (1, 0): 0.08,
        (0, 1): 0.06,
        (0, 0): 0.05,
    }
    score, reasoning, trace = _scenario_score_pick(
        matrix,
        {"home": 0.55, "draw": 0.25, "away": 0.20},
        [{"goals": "3", "probability": 0.40}, {"goals": "2", "probability": 0.30}],
        {"yes": 0.65, "no": 0.35},
        expected_goals=2.8,
        market_probabilities={"home": 0.58, "draw": 0.24, "away": 0.18},
        market_total=3.0,
        market_handicap=-1.0,
        script_context={},
    )
    assert trace["mathematical_first_score"] == "1-1"
    assert score == "1-1"
    assert trace["scenario_selected_score"] == "2-1"
    assert "正式唯一比分采用比分矩阵峰值" in reasoning
