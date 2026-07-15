import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from risk_engine import (  # noqa: E402
    analyze,
    annualized_return,
    apply_log_lambda_corrections,
    asian_handicap_settlement,
    asian_total_settlement,
    binary_kelly_diagnostic,
    dixon_coles_score_matrix,
    exact_total_goals_set,
    fixed_odds_arbitrage,
    half_full_time_probabilities,
    lambdas_from_home_away_rates,
    mutually_exclusive_coverage_ev,
    poisson_truncation_audit,
    theoretical_asian_handicap,
    theoretical_asian_total,
)


class RiskEngineTests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads((ROOT / "config" / "trap_rules.json").read_text(encoding="utf-8"))

    def test_registry_preserves_upstream_47_of_49_gap(self):
        self.assertEqual(47, len(self.registry["rules"]))
        self.assertEqual(49, self.registry["upstream_claimed_total"])
        self.assertEqual(2, len(self.registry["unresolved_upstream_rules"]))

    def test_six_d_is_bounded_and_degraded_without_fundamentals(self):
        deep = {
            "ouzhi": {"bookmakers": [
                {"cid": 1055, "spf_open": {"home": 1.50, "draw": 4.0, "away": 6.0}, "spf_current": {"home": 1.40, "draw": 4.2, "away": 7.0}},
                {"cid": 3, "spf_open": {"home": 1.50, "draw": 4.0, "away": 6.0}, "spf_current": {"home": 1.52, "draw": 4.0, "away": 6.0}},
                {"cid": 5, "spf_open": {"home": 1.50, "draw": 4.0, "away": 6.0}, "spf_current": {"home": 1.50, "draw": 4.0, "away": 6.0}},
            ]},
            "yazhi": {"companies": [
                {"cid": 1055, "open_handicap": 1.5, "current_handicap": 1.25, "open_water_home": .90, "current_water_home": .92},
                {"cid": 3, "open_handicap": 1.5, "current_handicap": 1.25, "open_water_home": .91, "current_water_home": .93},
                {"cid": 5, "open_handicap": 1.5, "current_handicap": 1.25, "open_water_home": .92, "current_water_home": .94},
            ]},
        }
        mbi = {
            "consensus": {"shin": {"probabilities": {"home": .76, "draw": .15, "away": .09}}, "current": {"home": 1.50}},
            "modules": {"dri": {"raw": 30, "calibrated": None}, "scs": {"per_outcome": {"home": {"tier_scores": {"sharp": .1, "asian": .1}}}}},
        }
        result = analyze(deep, mbi, self.registry)
        self.assertGreaterEqual(result["six_d"]["legacy_0_to_6"], 0)
        self.assertLessEqual(result["six_d"]["legacy_0_to_6"], 6)
        self.assertEqual("degraded", result["six_d"]["calculation_status"])
        self.assertIn("EA12", [item["id"] for item in result["traps"]["triggered"]])
        self.assertIn("U18", [item["id"] for item in result["traps"]["triggered"]])

    def test_theoretical_handicap_uses_score_distribution(self):
        model = {"lambda_home": 2.75, "lambda_away": 0.82, "rho": -0.03}
        result = theoretical_asian_handicap(model)
        self.assertIsNotNone(result)
        self.assertEqual(-1.75, result["line"])
        self.assertAlmostEqual(1.91725, result["fair_decimal_odds"], places=4)

    def test_xg_rates_are_normalized_by_league_baseline_not_raw_multiplied(self):
        result = lambdas_from_home_away_rates(
            home_for=2.0,
            home_against=0.9,
            away_for=1.1,
            away_against=1.2,
            league_home_average=1.5,
            league_away_average=1.2,
            metric="xg",
        )
        self.assertAlmostEqual(1.6, result["lambda_home"], places=8)
        self.assertAlmostEqual(0.825, result["lambda_away"], places=8)
        self.assertNotEqual(2.4, result["lambda_home"])

    def test_xg_rate_builder_rejects_non_positive_baseline(self):
        with self.assertRaises(ValueError):
            lambdas_from_home_away_rates(
                home_for=2.0,
                home_against=0.9,
                away_for=1.1,
                away_against=1.2,
                league_home_average=0,
                league_away_average=1.2,
            )

    def test_log_lambda_corrections_reproduce_article_example_when_explicit(self):
        result = apply_log_lambda_corrections(
            1.92,
            0.82,
            home_log_adjustments={"form": 0.05, "rest": 0.06, "injury": 0.025},
            away_log_adjustments={"form": -0.05, "rest": -0.06, "injury": -0.025},
        )
        self.assertAlmostEqual(0.135, result["delta_home"], places=12)
        self.assertAlmostEqual(-0.135, result["delta_away"], places=12)
        self.assertAlmostEqual(2.19751, result["lambda_home"], places=5)
        self.assertAlmostEqual(0.71645, result["lambda_away"], places=5)

    def test_home_log_adjustment_never_silently_forces_away_opposite(self):
        result = apply_log_lambda_corrections(
            1.92,
            0.82,
            home_log_adjustments={"rest": 0.06},
        )
        self.assertAlmostEqual(1.92 * __import__("math").exp(0.06), result["lambda_home"], places=12)
        self.assertAlmostEqual(0.82, result["lambda_away"], places=12)
        self.assertEqual(0.0, result["delta_away"])

    def test_poisson_truncation_audit_reproduces_article_tail_gap(self):
        result = poisson_truncation_audit(0.685, 1.741, 5)
        self.assertAlmostEqual(0.9909992165, result["retained_probability_mass"], places=9)
        self.assertAlmostEqual(0.0090007835, result["omitted_probability_mass"], places=9)
        self.assertAlmostEqual(0.6189587680, result["raw_truncated_outcome_probabilities"]["away"], places=9)
        self.assertAlmostEqual(1.0, sum(result["normalized_within_grid_outcome_probabilities"].values()), places=9)
        self.assertFalse(result["pricing_allowed_without_overflow"])

    def test_poisson_truncation_audit_allows_negligible_tail_at_twelve(self):
        result = poisson_truncation_audit(0.685, 1.741, 12)
        self.assertLessEqual(result["omitted_probability_mass"], 1e-6)
        self.assertTrue(result["pricing_allowed_without_overflow"])

    def test_poisson_truncation_audit_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            poisson_truncation_audit(0, 1.7, 5)
        with self.assertRaises(ValueError):
            poisson_truncation_audit(0.7, 1.7, 5.5)

    def test_half_full_time_builds_nine_joint_outcomes(self):
        result = half_full_time_probabilities(
            lambda_home_first_half=0.8,
            lambda_away_first_half=0.3,
            lambda_home_second_half=0.4,
            lambda_away_second_half=1.0,
        )
        self.assertEqual(9, len(result["joint_probabilities"]))
        self.assertAlmostEqual(1.0, sum(result["joint_probabilities"].values()), places=9)
        self.assertAlmostEqual(1.0, sum(result["half_time_marginal"].values()), places=9)
        self.assertAlmostEqual(1.0, sum(result["full_time_marginal"].values()), places=9)
        self.assertGreater(result["joint_probabilities"]["H/A"], 0.0)
        self.assertTrue(result["pricing_allowed_without_overflow"])

    def test_half_full_time_does_not_infer_joint_from_marginals(self):
        result = half_full_time_probabilities(
            lambda_home_first_half=0.8,
            lambda_away_first_half=0.3,
            lambda_home_second_half=0.4,
            lambda_away_second_half=1.0,
        )
        product_of_marginals = result["half_time_marginal"]["H"] * result["full_time_marginal"]["A"]
        self.assertNotAlmostEqual(product_of_marginals, result["joint_probabilities"]["H/A"], places=6)

    def test_half_full_time_rejects_invalid_phase_rate(self):
        with self.assertRaises(ValueError):
            half_full_time_probabilities(
                lambda_home_first_half=-0.1,
                lambda_away_first_half=0.3,
                lambda_home_second_half=0.4,
                lambda_away_second_half=1.0,
            )

    def test_asian_minus_two_handles_push(self):
        matrix = dixon_coles_score_matrix({"lambda_home": 2.75, "lambda_away": 0.82, "rho": -0.03})
        result = asian_handicap_settlement(matrix, -2.0)
        self.assertAlmostEqual(1.0, sum(result[key] for key in ("full_win", "half_win", "push", "half_loss", "full_loss")), places=8)
        self.assertGreater(result["push"], 0.20)
        self.assertAlmostEqual(2.18854, result["fair_decimal_odds"], places=4)

    def test_asian_minus_half_draw_is_full_loss(self):
        result = asian_handicap_settlement({(1, 1): 1.0}, -0.5)
        self.assertEqual(1.0, result["full_loss"])
        self.assertEqual(0.0, result["push"])

    def test_over_2_75_at_three_goals_is_half_win(self):
        result = asian_total_settlement({(2, 1): 1.0}, 2.75, "over")
        self.assertEqual(1.0, result["half_win"])
        self.assertEqual(0.0, result["half_loss"])

    def test_under_2_75_at_three_goals_is_half_loss(self):
        result = asian_total_settlement({(2, 1): 1.0}, 2.75, "under")
        self.assertEqual(1.0, result["half_loss"])
        self.assertEqual(0.0, result["half_win"])

    def test_theoretical_handicap_requires_explicit_model(self):
        self.assertIsNone(theoretical_asian_handicap(None))

    def test_theoretical_total_uses_full_score_distribution(self):
        model = {"lambda_home": 2.75, "lambda_away": 0.82, "rho": -0.03}
        result = theoretical_asian_total(model)
        self.assertIsNotNone(result)
        self.assertEqual(3.5, result["line"])
        self.assertAlmostEqual(2.09034, result["fair_over_decimal_odds"], places=4)
        self.assertAlmostEqual(3.57, result["expected_total_goals"], places=8)

    def test_theoretical_total_requires_explicit_model(self):
        self.assertIsNone(theoretical_asian_total(None))

    def test_total_lambda_above_line_does_not_make_low_water_positive_ev(self):
        matrix = dixon_coles_score_matrix({"lambda_home": 1.4, "lambda_away": 1.4, "rho": 0.0}, max_goals=15)
        result = asian_total_settlement(matrix, 2.5, "over")
        self.assertAlmostEqual(0.5305463165, result["full_win"], places=9)
        self.assertAlmostEqual(1.8848495765, result["fair_decimal_odds"], places=9)
        self.assertLess(result["full_win"] * 1.85 - 1.0, 0.0)

    def test_exact_total_set_sums_score_matrix_without_overlap(self):
        matrix = {
            (1, 0): 0.20,
            (2, 0): 0.15,
            (2, 1): 0.30,
            (2, 2): 0.25,
            (3, 2): 0.10,
        }
        result = exact_total_goals_set(matrix, (1, 3, 3))
        self.assertEqual([1, 3], result["totals"])
        self.assertAlmostEqual(0.50, result["probability"], places=8)
        self.assertAlmostEqual(2.00, result["fair_decimal_odds"], places=8)
        self.assertAlmostEqual(0.00, result["edge_at_2_00"], places=8)

    def test_no_draw_does_not_imply_odd_total(self):
        result = exact_total_goals_set({(2, 0): 1.0}, (1, 3))
        self.assertEqual(0.0, result["probability"])

    def test_exact_total_set_rejects_invalid_totals(self):
        with self.assertRaises(ValueError):
            exact_total_goals_set({(0, 0): 1.0}, ())
        with self.assertRaises(ValueError):
            exact_total_goals_set({(0, 0): 1.0}, (-1, 3))

    def test_fixed_odds_arbitrage_reproduces_article_example(self):
        result = fixed_odds_arbitrage({"home": 9.0, "draw": 4.2, "away": 1.54}, total_stake=153.7777777778)
        self.assertTrue(result["theoretical_arbitrage"])
        self.assertAlmostEqual(0.9985569986, result["inverse_sum"], places=9)
        self.assertAlmostEqual(154.0, result["gross_payout_each_outcome"], places=8)
        self.assertAlmostEqual(17.1111111111, result["equal_payout_stakes"]["home"], places=8)
        self.assertAlmostEqual(36.6666666667, result["equal_payout_stakes"]["draw"], places=8)
        self.assertAlmostEqual(100.0, result["equal_payout_stakes"]["away"], places=8)
        self.assertAlmostEqual(0.0014450867, result["roi_before_costs"], places=9)

    def test_fixed_odds_arbitrage_reports_balanced_loss_when_inverse_sum_above_one(self):
        result = fixed_odds_arbitrage({"home": 2.0, "draw": 3.2, "away": 4.0})
        self.assertFalse(result["theoretical_arbitrage"])
        self.assertGreater(result["inverse_sum"], 1.0)
        self.assertLess(result["guaranteed_profit_before_costs"], 0.0)

    def test_fixed_odds_arbitrage_rejects_invalid_prices(self):
        with self.assertRaises(ValueError):
            fixed_odds_arbitrage({"home": 1.0, "away": 2.0})
        with self.assertRaises(ValueError):
            fixed_odds_arbitrage({"home": 2.0}, total_stake=100)

    def test_coverage_ev_reproduces_article_single_match_loss(self):
        result = mutually_exclusive_coverage_ev(
            {"H/H": 0.38, "D/H": 0.20, "D/D": 0.14},
            {"H/H": 2.5, "D/H": 4.0, "D/D": 8.0},
        )
        self.assertAlmostEqual(0.72, result["covered_probability_single_leg"], places=9)
        self.assertAlmostEqual(6.0, result["total_stake"], places=9)
        self.assertAlmostEqual(5.74, result["expected_gross"], places=9)
        self.assertAlmostEqual(-0.26, result["expected_net"], places=9)
        self.assertAlmostEqual(-0.0433333333, result["expected_roi"], places=9)

    def test_coverage_ev_shows_independent_two_leg_parlay_compounds_loss(self):
        result = mutually_exclusive_coverage_ev(
            {"H/H": 0.38, "D/H": 0.20, "D/D": 0.14},
            {"H/H": 2.5, "D/H": 4.0, "D/D": 8.0},
            independent_legs=2,
        )
        self.assertEqual(9, result["ticket_count"])
        self.assertAlmostEqual(18.0, result["total_stake"], places=9)
        self.assertAlmostEqual(16.4738, result["expected_gross"], places=9)
        self.assertAlmostEqual(-1.5262, result["expected_net"], places=9)
        self.assertLess(result["expected_roi"], -0.08)

    def test_coverage_ev_rejects_incomplete_or_invalid_contract(self):
        with self.assertRaises(ValueError):
            mutually_exclusive_coverage_ev({"H/H": 0.7}, {"D/H": 4.0})
        with self.assertRaises(ValueError):
            mutually_exclusive_coverage_ev({"H/H": 0.7, "D/H": 0.4}, {"H/H": 2.0, "D/H": 3.0})
        with self.assertRaises(ValueError):
            mutually_exclusive_coverage_ev({"H/H": 0.7}, {"H/H": 2.0}, independent_legs=0)

    def test_binary_half_kelly_rejects_article_negative_ev_example(self):
        result = binary_kelly_diagnostic(0.45, 2.0, fraction_multiplier=0.5)
        self.assertAlmostEqual(-0.10, result["expected_value"], places=9)
        self.assertAlmostEqual(-0.05, result["scaled_kelly_fraction"], places=9)
        self.assertEqual(0.0, result["stake_fraction_after_no_negative_gate"])
        self.assertFalse(result["positive_ev"])

    def test_binary_half_kelly_positive_example(self):
        result = binary_kelly_diagnostic(0.55, 2.0, fraction_multiplier=0.5)
        self.assertAlmostEqual(0.05, result["stake_fraction_after_no_negative_gate"], places=9)
        self.assertTrue(result["positive_ev"])

    def test_binary_kelly_rejects_invalid_probability(self):
        with self.assertRaises(ValueError):
            binary_kelly_diagnostic(1.1, 2.0)

    def test_binary_kelly_uses_selected_price_not_market_return_rate(self):
        result = binary_kelly_diagnostic(0.59, 1.20, fraction_multiplier=0.5)
        self.assertAlmostEqual(-0.292, result["expected_value"], places=9)
        self.assertEqual(0.0, result["stake_fraction_after_no_negative_gate"])
        self.assertFalse(result["positive_ev"])

    def test_annualized_return_separates_280_day_gain_from_annual_rate(self):
        result = annualized_return(1000, 1472, 280)
        self.assertAlmostEqual(0.472, result["holding_period_return"], places=9)
        self.assertAlmostEqual(0.6553118488, result["annualized_return"], places=9)

    def test_annualized_return_rejects_non_positive_horizon(self):
        with self.assertRaises(ValueError):
            annualized_return(1000, 1472, 0)


if __name__ == "__main__":
    unittest.main()
