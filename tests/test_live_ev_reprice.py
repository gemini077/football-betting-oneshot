import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from live_ev_reprice import (  # noqa: E402
    RepriceValidationError,
    canonical_line,
    evaluate_request,
)


def request_template():
    return {
        "schema_version": "1.0",
        "contract": {
            "match_id": "5503037",
            "market_code": "2",
            "market_name": "全场大小",
            "handicap_line": "2.5",
            "selection_code": "Over",
            "contract_type": "binary_no_push",
        },
        "probability": {
            "point": 0.56,
            "conservative": 0.53,
            "confirmed_model_output": True,
            "source": "test_calibrated_model",
            "calibration_status": "test_fixture",
        },
        "price": {"source": "bridge", "max_quote_age_ms": 15000},
        "execution": {"minimum_conservative_ev": 0.0},
    }


def quote(*, odds=1.99, age=3000, verified=True, line="2.5", market_id="m1"):
    return {
        "match_id": "5503037",
        "market_code": "2",
        "market_name": "全场大小",
        "child_market_code": "2",
        "market_id": market_id,
        "handicap_line": line,
        "selection_code": "Over",
        "selection_name": "大 2.5",
        "inferred_decimal_odds": odds,
        "display_price": "0.99",
        "odds_scale_verified": verified,
        "source_timestamp_ms": "1784016358220",
        "received_at": "2026-07-14T16:05:58+08:00",
        "quote_age_ms": age,
        "market_status": 0,
        "selection_status": 1,
    }


