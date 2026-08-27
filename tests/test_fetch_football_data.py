import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import fetch_football_data as fetcher
from scripts.fetch_football_data import _attach_nowscore, _deep_summary, _match_filter


class MatchFilterTests(unittest.TestCase):
    def setUp(self):
        self.matches = [
            {
                "matchId": "2040514",
                "matchNum": "周三202",
                "homeTeam": "苏捷斯卡",
                "awayTeam": "阿拉木图",
                "league": "欧冠",
            },
            {
                "matchId": "2040513",
                "matchNum": "周三201",
                "homeTeam": "比森",
                "awayTeam": "克拉克斯",
                "league": "欧冠",
            },
        ]

    def test_filters_exact_pair_with_vs_separator(self):
        rows = _match_filter(self.matches, "苏捷斯卡 vs 阿拉木图")
        self.assertEqual(["2040514"], [row["matchId"] for row in rows])

    def test_filters_pair_without_spaces_and_case_insensitively(self):
        rows = _match_filter(self.matches, "比森VS克拉克斯")
        self.assertEqual(["2040513"], [row["matchId"] for row in rows])

    def test_preserves_single_team_and_match_id_search(self):
        self.assertEqual("2040514", _match_filter(self.matches, "苏捷斯卡")[0]["matchId"])
        self.assertEqual("2040513", _match_filter(self.matches, "2040513")[0]["matchId"])

    def test_workspace_style_id_is_supported(self):
        rows = _match_filter([{"id": "2040516", "home": "德里城", "away": "索陆军"}], "2040516")
        self.assertEqual("2040516", rows[0]["id"])

    def test_verified_nowscore_is_primary_and_500_only_fills_missing_companies(self):
        five_hundred = {
            "ouzhi": {"bookmakers": [
                {"cid": 3, "source": "500_deep", "spf_current": {"home": 1.80}},
                {"cid": 293, "source": "500_deep", "spf_current": {"home": 1.90}},
            ]},
            "yazhi": {"companies": []}, "daxiao": {"companies": []},
        }
        nowscore = {
            "status": "OK", "nowscore_id": 99,
            "ouzhi": {"source": "nowscore_3in1", "bookmakers": [
                {"cid": 3, "source": "nowscore_3in1", "spf_current": {"home": 1.70}},
            ]},
            "yazhi": {"source": "nowscore_3in1", "companies": []},
            "daxiao": {"source": "nowscore_3in1", "companies": []},
            "shuju": {"recent_form": {"home_overall": {"matches": 10}}},
        }
        merged = _attach_nowscore(five_hundred, nowscore)
        rows = merged["ouzhi"]["bookmakers"]
        self.assertEqual(1.70, next(row for row in rows if row["cid"] == 3)["spf_current"]["home"])
        self.assertEqual("500_deep", next(row for row in rows if row["cid"] == 293)["source"])
        self.assertEqual(10, merged["shuju"]["recent_form"]["home_overall"]["matches"])
        self.assertEqual("nowscore", merged["source_provenance"]["market_primary"])
        self.assertEqual("nowscore_analysis", merged["source_provenance"]["form_primary"])

    def test_effective_market_providers_distinguish_nowscore_only_and_mixed_rows(self):
        nowscore = {
            "status": "OK", "nowscore_id": 99,
            "ouzhi": {"source": "nowscore_3in1", "bookmakers": [
                {"cid": 3, "source": "nowscore_3in1", "spf_current": {"home": 1.70}},
            ]},
            "yazhi": {"source": "nowscore_3in1", "companies": []},
            "daxiao": {"source": "nowscore_3in1", "companies": []},
        }
        only = _attach_nowscore(
            {"ouzhi": {"error": "fetch failed"}, "yazhi": {"error": "fetch failed"}, "daxiao": {"error": "fetch failed"}},
            nowscore,
        )
        self.assertEqual(["nowscore"], only["source_provenance"]["effective_market_providers"])
        self.assertNotIn("market_fallback", only["source_provenance"])

        mixed = _attach_nowscore(
            {"ouzhi": {"bookmakers": [
                {"cid": 293, "source": "500_deep", "spf_current": {"home": 1.90}},
            ]}, "yazhi": {"companies": []}, "daxiao": {"companies": []}},
            nowscore,
        )
        self.assertEqual(["nowscore", "500.com"], mixed["source_provenance"]["effective_market_providers"])
        self.assertEqual("500.com", mixed["source_provenance"]["market_fallback"])

    def test_deep_summary_marks_500_failure_with_nowscore_as_fallback_partial(self):
        result = _attach_nowscore(
            {
                "shuju_id": 1464455,
                **{page: {"error": "fetch failed", "page": page} for page in ("ouzhi", "yazhi", "rangqiu", "daxiao", "shuju", "touzhu")},
            },
            {
                "status": "OK", "nowscore_id": 99,
                "ouzhi": {"source": "nowscore_3in1", "bookmakers": [{"cid": 3, "source": "nowscore_3in1", "spf_current": {"home": 1.7}}]},
                "yazhi": {"source": "nowscore_3in1", "companies": []},
                "daxiao": {"source": "nowscore_3in1", "companies": []},
            },
        )
        summary = _deep_summary(result)

        self.assertEqual("FALLBACK/PARTIAL", summary["status"])
        self.assertFalse(summary["all_pages_ok"])
        self.assertTrue(summary["market_usable"])
        self.assertEqual("unavailable", summary["official_market_status"]["spf"])
        self.assertEqual("unavailable", summary["official_market_status"]["rqspf"])
        self.assertEqual("nowscore", result["source_provenance"]["market_primary"])
        self.assertEqual(["nowscore"], result["source_provenance"]["effective_market_providers"])
        self.assertEqual("fetch failed", result["source_provenance"]["500_deep_page_status"]["rangqiu"])
        self.assertNotIn("500.com", result["source_provenance"]["effective_market_providers"])
        self.assertNotIn("500_deep", result["source_provenance"]["effective_market_providers"])

        manifest = fetcher._deep_source_manifest([summary])
        self.assertEqual("FALLBACK/PARTIAL", manifest["status"])
        self.assertFalse(manifest["success"])
        self.assertEqual(["nowscore"], manifest["effective_market_providers"])

    def test_unknown_explicit_deep_id_does_not_borrow_first_match_identity(self):
        first_match = {"shuju_id": 1464455, "home_team": "??", "away_team": "??????"}
        discovered = {1464455: first_match}

        self.assertIs(first_match, fetcher._identity_for_deep_id(1464455, discovered))
        self.assertEqual({}, fetcher._identity_for_deep_id(9999999, discovered))


if __name__ == "__main__":
    unittest.main()
