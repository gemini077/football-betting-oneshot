import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_analysis_report import (  # noqa: E402
    normalize_betting_portfolio,
    score_matrix_summary,
    sensitivity_scenarios,
    timeline_svg,
    pct,
    render,
)


class AnalysisReportVisualTests(unittest.TestCase):
    def setUp(self):
        self.model = {"lambda_home": 1.10, "lambda_away": 0.98, "rho": -0.06}

    def test_negative_ev_is_rendered_as_a_fractional_percentage(self):
        self.assertEqual("-17.5%", pct(-0.175))

    def test_score_matrix_is_normalized_and_has_a_top_score(self):
        summary = score_matrix_summary(self.model)
        self.assertAlmostEqual(1.0, sum(summary["matrix"].values()), places=8)
        self.assertAlmostEqual(1.0, sum(summary["probabilities"].values()), places=8)
        self.assertRegex(summary["top_score"], r"^\d+-\d+$")

    def test_sensitivity_includes_baseline_and_directional_stresses(self):
        rows = sensitivity_scenarios(self.model)
        self.assertEqual(5, len(rows))
        self.assertEqual("基准", rows[0]["label"])
        self.assertGreater(rows[2]["under_25"], 0.0)
        self.assertGreater(rows[3]["lambda_home"], rows[0]["lambda_home"])
        self.assertGreater(rows[4]["lambda_away"], rows[0]["lambda_away"])

    def test_timeline_refuses_to_draw_from_two_points(self):
        two_points = [
            {"time": "t1", "home": 2.0, "draw": 3.0, "away": 4.0},
            {"time": "t2", "home": 1.9, "draw": 3.1, "away": 4.2},
        ]
        rendered = timeline_svg(two_points)
        self.assertIn("尚未形成至少3个独立时间点", rendered)
        self.assertNotIn("<svg", rendered)
        self.assertIn("真实多快照赔率轨迹", timeline_svg(two_points + [{"time": "t3", "home": 1.8, "draw": 3.2, "away": 4.4}]))

    def test_betting_portfolio_keeps_three_layers_without_forcing_candidates(self):
        betting = normalize_betting_portfolio({"candidates": [], "open_bets": []})
        self.assertEqual(["保本层", "中轴层", "博上层"], [item["label"] for item in betting["layers"]])
        self.assertTrue(all(item["status"] == "暂无合格候选" for item in betting["layers"]))
        self.assertEqual(0, betting["candidate_exposure"])

    def test_correct_score_is_upside_and_same_match_tickets_are_audited(self):
        betting = normalize_betting_portfolio({
            "candidates": [
                {"match": "法国 vs 摩洛哥", "market": "小2.5/3", "amount": 4},
                {"match": "法国 vs 摩洛哥", "market": "正确比分1-0", "amount": 2},
            ],
            "open_bets": [],
        })
        self.assertEqual("中轴层", betting["candidates"][0]["tier"])
        self.assertEqual("博上层", betting["candidates"][1]["tier"])
        self.assertEqual(6, betting["candidate_exposure"])
        self.assertEqual("同场多票", betting["overlap_audit"][0]["risk"])

    def test_parlay_is_preserved_as_a_separate_ticket(self):
        betting = normalize_betting_portfolio({
            "candidates": [],
            "parlays": [{"tier": "中轴", "legs": ["A主胜", "B小2.5"], "combined_odds": 2.4}],
        })
        self.assertEqual("P001", betting["parlays"][0]["ticket_id"])
        self.assertEqual("中轴层", betting["parlays"][0]["tier"])
        self.assertEqual("待逐腿价格审核", betting["parlays"][0]["status"])

    def test_report_restores_narrative_bridge_without_removing_new_modules(self):
        payload = {
            "report": {"model_name": "Football Betting OneShot", "model_version": "v0.14.1"},
            "match": {"home": "主队", "away": "客队"},
            "market": {}, "data_quality": {"missing": []},
            "model": {}, "betting": {"candidates": [], "open_bets": []},
            "decisions": {
                "match_story": "主队控球，客队反击",
                "market_conflict": "市场与模型存在分歧",
                "score_vs_outcome_explanation": "比分单格与方向合计不同",
                "maximum_error_points": ["首发变化"],
            },
        }
        page = render(payload)
        self.assertIn("比赛怎么发展", page)
        self.assertIn("市场在防什么", page)
        self.assertIn("比分与方向为何可能不同", page)
        self.assertIn("EV与实时渠道复算", page)


if __name__ == "__main__":
    unittest.main()