class LiveEvRepriceTests(unittest.TestCase):
    def test_canonical_line_matches_split_and_decimal_quarter_line(self):
        self.assertEqual("2.75", canonical_line("2.5/3"))
        self.assertEqual(canonical_line("2.5/3"), canonical_line(2.75))

    def test_fresh_verified_quote_passes_conservative_ev_gate(self):
        result = evaluate_request(request_template(), latest_payload={"quotes": [quote()]})
        self.assertEqual("candidate_price_pass", result["decision_status"])
        self.assertEqual("candidate", result["bet_status"])
        self.assertAlmostEqual(0.0547, result["ev"]["conservative_ev"], places=9)
        self.assertAlmostEqual(1 / 0.53, result["ev"]["minimum_acceptable_decimal_odds"], places=9)
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["lock_state_changed"])
        self.assertFalse(result["bankroll_state_changed"])

    def test_stale_quote_is_rejected_before_ev(self):
        result = evaluate_request(request_template(), latest_payload={"quotes": [quote(age=15001)]})
        self.assertEqual("quote_stale", result["decision_status"])
        self.assertIsNone(result["ev"])
        self.assertEqual("no_bet", result["bet_status"])

    def test_unchanged_quote_remains_fresh_while_exact_match_page_is_live(self):
        result = evaluate_request(
            request_template(),
            latest_payload={
                "quotes": [quote(age=120000)],
                "match_activity": {"match_id": "5503037", "age_ms": 1000},
            },
        )
        self.assertEqual("candidate_price_pass", result["decision_status"])
        self.assertEqual("active_match_page_heartbeat", result["price"]["freshness_basis"])

    def test_unverified_odds_scale_is_rejected_before_ev(self):
        result = evaluate_request(request_template(), latest_payload={"quotes": [quote(verified=False)]})
        self.assertEqual("odds_unverified", result["decision_status"])
        self.assertIsNone(result["ev"])

    def test_multiple_exact_matches_require_more_contract_identity(self):
        result = evaluate_request(
            request_template(),
            latest_payload={"quotes": [quote(market_id="m1"), quote(market_id="m2")]},
        )
        self.assertEqual("contract_ambiguous", result["decision_status"])

    def test_market_id_disambiguates_quote(self):
        request = request_template()
        request["contract"]["market_id"] = "m2"
        result = evaluate_request(
            request,
            latest_payload={"quotes": [quote(market_id="m1"), quote(market_id="m2")]},
        )
        self.assertEqual("candidate_price_pass", result["decision_status"])

    def test_manual_same_contract_reprices(self):
        request = request_template()
        request["price"] = {
            "source": "manual",
            "decimal_odds": 1.95,
            "odds_format": "decimal",
            "handicap_line": "2.5",
            "selection_code": "Over",
        }
        result = evaluate_request(request)
        self.assertEqual("candidate_price_pass", result["decision_status"])
        self.assertEqual("user_channel_manual", result["price"]["source"])

    def test_manual_changed_line_requires_probability_recompute(self):
        request = request_template()
        request["price"] = {
            "source": "manual",
            "decimal_odds": 2.02,
            "odds_format": "decimal",
            "handicap_line": "2.75",
            "selection_code": "Over",
        }
        result = evaluate_request(request)
        self.assertEqual("requires_probability_recompute", result["decision_status"])
        self.assertIsNone(result["ev"])

    def test_manual_missing_decimal_declaration_is_rejected(self):
        request = request_template()
        request["price"] = {"source": "manual", "decimal_odds": 2.0}
        result = evaluate_request(request)
        self.assertEqual("odds_format_unverified", result["decision_status"])

    def test_missing_conservative_probability_is_shadow_only(self):
        request = request_template()
        request["probability"].pop("conservative")
        result = evaluate_request(request, latest_payload={"quotes": [quote()]})
        self.assertEqual("probability_uncertainty_missing", result["decision_status"])
        self.assertEqual("shadow_only", result["bet_status"])

    def test_validation_fixture_never_becomes_candidate(self):
        request = request_template()
        request["validation_only"] = True
        result = evaluate_request(request, latest_payload={"quotes": [quote()]})
        self.assertEqual("shadow_only_validation", result["decision_status"])
        self.assertEqual("shadow_only", result["bet_status"])

    def test_unconfirmed_probability_never_becomes_candidate(self):
        request = request_template()
        request["probability"]["confirmed_model_output"] = False
        result = evaluate_request(request, latest_payload={"quotes": [quote()]})
        self.assertEqual("probability_provenance_unconfirmed", result["decision_status"])
        self.assertEqual(0.0, result["staking"]["suggested_stake"])

    def test_fixed_small_stake_respects_five_percent_single_match_cap(self):
        request = request_template()
        request["staking"] = {
            "bankroll": 51.43,
            "current_daily_exposure": 0,
            "daily_exposure_cap_pct": 0.05,
            "single_match_cap_pct": 0.05,
            "fixed_stake_min": 2,
            "fixed_stake_max": 3,
        }
        result = evaluate_request(request, latest_payload={"quotes": [quote()]})
        self.assertEqual("candidate_price_pass", result["decision_status"])
        self.assertEqual(2.0, result["staking"]["suggested_stake"])
        self.assertTrue(result["staking"]["kelly_is_diagnostic_only"])

    def test_exhausted_daily_cap_forces_no_bet(self):
        request = request_template()
        request["staking"] = {
            "bankroll": 51.43,
            "current_daily_exposure": 2.57,
            "daily_exposure_cap_pct": 0.05,
            "single_match_cap_pct": 0.05,
        }
        result = evaluate_request(request, latest_payload={"quotes": [quote()]})
        self.assertEqual("exposure_limit", result["decision_status"])
        self.assertEqual("no_bet", result["bet_status"])

    def test_non_pre_match_state_blocks_pre_match_probability(self):
        request = request_template()
        latest = {
            "quotes": [quote()],
            "match_metadata": [{"match_id": "5503037", "match_status": "1", "match_period": "1"}],
        }
        result = evaluate_request(request, latest_payload=latest)
        self.assertEqual("in_play_probability_not_supported", result["decision_status"])
        self.assertIsNone(result["ev"])

    def test_asian_full_settlement_is_rejected(self):
        request = request_template()
        request["contract"]["contract_type"] = "asian_full_settlement"
        result = evaluate_request(request, latest_payload={"quotes": [quote()]})
        self.assertEqual("unsupported_settlement", result["decision_status"])

    def test_conservative_probability_cannot_exceed_point(self):
        request = request_template()
        request["probability"]["conservative"] = 0.57
        with self.assertRaises(RepriceValidationError):
            evaluate_request(request, latest_payload={"quotes": [quote()]})


if __name__ == "__main__":
    unittest.main()
