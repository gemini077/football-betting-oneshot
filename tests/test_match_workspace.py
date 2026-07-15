import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.match_workspace import RUNTIME, build, build_daily_portfolio, create_unique_output_dir, find_review, render, report_candidates, review_rows


class MatchWorkspacePortfolioTests(unittest.TestCase):
    def test_same_second_rebuild_uses_a_unique_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            first = create_unique_output_dir(output, "20260715_075740")
            second = create_unique_output_dir(output, "20260715_075740")
            self.assertEqual("20260715_075740", first.name)
            self.assertEqual("20260715_075740_02", second.name)

    def test_empty_portfolio_keeps_all_three_layers_empty(self):
        portfolio = build_daily_portfolio([], {"exposure": {"open_bets": [], "current_open_exposure": 0}})

        self.assertEqual("三层均为空仓", portfolio["state"])
        self.assertEqual(["保本层", "中轴层", "博上层"], [row["name"] for row in portfolio["layers"]])
        self.assertTrue(all(row["ticket_count"] == 0 for row in portfolio["layers"]))
        self.assertEqual([], portfolio["parlays"])

    def test_candidates_are_aggregated_and_same_match_overlap_is_audited(self):
        report = {
            "payload": {
                "betting": {
                    "candidates": [
                        {"ticket_id": "C101", "market": "小2.5", "tier": "中轴层", "amount": 4},
                        {"ticket_id": "C102", "market": "正确比分1-0", "amount": 1},
                    ]
                }
            }
        }
        candidates = report_candidates(report, "主队", "客队")
        matches = [{"id": "M101", "portfolio_candidates": candidates}]

        portfolio = build_daily_portfolio(matches, {"exposure": {"open_bets": [], "current_open_exposure": 0}})

        self.assertEqual("中轴层", candidates[0]["tier"])
        self.assertEqual("博上层", candidates[1]["tier"])
        self.assertEqual(5.0, portfolio["candidate_exposure"])
        self.assertEqual(["C101", "C102"], portfolio["overlap_audit"][0]["ticket_ids"])

    def test_configured_parlay_is_homepage_portfolio_data_only(self):
        runtime = {
            "exposure": {"open_bets": [], "current_open_exposure": 0},
            "betting_portfolio": {
                "parlays": [{"ticket_id": "P001", "legs": ["A", "B"], "status": "候选｜未锁单"}]
            },
        }

        portfolio = build_daily_portfolio([], runtime)

        self.assertEqual("P001", portfolio["parlays"][0]["ticket_id"])
        self.assertEqual("组合候选待用户确认", portfolio["state"])

    def test_stdlib_xlsx_fallback_exposes_full_review_dimensions(self):
        runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
        rows = review_rows(runtime)

        self.assertGreaterEqual(len(rows), 1)
        latest = rows[-1]
        self.assertIn("赛前亚盘方向", latest)
        self.assertIn("赛前大小球方向", latest)
        self.assertIn("赛前BTTS判断", latest)
        self.assertIsInstance(latest.get("_timeline"), dict)
        self.assertIsInstance(latest.get("_root_cause"), dict)

    def test_review_team_alias_can_match_short_schedule_name(self):
        rows = [{"赛事与对阵": "测试联赛｜杰尔 vs 雷克雅未克维京人", "实际90分钟比分": "2-2"}]

        review = find_review("杰尔", "雷克维京", rows)

        self.assertEqual("2-2", review["实际90分钟比分"])

    def test_historical_snapshot_does_not_overwrite_stable_homepage(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            latest = output / "latest.html"
            latest.write_text("KEEP_CURRENT", encoding="utf-8")

            build((date.today() - timedelta(days=2)).isoformat(), output)

            self.assertEqual("KEEP_CURRENT", latest.read_text(encoding="utf-8"))

    def test_homepage_has_separate_review_and_prematch_actions(self):
        page = render("{}")

        self.assertIn("data-review", page)
        self.assertIn("data-prematch", page)
        self.assertIn("赛前各维度逐项复核", page)
        self.assertIn("根因、反事实与模型修正", page)


if __name__ == "__main__":
    unittest.main()
