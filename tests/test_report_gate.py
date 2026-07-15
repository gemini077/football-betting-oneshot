import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_analysis_report import build_base_engine_audit, enforce_complete_report_gate, mean_spf, normalize_page_pl_labels  # noqa: E402
from market_intelligence import fixed_odds_scenario_profit, kelly_panel, shin_no_vig  # noqa: E402


class ReportGateTests(unittest.TestCase):
    def test_legacy_house_pl_label_is_normalized(self):
        payload = {"fundamentals": ["庄家主胜方向盈亏为负，热门端风险集中"], "evidence": "庄家盈亏"}
        normalized = normalize_page_pl_labels(payload)
        self.assertEqual("页面模拟主胜盈亏为负（仅展示，不参与方向或EV）", normalized["fundamentals"][0])
        self.assertEqual("页面模拟盈亏", normalized["evidence"])

    def test_page_kelly_index_cannot_size_stakes(self):
        config = {"tiers": {"sharp": {"weight": 1.0, "members": {"1055": "Pinnacle"}}}}
        bookmakers = [{"cid": 1055, "kelly_current": {"home": 0.94, "draw": 0.95, "away": 1.0}}]
        panel = kelly_panel(bookmakers, config)
        self.assertEqual("bookmaker_page_kelly_index_not_bankroll_kelly_fraction", panel["semantic_scope"])
        self.assertEqual("forbidden", panel["staking_usage"])

    def test_shin_probabilities_are_normalized(self):
        result = shin_no_vig({"home": 1.21, "draw": 6.43, "away": 10.98})
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0)
        self.assertAlmostEqual(result["payout_rate"], 1.0 / result["overround"])
        self.assertGreaterEqual(result["z"], 0.0)

    def test_operator_profit_uses_actual_stakes_without_double_applying_payout_rate(self):
        result = fixed_odds_scenario_profit(
            {"home": 5200, "draw": 2400, "away": 2400},
            {"home": 1.82, "draw": 3.50, "away": 5.00},
        )
        self.assertEqual(10000.0, result["total_stakes"])
        self.assertAlmostEqual(536.0, result["operator_profit_by_outcome"]["home"], places=8)
        self.assertAlmostEqual(0.0536, result["operator_margin_on_stakes_by_outcome"]["home"], places=8)

    def test_operator_profit_rejects_poll_only_or_invalid_inputs(self):
        self.assertIsNone(fixed_odds_scenario_profit({"home": 0.8}, {"home": 1.25}))
        with self.assertRaises(ValueError):
            fixed_odds_scenario_profit(
                {"home": 0, "draw": 0, "away": 0},
                {"home": 1.25, "draw": 6.0, "away": 12.0},
            )

    def test_consensus_is_not_pinnacle_only(self):
        books = [
            {"spf_current": {"home": 2.0, "draw": 3.0, "away": 4.0}},
            {"spf_current": {"home": 2.2, "draw": 3.2, "away": 4.2}},
        ]
        self.assertEqual(mean_spf(books, "spf_current"), {"home": 2.1, "draw": 3.1, "away": 4.1})

    def test_full_report_is_downgraded_when_base_modules_not_run(self):
        payload = {
            "report": {"report_type": "完整分析版", "final_execution_version": True},
            "data_quality": {"missing": []},
            "base_engine_audit": build_base_engine_audit({}),
        }
        enforce_complete_report_gate(payload)
        self.assertEqual(payload["report"]["report_type"], "模型分析草稿（基础内核未完成）")
        self.assertFalse(payload["report"]["final_execution_version"])
        self.assertTrue(payload["base_engine_audit"]["incomplete_modules"])

    def test_full_report_survives_when_every_module_completed(self):
        audit = build_base_engine_audit({})
        for module in audit["modules"].values():
            module["calculation_status"] = "completed"
        payload = {
            "report": {"report_type": "完整分析版", "final_execution_version": False},
            "data_quality": {"missing": []},
            "base_engine_audit": audit,
        }
        enforce_complete_report_gate(payload)
        self.assertEqual(payload["report"]["report_type"], "完整分析版")
        self.assertEqual(payload["base_engine_audit"]["completion_status"], "complete")


if __name__ == "__main__":
    unittest.main()
