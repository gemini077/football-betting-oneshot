import inspect
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import polymarket_public as poly  # noqa: E402


def market(market_id, label, bid, ask, market_type="moneyline", description=None):
    return {
        "id": str(market_id),
        "conditionId": f"condition-{market_id}",
        "question": f"Will {label} happen?",
        "groupItemTitle": label,
        "sportsMarketType": market_type,
        "bestBid": bid,
        "bestAsk": ask,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'[{(bid + ask) / 2}, {1 - ((bid + ask) / 2)}]',
        "clobTokenIds": f'["yes-{market_id}", "no-{market_id}"]',
        "liquidityNum": 10000,
        "volume24hr": 2500,
        "feesEnabled": True,
        "feeSchedule": {"rate": 0.05},
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "clearBookOnStart": True,
        "description": description or "This market refers only to the outcome within the first 90 minutes of regular play plus stoppage time.",
        "events": [{
            "id": "event-1",
            "gameId": 123,
            "slug": "france-spain",
            "title": "France vs. Spain",
            "startTime": "2026-07-14T19:00:00Z",
        }],
    }


class PolymarketPublicTests(unittest.TestCase):
    def test_complete_three_way_is_normalized_but_never_used_for_ev(self):
        rows = [
            market(1, "France", 0.40, 0.42),
            market(2, "Draw (France vs. Spain)", 0.29, 0.31),
            market(3, "Spain", 0.28, 0.30),
            market(4, "Any Other Score", 0.15, 0.17, "soccer_exact_score"),
            market(5, "1-0", 0.08, 0.10, "soccer_exact_score"),
        ]
        result = poly.build_snapshot(rows, "France", "Spain", "2026-07-14T19:00:00Z")
        self.assertEqual("EXACT_EVENT_MATCH", result["match"]["status"])
        self.assertTrue(result["settlement"]["compatible"])
        self.assertTrue(result["three_way_consensus"]["complete"])
        self.assertAlmostEqual(1.0, sum(result["three_way_consensus"]["normalized_mid_probabilities"].values()))
        self.assertTrue(result["correct_score"]["complete_distribution"])
        self.assertFalse(result["used_for_ev"])
        self.assertFalse(result["used_for_model_probability"])
        self.assertFalse(result["execution_source"])
        self.assertFalse(result["authentication_used"])
        self.assertFalse(result["account_connected"])
        self.assertFalse(result["trading_enabled"])

    def test_kickoff_mismatch_refuses_binding(self):
        result = poly.build_snapshot(
            [market(1, "France", 0.4, 0.42)],
            "France",
            "Spain",
            "2026-07-18T19:00:00Z",
        )
        self.assertEqual("NO_EXACT_EVENT_MATCH", result["match"]["status"])
        self.assertIn("NO_EXACT_EVENT_MATCH", result["quality_flags"])

    def test_extra_time_scope_is_rejected(self):
        result = poly.build_snapshot(
            [market(1, "France", 0.4, 0.42, description="This market includes extra time and a penalty shootout.")],
            "France",
            "Spain",
        )
        self.assertFalse(result["settlement"]["compatible"])
        self.assertIn("SETTLEMENT_SCOPE_NOT_CONFIRMED", result["quality_flags"])

    def test_module_contains_no_trade_or_auth_transport(self):
        source = inspect.getsource(poly)
        self.assertNotIn('method="POST"', source)
        self.assertNotIn("private_key", source.casefold())
        self.assertNotIn("api_secret", source.casefold())
        self.assertNotIn("create_order", source.casefold())
        self.assertNotIn("cancel_order", source.casefold())


if __name__ == "__main__":
    unittest.main()

